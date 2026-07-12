"""External provider HTTP boundaries."""

from .ollama import fetch_ollama_models_status, ollama_base_url, request_ollama_chat_message
from .openrouter import (
    extract_openrouter_generation_cost,
    extract_openrouter_error_payload,
    fetch_openrouter_key_details,
    fetch_openrouter_image_model_documents,
    fetch_openrouter_text_models,
    is_openrouter_size_error,
    normalize_openrouter_endpoint_capability,
    normalize_openrouter_model_capability,
    openrouter_error_message,
    parse_openrouter_text_models,
    request_openrouter_chat_completion,
    select_openrouter_first_image,
)

__all__ = [
    "fetch_ollama_models_status",
    "ollama_base_url",
    "request_ollama_chat_message",
    "extract_openrouter_generation_cost",
    "extract_openrouter_error_payload",
    "fetch_openrouter_key_details",
    "fetch_openrouter_image_model_documents",
    "fetch_openrouter_text_models",
    "is_openrouter_size_error",
    "normalize_openrouter_endpoint_capability",
    "normalize_openrouter_model_capability",
    "openrouter_error_message",
    "parse_openrouter_text_models",
    "request_openrouter_chat_completion",
    "select_openrouter_first_image",
]
