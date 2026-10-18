"""Task-local provider transport, shared only by a claimed execution session."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar


_transport = ContextVar("generation_provider_transport", default=None)


def executor_bound() -> bool:
    return _transport.get() is not None


@contextmanager
def bind(transport):
    marker = _transport.set(transport)
    try:
        yield
    finally:
        _transport.reset(marker)


def client_options(options: dict, explicit=None) -> dict:
    """Existing callers retain their HTTP configuration outside a worker claim."""
    selected = _transport.get()
    if selected is not None and explicit is not None and selected is not explicit:
        raise RuntimeError("GENERATION_PROVIDER_TRANSPORT_OVERRIDE_FORBIDDEN")
    selected = selected if selected is not None else explicit
    result = dict(options)
    if selected is not None:
        result["transport"] = selected
        result["trust_env"] = False
    return result
