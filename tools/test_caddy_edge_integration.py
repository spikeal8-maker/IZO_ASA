from __future__ import annotations

import gzip
import hashlib
import http.client
import json
import os
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = json.loads((ROOT / "ops" / "caddy" / "runtime.json").read_text(encoding="utf-8"))
CADDY = ROOT / Path(SPEC["install_relative_path"])
CADDYFILE = ROOT / "ops" / "caddy" / "Caddyfile"
RELEASE = "edge-integration-release"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class _BackendHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/api/version"):
            body = json.dumps({"release_id": RELEASE, "frontend_build": RELEASE}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
        elif self.path.startswith(("/feed", "/gallery")):
            body = b"<!doctype html><title>backend shell</title>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("X-IZO-Release", RELEASE)
            self.send_header("Cache-Control", "no-store")
        elif self.path.startswith("/api/health"):
            body = b'{"status":"ok"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
        elif self.path.startswith(("/api", "/media", "/static")):
            body = b'{"detail":"unauthorized"}'
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
        else:
            body = b"not found"
            self.send_response(404)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def _request(port: int, path: str, *, host: str = "izo.alikinas.ru", headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], bytes]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    request_headers = {"Host": host, **(headers or {})}
    try:
        connection.request("GET", path, headers=request_headers)
        response = connection.getresponse()
        return response.status, {key.lower(): value for key, value in response.getheaders()}, response.read()
    finally:
        connection.close()


@pytest.mark.skipif(not CADDY.is_file(), reason="pinned Caddy runtime is installed by verify.ps1")
def test_real_caddy_config_serves_spa_proxies_backend_and_redacts_logs(tmp_path: Path) -> None:
    assert hashlib.sha256(CADDY.read_bytes()).hexdigest() == SPEC["executable_sha256"]
    release_root = tmp_path / "release"
    assets = release_root / "assets"
    assets.mkdir(parents=True)
    (assets / "index-ABC12345.js").write_text("console.log('edge');" * 400, encoding="utf-8")
    (release_root / "index.html").write_text(
        f'<!doctype html><meta name="izo-release" content="{RELEASE}"><script src="/assets/index-ABC12345.js"></script><main>{"x" * 8000}</main>',
        encoding="utf-8",
    )
    access_log = tmp_path / "access.jsonl"
    runtime_log = tmp_path / "runtime.jsonl"
    edge_port, admin_port, backend_port = _free_port(), _free_port(), _free_port()
    backend = ThreadingHTTPServer(("127.0.0.1", backend_port), _BackendHandler)
    backend_thread = threading.Thread(target=backend.serve_forever, daemon=True)
    backend_thread.start()

    environment = os.environ.copy()
    environment.update(
        {
            "IZO_FRONTEND_ROOT": release_root.as_posix(),
            "IZO_CADDY_PORT": str(edge_port),
            "IZO_CADDY_ADMIN_ADDRESS": f"127.0.0.1:{admin_port}",
            "IZO_CADDY_BACKEND_ADDRESS": f"127.0.0.1:{backend_port}",
            "IZO_CADDY_ACCESS_LOG": access_log.as_posix(),
            "IZO_CADDY_RUNTIME_LOG": runtime_log.as_posix(),
        }
    )
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    process = subprocess.Popen(
        [str(CADDY), "run", "--config", str(CADDYFILE), "--adapter", "caddyfile"],
        cwd=ROOT,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creation_flags,
    )
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                if _request(edge_port, "/")[0] == 200:
                    break
            except OSError:
                pass
            time.sleep(0.1)
        else:
            raise AssertionError("Caddy integration listener did not start")

        status, headers, body = _request(
            edge_port,
            "/?token=edge-query-sentinel&userId=edge-user-id",
            headers={
                "Authorization": "Bearer edge-secret-sentinel",
                "Cookie": "onenode_session=edge-cookie-sentinel",
                "Accept-Encoding": "gzip",
            },
        )
        assert status == 200
        assert headers["content-encoding"] == "gzip"
        assert RELEASE.encode() in gzip.decompress(body)
        assert headers["cache-control"] == "no-store"
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["x-frame-options"] == "SAMEORIGIN"
        assert "server" not in headers

        assert _request(edge_port, "/", host="127.0.0.1")[0] == 200
        assert _request(edge_port, "/", host="localhost")[0] == 200
        assert _request(edge_port, "/", host="evil.example")[0] == 421
        assert _request(edge_port, "/", host="sub.izo.alikinas.ru")[0] == 421

        asset_status, asset_headers, _ = _request(edge_port, "/assets/index-ABC12345.js")
        assert asset_status == 200
        assert asset_headers["cache-control"] == "public, max-age=31536000, immutable"
        profile_status, profile_headers, profile_body = _request(edge_port, "/profile")
        assert profile_status == 200
        assert profile_headers["cache-control"] == "no-store"
        assert RELEASE.encode() in profile_body

        for route in ("/feed", "/gallery"):
            route_status, route_headers, _ = _request(edge_port, route)
            assert route_status == 200
            assert route_headers["x-izo-release"] == RELEASE
        version_status, _, version_body = _request(edge_port, "/api/version")
        assert version_status == 200
        assert json.loads(version_body) == {"release_id": RELEASE, "frontend_build": RELEASE}
        assert _request(edge_port, "/media/private.webp")[0] == 401

        second_root = tmp_path / "release-two"
        second_root.mkdir()
        second_release = "edge-integration-release-two"
        (second_root / "index.html").write_text(
            f'<!doctype html><meta name="izo-release" content="{second_release}"><main>{"y" * 8000}</main>',
            encoding="utf-8",
        )
        reload_environment = {**environment, "IZO_FRONTEND_ROOT": second_root.as_posix()}
        reload_result = subprocess.run(
            [
                str(CADDY),
                "reload",
                "--config",
                str(CADDYFILE),
                "--adapter",
                "caddyfile",
                "--address",
                f"127.0.0.1:{admin_port}",
            ],
            cwd=ROOT,
            env=reload_environment,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
            creationflags=creation_flags,
        )
        assert reload_result.returncode == 0, reload_result.stdout + reload_result.stderr
        second_status, _, second_body = _request(edge_port, "/")
        assert second_status == 200
        assert second_release.encode() in second_body
        assert process.poll() is None

        restore_result = subprocess.run(
            [
                str(CADDY),
                "reload",
                "--config",
                str(CADDYFILE),
                "--adapter",
                "caddyfile",
                "--address",
                f"127.0.0.1:{admin_port}",
            ],
            cwd=ROOT,
            env=environment,
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
            creationflags=creation_flags,
        )
        assert restore_result.returncode == 0, restore_result.stdout + restore_result.stderr
        restored_status, _, restored_body = _request(edge_port, "/")
        assert restored_status == 200
        assert RELEASE.encode() in restored_body

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and (not access_log.is_file() or not access_log.read_text(encoding="utf-8")):
            time.sleep(0.1)
        log_text = access_log.read_text(encoding="utf-8")
        for sentinel in ("edge-secret-sentinel", "edge-cookie-sentinel", "edge-query-sentinel", "edge-user-id"):
            assert sentinel not in log_text
        assert all(json.loads(line) for line in log_text.splitlines() if line.strip())
    finally:
        subprocess.run(
            [str(CADDY), "stop", "--address", f"127.0.0.1:{admin_port}"],
            cwd=ROOT,
            env=environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
            creationflags=creation_flags,
        )
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        backend.shutdown()
        backend.server_close()
        backend_thread.join(timeout=5)
