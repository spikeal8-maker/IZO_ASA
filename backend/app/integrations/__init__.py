"""External provider HTTP boundaries."""

from .ollama import fetch_ollama_models_status, ollama_base_url, request_ollama_chat_message
from .openrouter import (
    fetch_openrouter_key_details,
    fetch_openrouter_image_model_documents,
    fetch_openrouter_text_models,
    normalize_openrouter_endpoint_capability,
    normalize_openrouter_model_capability,
    parse_openrouter_text_models,
    request_openrouter_chat_completion,
)

__all__ = [
    "fetch_ollama_models_status",
    "ollama_base_url",
    "request_ollama_chat_message",
    "fetch_openrouter_key_details",
    "fetch_openrouter_image_model_documents",
    "fetch_openrouter_text_models",
    "normalize_openrouter_endpoint_capability",
    "normalize_openrouter_model_capability",
    "parse_openrouter_text_models",
    "request_openrouter_chat_completion",
]
