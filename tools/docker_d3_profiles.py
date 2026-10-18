"""Exact optional D3 overlays and original owned registration credentials."""
from copy import deepcopy
import json

from tools.docker_clean_admin_runtime import CapturedAdminShadow
from tools.docker_shadow_product import ProductFlow, require

MARKER = "controlled-chat-video-v1"
AUDIO = "controlled-audio-v1"
DELTA = {"IZO_SHADOW_FIXTURE": MARKER, "OLLAMA_BASE_URL": "http://127.0.0.1:48991",
    "LOCAL_LTX_ENABLED": "true", "LOCAL_LTX_COMFYUI_BASE_URL": "http://127.0.0.1:48991",
    "LOCAL_LTX_WORKFLOW_API_PATH": "/opt/izo/backend/workflows/ltx23_t2v_api.json"}
PROFILES = {MARKER: ("compose.d3-chat-video.yml", DELTA),
            AUDIO: ("compose.d3-audio.yml", {"IZO_SHADOW_FIXTURE": AUDIO})}


class D3Shadow(CapturedAdminShadow):
    active = False
    marker = MARKER

    def config(self):
        if not self.active:
            return super().config()
        approved_files = self.files
        try:
            self.files = approved_files[:-1]
            baseline = super().config()
        finally:
            self.files = approved_files
        actual = json.loads(self.compose("config", "--format", "json"))
        expected = deepcopy(baseline)
        expected["services"]["backend"]["environment"].update(PROFILES[self.marker][1])
        require(actual == expected, "D3_UNAPPROVED_PROFILE_CHANGE")
        return actual

    def activate(self, marker=MARKER):
        require(marker in PROFILES and (not self.active or self.marker == marker), "D3_PROFILE_REUSE_REJECTED")
        if not self.active:
            overlay = self.root / "ops/docker/dev" / PROFILES[marker][0]
            require(overlay.is_file() and not overlay.is_symlink(), "D3_PROFILE_OVERLAY_MISSING")
            self.files.append(overlay)
            self.active, self.marker = True, marker
        return self.up(build=False, recreate=True, application_only=True)


class RegisteredFlow(ProductFlow):
    def __init__(self, attestation):
        super().__init__(attestation)
        self.registration_credentials = []

    def register(self, client, index):
        require(client in (self.owner, self.other), "D3_FOREIGN_REGISTRATION_CLIENT")
        result = super().register(client, index)
        self.registration_credentials.append(self.credentials[-1])
        return result

    def browser_credentials(self):
        require(bool(self.saved) and len(self.registration_credentials) == 2
                and {id(row[0]) for row in self.registration_credentials} == {id(self.owner), id(self.other)},
                "D3_REAL_PRODUCT_BASELINE_REQUIRED")
        self.credentials[:] = self.registration_credentials

    def close(self):
        try:
            return super().close()
        finally:
            self.registration_credentials.clear()


def run_audio(seed, directory, images):
    from tools.docker_d3_audio_runtime import prove_audio_runtime
    from tools.docker_d3_orchestration import (checkpoint_step, fixed_provider_reader, owned_project, provider_checkpoint)
    with owned_project(seed, directory, "-audio", images) as (shadow, attestation, _code, report):
        flow = ProductFlow(attestation)
        step = lambda name, seconds, action: checkpoint_step(report, directory, name, seconds, action)
        try:
            def activate():
                retained = shadow.activate(AUDIO)
                return {"status": "PASS", "retainedRuntime": retained}
            started = step("audioProfile", 90, activate)
            if started["status"] != "PASS":
                return report
            def register():
                flow.register(flow.owner, 1)
                flow.register(flow.other, 2)
                return {"status": "PASS", "normalRegistrations": 2}
            registered = step("registration", 45, register)
            if registered["status"] != "PASS":
                return report
            reader = fixed_provider_reader(shadow, images)
            def checkpoint(value):
                from tools.docker_d3_images import save_private
                report["checks"]["audio"] = value
                save_private(directory / "receipt.json", report)
            step("audio", 150, lambda: prove_audio_runtime(flow, attestation=attestation,
                provider_receipt=reader, checkpoint=checkpoint))
            step("audioFinalProvider", 8, lambda: provider_checkpoint(directory, "audio-final", reader))
        finally:
            step("sessionCleanup", 60, lambda: {"status": flow.close()["sessionCleanup"]})
            for client in flow.clients:
                client.cookies.clear()
            flow.credentials.clear()
        expected = {"audioProfile", "registration", "audio", "audioFinalProvider", "sessionCleanup"}
        report["status"] = "PASS" if set(report["checks"]) == expected and all(
            row.get("status") == "PASS" for row in report["checks"].values()) else "FAIL"
    return report
