"""External provider HTTP boundaries."""

from .ollama import fetch_ollama_models_status, ollama_base_url, request_ollama_chat_message
from .openrouter_images import (
    build_openrouter_image_request_body,
    build_openrouter_image_request_plan,
    image_edit_influence_instruction,
    openrouter_descriptor_values,
    openrouter_ratio_size,
    requested_orientation,
)
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
    "build_openrouter_image_request_body",
    "build_openrouter_image_request_plan",
    "fetch_ollama_models_status",
    "ollama_base_url",
    "request_ollama_chat_message",
    "extract_openrouter_generation_cost",
    "extract_openrouter_error_payload",
    "fetch_openrouter_key_details",
    "fetch_openrouter_image_model_documents",
    "fetch_openrouter_text_models",
    "is_openrouter_size_error",
    "image_edit_influence_instruction",
    "normalize_openrouter_endpoint_capability",
    "normalize_openrouter_model_capability",
    "openrouter_descriptor_values",
    "openrouter_error_message",
    "openrouter_ratio_size",
    "parse_openrouter_text_models",
    "request_openrouter_chat_completion",
    "requested_orientation",
    "select_openrouter_first_image",
]
