"""External provider HTTP boundaries."""

from .ollama import fetch_ollama_models_status, ollama_base_url, request_ollama_chat_message
from .max_tls import build_max_http_verify, normalize_max_tls_trust_store
from .openrouter_image_client import request_openrouter_image
from .openrouter_image_io import load_openrouter_response_image, resolve_openrouter_reference_value
from .openrouter_images import (
    build_openrouter_image_request_metadata,
    build_openrouter_image_request_body,
    build_openrouter_image_request_plan,
    image_edit_influence_instruction,
    openrouter_descriptor_values,
    openrouter_ratio_size,
    requested_orientation,
    resolve_openrouter_image_model,
)
from .openrouter import (
    extract_openrouter_generation_cost,
    extract_openrouter_error_payload,
    fetch_openrouter_key_details,
    fetch_openrouter_image_model_documents,
    fetch_openrouter_text_models,
    format_openrouter_public_error,
    is_openrouter_size_error,
    normalize_openrouter_endpoint_capability,
    normalize_openrouter_image_response_metadata,
    normalize_openrouter_model_capability,
    openrouter_error_message,
    parse_openrouter_text_models,
    request_openrouter_chat_completion,
    select_openrouter_first_image,
)

__all__ = [
    "build_max_http_verify",
    "build_openrouter_image_request_metadata",
    "build_openrouter_image_request_body",
    "build_openrouter_image_request_plan",
    "fetch_ollama_models_status",
    "ollama_base_url",
    "request_ollama_chat_message",
    "request_openrouter_image",
    "extract_openrouter_generation_cost",
    "extract_openrouter_error_payload",
    "fetch_openrouter_key_details",
    "fetch_openrouter_image_model_documents",
    "fetch_openrouter_text_models",
    "format_openrouter_public_error",
    "is_openrouter_size_error",
    "image_edit_influence_instruction",
    "load_openrouter_response_image",
    "normalize_openrouter_endpoint_capability",
    "normalize_openrouter_image_response_metadata",
    "normalize_openrouter_model_capability",
    "normalize_max_tls_trust_store",
    "openrouter_descriptor_values",
    "openrouter_error_message",
    "openrouter_ratio_size",
    "parse_openrouter_text_models",
    "request_openrouter_chat_completion",
    "requested_orientation",
    "resolve_openrouter_image_model",
    "resolve_openrouter_reference_value",
    "select_openrouter_first_image",
]
