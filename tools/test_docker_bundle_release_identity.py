"""Release-chain regressions using isolated bytes and fake Docker; no deployment."""
from __future__ import annotations

import contextlib
from io import BytesIO
from types import SimpleNamespace

import pytest

from tools import docker_test_bundle_runtime as runtime
from tools.docker_test_bundle_format import BundleError, UVICORN, json_bytes
from tools.test_docker_synthetic_runtime import make_runtime, repin


def frontend_bytes(release):
    return {
        "/": ('<!doctype html><html><head><meta name="izo-release" content="' + release +
              '"><script type="module" src="/assets/index-unit.js"></script></head></html>').encode(),
        "/assets/index-unit.js": ('const release="' + release + '";export{release};').encode(),
    }


def frontend_runtime(tmp_path, monkeypatch):
    root, _, manifest = make_runtime(tmp_path / "runtime")
    payloads = frontend_bytes(manifest["release_id"])
    (root / "frontend/assets").mkdir(exist_ok=True)
    (root / "frontend/index.html").write_bytes(payloads["/"])
    (root / "frontend/assets/index-unit.js").write_bytes(payloads["/assets/index-unit.js"])
    repin(root, manifest)
    rows = [{"Id": role + "-id", "Image": manifest["images"][role],
             "State": {"Running": True, "Health": {"Status": "healthy"}},
             "Config": {"Cmd": list(UVICORN) if role == "backend" else [], "Labels": {
                 "com.docker.compose.service": role,
                 "com.docker.compose.project.config_files": str(root / "compose.json")}},
             "HostConfig": {"NetworkMode": "container:guard-id"}}
            for role in ("backend", "web", "guard")]
    monkeypatch.setattr(runtime, "owned_resources", lambda *args: {"containers": rows})
    payloads["/api/version"] = json_bytes({
        "backend_commit": manifest["source_sha"], "release_id": manifest["release_id"],
        "frontend_build": manifest["release_id"],
        "schema_compatibility": {"min_version": 7, "max_version": 7},
    })
    origin = "http://127.0.0.1:" + str(manifest["ports"]["web"])
    calls = []
    def open_response(request, **kwargs):
        url = request.full_url
        calls.append(url)
        assert url.startswith(origin + "/")
        data = payloads[url[len(origin):]]
        response = SimpleNamespace(geturl=lambda: url, read1=BytesIO(data).read1, status=200,
                                   read_deadline=request.izo_read_deadline)
        return contextlib.nullcontext(response)
    monkeypatch.setattr(runtime, "build_opener", lambda *args: SimpleNamespace(open=open_response, handlers=args))
    return root, manifest, payloads, calls


@pytest.mark.parametrize("stale", ["/", "/assets/index-unit.js"])
def test_expected_api_cannot_hide_stale_frontend(tmp_path, monkeypatch, stale):
    root, manifest, payloads, _ = frontend_runtime(tmp_path, monkeypatch)
    payloads[stale] = frontend_bytes(manifest["source_sha"])[stale]
    with pytest.raises(BundleError, match="FRONTEND_RELEASE_MISMATCH|FRONTEND_BYTES_MISMATCH"):
        runtime.health(None, root, manifest)


def test_matching_http_bytes_are_reported_and_each_entry_is_fetched(tmp_path, monkeypatch):
    root, manifest, _, calls = frontend_runtime(tmp_path, monkeypatch)
    proof = runtime.health(None, root, manifest)["frontend"]
    assert proof["release_id"] == manifest["release_id"]
    assert proof["html_sha256"] == manifest["files"]["frontend/index.html"]["sha256"]
    assert proof["entry_sha256"] == manifest["files"]["frontend/assets/index-unit.js"]["sha256"]
    assert [url.rsplit(str(manifest["ports"]["web"]), 1)[1] for url in calls] == [
        "/api/version", "/", "/assets/index-unit.js"]


@pytest.mark.parametrize("stale", ["/", "/assets/index-unit.js"])
def test_wrong_release_is_rejected_even_when_bytes_match_inventory(tmp_path, monkeypatch, stale):
    import hashlib
    root, manifest, payloads, _ = frontend_runtime(tmp_path, monkeypatch)
    data = frontend_bytes(manifest["source_sha"])[stale]
    payloads[stale] = data
    name = "frontend/" + ("index.html" if stale == "/" else stale[1:])
    manifest["files"][name] = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    with pytest.raises(BundleError, match="FRONTEND_RELEASE_MISMATCH"):
        runtime.health(None, root, manifest)


def test_release_uses_source_commit_utc_time_and_never_wall_clock(monkeypatch):
    from datetime import datetime
    from tools import docker_bundle_release_identity as identity
    class NoClock(datetime):
        @classmethod
        def now(cls, *args, **kwargs):
            pytest.fail("Wall clock must not determine release identity")
    monkeypatch.setattr(identity, "datetime", NoClock)
    monkeypatch.setenv("TZ", "Pacific/Honolulu")
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "0")
    expected = ("a" * 12 + "-20261027130000", "2026-10-27T13:00:00+00:00")
    assert identity.source_release_identity("a" * 40, "1793106000") == expected
    assert identity.source_release_identity("a" * 40, "1793106000") == expected
    assert identity.source_release_identity("b" * 40, "1793106000")[0] != expected[0]
    assert identity.source_release_identity("a" * 40, "1793106001")[0] != expected[0]


@pytest.mark.parametrize("timestamp", ["", "-1", "1793106000\n", "1.5", "999999999999", None])
def test_invalid_commit_time_fails_closed(timestamp):
    from tools.docker_bundle_release_identity import source_release_identity
    with pytest.raises(BundleError, match="SOURCE_COMMIT_TIME_INVALID"):
        source_release_identity("a" * 40, timestamp)


@pytest.mark.parametrize("sha", ["", "a" * 39, "g" * 40, "A" * 40])
def test_invalid_source_sha_cannot_define_release(sha):
    from tools.docker_bundle_release_identity import source_release_identity
    with pytest.raises(BundleError, match="SOURCE_SHA_INVALID"):
        source_release_identity(sha, "1793106000")


@pytest.mark.parametrize("entry", ["https://outside.invalid/a.js", "//outside.invalid/a.js",
    "/assets/../a.js", "/assets/%2e%2e/a.js", "/assets/index.js?query=1",
    "/assets/index.js#fragment", "/api/private.js", "/assets/index.js/sub", "assets/index.js"])
def test_frontend_cannot_redirect_asset_lookup(entry):
    from tools.docker_bundle_release_identity import frontend_entry
    release = "a" * 12 + "-20261027130000"
    html = frontend_bytes(release)["/"].replace(b"/assets/index-unit.js", entry.encode())
    with pytest.raises(BundleError, match="FRONTEND_ENTRY_INVALID"):
        frontend_entry(html, release)


@pytest.mark.parametrize("change", ["base", "duplicate-meta", "duplicate-entry", "duplicate-attribute", "inline-module"])
def test_ambiguous_html_never_selects_a_convenient_identity(change):
    from tools.docker_bundle_release_identity import frontend_entry
    release = "a" * 12 + "-20261027130000"
    html = frontend_bytes(release)["/"]
    if change == "base": html += b'<base href="https://outside.invalid/">'
    elif change == "duplicate-meta": html += ('<meta name="izo-release" content="' + release + '">').encode()
    elif change == "duplicate-entry": html += b'<script type="module" src="/assets/second.js"></script>'
    elif change == "duplicate-attribute": html = html.replace(b'name="izo-release"', b'name="old" name="izo-release"')
    else: html = html.replace(b' src="/assets/index-unit.js"', b'')
    with pytest.raises(BundleError, match="FRONTEND_(ENTRY_INVALID|RELEASE_MISMATCH|HTML_INVALID)"):
        frontend_entry(html, release)


def test_compiled_entry_rejects_conflicting_release_or_invalid_utf8():
    from tools.docker_bundle_release_identity import verify_javascript
    release = "a" * 12 + "-20261027130000"
    expected = frontend_bytes(release)["/assets/index-unit.js"]
    verify_javascript(expected, release)
    for raw in [b"const x='old';", expected + b';const stale="bbbbbbbbbbbb-20261027130000";']:
        with pytest.raises(BundleError, match="FRONTEND_RELEASE_MISMATCH"):
            verify_javascript(raw, release)
    with pytest.raises(BundleError, match="FRONTEND_JAVASCRIPT_INVALID"):
        verify_javascript(b"\xff", release)


@pytest.mark.parametrize("status,url,body,reason", [
    (200, "http://127.0.0.1:48614/", b"123456789", "HTTP_RESPONSE_TOO_LARGE"),
    (200, "http://127.0.0.1:48614/elsewhere", b"ok", "REDIRECT_FORBIDDEN"),
    (401, "http://127.0.0.1:48614/", b"private", "HEALTH_HTTP_STATUS_INVALID"),
])
def test_http_identity_reads_are_bounded_and_exact(status, url, body, reason):
    from tools.docker_bundle_release_identity import DeadlineHTTPHandler, read_http
    def open_response(request, **kwargs):
        response = SimpleNamespace(status=status, geturl=lambda: url, read1=BytesIO(body).read1,
                                   read_deadline=request.izo_read_deadline)
        return contextlib.nullcontext(response)
    opener = SimpleNamespace(open=open_response, handlers=[DeadlineHTTPHandler()])
    with pytest.raises(BundleError, match=reason):
        read_http(opener, "http://127.0.0.1:48614/", 8)


@pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
def test_urllib_redirect_is_refused_before_any_second_request(code):
    from email.message import Message
    from io import BytesIO
    from urllib.request import Request
    from tools.docker_bundle_release_identity import NoRedirect
    handler = NoRedirect()
    handler.parent = SimpleNamespace(open=lambda *args, **kwargs: pytest.fail("Redirect followed"))
    response = BytesIO(b"private redirect response")
    headers = Message(); headers["Location"] = "https://outside.invalid/should-never-be-opened"
    with pytest.raises(BundleError, match="REDIRECT_FORBIDDEN"):
        getattr(handler, "http_error_" + str(code))(
            Request("http://127.0.0.1:48614/"), response, code, "redirect", headers)
    assert response.closed


def test_exported_frontend_rejects_symlink_entry(tmp_path):
    from tools.docker_bundle_release_identity import verify_frontend_directory
    release = "a" * 12 + "-20261027130000"
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_bytes(frontend_bytes(release)["/"])
    (tmp_path / "elsewhere.js").write_bytes(frontend_bytes(release)["/assets/index-unit.js"])
    (tmp_path / "assets/index-unit.js").symlink_to(tmp_path / "elsewhere.js")
    with pytest.raises(BundleError, match="SYMLINK_PATH_FORBIDDEN"):
        verify_frontend_directory(tmp_path, release)


def test_installer_identity_helper_is_git_free_and_standalone(tmp_path):
    import shutil
    import subprocess
    import sys
    from pathlib import Path
    from tools import docker_bundle_release_identity as identity
    for name in ["docker_test_bundle_runtime.py", "docker_test_bundle_format.py",
                 "docker_test_bundle_images.py", "docker_bundle_release_identity.py"]:
        shutil.copyfile(Path(identity.__file__).parent / name, tmp_path / name)
    code = ("import sys;sys.path.insert(0,sys.argv[1]);import docker_test_bundle_runtime as r;"
            "import docker_bundle_release_identity as i;"
            "print(i.source_release_identity('a'*40,'1793106000')[0])")
    result = subprocess.run([sys.executable, "-I", "-B", "-c", code, str(tmp_path)],
                            capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "a" * 12 + "-20261027130000"


def test_web_build_keeps_source_sha_but_embeds_release_and_readable_nginx():
    from pathlib import Path
    import yaml
    root = Path(__file__).resolve().parents[1]
    dockerfile = (root / "ops/docker/dev/Dockerfile.web").read_text()
    assert 'FRONTEND_BUILD_LABEL="${IZO_RELEASE_ID}"' in dockerfile
    assert 'org.opencontainers.image.revision="${IZO_SOURCE_SHA}"' in dockerfile
    assert 'org.opencontainers.image.version="${IZO_RELEASE_ID}"' in dockerfile
    assert "COPY --chmod=0644 ops/docker/dev/nginx.shadow.conf /etc/nginx/nginx.conf" in dockerfile
    assert "USER 101:101" in dockerfile
    compose = yaml.safe_load((root / "ops/docker/dev/compose.shadow.yml").read_text())
    assert compose["services"]["web"]["build"]["args"]["IZO_RELEASE_ID"] == "${IZO_RELEASE_ID:?IZO_RELEASE_ID is required}"


@pytest.mark.parametrize("hidden", [
    '<script type="module" type="ignored" src="https://example.invalid/second.js"></script>',
    '<meta name="izo-release" name="ignored" content="bbbbbbbbbbbb-20261027130000">',
])
def test_duplicate_attributes_cannot_hide_browser_first_value(hidden):
    from tools.docker_bundle_release_identity import frontend_entry
    release = "a" * 12 + "-20261027130000"
    with pytest.raises(BundleError, match="FRONTEND_HTML_INVALID"):
        frontend_entry(frontend_bytes(release)["/"] + hidden.encode(), release)


def test_real_slow_stream_has_total_deadline_and_closes_connection():
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from threading import Event, Thread
    from time import monotonic
    from urllib.request import ProxyHandler, build_opener
    from tools.docker_bundle_release_identity import DeadlineHTTPHandler, NoRedirect, read_http
    stop, sent = Event(), []
    class SlowResponse(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.connection.settimeout(0.2)
            self.send_response(200)
            self.send_header("Content-Length", "12")
            self.end_headers()
            try:
                for index in range(12):
                    if stop.wait(0.025):
                        break
                    self.wfile.write(b"x"); self.wfile.flush()
                    sent.append(index)
            except (BrokenPipeError, ConnectionResetError, TimeoutError):
                pass
    server = HTTPServer(("127.0.0.1", 0), SlowResponse)
    thread = Thread(target=lambda: server.serve_forever(poll_interval=0.01))
    thread.start()
    try:
        opener = build_opener(ProxyHandler({}), NoRedirect(), DeadlineHTTPHandler())
        started = monotonic()
        with pytest.raises(BundleError, match="HTTP_READ_DEADLINE_EXCEEDED"):
            read_http(opener, "http://127.0.0.1:" + str(server.server_port) + "/", 100, timeout=0.08)
        assert monotonic() - started < 0.4
        assert len(sent) < 12
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)
    assert not thread.is_alive()



def test_actual_vite_static_template_literal_is_accepted():
    from tools.docker_bundle_release_identity import verify_javascript
    # Exact emitted fragment from clean 9f20dfd5a8d749134e07c320c1ed0e080f4ac777.
    release = "9f20dfd5a8d7-20261104195840"
    data = b"var Ce=`9f20dfd5a8d7-20261104195840`,we=`/api`,Te=new Set;"
    verify_javascript(data, release)


@pytest.mark.parametrize("body", [
    "`RELEASE${suffix}`",
    "`${prefix}RELEASE`",
    r"`\u0039f20dfd5a8d7-20261104195840`",
    r"`\x39f20dfd5a8d7-20261104195840`",
    r"`RELEASE\``",
    "`prefix-RELEASE`",
    "`RELEASE-suffix`",
    '`RELEASE"',
    "`RELEASE",
    "`bbbbbbbbbbbb-20261104195840`",
    "`RELEASE`,old=`bbbbbbbbbbbb-20261104195840`",
])
def test_nonstatic_or_wrong_javascript_release_fails(body):
    from tools.docker_bundle_release_identity import verify_javascript
    release = "9f20dfd5a8d7-20261104195840"
    data = ("var Ce=" + body.replace("RELEASE", release) + ";").encode()
    with pytest.raises(BundleError, match="FRONTEND_RELEASE_MISMATCH"):
        verify_javascript(data, release)


@pytest.mark.parametrize("quote", ["'", '"', "`"])
@pytest.mark.parametrize("backslashes", [1, 3])
def test_escaped_javascript_release_delimiter_fails(quote, backslashes):
    from tools.docker_bundle_release_identity import verify_javascript
    release = "9f20dfd5a8d7-20261104195840"
    data = ("var Ce=" + "\\" * backslashes + quote + release + quote + ";").encode()
    with pytest.raises(BundleError, match="FRONTEND_RELEASE_MISMATCH"):
        verify_javascript(data, release)
