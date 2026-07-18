"""Safe local-directory browsing and SMB host discovery helpers.

The discovery endpoints are intentionally independent from the storage
drivers.  They are used while configuring a mount, before a driver exists,
and therefore must not accept a user-supplied network range or follow local
symbolic links.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeoutError
import ipaddress
import os
import socket
import string
import threading
import time


# Keep discovery responsive even on a machine with several interfaces.  These
# are module constants so tests and deployments can tune them without changing
# the endpoint contract.
MAX_DISCOVERY_NETWORKS = 4
MAX_DISCOVERY_HOSTS = 1024
MAX_DISCOVERY_RESULTS = 128
MAX_REVERSE_LOOKUPS = 8
DISCOVERY_WORKERS = 64
TCP_PROBE_TIMEOUT = 0.15
DISCOVERY_TIMEOUT = 4.0
REVERSE_LOOKUP_TIMEOUT = 0.05
DISCOVERY_CACHE_TTL = 15.0
_RFC1918_NETWORKS = tuple(
    ipaddress.ip_network(value)
    for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)

_discovery_condition = threading.Condition()
_discovery_inflight = False
_discovery_cache = None
_discovery_cache_time = 0.0


def _is_allowed_ipv4(value):
    """Return whether *value* is a usable private/link-local IPv4 address."""
    try:
        address = ipaddress.ip_address(str(value))
    except ValueError:
        return False
    if not isinstance(address, ipaddress.IPv4Address):
        return False
    # Loopback, unspecified, multicast and reserved addresses are not LAN
    # peers, even though some Python versions classify loopback as private.
    if (
        address.is_loopback
        or address.is_unspecified
        or address.is_multicast
        or address.is_reserved
    ):
        return False
    return bool(address.is_link_local or any(address in network for network in _RFC1918_NETWORKS))


def _local_ipv4_addresses():
    """Collect local IPv4 addresses without accepting caller-controlled input.

    Hostname resolution catches statically configured interfaces.  The UDP
    route probe discovers the interface selected for normal outbound traffic;
    ``connect`` on a UDP socket does not send a packet.
    """
    values = set()

    try:
        hostname = socket.gethostname()
        for result in socket.getaddrinfo(hostname, None, socket.AF_INET, socket.SOCK_DGRAM):
            values.add(result[4][0])
    except (OSError, socket.gaierror):
        pass

    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # TEST-NET-1 is unroutable by definition, but still lets the kernel
        # select the default interface.  No datagram is sent by connect().
        sock.connect(("192.0.2.1", 9))
        values.add(sock.getsockname()[0])
    except OSError:
        pass
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    return sorted(value for value in values if _is_allowed_ipv4(value))


def _candidate_networks(addresses=None):
    """Build a bounded, de-duplicated list of inferred /24 networks."""
    if addresses is None:
        addresses = _local_ipv4_addresses()
    networks = []
    seen = set()
    for value in addresses:
        if not _is_allowed_ipv4(value):
            continue
        network = ipaddress.ip_network("{}/24".format(value), strict=False)
        key = str(network.network_address)
        if key in seen:
            continue
        seen.add(key)
        networks.append(network)
        if len(networks) >= MAX_DISCOVERY_NETWORKS:
            break
    return networks


def _candidate_hosts(networks):
    """Return at most ``MAX_DISCOVERY_HOSTS`` usable hosts from networks."""
    hosts = []
    seen = set()
    for network in networks:
        for address in network.hosts():
            value = str(address)
            if value in seen:
                continue
            seen.add(value)
            hosts.append(value)
            if len(hosts) >= MAX_DISCOVERY_HOSTS:
                return hosts
    return hosts


def _probe_smb_port(address, timeout=TCP_PROBE_TIMEOUT):
    """Probe TCP/445 and return the address only when it accepts a connection."""
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        return str(address) if sock.connect_ex((str(address), 445)) == 0 else None
    except OSError:
        return None
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass


def _reverse_lookup(address, timeout=REVERSE_LOOKUP_TIMEOUT):
    """Best-effort, bounded reverse lookup; the address is always a fallback."""
    result = []

    def lookup():
        try:
            name = socket.gethostbyaddr(str(address))[0]
            if name:
                result.append(str(name))
        except (OSError, socket.herror, socket.gaierror):
            pass

    # libc DNS calls do not consistently honor a Python socket timeout.  A
    # daemon thread keeps the HTTP worker bounded when a resolver is offline.
    worker = threading.Thread(target=lookup, name="taosync-reverse-lookup", daemon=True)
    worker.start()
    worker.join(timeout=max(0.0, float(timeout)))
    return result[0] if result else str(address)


def _smb_discover_uncached():
    """Perform one bounded SMB scan without consulting the result cache."""
    networks = _candidate_networks()
    hosts = _candidate_hosts(networks)
    if not hosts:
        return []

    executor = ThreadPoolExecutor(max_workers=min(DISCOVERY_WORKERS, len(hosts)))
    futures = {executor.submit(_probe_smb_port, address): address for address in hosts}
    active = []
    deadline = time.monotonic() + max(0.1, float(DISCOVERY_TIMEOUT))
    try:
        pending = set(futures)
        while pending and time.monotonic() < deadline:
            remaining = max(0.01, deadline - time.monotonic())
            try:
                completed = as_completed(pending, timeout=remaining)
                for future in completed:
                    pending.discard(future)
                    try:
                        value = future.result()
                    except Exception:
                        value = None
                    if value:
                        active.append(str(value))
                    if time.monotonic() >= deadline:
                        break
            except FuturesTimeoutError:
                break
    finally:
        # Socket probes have their own short timeout.  Do not make the request
        # wait for a worker that is already beyond the overall deadline.
        executor.shutdown(wait=False, cancel_futures=True)

    return _format_smb_devices(active)


def _format_smb_devices(addresses):
    ordered = sorted(
        set(addresses), key=lambda item: tuple(int(part) for part in item.split("."))
    )[:MAX_DISCOVERY_RESULTS]
    return [
        {
            "address": address,
            "name": (
                _reverse_lookup(address)
                if index < MAX_REVERSE_LOOKUPS
                else address
            ),
        }
        for index, address in enumerate(ordered)
    ]


def _copy_discovery_result(result):
    return [dict(item) for item in (result or [])]


def clear_smb_discovery_cache():
    """Clear the process-local discovery cache (primarily useful in tests)."""
    global _discovery_cache, _discovery_cache_time
    with _discovery_condition:
        _discovery_cache = None
        _discovery_cache_time = 0.0
        _discovery_condition.notify_all()


def smbDiscover():
    """Discover SMB hosts on inferred private/link-local /24 networks.

    No caller-provided address, network, or hostname is used.  Results are
    stable and de-duplicated, making them safe to display directly in a
    configuration picker.
    """
    global _discovery_cache, _discovery_cache_time, _discovery_inflight
    deadline = time.monotonic() + max(0.1, float(DISCOVERY_TIMEOUT))
    with _discovery_condition:
        now = time.monotonic()
        if (
            _discovery_cache is not None
            and now - _discovery_cache_time < max(0.0, float(DISCOVERY_CACHE_TTL))
        ):
            return _copy_discovery_result(_discovery_cache)
        while _discovery_inflight:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                # A previous scan is still bounded by its own deadline.  Do
                # not start a duplicate scan merely because this caller timed
                # out waiting for the shared result.
                return _copy_discovery_result(_discovery_cache)
            _discovery_condition.wait(timeout=remaining)
            now = time.monotonic()
            if (
                _discovery_cache is not None
                and now - _discovery_cache_time < max(0.0, float(DISCOVERY_CACHE_TTL))
            ):
                return _copy_discovery_result(_discovery_cache)
        _discovery_inflight = True
    try:
        result = _smb_discover_uncached()
    except BaseException:
        with _discovery_condition:
            _discovery_inflight = False
            _discovery_condition.notify_all()
        raise
    with _discovery_condition:
        _discovery_cache = _copy_discovery_result(result)
        _discovery_cache_time = time.monotonic()
        _discovery_inflight = False
        _discovery_condition.notify_all()
        return _copy_discovery_result(_discovery_cache)


def _safe_root(name, path):
    try:
        path = os.path.realpath(os.path.abspath(path))
    except OSError:
        return None
    try:
        if os.path.islink(path) or not os.path.isdir(path):
            return None
    except OSError:
        return None
    return {"name": name, "path": path}


def _filesystem_roots():
    roots = []
    seen = set()

    def add(name, path):
        root = _safe_root(name, path)
        if root is None:
            return
        key = os.path.normcase(root["path"])
        if key in seen:
            return
        seen.add(key)
        roots.append(root)

    if os.name == "nt":
        for letter in string.ascii_uppercase:
            add(letter + ":", letter + ":\\")
    else:
        add("/", os.path.sep)
        home = os.path.abspath(os.path.expanduser("~"))
        if home != os.path.abspath(os.path.sep):
            add("home", home)
        add("cwd", os.getcwd())
    return roots


def _browse_path(path):
    if path is None or str(path) == "":
        path = os.getcwd()
    path = str(path)
    if "\x00" in path or not os.path.isabs(path):
        raise ValueError("local browse path must be absolute")
    try:
        path = os.path.realpath(os.path.abspath(path))
        if not os.path.isdir(path):
            raise ValueError("local browse path must be an existing directory")
    except OSError as exc:
        raise ValueError("local browse path is not accessible") from exc
    return path


def localBrowse(path=None):
    """List safe child directories for the local-directory picker."""
    current = _browse_path(path)
    parent = os.path.dirname(current)
    # ``dirname`` of a filesystem root is the root itself.
    if os.path.normcase(parent) == os.path.normcase(current):
        parent = None
    directories = []
    try:
        entries = os.scandir(current)
    except (OSError, PermissionError) as exc:
        raise ValueError("local browse path is not accessible") from exc
    try:
        for entry in entries:
            try:
                if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
                    continue
                entry_path = os.path.realpath(os.path.abspath(entry.path))
                directories.append({"name": entry.name, "path": entry_path})
            except (OSError, PermissionError):
                continue
    finally:
        close = getattr(entries, "close", None)
        if close is not None:
            close()
    directories.sort(key=lambda item: item["name"].casefold())
    return {
        "path": current,
        "parent": parent,
        "roots": _filesystem_roots(),
        "directories": directories,
    }


# PEP-8 aliases for callers that prefer snake_case; retain the camelCase names
# used by the existing JavaScript action API.
local_browse = localBrowse
smb_discover = smbDiscover
