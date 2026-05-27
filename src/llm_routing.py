"""Shared LiteLLM routing helpers for local provider routers."""

from __future__ import annotations

import os
import platform
from typing import Any
from urllib.parse import urlsplit, urlunsplit


DEFAULT_DIRECT_NVIDIA_MODEL = "openai/gpt-oss-120b"
DEFAULT_9ROUTER_API_BASE = "http://localhost:20128/v1"
DEFAULT_9ROUTER_MODEL = "nvidia/openai/gpt-oss-120b"
DEFAULT_9ROUTER_PROVIDER = "nvidia_nim"


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def use_9router() -> bool:
    return env_bool("USE_9ROUTER", False)


def running_in_wsl() -> bool:
    if platform.system().lower() != "linux":
        return False
    try:
        os_release = open("/proc/sys/kernel/osrelease", encoding="utf-8").read()
    except OSError:
        return False
    return "microsoft" in os_release.lower() or "wsl" in os_release.lower()


def windows_host_from_wsl() -> str | None:
    try:
        with open("/etc/resolv.conf", encoding="utf-8") as resolv_conf:
            for line in resolv_conf:
                parts = line.split()
                if len(parts) == 2 and parts[0] == "nameserver":
                    return parts[1]
    except OSError:
        return None
    return None


def remap_localhost_for_wsl(api_base: str) -> str:
    if env_bool("NINE_ROUTER_DISABLE_WSL_REMAP", False):
        return api_base

    parsed = urlsplit(api_base)
    if parsed.hostname not in {"localhost", "127.0.0.1"} or not running_in_wsl():
        return api_base

    windows_host = windows_host_from_wsl()
    if not windows_host:
        return api_base

    netloc = windows_host
    if parsed.port:
        netloc = f"{windows_host}:{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def nine_router_api_base() -> str:
    api_base = os.getenv("NINE_ROUTER_API_BASE", DEFAULT_9ROUTER_API_BASE).rstrip("/")
    return remap_localhost_for_wsl(api_base)


def nine_router_api_key() -> str:
    return os.getenv("NINE_ROUTER_API_KEY") or ""


def nine_router_provider() -> str:
    return os.getenv("NINE_ROUTER_LITELLM_PROVIDER", DEFAULT_9ROUTER_PROVIDER)


def nine_router_model() -> str:
    return os.getenv("NINE_ROUTER_MODEL", DEFAULT_9ROUTER_MODEL)


def prefixed_model(model: str, provider: str) -> str:
    if not provider or model.split("/", 1)[0] == provider:
        return model
    return f"{provider}/{model}"


def default_agent_model() -> str:
    if use_9router():
        return prefixed_model(nine_router_model(), nine_router_provider())
    return DEFAULT_DIRECT_NVIDIA_MODEL


def default_evaluator_model() -> str:
    if use_9router():
        return nine_router_model()
    return DEFAULT_DIRECT_NVIDIA_MODEL


def default_evaluator_provider() -> str:
    if use_9router():
        return nine_router_provider()
    return DEFAULT_9ROUTER_PROVIDER


def configure_litellm_router_env() -> None:
    """Expose 9Router through the env vars LiteLLM expects for a provider."""
    if not use_9router():
        return

    provider = nine_router_provider()
    api_base = nine_router_api_base()
    api_key = nine_router_api_key()

    if provider == "nvidia_nim":
        os.environ["NVIDIA_NIM_API_BASE"] = api_base
        os.environ["NVIDIA_NIM_API_KEY"] = api_key or "unused"
    elif provider == "openai_like":
        os.environ["OPENAI_LIKE_API_BASE"] = api_base
        os.environ["OPENAI_LIKE_API_KEY"] = api_key or "unused"
    elif provider == "openai":
        os.environ["OPENAI_API_BASE"] = api_base
        os.environ["OPENAI_API_KEY"] = api_key or "unused"


def completion_router_kwargs(model: str) -> dict[str, Any]:
    if not use_9router():
        return {}

    configure_litellm_router_env()
    return {
        "model": prefixed_model(model, nine_router_provider()),
        "api_base": nine_router_api_base(),
        # Local OpenAI-compatible routers often ignore auth, but LiteLLM still
        # expects a string for provider routes that use the OpenAI client.
        "api_key": nine_router_api_key() or "unused",
    }


def routing_summary(model: str | None = None) -> dict[str, Any]:
    if not use_9router():
        return {"use_9router": False}
    provider = nine_router_provider()
    raw_model = model or nine_router_model()
    return {
        "use_9router": True,
        "provider": provider,
        "model": prefixed_model(raw_model, provider),
        "api_base": nine_router_api_base(),
        "has_router_key": bool(nine_router_api_key()),
    }
