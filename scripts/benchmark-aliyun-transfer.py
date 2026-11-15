"""Compare local pipe-to-HTTP upload throughput without cloud credentials."""
import argparse
import hashlib
import json
import subprocess
import sys
import threading
import time
import types
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from service.storage.drivers.aliyun import AliyunDriveDriver
from service.storage.drivers.base import StorageDriver, stream_transfer

CHUNK = bytes(range(256)) * 4096


class Source(StorageDriver):
    def __init__(self, rate):
        self.rate = rate

    def download(self, path, target, progress=None, cancel=None):
        for _ in range(int(path)):
            if self.rate:
                time.sleep(1 / self.rate)
            target.write(CHUNK)


def run(driver_class, size_mib, workers, rate):
    received = []
    first_byte = []

    class Handler(BaseHTTPRequestHandler):
        def do_PUT(self):
            remaining = int(self.headers["Content-Length"])
            digest = hashlib.sha256()
            while remaining:
                data = self.rfile.read(min(256 * 1024, remaining))
                if not data:
                    raise IOError("truncated request")
                if not first_byte:
                    first_byte.append(time.perf_counter())
                remaining -= len(data)
                digest.update(data)
                if rate:
                    time.sleep(len(data) / len(CHUNK) / rate)
            received.append(digest.digest())
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    driver = driver_class({
        "client_id": "benchmark", "client_secret": "unused",
        "refresh_token": "unused", "drive_id": "local",
    })
    driver._resolve = lambda _path: {"file_id": "parent"}
    driver._assert_file_destination = lambda *_args: None
    driver._remove_duplicates = lambda *_args: None
    parts = max(1, (size_mib + 19) // 20)

    def request(endpoint, _data):
        if endpoint.endswith("/create"):
            return {"file_id": "file", "upload_id": "upload", "part_info_list": [
                {"part_number": index + 1, "upload_url": "http://127.0.0.1:{}/{}".format(
                    server.server_port, index)} for index in range(parts)
            ]}
        return {"file_id": "file"}

    driver._request = request
    started = time.perf_counter()
    try:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(stream_transfer, Source(rate), str(size_mib), driver,
                                   "/file-{}".format(index), size_mib * len(CHUNK))
                       for index in range(workers)]
            for future in futures:
                future.result()
        elapsed = time.perf_counter() - started
    finally:
        driver.session.close()
        server.shutdown()
        server.server_close()
        server_thread.join()
    expected = []
    for offset in range(0, size_mib, 20):
        digest = hashlib.sha256()
        for _ in range(min(20, size_mib - offset)):
            digest.update(CHUNK)
        expected.append(digest.digest())
    assert sorted(received) == sorted(expected * workers), "uploaded part hash mismatch"
    return {"workers": workers, "total_mib": size_mib * workers, "source_and_sink_rate_mib_s": rate,
            "seconds": round(elapsed, 3), "mib_per_second": round(size_mib * workers / elapsed, 2),
            "first_byte_seconds": round(first_byte[0] - started, 3), "hashes_verified": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size-mib", type=int, default=64)
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--rate-mib-per-second", type=float, default=0)
    parser.add_argument("--compare-ref")
    args = parser.parse_args()
    if args.size_mib < 1 or not 1 <= args.workers <= 100 or args.rate_mib_per_second < 0:
        parser.error("size must be positive and workers between 1 and 100")
    if args.compare_ref:
        source = subprocess.check_output(["git", "show",
            args.compare_ref + ":service/storage/drivers/aliyun.py"], cwd=ROOT).decode("utf-8")
        module = types.ModuleType("service.storage.drivers._benchmark_baseline")
        exec(compile(source, "<git-baseline>", "exec"), module.__dict__)
        print(json.dumps({"version": args.compare_ref, **run(module.AliyunDriveDriver, args.size_mib, args.workers, args.rate_mib_per_second)}), flush=True)
    print(json.dumps({"version": "working-tree", **run(AliyunDriveDriver, args.size_mib, args.workers, args.rate_mib_per_second)}), flush=True)


if __name__ == "__main__":
    main()
