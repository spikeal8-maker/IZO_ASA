"""Failure bookkeeping tests; only the separate live API run can prove D3 results."""
from contextlib import ExitStack
from email.message import Message
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch
import wave

from tools import docker_clean_features as features


def flow():
    value = features.ProductFlow({"origin": "http://127.0.0.1:48125", "sourceSha": "a" * 40,
        "project": "izo-asa-shadow-features", "isolatedData": True, "fakeProviderOnly": True,
        "networkEgressDenied": True, "externalEffectsDisabled": True})
    value.saved = {"baseline": True}
    for client in value.clients:
        client.request = Mock()
    return value


class FeatureBookkeepingTests(unittest.TestCase):
    def execute(self, active, configure):
        value = flow()
        configure(value)
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            for name in ("health", "chat_history", "fake_speech", "commerce", "admin_boundary", "bot_webhooks", "video_config"):
                if name != active:
                    stack.enter_context(patch.object(features, name, return_value=None))
            receipt = Path(directory) / "features.json"
            result = features.prove_features(value, receipt)
            self.assertEqual(json.loads(receipt.read_text()), result)
            return result

    def test_unconditional_ok_does_not_override_failed_readiness(self):
        result = self.execute("health", lambda f: setattr(f.guest.request, "return_value", {"ok": True, "ready": False}))
        self.assertEqual(result["checks"]["health"]["status"], "FAIL")
        self.assertEqual(result["checks"]["health"]["errorCode"], "FEATURE_DATABASE_NOT_READY")
        self.assertEqual(result["status"], "FAIL")

    def test_video_500_is_retained_and_unverified_models_never_pass(self):
        result = self.execute("video_config", lambda f: setattr(f.owner.request, "return_value", {"httpStatus": 500}))
        self.assertEqual(result["checks"]["videoConfig"], {"status": "FAIL", "httpStatus": 500,
                                                          "errorCode": "FEATURE_VIDEO_CONFIG_HTTP_500"})
        self.assertEqual(result["checks"]["chatInference"]["status"], "BLOCKED")
        self.assertFalse(result["checks"]["chatInference"]["featureDisabled"])
        self.assertEqual(result["checks"]["threeD"]["status"], "NOT_VERIFIED")

    def test_failure_is_redacted_and_later_feature_checks_continue(self):
        for raw in ("secret/raw/body", "FEATURE_TOP_SECRET_RAW_DATA"):
            result = self.execute("health", lambda f: setattr(f.guest.request, "side_effect", RuntimeError(raw)))
            self.assertEqual(result["checks"]["health"]["errorCode"], "FEATURE_OPERATION_FAILED")
            self.assertEqual(result["checks"]["videoConfig"]["status"], "PASS")
            self.assertNotIn(raw, json.dumps(result))

    def test_prior_receipt_and_mismatched_target_prevent_http(self):
        value = flow()
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "features.json"
            receipt.write_text("original failure")
            with self.assertRaises(FileExistsError):
                features.prove_features(value, receipt)
            self.assertEqual(receipt.read_text(), "original failure")
            value.other.origin = "http://127.0.0.1:48126"
            with self.assertRaisesRegex(features.FeatureError, "CLIENT_TARGET_MISMATCH"):
                features.prove_features(value, Path(directory) / "new.json")
            for client in value.clients:
                client.request.assert_not_called()

    def test_chat_cleanup_runs_after_failure_and_cleanup_failure_remains_failed(self):
        for cleanup_fails, stale_title in ((False, False), (True, False), (False, True)):
            with self.subTest(cleanup_fails=cleanup_fails):
                value, row, state = flow(), {}, {"listed": False, "deleted": False}
                identifier = "f" * 32

                def request(method, path, payload=None, **kwargs):
                    if method == "POST":
                        state["title"] = payload["title"]
                        return {"ok": True, "thread": {"id": identifier, "title": payload["title"]}}
                    if method == "GET" and path == features.THREADS:
                        entries = [{"id": identifier}] if state["listed"] else []
                        state["listed"] = True
                        return {"ok": True, "threads": entries}
                    if method == "PATCH":
                        return {"ok": True, "thread": {"id": identifier, "title": payload["title"]}}
                    if method == "DELETE":
                        if cleanup_fails:
                            raise RuntimeError("private cleanup text")
                        state["deleted"] = True
                        return {"ok": True}
                    if state["deleted"]:
                        self.assertEqual(kwargs["expected"], (404,))
                        return {"httpStatus": 404}
                    if stale_title:
                        return {"ok": True, "thread": {"id": identifier, "title": state["title"]}, "messages": []}
                    raise RuntimeError("private read error")

                value.owner.request.side_effect = request
                with self.assertRaises(RuntimeError):
                    features.chat_history(value, row)
                self.assertEqual(row["threadCleanup"], "FAIL" if cleanup_fails else "PASS")
                self.assertEqual(row["errorCode"], "FEATURE_CHAT_READ_INVALID" if stale_title else "FEATURE_OPERATION_FAILED")
                self.assertNotIn("private", json.dumps(row))
                self.assertEqual(sum(call.args[0] == "DELETE" for call in value.owner.request.call_args_list), 1)

    def test_lost_create_response_discovers_and_cleans_only_its_new_thread(self):
        value, row, created, old, new = flow(), {}, {}, "a" * 32, "b" * 32
        def request(method, path, payload=None, **kwargs):
            if method == "POST":
                created.update(id=new, title=payload["title"])
                raise RuntimeError("private lost create response")
            if path == features.THREADS:
                return {"ok": True, "threads": [{"id": old, "title": "existing"}] + ([created] if created else [])}
            self.assertTrue(path.startswith(features.THREADS + "/" + new))
            return {"ok": True} if method == "DELETE" else {"httpStatus": 404}
        value.owner.request.side_effect = request
        with self.assertRaisesRegex(RuntimeError, "lost create response"):
            features.chat_history(value, row)
        self.assertEqual(row, {"errorCode": "FEATURE_OPERATION_FAILED", "threadCleanup": "PASS"})
        value.owner.request.assert_any_call("DELETE", features.THREADS + "/" + new, expected=(200, 404))
        self.assertEqual(sum(call.args[0] == "DELETE" for call in value.owner.request.call_args_list), 1)

    def test_speech_needs_no_store_and_exact_fake_wave_format(self):
        for cache, frames in (("public", 800), ("private, no-store", 799)):
            value, data = flow(), io.BytesIO()
            with wave.open(data, "wb") as audio:
                audio.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
                audio.writeframes(b"\0\0" * frames)
            value.owner.request.return_value = {"speechPublished": True, "speechMaxChars": 4000,
                                                "voices": [{"id": "irina"}, {"id": "pavel"}]}
            response = MagicMock(status=200)
            response.__enter__.return_value = response
            response.headers = Message()
            response.headers["Content-Type"], response.headers["Cache-Control"] = "audio/wav", cache
            response.read.return_value = data.getvalue()
            with patch.object(value.owner.opener, "open", return_value=response), self.assertRaises(features.FeatureError):
                features.fake_speech(value, {})
            response.__exit__.assert_called_once()
            value.guest.request.assert_any_call("POST", features.SPEECH,
                {"text": "Docker fixture voice", "voice": "irina", "rate": 0}, expected=(401,))


if __name__ == "__main__":
    unittest.main()
