"""Build the LLM client used for extraction.

Wraps a LangChain ChatOpenAI pointed at an OpenAI-compatible gateway.
Uses environment variables DEFAULT_BASE_URL, DEFAULT_API_KEY, DEFAULT_MODEL.
"""

from __future__ import annotations
import os
from pathlib import Path
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI


def _disable_external_langchain_tracing():
    os.environ.setdefault("LANGCHAIN_TRACING", "false")
    os.environ.setdefault("LANGCHAIN_TRACING_V2", "false")

def _required_env(name):
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Missing {name}. Set DEFAULT_BASE_URL, DEFAULT_API_KEY, and DEFAULT_MODEL in .env")
    return value


def build_gateway_llm(temperature: float = 0, timeout: float = 120, max_retries: int = 2):
    load_dotenv(dotenv_path=Path.cwd() / ".env")
    _disable_external_langchain_tracing()
    return ChatOpenAI(
        base_url=_required_env("DEFAULT_BASE_URL"),
        api_key=_required_env("DEFAULT_API_KEY"),
        model=_required_env("DEFAULT_MODEL"),
        temperature=temperature,
        timeout=timeout,
        max_retries=max_retries
    )
