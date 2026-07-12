"""External provider HTTP boundaries."""

from .ollama import fetch_ollama_models_status, ollama_base_url

__all__ = ["fetch_ollama_models_status", "ollama_base_url"]
