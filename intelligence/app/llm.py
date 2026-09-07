"""LLM factory. Single place that constructs ChatAnthropic instances."""

from __future__ import annotations

from langchain_anthropic import ChatAnthropic

from .settings import get_settings


def get_llm(
    temperature: float = 0.0,
    max_tokens: int = 4096,
    *,
    streaming: bool = False,
    timeout: float = 120,
) -> ChatAnthropic:
    """Construct a ChatAnthropic client.

    Long generations (large max_tokens) must stream. A non-streaming request is held
    open as one blocking read; the Anthropic API interrupts non-streaming requests past
    ~10 minutes, and a short client read timeout cuts it off even sooner. The Seguin deal
    (2026-06-09 post-mortem) failed exactly here: a 16384-token structured generate call
    read-timed-out at 120s, retried, and gave up. Streaming keeps the connection fed
    chunk-by-chunk so the read clock never expires and the API does not interrupt it.
    """
    s = get_settings()
    return ChatAnthropic(
        model=s.anthropic_model,
        api_key=s.anthropic_api_key,
        temperature=temperature,
        max_tokens=max_tokens,
        streaming=streaming,
        default_request_timeout=timeout,
        max_retries=3,
    )
