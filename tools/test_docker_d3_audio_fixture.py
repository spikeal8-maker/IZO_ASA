"""Startup configuration isolation and token cleanup; no installed speech claim."""
from copy import deepcopy
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools import docker_d3_audio_fixture as subject
from tools import docker_shadow_fixture as fixture


class AudioStartupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.environment = {"IZO_SHADOW_FIXTURE": subject.MARKER, "IZO_PROCESS_ROLE": "server",
            "APP_ENV": "test", "ENV": "test", "MODE": "test", "IZO_PHONE_TTS_PROVIDER": "fake"}
        self.provider = SimpleNamespace(base_url=subject.BASE, speech_token="owned-unit-capability-value")

    @unittest.skipUnless(os.name == "posix", "Container UID/token mode is verified on Linux")
    def test_token_is_private_path_only_and_removed_after_startup_failure(self):
        with patch.dict(os.environ, self.environment, clear=True), patch.object(tempfile, "tempdir", self.temporary.name):
            before = dict(os.environ)
            with self.assertRaisesRegex(RuntimeError, "deliberate-unit-failure"):
                with subject.audio_environment(self.provider):
                    token = Path(os.environ[subject.KEYS[2]])
                    self.assertEqual(token.stat().st_mode & 0o777, 0o600)
                    self.assertEqual(token.read_text(), self.provider.speech_token)
                    self.assertNotIn(self.provider.speech_token, repr(dict(os.environ)))
                    self.assertEqual(os.environ[subject.KEYS[0]], "http")
                    raise RuntimeError("deliberate-unit-failure")
            self.assertFalse(token.exists())
            self.assertEqual(dict(os.environ), before)

    def test_seed_preserves_other_sections_flags_and_uses_existing_api_writer_once(self):
        original = {"voice": {"transcriptionPublished": True, "speechPublished": True, "minRecordingSeconds": 1,
            "route": "local", "customRetained": "unchanged"}, "chat": {"route": "local", "model": "prior-model"},
            "improve": {"enabled": False}}
        saved = []
        def write(key, value):
            self.assertEqual(key, "assistant_models")
            saved.append(value)
        dispatcher = SimpleNamespace(database_lock=SimpleNamespace(closed=False), snapshot=lambda: {
            "role": "server", "localConsumer": False, "watchdog": "running"})
        app = SimpleNamespace(worker_started=False, generation_dispatcher=dispatcher, _save_setting=Mock(side_effect=write),
            assistant_models_config=lambda: deepcopy(saved[-1] if saved else original))
        startup = subject.StartupVoice(); startup.seed(app)
        result = saved[0]
        self.assertEqual(result["chat"], original["chat"])
        self.assertEqual(result["improve"], original["improve"])
        self.assertEqual(result["voice"]["customRetained"], "unchanged")
        self.assertEqual(result["voice"]["qwenBaseUrl"], subject.BASE)
        self.assertEqual(original["voice"]["route"], "local")
        with self.assertRaisesRegex(RuntimeError, "STARTUP_REJECTED"):
            startup.seed(app)
        self.assertEqual(app._save_setting.call_count, 1)

    def test_disabled_publication_or_unstarted_writer_cannot_be_seeded(self):
        for started, published, closed in ((True, True, False), (False, False, False), (False, True, True)):
            dispatcher = SimpleNamespace(database_lock=SimpleNamespace(closed=closed), snapshot=lambda: {
                "role": "server", "localConsumer": False, "watchdog": "running"})
            app = SimpleNamespace(worker_started=started, generation_dispatcher=dispatcher,
                _save_setting=Mock(), assistant_models_config=lambda: {
                "voice": {"transcriptionPublished": published, "speechPublished": True, "minRecordingSeconds": 1}})
            with self.subTest(started=started), self.assertRaises(RuntimeError):
                subject.StartupVoice().seed(app)
            app._save_setting.assert_not_called()

    def test_audio_marker_does_not_enable_external_chat_video_or_supplied_http_secret_paths(self):
        from tools.test_docker_shadow_fixture import safe_environment
        safe = {**safe_environment(), "IZO_SHADOW_FIXTURE": subject.MARKER, "IZO_PROCESS_ROLE": "server"}
        fixture.validate_environment(safe)
        for changes in ({"OLLAMA_BASE_URL": subject.BASE}, {"LOCAL_LTX_COMFYUI_BASE_URL": subject.BASE},
                        {"IZO_PHONE_TTS_HTTP_URL": "http://foreign.invalid"},
                        {"IZO_PHONE_TTS_HTTP_TOKEN_FILE": "/foreign/token"}, {"IZO_PROCESS_ROLE": "worker"}):
            with self.subTest(fields=tuple(changes)), self.assertRaises(RuntimeError):
                fixture.validate_environment({**safe, **changes})
        fixture.validate_environment(safe_environment())
