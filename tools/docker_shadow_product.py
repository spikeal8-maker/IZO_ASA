"""Real HTTP product checks for an explicitly attested, isolated fake-provider Shadow.

This tool neither starts Docker nor proves the supplied infrastructure attestation.
An executor must establish that attestation first. Keep ProductFlow in memory to
call verify_persistence after owned recreates; credentials never enter receipts.
"""
from __future__ import annotations

import argparse
import hashlib
import http.cookiejar
import json
import re
import secrets
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPCookieProcessor, ProxyHandler, Request, build_opener


class ProductError(RuntimeError):
    """Only fixed, secret-free diagnostic codes may cross the receipt boundary."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise ProductError(code)


def validate_target(attestation: dict) -> str:
    origin = attestation.get("origin", "")
    try:
        parsed = urlsplit(origin)
        valid_port = parsed.port is not None and 20000 <= parsed.port <= 65535
    except (ValueError, TypeError):
        raise ProductError("PRODUCT_TARGET_INVALID") from None
    require(parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}
            and valid_port and not parsed.username and not parsed.password
            and not parsed.query and not parsed.fragment and parsed.path in {"", "/"},
            "PRODUCT_TARGET_INVALID")
    require(isinstance(attestation.get("sourceSha"), str)
            and re.fullmatch(r"[0-9a-f]{40}", attestation["sourceSha"]) is not None,
            "PRODUCT_SOURCE_INVALID")
    require(isinstance(attestation.get("project"), str)
            and re.fullmatch(r"izo-asa-shadow-[a-z0-9][a-z0-9-]{2,39}", attestation["project"]) is not None,
            "PRODUCT_PROJECT_INVALID")
    for name in ("isolatedData", "fakeProviderOnly", "networkEgressDenied", "externalEffectsDisabled"):
        require(attestation.get(name) is True, "PRODUCT_ATTESTATION_REQUIRED")
    return origin.rstrip("/")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProductError("PRODUCT_REDIRECT_FORBIDDEN")


class HttpClient:
    def __init__(self, origin: str):
        self.origin = origin
        self.cookies = http.cookiejar.CookieJar()
        self.opener = build_opener(ProxyHandler({}), NoRedirect(), HTTPCookieProcessor(self.cookies))

    def request(self, method: str, path: str, payload: dict | None = None,
                *, expected: tuple[int, ...] = (200,), binary: bool = False):
        parsed = urlsplit(path)
        require(path.startswith("/") and not path.startswith("//") and not parsed.scheme
                and not parsed.netloc and not parsed.fragment, "PRODUCT_CROSS_ORIGIN_PATH")
        headers = {"Origin": self.origin, "Accept": "application/json"}
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload).encode("utf-8")
        request = Request(self.origin + path, data=data, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=8) as response:
                status, content = response.status, response.read(20_000_001)
        except HTTPError as error:
            status = error.code
            content = b""  # Error bodies can contain paths or personal information.
            error.close()
        except (OSError, URLError, TimeoutError):
            raise ProductError("PRODUCT_HTTP_UNAVAILABLE") from None
        require(status in expected, "PRODUCT_HTTP_STATUS_UNEXPECTED")
        require(len(content) <= 20_000_000, "PRODUCT_RESPONSE_TOO_LARGE")
        if status != 200:
            return {"httpStatus": status}
        if binary:
            return content
        try:
            value = json.loads(content)
        except (ValueError, UnicodeError):
            raise ProductError("PRODUCT_RESPONSE_INVALID") from None
        require(isinstance(value, dict), "PRODUCT_RESPONSE_INVALID")
        return value


def path_id(value) -> str:
    require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,120}", value) is not None,
            "PRODUCT_OBJECT_ID_INVALID")
    return value


class ProductFlow:
    def __init__(self, attestation: dict):
        self.origin = validate_target(attestation)
        self.source_sha, self.project = attestation["sourceSha"], attestation["project"]
        self.owner, self.other, self.guest = (HttpClient(self.origin) for _ in range(3))
        self.run_id = uuid.uuid4().hex
        self.credentials: list[tuple[HttpClient, str, str]] = []
        self.checks: dict = {}
        self.saved: dict = {}

    def register(self, client: HttpClient, index: int) -> dict:
        email, password = f"shadow-{self.run_id}-{index}@example.invalid", secrets.token_urlsafe(32)
        body = {"email": email, "password": password, "password_repeat": password,
                "accepted_terms": True, "accepted_privacy": True, "accepted_personal_data": True,
                "platform": "web_desktop"}
        result = client.request("POST", "/api/auth/password/register-v2", body)
        self.credentials.append((client, email, password))
        require(result.get("ok") is True and result.get("requires_email_verification") is False,
                "PRODUCT_FIXTURE_SIGNUP_REQUIRES_EXTERNAL_VERIFICATION")
        me = client.request("GET", "/api/me-v2")
        require(me.get("legacy_user_id") == result.get("legacy_user_id"), "PRODUCT_SESSION_IDENTITY_MISMATCH")
        return me

    def generate(self, payload: dict) -> dict:
        require(payload.get("provider") == "comfyui"
                and payload.get("mode") in {"text_to_image", "image_to_image"},
                "PRODUCT_PROVIDER_OR_MODE_FORBIDDEN")
        history_before = self.owner.request("GET", "/api/account/token-history-v2")
        started = self.owner.request("POST", "/api/generate", payload)
        job_id = path_id(started.get("id"))
        require(started.get("status") == "queued" and isinstance(started.get("queuePosition"), int)
                and isinstance(started.get("tokenCost"), int) and started["tokenCost"] > 0,
                "PRODUCT_QUEUE_CONTRACT_INVALID")
        self.other.request("GET", f"/api/jobs/{job_id}", expected=(404,))
        deadline, states = time.monotonic() + 60, {"queued"}
        while True:
            job = self.owner.request("GET", f"/api/jobs/{job_id}")
            state = job.get("status")
            require(state in {"queued", "running", "uploading", "sent_to_comfyui", "completed"},
                    "PRODUCT_JOB_TERMINAL_FAILURE")
            states.add(state)
            if state == "completed":
                break
            require(time.monotonic() < deadline, "PRODUCT_JOB_TIMEOUT")
            time.sleep(.2)
        image_id = path_id(job.get("resultImageId"))
        image = self.owner.request("GET", f"/api/gallery/{image_id}")
        require(image.get("id") == image_id and image.get("url") == job.get("resultUrl"),
                "PRODUCT_RESULT_PROVENANCE_MISMATCH")
        history_after = self.owner.request("GET", "/api/account/token-history-v2")
        summary_before, summary_after = history_before["summary"], history_after["summary"]
        require(summary_after["spentTokens"] - summary_before["spentTokens"] == started["tokenCost"]
                and summary_after["refundedTokens"] == summary_before["refundedTokens"],
                "PRODUCT_ACCOUNTING_MISMATCH")
        previous_ids = {item["id"] for item in history_before["items"]}
        charges = [item for item in history_after["items"] if item["id"] not in previous_ids
                   and item["spentTokens"] > 0]
        require(len(charges) == 1 and charges[0]["spentTokens"] == started["tokenCost"]
                and charges[0]["jobId"] == job_id[:10] + ("…" if len(job_id) > 10 else ""),
                "PRODUCT_LEDGER_CHARGE_MISMATCH")
        me = self.owner.request("GET", "/api/me-v2")
        require(me["account"]["token_balance"] == started["tokenBalance"]
                and me["account"]["daily_tokens_used"] == started["dailyTokensUsed"],
                "PRODUCT_ACCOUNT_BALANCE_MISMATCH")
        self.checks.setdefault("generation", []).append({"jobId": job_id, "imageId": image_id,
                "observedStates": sorted(states), "tokenCost": started["tokenCost"], "accounting": "PASS"})
        return image

    def media_hash(self, client: HttpClient, path: str) -> str:
        content = client.request("GET", path, binary=True)
        require(content.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff"))
                or (content[:4] == b"RIFF" and content[8:12] == b"WEBP"),
                "PRODUCT_MEDIA_NOT_IMAGE")
        return hashlib.sha256(content).hexdigest()

    def run(self) -> dict:
        html = self.guest.request("GET", "/", binary=True)
        require(f'content="{self.source_sha}"'.encode() in html, "PRODUCT_FRONTEND_SOURCE_MISMATCH")
        self.guest.request("GET", "/api/me-v2", expected=(401,))
        owner_me, other_me = self.register(self.owner, 1), self.register(self.other, 2)
        require(owner_me["legacy_user_id"] != other_me["legacy_user_id"], "PRODUCT_TWO_USERS_REQUIRED")
        for client, email, password in self.credentials:
            client.request("POST", "/api/auth/session/logout-v2", {})
            client.request("GET", "/api/me-v2", expected=(401,))
            logged_in = client.request("POST", "/api/auth/password/login-v2", {
                "email": email, "password": password, "platform": "web_desktop"})
            require(logged_in.get("ok") is True, "PRODUCT_LOGIN_FAILED")
            client.request("GET", "/api/me-v2")
        self.guest.request("POST", "/api/auth/password/login-v2", {
            "email": self.credentials[0][1], "password": "wrong-password", "platform": "web_desktop"}, expected=(401,))
        self.checks["auth"] = "PASS"
        payload = {"mode": "text_to_image", "provider": "comfyui", "prompt": "A blue ceramic cup on a plain table",
                   "width": 704, "height": 704, "steps": 4, "seed": 18731}
        image = self.generate(payload)
        image_id = path_id(image["id"])
        media_path = image["url"]
        original_hash = self.media_hash(self.owner, media_path)
        for client in (self.other, self.guest):
            client.request("GET", media_path, expected=(401, 403, 404))
        self.other.request("GET", f"/api/gallery/{image_id}", expected=(404,))
        self.other.request("POST", f"/api/gallery/{image_id}/favorite", {"isFavorite": True}, expected=(404,))
        self.other.request("POST", f"/api/gallery/{image_id}/use-as", {"target": "image_to_image"}, expected=(404,))
        self.owner.request("POST", f"/api/gallery/{image_id}/favorite", {"isFavorite": True})
        require(self.owner.request("GET", f"/api/gallery/{image_id}").get("isFavorite") is True,
                "PRODUCT_FAVORITE_NOT_PERSISTED")
        reuse = self.owner.request("POST", f"/api/gallery/{image_id}/use-as", {"target": "image_to_image"})
        require(reuse.get("ok") is True and reuse.get("inputImage") == media_path,
                "PRODUCT_REUSE_SOURCE_MISMATCH")
        reused = self.generate({**payload, "mode": "image_to_image", "inputImage1": reuse["inputImage"]})
        self.checks["ownershipGalleryReuse"] = "PASS"
        publication_payload = {"imageId": image_id, "title": "Shadow fixture ceramic cup",
                               "promptVisibility": "open", "allowRecreate": True}
        self.other.request("POST", "/api/feed/publications", publication_payload, expected=(404,))
        publication = self.owner.request("POST", "/api/feed/publications", publication_payload)
        require(publication.get("moderation") == "approved", "PRODUCT_DIRECT_PUBLICATION_NOT_APPROVED")
        publication_id = path_id(publication["publication"]["id"])
        feed = self.guest.request("GET", "/api/feed?type=fresh&limit=60")
        require(any(item.get("id") == publication_id for item in feed["items"]), "PRODUCT_GUEST_FEED_MISSING")
        self.media_hash(self.guest, f"/api/feed/media/{publication_id}")
        pending = self.owner.request("POST", "/api/feed/publications", {
            **publication_payload, "imageId": reused["id"], "title": "Shadow fixture review required"})
        require(pending.get("moderation") == "pending_review", "PRODUCT_MODERATION_BYPASSED")
        pending_id = path_id(pending["publication"]["id"])
        feed = self.guest.request("GET", "/api/feed?type=fresh&limit=60")
        require(all(item.get("id") != pending_id for item in feed["items"]), "PRODUCT_PENDING_FEED_LEAK")
        self.guest.request("GET", f"/api/feed/media/{pending_id}", expected=(404,))
        self.checks["publicationModeration"] = "PASS"
        self.saved = {"imageId": image_id, "mediaPath": media_path, "mediaHash": original_hash,
                      "publicationId": publication_id, "legacyUserId": owner_me["legacy_user_id"]}
        return self.checks

    def verify_persistence(self) -> dict:
        require(bool(self.saved), "PRODUCT_PERSISTENCE_BASELINE_MISSING")
        me = self.owner.request("GET", "/api/me-v2")
        require(me["legacy_user_id"] == self.saved["legacyUserId"], "PRODUCT_SESSION_LOST_AFTER_RECREATE")
        image = self.owner.request("GET", f"/api/gallery/{self.saved['imageId']}")
        require(image.get("isFavorite") is True and self.media_hash(self.owner, self.saved["mediaPath"])
                == self.saved["mediaHash"], "PRODUCT_DATA_LOST_AFTER_RECREATE")
        feed = self.guest.request("GET", "/api/feed?type=fresh&limit=60")
        require(any(item.get("id") == self.saved["publicationId"] for item in feed["items"]),
                "PRODUCT_PUBLICATION_LOST_AFTER_RECREATE")
        return {"status": "PASS", "mediaHash": self.saved["mediaHash"]}

    def close(self) -> dict:
        failures = 0
        for client, _, _ in self.credentials:
            try:
                client.request("POST", "/api/auth/session/logout-v2", {})
                client.request("GET", "/api/me-v2", expected=(401,))
            except ProductError:
                failures += 1
        self.credentials.clear()
        return {"sessionCleanup": "PASS" if not failures else "FAIL", "failedSessions": failures,
                "fixtureData": "RETAINED_IN_ATTESTED_ISOLATED_VOLUMES", "foreignResourcesTouched": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attestation", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    result = {"contract": "SHADOW-PRODUCT-FLOW-001", "status": "FAIL",
              "startedAt": datetime.now(timezone.utc).isoformat(), "dockerLifecycle": "NOT_RUN",
              "dockerAcceptance": "NOT_VERIFIED_BY_THIS_TOOL", "checks": {}}
    flow = None
    try:
        attestation = json.loads(args.attestation.read_text(encoding="utf-8"))
        require(isinstance(attestation, dict), "PRODUCT_ATTESTATION_INVALID")
        flow = ProductFlow(attestation)
        result.update(sourceSha=flow.source_sha, project=flow.project)
        result["checks"] = flow.run()
        result["status"] = "HTTP_SCENARIOS_PASS"
    except ProductError as error:
        result["errorCode"] = str(error)
    except (OSError, ValueError, KeyError, TypeError):
        result["errorCode"] = "PRODUCT_CONTRACT_OR_INPUT_INVALID"
    finally:
        if flow is not None:
            result["checks"] = flow.checks
            result["cleanup"] = flow.close()
            if result["cleanup"]["sessionCleanup"] != "PASS":
                result["status"] = "FAIL"
        result["finishedAt"] = datetime.now(timezone.utc).isoformat()
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"SHADOW_PRODUCT status={result['status']}")
    return 0 if result["status"] == "HTTP_SCENARIOS_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
