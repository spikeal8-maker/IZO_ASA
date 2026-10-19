"""Contract counterexamples; no installed application or model execution is claimed."""
import base64
import copy
from email.message import Message
import io
import json
from unittest import TestCase, main
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from tools import docker_d3_audio_provider as provider
from tools import docker_d3_audio_runtime as runtime
from tools.docker_shadow_product import ProductError, ProductFlow


def headers(mime="application/json", **extras):
    value = Message()
    value["Content-Type"] = mime
    for name, text in extras.items():
        value[name] = text
    return value


def request_audio(raw):
    return {"model": provider.ASR_MODEL, "temperature": 0, "max_tokens": 1000,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": "Transcribe the Russian speech exactly. Return only the transcript."},
            {"type": "audio_url", "audio_url": {"url": "data:audio/wav;base64," + base64.b64encode(raw).decode()}}]}]}


def new_provider():
    # Construction only. The tests below never bind these ports or contact HTTP.
    return provider.AudioProvider(bind="127.0.0.1", port=48991, control_port=48992, lifetime_seconds=300)


def receipt(fixture):
    return copy.deepcopy({"fixture": provider.MARKER, "lifetimeSeconds": 300, "provider": fixture.receipt()})


def transcript(fixture, index):
    raw = provider.wave_bytes(index, 16000 if index == 2 else 8000)
    body = json.dumps(request_audio(raw)).encode()
    return fixture._provider("POST", "/v1/chat/completions", {"content-type": "application/json"}, body)


def speech(fixture, case):
    body = json.dumps(provider.speech_request(case)).encode()
    return fixture._provider("POST", "/v1/speech", {"content-type": "application/json",
        "authorization": "Bearer " + fixture.speech_token}, body)


def completed_fixture():
    fixture = new_provider()
    before = receipt(fixture)
    for index in range(1, 5):
        transcript(fixture, index)
    results = {}
    for case, _rate in provider.SPEECH_CASES:
        status, content, _mime = speech(fixture, case)
        results["tts_" + case] = {"wave": provider.wave_facts(content) if status == 200 else None}
    return fixture, before, receipt(fixture), results


class ProviderContracts(TestCase):
    def test_pcm_shapes_nonwav_container_and_distinct_inputs(self):
        self.assertTrue(provider.OGG.startswith(b"OggS"))
        self.assertEqual(provider.digest(provider.OGG), "3c3c8badf0c43620c96aa90db6a7edf0690241447a341c038c3368d6719dd620")
        facts = [provider.wave_facts(provider.wave_bytes(index)) for index in range(1, 7)]
        self.assertEqual(len({row["pcmSha256"] for row in facts}), 6)
        self.assertTrue(all(row["sampleRate"] == row["frames"] == 8000 and row["bytes"] == 16044 for row in facts))
        with self.assertRaises(provider.RequestError):
            provider.wave_facts(provider.OGG)

    def test_case_sequence_and_private_error_body_do_not_enter_receipt(self):
        fixture, before, after, results = completed_fixture()
        self.assertEqual(runtime.correlate(before, after, results)["speechRequests"], 3)
        self.assertEqual([row["httpStatus"] for row in after["provider"]["audio"]["asr"]], [200, 200, 503, 200])
        encoded = json.dumps(after)
        for hidden in (provider.CANARY, "D3_CANARY", fixture.speech_token, fixture.control_token, "D3 audio protocol:"):
            self.assertNotIn(hidden, encoded)
        for operation in (lambda: transcript(fixture, 1), lambda: speech(fixture, "irina")):
            with self.assertRaises(provider.RequestError) as error:
                operation()
            self.assertEqual(error.exception.status, 409)

    def test_asr_rejects_external_url_wrong_model_oversized_or_unconverted_audio(self):
        cases = []
        external = request_audio(provider.wave_bytes(1))
        external["messages"][0]["content"][1]["audio_url"]["url"] = "http://127.0.0.1:1/private/D3_CANARY"
        cases.append(json.dumps(external).encode())
        wrong = request_audio(provider.wave_bytes(1)); wrong["model"] = "unapproved-model"
        cases.extend((json.dumps(wrong).encode(), b"x" * 65537, json.dumps(request_audio(provider.OGG)).encode()))
        for body in cases:
            fixture = new_provider()
            with self.subTest(length=len(body)), self.assertRaises(provider.RequestError):
                fixture._provider("POST", "/v1/chat/completions", {"content-type": "application/json"}, body)
            self.assertEqual(fixture.receipt()["audio"]["asr"], [])

    def test_tts_requires_exact_auth_input_and_integer_rate(self):
        for payload, authorization in ((provider.speech_request("irina"), "wrong"),
                ({"text": "private D3_CANARY", "voice": "irina", "rate": -1}, None),
                ({**provider.speech_request("failure"), "rate": False}, None),
                ({**provider.speech_request("irina"), "extra": "value"}, None)):
            fixture = new_provider()
            with self.subTest(payload=payload), self.assertRaises(provider.RequestError):
                fixture._provider("POST", "/v1/speech", {"content-type": "application/json",
                    "authorization": authorization or "Bearer " + fixture.speech_token}, json.dumps(payload).encode())
            self.assertEqual(fixture.receipt()["audio"]["speech"], [])

    def test_rejects_unowned_bind_and_lifetime(self):
        for override in ({"bind": "0.0.0.0"}, {"lifetime_seconds": 301}, {"port": 443}):
            kwargs = {"bind": "127.0.0.1", "port": 48991, "control_port": 48992, "lifetime_seconds": 300, **override}
            with self.assertRaises(ValueError):
                provider.AudioProvider(**kwargs)


class EvidenceContracts(TestCase):
    def test_receipt_rejects_replay_swapped_pcm_wrong_body_and_unrelated_submit(self):
        _fixture, before, after, results = completed_fixture()
        mutations = (
            lambda v: v["provider"]["audio"].update(instanceId="0" * 32),
            lambda v: v["provider"]["audio"]["asr"][1]["wave"].update(pcmSha256="0" * 64),
            lambda v: v["provider"]["audio"]["asr"][1].update(requestSha256=v["provider"]["audio"]["asr"][0]["requestSha256"]),
            lambda v: v["provider"]["audio"]["speech"][0].update(requestSha256="0" * 64),
            lambda v: v["provider"]["audio"].update(asr=v["provider"]["audio"]["asr"][:-1]),
            lambda v: v["provider"]["jobs"].append({"foreign": True}),
            lambda v: v["provider"]["counts"].update(audio_asr_requests=5),
        )
        for index, mutate in enumerate(mutations):
            changed = copy.deepcopy(after); mutate(changed)
            with self.subTest(index=index), self.assertRaises(ProductError):
                runtime.correlate(before, changed, results)
        with self.assertRaises(ProductError):
            runtime.correlate(after, after, results)

    def test_profile_and_model_execution_cannot_be_relabeled(self):
        valid = receipt(new_provider())
        for mutate in (lambda v: v.update(fixture="controlled-comfyui-v1"),
                lambda v: v["provider"]["audio"].update(modelExecution=True),
                lambda v: v["provider"]["audio"].update(lifetimeSeconds=301),
                lambda v: v.update(provider=[])):
            value = copy.deepcopy(valid); mutate(value)
            with self.assertRaises(ProductError):
                runtime.admitted_audio(value)

    def test_error_reader_accepts_only_fixed_expected_errors(self):
        for value, expected_ok in (({"detail": runtime.ASR_ERROR}, True), ({"detail": provider.CANARY}, False),
                ({"detail": runtime.ASR_ERROR, "debug": provider.CANARY}, False)):
            error = HTTPError("http://127.0.0.1:49201" + runtime.ASR_PATH, 502, "controlled", headers(),
                              io.BytesIO(json.dumps(value).encode()))
            client = Mock(origin="http://127.0.0.1:49201")
            client.opener.open.side_effect = error
            with patch.object(runtime.time, "monotonic", return_value=0):
                if expected_ok:
                    content, _ = runtime.exchange(client, runtime.ASR_PATH, b"bounded", "audio/wav", 502, 1)
                    self.assertIsNone(content)
                else:
                    with self.assertRaisesRegex(ProductError, "^D3_AUDIO_ERROR_NOT_REDACTED$"):
                        runtime.exchange(client, runtime.ASR_PATH, b"bounded", "audio/wav", 502, 1)
            self.assertTrue(error.fp.closed)

    def test_unexpected_error_body_is_not_read_and_cross_route_is_rejected(self):
        stream = Mock()
        error = HTTPError("http://127.0.0.1:49201", 500, "controlled", headers(), stream)
        client = Mock(origin="http://127.0.0.1:49201"); client.opener.open.side_effect = error
        with patch.object(runtime.time, "monotonic", return_value=0):
            with self.assertRaisesRegex(ProductError, "D3_AUDIO_HTTP_RESPONSE_INVALID"):
                runtime.exchange(client, runtime.ASR_PATH, b"x", "audio/wav", 502, 1)
            stream.read.assert_not_called()
            with self.assertRaisesRegex(ProductError, "D3_AUDIO_REQUEST_INVALID"):
                runtime.exchange(client, "/api/private", b"x", "audio/wav", 200, 1)
        self.assertEqual(client.opener.open.call_count, 1)

    def test_late_http_response_cannot_establish_pass(self):
        response = io.BytesIO(b"{}")
        response.status, response.headers = 200, headers()
        client = Mock(origin="http://127.0.0.1:49201")
        client.opener.open.return_value = response
        with patch.object(runtime.time, "monotonic", side_effect=[0.0, 3.0]):
            with self.assertRaisesRegex(ProductError, "D3_AUDIO_DEADLINE_EXCEEDED"):
                runtime.exchange(client, runtime.ASR_PATH, b"x", "audio/wav", 200, 2.0)
        self.assertTrue(response.closed)


class FlowContracts(TestCase):
    def exercise(self, *, change_account=False, late_receipt=False, false_cost=False):
        fixture, before, after, results = completed_fixture()
        attestation = {"origin": "http://127.0.0.1:49201", "sourceSha": "a" * 40,
            "project": "izo-asa-shadow-audio-unit", "isolatedData": True, "fakeProviderOnly": True,
            "networkEgressDenied": True, "externalEffectsDisabled": True}
        flow = ProductFlow(attestation)
        flow.account_snapshot = Mock(side_effect=[{"balance": 10}, {"balance": 9 if change_account else 10}])
        flow.owner.request = Mock(return_value={"speechPublished": True, "transcriptionPublished": True})
        snapshots, clock, calls = [], [0.0], []
        def callback():
            calls.append(True)
            if len(calls) == 1:
                return before
            if late_receipt:
                clock[0] = 6.0
            return after
        def exchange(_client, path, body, _mime, expected, _deadline):
            if path == runtime.ASR_PATH:
                case = next(case for case in runtime.ROUTE_ASR_CASES if runtime.upload(case)[0] == body)
                payload = {"ok": True, "text": provider.TRANSCRIPTS.get(case), "model": provider.ASR_MODEL,
                    "provider": "qwen", "usage": {"prompt_tokens": 0, "completion_tokens": 0},
                    "actualCostUsd": False if false_cost else 0.0}
                return (json.dumps(payload).encode() if expected == 200 else None), headers()
            case = json.loads(body)["text"].rsplit(" ", 1)[1]
            content = provider.wave_bytes(5 if case == "irina" else 6) if expected == 200 else None
            return content, headers("audio/wav", **{"Cache-Control": "private, no-store"})
        with patch.object(runtime, "exchange", side_effect=exchange), patch.object(runtime.time, "monotonic", side_effect=lambda: clock[0]):
            result = runtime.prove_audio_runtime(flow, attestation=attestation, provider_receipt=callback,
                                               checkpoint=lambda value: snapshots.append(copy.deepcopy(value)))
        return result, snapshots

    def test_success_means_controlled_protocol_only_and_preserves_account(self):
        result, snapshots = self.exercise()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["ownerAccountAndLedger"], "UNCHANGED")
        self.assertEqual(len(result["cases"]), 8)
        self.assertEqual(result["realSpeechRecognition"], "NOT_VERIFIED")
        self.assertEqual(result["realVoiceSynthesis"], "NOT_VERIFIED")
        self.assertEqual(result["audioUiResumeCancel"], "NOT_RUN")
        self.assertEqual(snapshots[-1], result)

    def test_charge_or_late_receipt_fails_but_preserves_prior_http_checkpoints(self):
        for options, code in (({"change_account": True}, "D3_AUDIO_ACCOUNT_OR_LEDGER_CHANGED"),
                ({"late_receipt": True}, "D3_AUDIO_RECEIPT_TIMEOUT")):
            result, snapshots = self.exercise(**options)
            self.assertEqual(result["status"], "FAIL")
            self.assertEqual(result["errorCode"], code)
            self.assertEqual(len(result["cases"]), 8)
            self.assertEqual(snapshots[-1], result)

    def test_boolean_cost_is_not_accepted_as_measured_zero(self):
        result, _snapshots = self.exercise(false_cost=True)
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["errorCode"], "D3_AUDIO_ASR_RESULT_INVALID")


if __name__ == "__main__":
    main()
