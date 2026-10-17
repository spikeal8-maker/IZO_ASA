"""Fake-only HTTP speech protocol checks; no Windows synthesis or real provider."""
from __future__ import annotations

import io
import json
import socket
import threading
import time
import wave
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, ProxyHandler, build_opener
from http.server import BaseHTTPRequestHandler

import pytest

from backend.app.integrations import phone_speech_http as client
from tools.phone_speech_host import SpeechServer

TOKEN = "test-speech-token-" + "a" * 40


def wav_bytes():
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\0\0" * 80)
    return output.getvalue()


@pytest.fixture
def host(tmp_path):
    state = {"calls": [], "failure": False, "invalid": False}
    def fake(text, voice, rate, output):
        state["calls"].append((text, voice, rate))
        if state["failure"]:
            raise RuntimeError("PRIVATE-PROVIDER-DIAGNOSTIC")
        Path(output).write_bytes(b"invalid" if state["invalid"] else wav_bytes())
    work = tmp_path / "work"
    work.mkdir()
    server = SpeechServer(("127.0.0.1", 0), TOKEN, fake, work)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .02})
    thread.start()
    port = server.server_address[1]
    try:
        yield server, f"http://127.0.0.1:{port}", state, work
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert not list(work.iterdir())
        with socket.socket() as probe:
            probe.setsockopt(socket.SOL_SOCKET, getattr(socket, "SO_EXCLUSIVEADDRUSE", socket.SO_REUSEADDR), 1)
            probe.bind(("127.0.0.1", port))


def post(origin, body, token=TOKEN, *, path="/v1/speech", content_type="application/json"):
    payload = json.dumps(body).encode() if not isinstance(body, bytes) else body
    request = Request(origin + path, method="POST", data=payload,
                      headers={"Authorization": "Bearer " + token, "Content-Type": content_type})
    opener = build_opener(ProxyHandler({}))
    try:
        with opener.open(request, timeout=3) as response:
            return response.status, response.read()
    except HTTPError as error:
        try:
            return error.code, error.read()
        finally:
            error.close()


def test_client_host_fake_protocol_and_temp_cleanup(host, tmp_path, monkeypatch):
    _, origin, state, work = host
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1")
    output = tmp_path / "result.wav"
    client.synthesize(client.SpeechHttpSettings(origin, TOKEN), "Привет", "irina", 2, str(output))
    assert output.read_bytes() == wav_bytes()
    assert state["calls"] == [("Привет", "irina", 2)]
    assert not list(work.iterdir())


@pytest.mark.parametrize("text", ["я" * 4000, "😀" * 4000, "x" + "\x01" * 3999],
                         ids=["cyrillic", "non-bmp", "escaped-controls"])
def test_maximum_unicode_input_preserves_existing_character_contract(host, tmp_path, text):
    _, origin, state, _ = host
    output = tmp_path / "result.wav"
    client.synthesize(client.SpeechHttpSettings(origin, TOKEN), text, "pavel", 0, str(output))
    assert output.read_bytes() == wav_bytes()
    assert state["calls"] == [(text, "pavel", 0)]


@pytest.mark.parametrize("stage", ["headers", "body"])
def test_slow_input_has_absolute_deadline_and_releases_all_slots(host, stage):
    server, origin, state, _ = host
    sockets = []
    started = time.monotonic()
    try:
        for _ in range(4):
            connection = socket.create_connection(server.server_address, timeout=1)
            sockets.append(connection)
            if stage == "headers":
                connection.sendall(b"POST /v1/speech HTTP/1.0\r\nX-Slow: ")
            else:
                connection.sendall(("POST /v1/speech HTTP/1.0\r\nAuthorization: Bearer " + TOKEN
                                    + "\r\nContent-Type: application/json\r\nContent-Length: 100\r\n\r\n").encode())
        # Continued input arrives faster than the socket inactivity timeout.
        while time.monotonic() - started < 3.4:
            for connection in sockets:
                try:
                    connection.sendall(b"x")
                except OSError:
                    pass
            time.sleep(.2)
        for connection in sockets:
            try:
                assert connection.recv(4096) == b""
            except (ConnectionResetError, ConnectionAbortedError):
                pass  # Windows may reset a connection containing unread input.
        assert not state["calls"]
        assert post(origin, {"text": "after slow input", "voice": "irina", "rate": 0})[0] == 200
        assert len(state["calls"]) == 1
    finally:
        for connection in sockets:
            connection.close()


@pytest.mark.parametrize("body,status", [
    ({"text": "hello", "voice": "irina", "rate": 0}, 200),
    ({"text": " ", "voice": "irina", "rate": 0}, 400),
    ({"text": "a" * 4001, "voice": "irina", "rate": 0}, 400),
    ({"text": "hi", "voice": "not-a-voice", "rate": 0}, 400),
    ({"text": "hi", "voice": "pavel", "rate": True}, 400),
    ({"text": "hi", "voice": "pavel", "rate": 6}, 400),
    ({"text": "hi", "voice": "irina", "rate": 0, "output_path": "private"}, 400),
    (b"not-json", 400), (b"x" * (client.MAX_REQUEST_BYTES + 1), 400),
], ids=["valid", "blank", "too-long", "voice", "boolean-rate", "rate-range",
        "extra-key", "invalid-json", "oversized-body"])
def test_input_is_bounded_before_synthesis(host, body, status):
    _, origin, state, _ = host
    observed, content = post(origin, body)
    assert observed == status
    assert len(state["calls"]) == (1 if status == 200 else 0)
    assert status == 200 or content == b""


@pytest.mark.parametrize("token", ["", "wrong-secret", TOKEN + "x", "а" * 32])
def test_bad_authentication_never_synthesizes(host, token):
    _, origin, state, _ = host
    if not token.isascii():
        assert not client.authorized("Bearer " + token, TOKEN)
    else:
        assert post(origin, {"text": "hello", "voice": "irina", "rate": 0}, token)[0] == 401
    assert state["calls"] == []


@pytest.mark.parametrize("url", ["https://example.com:49231", "http://127.0.0.1:8000",
    "http://0.0.0.0:49231", "http://169.254.169.254:49231", "http://127.0.0.1:49231/path",
    "http://127.0.0.1:49231?token=sensitive", "http://user:secret@127.0.0.1:49231",
    "file:///private/path", "http://127.0.0.1:bad", "http://[::]:49231"])
def test_endpoint_config_rejects_public_metadata_credentials_and_implicit_paths(url, tmp_path):
    secret = tmp_path / "private-token"
    secret.write_text(TOKEN)
    with pytest.raises(client.SpeechHttpError, match="SPEECH_HTTP_CONFIG_INVALID") as error:
        client.load_settings({"IZO_PHONE_TTS_HTTP_URL": url, "IZO_PHONE_TTS_HTTP_TOKEN_FILE": str(secret)})
    assert "secret" not in str(error.value) and str(secret) not in str(error.value)


def test_explicit_secret_file_required_and_hidden_in_settings_repr(tmp_path):
    path = tmp_path / "token"
    path.write_text(TOKEN)
    settings = client.load_settings({"IZO_PHONE_TTS_HTTP_URL": "http://host.docker.internal:49231",
                                     "IZO_PHONE_TTS_HTTP_TOKEN_FILE": str(path)})
    assert settings.token == TOKEN and TOKEN not in repr(settings)
    for value in ("short", "secret\n" * 20, "x" * 513):
        path.write_text(value)
        with pytest.raises(client.SpeechHttpError, match="SPEECH_HTTP_SECRET_INVALID"):
            client.read_token_file(str(path))


@pytest.mark.parametrize("failure", ["failure", "invalid"])
def test_provider_failures_redacted_and_no_output_or_work_files(host, tmp_path, failure, capsys):
    _, origin, state, work = host
    state[failure] = True
    output = tmp_path / "result.wav"
    with pytest.raises(client.SpeechHttpError, match="SPEECH_HTTP_UNAVAILABLE") as error:
        client.synthesize(client.SpeechHttpSettings(origin, TOKEN), "PRIVATE-TEXT", "irina", 0, str(output))
    assert not output.exists() and not list(work.iterdir())
    assert str(error.value) == "SPEECH_HTTP_UNAVAILABLE"
    output_logs = capsys.readouterr()
    assert output_logs.out == output_logs.err == ""


@pytest.mark.parametrize("content", [b"", b"RIFFtestWAVE", wav_bytes()[:-5]])
def test_truncated_or_non_wave_is_rejected(content):
    with pytest.raises(client.SpeechHttpError, match="SPEECH_HTTP_AUDIO_INVALID"):
        client.validate_wave(content)


def test_busy_render_slots_fail_without_callback(host):
    server, origin, state, _ = host
    assert server.render_slots.acquire(False) and server.render_slots.acquire(False)
    try:
        assert post(origin, {"text": "hello", "voice": "irina", "rate": 0})[0] == 503
        assert not state["calls"]
    finally:
        server.render_slots.release()
        server.render_slots.release()


def test_wrong_path_or_content_type_rejected_before_callback(host):
    _, origin, state, _ = host
    body = {"text": "hello", "voice": "irina", "rate": 0}
    assert post(origin, body, path="/anything")[0] == 404
    assert post(origin, body, content_type="text/plain")[0] == 400
    assert not state["calls"]


def test_redirect_never_reaches_another_endpoint_or_leaks_location(host, tmp_path):
    server, origin, _, _ = host
    class Redirect(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass
        def do_POST(self):
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:1/PRIVATE-REDIRECT")
            self.end_headers()
    server.RequestHandlerClass = Redirect
    with pytest.raises(client.SpeechHttpError, match="^SPEECH_HTTP_REDIRECT_FORBIDDEN$"):
        client.synthesize(client.SpeechHttpSettings(origin, TOKEN), "hello", "irina", 0,
                          str(tmp_path / "speech.wav"))
    assert not (tmp_path / "speech.wav").exists()
