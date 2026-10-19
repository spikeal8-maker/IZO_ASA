"""Transport/receipt fault tests, not installed application or model acceptance."""
from copy import deepcopy
import io
import json
import unittest
from unittest.mock import MagicMock, Mock
from urllib.error import HTTPError, URLError

from tools import docker_clean_audio_features as audio


class UnreadBody(io.BytesIO):
    def read(self, *args):
        raise AssertionError("negative response body must remain unread")


class AudioFeatureTests(unittest.TestCase):
    def setUp(self):
        self.flow = audio.ProductFlow({"origin": "http://127.0.0.1:48125", "sourceSha": "a" * 40,
            "project": "izo-asa-shadow-audio", "isolatedData": True, "fakeProviderOnly": True,
            "networkEgressDenied": True, "externalEffectsDisabled": True})
        self.flow.saved = {"baseline": True}
        self.config = {"transcriptionPublished": True, "speechPublished": True,
                       "transcriptionMaxBytes": audio.MAX_AUDIO}
        self.manifest = {"ok": True, "apiVersion": "v1", "defaultRoute": "/phone/image", "workspaces": [
            {"id": name, "route": "/phone/" + name, "enabled": True, "navigation": "primary",
             "stage": "partial" if name == "audio" else "ready", "operations": ["speech_to_text"]}
            for name in ("image", "video", "chat", "audio")]}
        self.ledger_reads, self.ledger_changed = 0, False
        self.flow.owner.request = Mock(side_effect=self.respond)
        self.flow.guest.request = Mock(return_value={"httpStatus": 401})
        self.statuses = [401, 422, 422, 400, 400, 415, 415, 413]
        self.bodies, self.responses = [], []
        self.transport = Mock(side_effect=self.open)
        for client in self.flow.clients:
            client.opener.open = Mock(side_effect=self.transport)

    def respond(self, method, path):
        self.assertEqual(method, "GET")
        if path == audio.CONFIG:
            return deepcopy(self.config)
        if path == audio.PLATFORM:
            return deepcopy(self.manifest)
        self.assertEqual(path, audio.LEDGER)
        self.ledger_reads += 1
        return {"ok": True, "summary": {"balance": 10 - int(self.ledger_changed and self.ledger_reads > 1)},
                "items": []}

    def open(self, request, *, timeout):
        self.assertEqual(timeout, 8)
        status = self.statuses.pop(0)
        body = UnreadBody(b"private provider path and response")
        self.bodies.append(body)
        if status >= 400:
            raise HTTPError(request.full_url, status, "private diagnostic", {}, body)
        response = MagicMock(status=status)
        response.__enter__.return_value = response
        response.__exit__.side_effect = lambda *_: body.close()
        response.read.side_effect = body.read
        self.responses.append(response)
        return response

    def test_normal_negative_matrix_is_bounded_and_never_claims_transcription(self):
        row = {}
        audio.asr_validation(self.flow, row)
        self.assertEqual(list(row["cases"].values()), [401, 422, 422, 400, 400, 415, 415, 413])
        self.assertEqual((row["ownerLedger"], row["successfulTranscription"]), ("UNCHANGED", "NOT_VERIFIED"))
        calls = self.transport.call_args_list
        self.assertEqual(len(calls), 8)
        self.assertEqual(self.flow.owner.opener.open.call_count, 7)
        self.assertEqual(self.flow.guest.opener.open.call_count, 1)
        self.flow.other.opener.open.assert_not_called()
        self.assertNotIn(b'name="file"', calls[1].args[0].data)
        self.assertTrue(calls[2].args[0].full_url.endswith("?duration_ms=invalid"))
        for call, size in zip(calls[-2:], (audio.MAX_AUDIO, audio.MAX_AUDIO + 1)):
            request = call.args[0]
            self.assertEqual(request.get_header("Origin"), self.flow.origin)
            self.assertIn(b'filename="probe.invalid"', request.data)
            self.assertIn(b"Content-Type: application/octet-stream", request.data)
            content = request.data.partition(b"\r\n\r\n")[2].rsplit(b"\r\n--", 1)[0]
            self.assertEqual(len(content), size)
            self.assertLessEqual(len(request.data), audio.MAX_AUDIO + 512)
        self.assertTrue(all(body.closed for body in self.bodies))

    def test_unexpected_success_redirect_and_provider_failure_are_not_accepted(self):
        for status in (200, 302, 502):
            with self.subTest(status=status):
                self.setUp()
                self.statuses[5] = status
                row = {}
                with self.assertRaisesRegex(audio.ProductError, "UNSUPPORTED_STATUS_INVALID"):
                    audio.asr_validation(self.flow, row)
                self.assertEqual(row["cases"]["unsupported"], status)
                self.assertEqual(self.transport.call_count, 6)
                self.assertNotIn("private", json.dumps(row))
                self.assertTrue(all(body.closed for body in self.bodies))
                for response in self.responses:
                    response.read.assert_not_called()

    def test_disabled_publication_or_changed_limit_prevents_uploads(self):
        for key, value in (("transcriptionPublished", False), ("speechPublished", False),
                           ("transcriptionMaxBytes", audio.MAX_AUDIO + 1)):
            with self.subTest(key=key):
                self.setUp()
                self.config[key] = value
                with self.assertRaisesRegex(audio.ProductError, "AUDIO_PROFILE_MISMATCH"):
                    audio.asr_validation(self.flow, {})
                self.transport.assert_not_called()
                self.assertEqual(self.ledger_reads, 0)

    def test_owner_ledger_change_fails_after_valid_negative_statuses(self):
        self.ledger_changed = True
        with self.assertRaisesRegex(audio.ProductError, "ASR_LEDGER_CHANGED"):
            audio.asr_validation(self.flow, {})
        self.assertEqual(self.transport.call_count, 8)

    def test_target_mismatch_and_probe_overrun_prevent_http(self):
        self.flow.other.origin = "http://127.0.0.1:48126"
        for action in (audio.asr_validation, audio.platform_capabilities):
            with self.assertRaisesRegex(audio.ProductError, "CLIENT_TARGET_MISMATCH"):
                action(self.flow, {})
        self.flow.owner.request.assert_not_called()
        with self.assertRaisesRegex(audio.ProductError, "PROBE_TOO_LARGE"):
            audio._upload_status(self.flow.owner, "10000", b"x" * (audio.MAX_AUDIO + 2))
        self.transport.assert_not_called()

    def test_transport_error_is_fixed_and_not_retried(self):
        self.transport.side_effect = URLError("private transport credentials")
        with self.assertRaisesRegex(audio.ProductError, "^FEATURE_ASR_HTTP_UNAVAILABLE$"):
            audio.asr_validation(self.flow, {})
        self.assertEqual(self.transport.call_count, 1)

    def test_phone_manifest_is_only_capability_evidence(self):
        row = {}
        audio.platform_capabilities(self.flow, row)
        self.assertEqual((row["phoneThreeD"], row["renderedUi"], row["threeDCreateApi"]),
                         ("NOT_ADVERTISED", "NOT_VERIFIED", "NOT_VERIFIED"))
        self.flow.guest.request.assert_called_once_with("GET", audio.PLATFORM, expected=(401,))
        self.transport.assert_not_called()

    def test_manifest_rejects_3d_duplicates_hidden_metadata_and_disabled_audio(self):
        for fault in ("3d", "duplicate", "private", "disabled", "audio_operation"):
            with self.subTest(fault=fault):
                self.setUp()
                item = self.manifest["workspaces"][-1]
                if fault in ("3d", "duplicate"):
                    item["id"] = "3d" if fault == "3d" else "image"
                elif fault == "private":
                    item["_workerClaim"] = {"token": "private claim"}
                elif fault == "disabled":
                    item["enabled"] = False
                else:
                    item["operations"] = ["speech_to_text", "text_to_speech"]
                row = {}
                with self.assertRaises(audio.ProductError):
                    audio.platform_capabilities(self.flow, row)
                self.assertNotIn("private", json.dumps(row))


if __name__ == "__main__":
    unittest.main()
