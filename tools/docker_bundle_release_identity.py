"""Source-derived release identity and bounded verification of real frontend bytes."""
from __future__ import annotations

import hashlib
import io
import os
import re
import stat
import time
from functools import partial
from http.client import HTTPConnection, HTTPResponse
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPHandler, HTTPRedirectHandler, Request

try:
    from tools.docker_test_bundle_format import BundleError, SHA, plain_path, require
except ModuleNotFoundError:
    from docker_test_bundle_format import BundleError, SHA, plain_path, require

HTML_LIMIT = 2 * 1024**2
JAVASCRIPT_LIMIT = 16 * 1024**2
RELEASE = re.compile(r"[0-9a-f]{12}-[0-9]{14}")
ENTRY = re.compile(r"/assets/[A-Za-z0-9][A-Za-z0-9._-]{0,200}\.js")


def source_release_identity(sha: str, commit_epoch: str) -> tuple[str, str]:
    """Use the exact source commit's UTC committer time, never packaging time."""
    require(SHA.fullmatch(sha or "") is not None, "SOURCE_SHA_INVALID")
    require(isinstance(commit_epoch, str) and re.fullmatch(r"[0-9]{1,12}", commit_epoch) is not None,
            "SOURCE_COMMIT_TIME_INVALID")
    try:
        committed = datetime.fromtimestamp(int(commit_epoch), timezone.utc)
    except (ValueError, OverflowError, OSError):
        raise BundleError("SOURCE_COMMIT_TIME_INVALID") from None
    release = sha[:12] + "-" + committed.strftime("%Y%m%d%H%M%S")
    require(RELEASE.fullmatch(release) is not None, "SOURCE_COMMIT_TIME_INVALID")
    return release, committed.isoformat()


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        response.close()
        raise BundleError("REDIRECT_FORBIDDEN")


def remaining(deadline: float) -> float:
    value = deadline - time.monotonic()
    require(value > 0, "HTTP_READ_DEADLINE_EXCEEDED")
    return value


class DeadlineReader(io.RawIOBase):
    """Bound every recv, including reads hidden inside header/chunk parsing."""
    def __init__(self, raw, sock, deadline):
        super().__init__()
        self.raw, self.sock, self.deadline = raw, sock, deadline

    def readable(self):
        return True

    def readinto(self, buffer):
        self.sock.settimeout(remaining(self.deadline))
        try:
            return self.raw.readinto(buffer)
        except TimeoutError:
            raise BundleError("HTTP_READ_DEADLINE_EXCEEDED") from None

    def close(self):
        try:
            self.raw.close()
        finally:
            super().close()


class DeadlineSocket:
    def __init__(self, sock, deadline):
        self.sock, self.deadline = sock, deadline

    def makefile(self, mode):
        return io.BufferedReader(DeadlineReader(
            self.sock.makefile(mode, buffering=0), self.sock, self.deadline))


class DeadlineResponse(HTTPResponse):
    def __init__(self, sock, *args, deadline, **kwargs):
        super().__init__(DeadlineSocket(sock, deadline), *args, **kwargs)
        self.read_deadline = deadline


class DeadlineConnection(HTTPConnection):
    def __init__(self, *args, deadline, **kwargs):
        self.deadline = deadline
        kwargs["timeout"] = remaining(deadline)
        super().__init__(*args, **kwargs)
        self.response_class = partial(DeadlineResponse, deadline=deadline)

    def connect(self):
        self.timeout = remaining(self.deadline)
        super().connect()
        self.sock.settimeout(remaining(self.deadline))

    def send(self, data):
        if self.sock is not None:
            self.sock.settimeout(remaining(self.deadline))
        return super().send(data)


class DeadlineHTTPHandler(HTTPHandler):
    def http_open(self, request):
        return self.do_open(
            partial(DeadlineConnection, deadline=request.izo_read_deadline), request)


def read_http(opener, url: str, limit: int, *, timeout: float = 8.0) -> bytes:
    require(type(timeout) in {int, float} and 0 < timeout <= 8.0, "HTTP_TIMEOUT_INVALID")
    target = urlsplit(url)
    require(target.scheme == "http" and target.hostname == "127.0.0.1"
            and target.username is None and target.password is None
            and target.port is not None and 0 < target.port <= 65535, "HEALTH_ORIGIN_INVALID")
    require(any(isinstance(handler, DeadlineHTTPHandler) for handler in getattr(opener, "handlers", [])),
            "HTTP_READ_DEADLINE_UNAVAILABLE")
    deadline = time.monotonic() + timeout
    request = Request(url)
    request.izo_read_deadline = deadline
    with opener.open(request, timeout=remaining(deadline)) as response:
        require(getattr(response, "read_deadline", None) == deadline, "HTTP_READ_DEADLINE_UNAVAILABLE")
        require(response.geturl() == url, "REDIRECT_FORBIDDEN")
        require(response.status == 200, "HEALTH_HTTP_STATUS_INVALID")
        chunks, size = [], 0
        while True:
            remaining(deadline)
            chunk = response.read1(min(65536, limit + 1 - size))
            remaining(deadline)
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            require(size <= limit, "HTTP_RESPONSE_TOO_LARGE")
    return b"".join(chunks)


class FrontendHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.releases, self.entries, self.has_base = [], [], False

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag in {"meta", "script"}:
            require(len(values) == len(attrs), "FRONTEND_HTML_INVALID")
        if tag == "base":
            self.has_base = True
        if tag == "meta" and values.get("name") == "izo-release":
            self.releases.append(values.get("content"))
        if tag == "script" and values.get("type") == "module":
            self.entries.append(values.get("src"))


def frontend_entry(html: bytes, release: str) -> str:
    require(RELEASE.fullmatch(release or "") is not None, "RELEASE_ID_INVALID")
    require(len(html) <= HTML_LIMIT, "HTTP_RESPONSE_TOO_LARGE")
    parser = FrontendHTML()
    try:
        parser.feed(html.decode("utf-8"))
        parser.close()
    except UnicodeError:
        raise BundleError("FRONTEND_HTML_INVALID") from None
    require(parser.releases == [release], "FRONTEND_RELEASE_MISMATCH")
    require(not parser.has_base and len(parser.entries) == 1
            and isinstance(parser.entries[0], str) and ENTRY.fullmatch(parser.entries[0]) is not None,
            "FRONTEND_ENTRY_INVALID")
    return parser.entries[0][1:]


def verify_javascript(data: bytes, release: str) -> None:
    require(len(data) <= JAVASCRIPT_LIMIT, "HTTP_RESPONSE_TOO_LARGE")
    try:
        text = data.decode("utf-8")
    except UnicodeError:
        raise BundleError("FRONTEND_JAVASCRIPT_INVALID") from None
    literals = {release.join((quote, quote)) for quote in ("'", '"')}
    require(any(value in text for value in literals)
            and set(RELEASE.findall(text)) == {release}, "FRONTEND_RELEASE_MISMATCH")


def verify_frontend(read, release: str, expected: dict | None = None) -> dict:
    """Check metadata and compiled entry, and optionally the pinned ZIP inventory."""
    def asset(name, limit):
        data = read(name, limit)
        require(isinstance(data, bytes) and len(data) <= limit, "HTTP_RESPONSE_TOO_LARGE")
        digest = hashlib.sha256(data).hexdigest()
        if expected is not None:
            require(expected.get("frontend/" + name) == {"size": len(data), "sha256": digest},
                    "FRONTEND_BYTES_MISMATCH")
        return data, digest

    html, html_digest = asset("index.html", HTML_LIMIT)
    entry = frontend_entry(html, release)
    javascript, javascript_digest = asset(entry, JAVASCRIPT_LIMIT)
    verify_javascript(javascript, release)
    return {"release_id": release, "html_sha256": html_digest,
            "entry_path": "/" + entry, "entry_sha256": javascript_digest}


def verify_frontend_directory(root: Path, release: str) -> dict:
    def read(name, limit):
        path = plain_path(root / name)
        require(path.is_file(), "FRONTEND_ASSET_MISSING")
        with path.open("rb") as stream:
            require(stat.S_ISREG(os.fstat(stream.fileno()).st_mode), "FRONTEND_ASSET_INVALID")
            return stream.read(limit + 1)
    return verify_frontend(read, release)


def verify_served_frontend(opener, origin: str, manifest: dict) -> dict:
    def read(name, limit):
        return read_http(opener, origin + ("/" if name == "index.html" else "/" + name), limit)
    return verify_frontend(read, manifest["release_id"], manifest["files"])
