"""Build the LLM client used for extraction.

Wraps a LangChain ``ChatOpenAI`` pointed at an OpenAI-compatible gateway whose
URL/key/model come from ``.env`` (``DEFAULT_BASE_URL`` / ``DEFAULT_API_KEY`` /
``DEFAULT_MODEL``).
"""

from __future__ import annotations
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI


def _disable_external_langchain_tracing() -> None:
    """
    Keep local runs limited to the configured AI Gateway unless tracing is
    explicitly enabled by the caller.
    """
    os.environ.setdefault("LANGCHAIN_TRACING", "false")
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")


def _required_env(name: str) -> str:
    """Return an env var or raise a clear error pointing to ``.env`` setup."""
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"Missing {name}. Set DEFAULT_BASE_URL, DEFAULT_API_KEY, "
            "and DEFAULT_MODEL in the environment or in .env."
        )
    return value


def build_gateway_llm(tools: Sequence[Any] | None = None, *, temperature: float = 0, timeout: float = 120, max_retries: int = 2,) -> Any:
    """
    Build an OpenAI-compatible LangChain chat model pointed at AI Gateway.

    The OpenAI client package is used only as the protocol implementation.
    Requests go to DEFAULT_BASE_URL, so this works with LiteLLM/corporate
    gateways and Qwen-compatible deployments.
    """
    load_dotenv(dotenv_path=Path.cwd() / ".env")
    _disable_external_langchain_tracing()

    llm = ChatOpenAI(
        base_url=_required_env("DEFAULT_BASE_URL"),
        api_key=_required_env("DEFAULT_API_KEY"),
        model=_required_env("DEFAULT_MODEL"),
        temperature=temperature,
        timeout=timeout,
        max_retries=max_retries
    )
    return llm.bind_tools(list(tools)) if tools else llm
