"""Startup-only voice configuration in the separately owned audio fixture API."""
from contextlib import contextmanager
from copy import deepcopy
import os
from pathlib import Path
import stat
import tempfile

MARKER = "controlled-audio-v1"
BASE = "http://127.0.0.1:48991"
KEYS = ("IZO_PHONE_TTS_PROVIDER", "IZO_PHONE_TTS_HTTP_URL", "IZO_PHONE_TTS_HTTP_TOKEN_FILE")


def require(value):
    if not value:
        raise RuntimeError("D3_AUDIO_FIXTURE_STARTUP_REJECTED")


class StartupVoice:
    def __init__(self):
        self.seeded = False

    def seed(self, application):
        # The fixture registers this callback after main's ownership/init startup;
        # this call uses that same API writer, never a second SQLite connection owner.
        dispatcher = getattr(application, "generation_dispatcher", None)
        lock = getattr(dispatcher, "database_lock", None)
        require(not self.seeded and application.worker_started is False and lock is not None and not lock.closed)
        snapshot = dispatcher.snapshot()
        require(snapshot.get("role") == "server" and snapshot.get("localConsumer") is False
                and snapshot.get("watchdog") == "running")
        before = application.assistant_models_config()
        voice = before.get("voice", {})
        require(voice.get("transcriptionPublished") is True and voice.get("speechPublished") is True
                and type(voice.get("minRecordingSeconds")) is int and voice["minRecordingSeconds"] == 1)
        after = deepcopy(before)
        after["voice"].update(route="qwen", qwenModel="d3-protocol-asr", qwenBaseUrl=BASE, requestTimeoutSeconds=10)
        application._save_setting("assistant_models", after)
        require(application.assistant_models_config() == after)
        self.seeded = True


@contextmanager
def audio_environment(provider):
    """Only this process gets a path to an exclusive temporary token, before main import."""
    require(os.environ.get("IZO_SHADOW_FIXTURE") == MARKER and os.environ.get("IZO_PROCESS_ROLE") == "server"
            and all(os.environ.get(key) == "test" for key in ("APP_ENV", "ENV", "MODE"))
            and provider.base_url == BASE and isinstance(provider.speech_token, str)
            and 16 <= len(provider.speech_token) <= 256 and not any(c.isspace() for c in provider.speech_token))
    previous = {key: os.environ.get(key) for key in KEYS}
    descriptor, name = tempfile.mkstemp(prefix="izo-d3-speech-", suffix=".token")
    path = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="ascii") as target:
            os.chmod(path, 0o600)
            target.write(provider.speech_token)
        info = path.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid() and stat.S_IMODE(info.st_mode) == 0o600)
        os.environ.update({KEYS[0]: "http", KEYS[1]: BASE, KEYS[2]: str(path)})
        yield StartupVoice()
    finally:
        path.unlink(missing_ok=True)
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
