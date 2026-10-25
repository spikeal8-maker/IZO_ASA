"""AST-extracted real /api/generate route; synthetic session identities only.

No imports of the long-lived backend/main.py module (so no server, billing,
background worker or provider is started). The actual route source AST is used.
"""
from __future__ import annotations

import __future__
import ast
import asyncio
import copy
from pathlib import Path
from types import SimpleNamespace

import pytest

MAIN = ast.parse((Path(__file__).parent / "main.py").read_text(encoding="utf-8"))


class HTTPError(Exception):
    def __init__(self, status_code, detail=None, **kwargs):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class AdmissionError(Exception):
    pass


def extracted_route():
    source = next(node for node in MAIN.body
                  if isinstance(node, ast.AsyncFunctionDef) and node.name == "generate")
    node = copy.deepcopy(source)
    node.decorator_list = []
    calls = []

    async def accept(req, trusted, key, runtime):
        calls.append(dict(trusted=trusted, key=key))
        return {"id": "job_synthetic", "userId": trusted["legacy_user_id"], "status": "queued"}

    namespace = {
        "normalize_generation_request": lambda req: req,
        "require_trusted_user": lambda request: request.trusted_user,
        "generation_admission": SimpleNamespace(admit=accept, AdmissionError=AdmissionError),
        "_generation_admission_runtime": lambda: object(),
        "COMFYUI_NATIVE4B_ONLY": False,
        "HTTPException": HTTPError,
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), "main.py", "exec",
                 flags=__future__.annotations.compiler_flag), namespace)
    return namespace["generate"], calls, namespace


def request(*, cookie_owner="account-B", expected=None):
    headers = {"Idempotency-Key": "synthetic-one-intent"}
    if expected is not None:
        headers["X-IZO-Expected-Internal-User"] = expected
    return SimpleNamespace(headers=headers, trusted_user={
        "internal_user_id": cookie_owner, "legacy_user_id": "legacy-" + cookie_owner})


@pytest.mark.parametrize("old_owner,new_cookie_owner", [
    ("account-A", "account-B"),
    ("account-B", "account-A"),
    ("account-A", "account-C"),
])
def test_owner_switch_before_paid_post_rejected_without_admission(old_owner, new_cookie_owner):
    generate, admissions, _ = extracted_route()
    req = SimpleNamespace(provider="openrouter")
    with pytest.raises(HTTPError) as caught:
        asyncio.run(generate(req, request(cookie_owner=new_cookie_owner, expected=old_owner)))
    assert caught.value.status_code == 409
    assert old_owner not in str(caught.value.detail)
    assert new_cookie_owner not in str(caught.value.detail)
    assert admissions == []


def test_matching_expected_account_enters_admission_exactly_once():
    generate, admissions, _ = extracted_route()
    result = asyncio.run(generate(SimpleNamespace(provider="openrouter"),
                                  request(cookie_owner="account-B", expected="account-B")))
    assert result["status"] == "queued"
    assert len(admissions) == 1
    assert admissions[0]["trusted"]["internal_user_id"] == "account-B"
    assert admissions[0]["key"] == "synthetic-one-intent"


def test_old_client_without_new_header_remains_session_authorized():
    generate, admissions, _ = extracted_route()
    result = asyncio.run(generate(SimpleNamespace(provider="openrouter"),
                                  request(cookie_owner="legacy-owner")))
    assert result["userId"] == "legacy-legacy-owner"
    assert len(admissions) == 1


def test_empty_expected_header_does_not_bypass_owner_guard():
    generate, admissions, _ = extracted_route()
    req = request(cookie_owner="account-A")
    req.headers["X-IZO-Expected-Internal-User"] = ""
    with pytest.raises(HTTPError) as caught:
        asyncio.run(generate(SimpleNamespace(provider="openrouter"), req))
    assert caught.value.status_code == 409
    assert not admissions


def test_guard_runs_before_local_provider_validation_or_gpu_access():
    generate, admissions, scope = extracted_route()
    scope["COMFYUI_NATIVE4B_ONLY"] = True
    scope["comfyui_native4b"] = SimpleNamespace(
        check_request=lambda **kwargs: pytest.fail("provider validation ran before owner fence"),
        Native4BError=Exception,
    )
    scope["_saved_setting"] = lambda _: {"imageEnabled": True}
    with pytest.raises(HTTPError) as caught:
        asyncio.run(generate(SimpleNamespace(provider="comfyui"),
                             request(cookie_owner="account-B", expected="account-A")))
    assert caught.value.status_code == 409
    assert admissions == []
