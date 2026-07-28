"""Enumerate file shares exposed by an SMB server.

The smbprotocol high-level API intentionally works with a known UNC share.
Share enumeration is provided by the SRVSVC RPC endpoint on IPC$, so this
module keeps the small amount of protocol framing needed by the configuration
picker separate from the normal storage driver.
"""

from __future__ import annotations

import re


MAX_SHARES = 128
_HOST_PATTERN = re.compile(r"^[^\\/\x00-\x1f]+$")


def _validate_config(config):
    config = dict(config or {})
    host = str(config.get("host") or config.get("server") or "").strip()
    if not host or not _HOST_PATTERN.match(host):
        raise ValueError("SMB host is required")
    raw_port = config.get("port")
    if raw_port in (None, ""):
        raw_port = 445
    try:
        port = int(raw_port)
    except (TypeError, ValueError) as exc:
        raise ValueError("SMB port must be between 1 and 65535") from exc
    if not 1 <= port <= 65535:
        raise ValueError("SMB port must be between 1 and 65535")
    domain = str(config.get("domain") or "").strip()
    username = str(config.get("username") or "")
    if domain and username and "\\" not in username:
        username = f"{domain}\\{username}"
    password = str(config.get("password") or "")
    return host, port, username, password


def _build_dce_rpc_request(call_id, packet_type, data):
    return b"".join(
        [
            b"\x05\x00",
            int(packet_type).to_bytes(1, byteorder="little"),
            b"\x03\x10\x00\x00\x00",
            (len(data) + 16).to_bytes(2, byteorder="little"),
            b"\x00\x00",
            int(call_id).to_bytes(4, byteorder="little"),
            data,
        ]
    )


def _build_dce_rpc_bind(call_id):
    data = b"".join(
        [
            b"\xb8\x10\xb8\x10\x00\x00\x00\x00",
            b"\x02\x00\x00\x00",
            b"\x00\x00\x01\x00\xc8\x4f\x32\x4b\x70\x16\xd3\x01\x12\x78\x5a\x47",
            b"\xbf\x6e\xe1\x88\x03\x00\x00\x00\x04\x5d\x88\x8a\xeb\x1c\xc9\x11",
            b"\x9f\xe8\x08\x00\x2b\x10\x48\x60\x02\x00\x00\x00",
            b"\x01\x00\x01\x00\xc8\x4f\x32\x4b\x70\x16\xd3\x01\x12\x78\x5a\x47",
            b"\xbf\x6e\xe1\x88\x03\x00\x00\x00\x2c\x1c\xb7\x6c\x12\x98\x40\x45",
            b"\x03\x00\x00\x00\x00\x00\x00\x00\x01\x00\x00\x00",
        ]
    )
    return _build_dce_rpc_request(call_id, 11, data)


def _build_share_enum_request(call_id, server):
    server_name = rf"\\{server}"
    server_len = len(server_name) + 1
    padding = b"\x00\x00" if server_len % 2 else b""
    encoded_server = (server_name + "\x00").encode("utf-16-le")
    stub = b"".join(
        [
            b"\x00\x00\x02\x00",
            server_len.to_bytes(4, byteorder="little"),
            b"\x00\x00\x00\x00",
            server_len.to_bytes(4, byteorder="little"),
            encoded_server,
            padding,
            (1).to_bytes(4, byteorder="little"),
            b"\x01\x00\x00\x00\x04\x00\x02\x00\x00\x00\x00\x00\x00\x00\x00\x00",
            b"\xff\xff\xff\xff",
            b"\x08\x00\x02\x00\x00\x00\x00\x00",
        ]
    )
    rpc_data = b"".join(
        [
            b"\x4c\x00\x00\x00",
            b"\x00\x00",
            (15).to_bytes(2, byteorder="little"),
            stub,
        ]
    )
    return _build_dce_rpc_request(call_id, 0, rpc_data)


def _read_utf16_field(view):
    length = int.from_bytes(view[8:12], byteorder="little")
    value = view[12 : 12 + max(0, length - 1) * 2].tobytes().decode(
        "utf-16-le", errors="replace"
    )
    aligned_length = length + (length % 2)
    return value, view[12 + aligned_length * 2 :]


def _unpack_share_info(data):
    data = memoryview(data)
    if len(data) < 48:
        raise ValueError("invalid SMB share enumeration response")
    result_len = int.from_bytes(data[36:40], byteorder="little")
    if result_len < 0 or result_len > MAX_SHARES:
        raise ValueError("invalid SMB share enumeration response")
    array_view = data[48:]
    string_view = array_view[12 * result_len :]
    shares = []
    for _ in range(result_len):
        if len(array_view) < 12:
            raise ValueError("invalid SMB share enumeration response")
        share_type = int.from_bytes(array_view[4:8], byteorder="little") & 0x0FFFFFFF
        array_view = array_view[12:]
        name, string_view = _read_utf16_field(string_view)
        comment, string_view = _read_utf16_field(string_view)
        # 0 is STYPE_DISKTREE. IPC, printer and device endpoints are not
        # valid values for the storage driver's share field.
        if (
            share_type == 0
            and name
            and name not in (".", "..")
            and _HOST_PATTERN.match(name)
        ):
            shares.append({"name": name, "comment": comment})
    shares.sort(key=lambda item: item["name"].casefold())
    return shares


def _get_share_info(smbclient, server, kwargs):
    from smbprotocol.ioctl import CtlCode, IOCTLFlags, SMB2IOCTLRequest, SMB2IOCTLResponse

    with smbclient.open_file(
        rf"\\{server}\IPC$\srvsvc",
        mode="w+b",
        buffering=0,
        file_type="pipe",
        **kwargs,
    ) as srvsvc:
        connection = srvsvc.fd.connection
        fid = srvsvc.fd.file_id
        sid = srvsvc.fd.tree_connect.session.session_id
        tid = srvsvc.fd.tree_connect.tree_connect_id
        srvsvc.write(_build_dce_rpc_bind(1))
        srvsvc.read(1024)

        ioctl_request = SMB2IOCTLRequest()
        ioctl_request["ctl_code"] = CtlCode.FSCTL_PIPE_TRANSCEIVE
        ioctl_request["file_id"] = fid
        ioctl_request["flags"] = IOCTLFlags.SMB2_0_IOCTL_IS_FSCTL
        ioctl_request["max_output_response"] = 8196
        ioctl_request["buffer"] = _build_share_enum_request(2, server)
        request = connection.send(ioctl_request, sid=sid, tid=tid)
        response = connection.receive(request)
        ioctl_response = SMB2IOCTLResponse()
        ioctl_response.unpack(response["data"].get_value())
        return _unpack_share_info(ioctl_response["buffer"].get_value())


def list_smb_shares(config):
    """Return disk shares visible to the supplied SMB credentials."""
    server, port, username, password = _validate_config(config)
    try:
        import smbclient
    except ImportError as exc:
        raise RuntimeError("SMB support requires the smbprotocol package") from exc

    connection_cache = {}
    kwargs = {"port": port, "connection_cache": connection_cache}
    if username:
        kwargs.update(username=username, password=password)
    try:
        smbclient.register_session(server, **kwargs)
        return _get_share_info(smbclient, server, kwargs)
    finally:
        try:
            smbclient.reset_connection_cache(
                fail_on_error=False, connection_cache=connection_cache
            )
        except Exception:
            pass
