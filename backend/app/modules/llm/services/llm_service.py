"""
Provider-agnostic LLM service.

Uses the ``openai`` SDK directly for OpenAI-compatible providers (openai,
lm_studio, azure_openai, mistral) and ``litellm`` for everything else
(anthropic, ollama, bedrock, vertex).  This avoids litellm response-parsing issues with
non-standard OpenAI-compatible servers such as LM Studio.
"""

from collections.abc import AsyncGenerator, Awaitable, Callable
from dataclasses import dataclass, field
import os
import ssl
from time import monotonic

import structlog

logger = structlog.get_logger(__name__)

# Providers that speak the OpenAI chat-completions protocol natively.
_OPENAI_COMPAT_PROVIDERS = {"openai", "lm_studio", "azure_openai", "mistral", "llama_cpp", "vllm", "openai_compatible"}

_FALSEY = {"0", "false", "no", "off"}


def _normalize_openai_base_url(provider: str, base_url: str | None) -> str | None:
    """Normalize OpenAI-compatible base URLs and apply provider defaults."""
    base = base_url
    if provider == "mistral" and not base:
        base = "https://api.mistral.ai/v1"
    if not base:
        return None

    normalized = base.rstrip("/")
    if not normalized.endswith("/v1"):
        normalized = f"{normalized}/v1"
    return normalized


def _resolve_openai_ssl_verify() -> bool | str | ssl.SSLContext:
    """Resolve TLS verification strategy for OpenAI-compatible HTTP clients.

    Priority:
    1) Explicit disable via MIST_LLM_SSL_VERIFY=false (debug only)
    2) Explicit CA bundle path via env var
    3) System trust store via truststore package (best for corporate MITM proxies)
    4) Library default verification behavior
    """
    if os.getenv("MIST_LLM_SSL_VERIFY", "true").strip().lower() in _FALSEY:
        logger.warning("llm_ssl_verification_disabled")
        return False

    ca_bundle = (
        os.getenv("MIST_LLM_CA_BUNDLE")
        or os.getenv("SSL_CERT_FILE")
        or os.getenv("REQUESTS_CA_BUNDLE")
        or os.getenv("CURL_CA_BUNDLE")
    )
    if ca_bundle:
        return ca_bundle

    if os.getenv("MIST_LLM_USE_SYSTEM_CERTS", "true").strip().lower() not in _FALSEY:
        try:
            import truststore

            return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        except Exception:
            logger.debug("llm_system_truststore_unavailable")

    return True


def _build_openai_client_kwargs(provider: str, api_key: str, base_url: str | None) -> dict:
    """Build kwargs for openai.AsyncOpenAI with shared TLS/base-url behavior."""
    import httpx

    kwargs: dict = {"api_key": api_key}
    normalized_base_url = _normalize_openai_base_url(provider, base_url)
    if normalized_base_url:
        kwargs["base_url"] = normalized_base_url

    verify = _resolve_openai_ssl_verify()
    if verify is not True:
        kwargs["http_client"] = httpx.AsyncClient(
            verify=verify,
            timeout=httpx.Timeout(60.0, connect=15.0),
            trust_env=True,
        )

    return kwargs


@dataclass
class LLMMessage:
    """A single message for the LLM API."""

    role: str  # "system", "user", "assistant", "tool"
    content: str
    tool_call_id: str | None = None  # Required for role="tool" messages
    tool_calls: list | None = None  # Raw tool_calls from assistant response


@dataclass
class LLMUsage:
    """Token usage from an LLM API call."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class LLMResponse:
    """Response from an LLM API call."""

    content: str
    model: str
    usage: LLMUsage = field(default_factory=LLMUsage)
    finish_reason: str = ""
    duration_ms: int = 0
    tool_calls: list | None = None


class LLMService:
    """Unified LLM interface. Provider-agnostic."""

    def __init__(
        self,
        provider: str,
        api_key: str,
        model: str,
        base_url: str | None = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ):
        self.provider = provider
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.temperature = temperature
        self.max_tokens = max_tokens

    # ------------------------------------------------------------------
    # OpenAI SDK path (openai, lm_studio, azure_openai, mistral)
    # ------------------------------------------------------------------

    def _get_openai_client(self):
        """Create an ``openai.AsyncOpenAI`` client for OpenAI-compatible providers."""
        from openai import AsyncOpenAI

        kwargs = _build_openai_client_kwargs(self.provider, self.api_key, self.base_url)
        return AsyncOpenAI(**kwargs)

    @staticmethod
    def _parse_openai_response(response, model_fallback: str, start: float) -> LLMResponse:
        """Extract an LLMResponse from an OpenAI SDK ChatCompletion object."""
        duration_ms = int((monotonic() - start) * 1000)
        usage = LLMUsage(
            prompt_tokens=response.usage.prompt_tokens if response.usage else 0,
            completion_tokens=response.usage.completion_tokens if response.usage else 0,
            total_tokens=response.usage.total_tokens if response.usage else 0,
        )
        choices = response.choices or []
        if not choices:
            return LLMResponse(content="", model=response.model or model_fallback, usage=usage, duration_ms=duration_ms)

        choice = choices[0]
        content = (choice.message.content if choice.message else None) or ""
        return LLMResponse(
            content=content,
            model=response.model or model_fallback,
            usage=usage,
            finish_reason=choice.finish_reason or "",
            duration_ms=duration_ms,
        )

    async def _complete_openai(self, messages: list[LLMMessage], json_mode: bool = False) -> LLMResponse:
        client = self._get_openai_client()
        kwargs: dict = {
            "model": self.model,
            "messages": self._messages_to_dicts(messages),
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if json_mode:
            # Some OpenAI-compat servers (LM Studio) reject json_object.
            # Try it, fall back to no response_format if it fails.
            kwargs["response_format"] = {"type": "json_object"}

        start = monotonic()
        try:
            response = await client.chat.completions.create(**kwargs)
        except Exception:
            if json_mode:
                # Retry without response_format — the system prompt already
                # instructs the model to return JSON.
                logger.info("json_mode_unsupported_retrying", model=self.model, provider=self.provider)
                kwargs.pop("response_format", None)
                try:
                    response = await client.chat.completions.create(**kwargs)
                except Exception:
                    logger.exception("llm_completion_failed", model=self.model, provider=self.provider)
                    raise
            else:
                logger.exception("llm_completion_failed", model=self.model, provider=self.provider)
                raise
        finally:
            await client.close()

        return self._parse_openai_response(response, self.model, start)

    async def _stream_openai(self, messages: list[LLMMessage]) -> AsyncGenerator[str, None]:
        client = self._get_openai_client()
        try:
            stream = await client.chat.completions.create(
                model=self.model,
                messages=self._messages_to_dicts(messages),
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                stream=True,
            )
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except Exception:
            logger.exception("llm_stream_failed", model=self.model, provider=self.provider)
            raise
        finally:
            await client.close()

    async def _complete_openai_with_tools(
        self,
        messages: list[LLMMessage],
        tools: list[dict],
        tool_choice: dict | str | None = None,
    ) -> LLMResponse:
        client = self._get_openai_client()
        start = monotonic()
        kwargs: dict = {
            "model": self.model,
            "messages": self._messages_to_dicts(messages),
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "tools": tools,
        }
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice
        try:
            response = await client.chat.completions.create(**kwargs)
        except Exception:
            logger.exception("llm_tool_completion_failed", model=self.model, provider=self.provider)
            raise
        finally:
            await client.close()

        result = self._parse_openai_response(response, self.model, start)
        choices = response.choices or []
        result.tool_calls = choices[0].message.tool_calls if choices and choices[0].message else None
        return result

    async def _stream_openai_with_tools(
        self,
        messages: list[LLMMessage],
        tools: list[dict],
        tool_choice: dict | str | None = None,
        on_content: Callable[[str], Awaitable[None]] | None = None,
    ) -> LLMResponse:
        """Stream a tool-calling completion, broadcasting content deltas via callback.

        Content deltas arrive before tool_call deltas in OpenAI-compatible streaming,
        so intermediate text (e.g. "Let me search...") is captured and broadcast
        even though non-streaming responses drop it.
        """
        client = self._get_openai_client()
        start = monotonic()
        kwargs: dict = {
            "model": self.model,
            "messages": self._messages_to_dicts(messages),
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "tools": tools,
            "stream": True,
        }
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice

        content_parts: list[str] = []
        # Accumulate tool calls: index → {id, function_name, arguments_parts}
        tc_accum: dict[int, dict] = {}
        finish_reason = ""

        try:
            stream = await client.chat.completions.create(**kwargs)
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if chunk.choices[0].finish_reason:
                    finish_reason = chunk.choices[0].finish_reason

                # Content tokens — broadcast immediately
                if delta and delta.content:
                    content_parts.append(delta.content)
                    if on_content:
                        await on_content(delta.content)

                # Tool call deltas — accumulate
                if delta and delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        if idx not in tc_accum:
                            tc_accum[idx] = {"id": "", "name": "", "arguments": ""}
                        entry = tc_accum[idx]
                        if tc_delta.id:
                            entry["id"] = tc_delta.id
                        if tc_delta.function:
                            if tc_delta.function.name:
                                entry["name"] = tc_delta.function.name
                            if tc_delta.function.arguments:
                                entry["arguments"] += tc_delta.function.arguments
        except Exception:
            logger.exception("llm_stream_tool_failed", model=self.model, provider=self.provider)
            raise
        finally:
            await client.close()

        # Assemble the response
        duration_ms = int((monotonic() - start) * 1000)
        content = "".join(content_parts)

        # Rebuild tool_calls as OpenAI SDK objects for compatibility with agent_service
        assembled_tool_calls = None
        if tc_accum:
            from types import SimpleNamespace

            assembled_tool_calls = []
            for _idx in sorted(tc_accum):
                entry = tc_accum[_idx]
                tc_obj = SimpleNamespace(
                    id=entry["id"],
                    function=SimpleNamespace(name=entry["name"], arguments=entry["arguments"]),
                    type="function",
                )
                assembled_tool_calls.append(tc_obj)

        return LLMResponse(
            content=content,
            model=self.model,
            usage=LLMUsage(),  # streaming doesn't provide usage in chunks
            finish_reason=finish_reason,
            duration_ms=duration_ms,
            tool_calls=assembled_tool_calls,
        )

    # ------------------------------------------------------------------
    # litellm path (anthropic, ollama, bedrock, vertex, etc.)
    # ------------------------------------------------------------------

    def _build_litellm_model(self) -> str:
        """Build the litellm model string with provider prefix."""
        prefix_map = {
            "anthropic": "anthropic/",
            "ollama": "ollama/",
            "bedrock": "bedrock/",
            "vertex": "vertex_ai/",
        }
        prefix = prefix_map.get(self.provider, "")
        return f"{prefix}{self.model}"

    def _build_litellm_kwargs(self, json_mode: bool = False) -> dict:
        kwargs: dict = {
            "model": self._build_litellm_model(),
            "api_key": self.api_key,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "drop_params": True,
        }
        if self.base_url:
            kwargs["api_base"] = self.base_url
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        return kwargs

    @staticmethod
    def _parse_litellm_response(response, model_fallback: str, start: float) -> LLMResponse:
        """Extract an LLMResponse from a litellm response object."""
        duration_ms = int((monotonic() - start) * 1000)
        usage = LLMUsage(
            prompt_tokens=response.usage.prompt_tokens if response.usage else 0,
            completion_tokens=response.usage.completion_tokens if response.usage else 0,
            total_tokens=response.usage.total_tokens if response.usage else 0,
        )
        choices = response.choices or []
        if not choices:
            return LLMResponse(content="", model=response.model or model_fallback, usage=usage, duration_ms=duration_ms)
        choice = choices[0]
        return LLMResponse(
            content=choice.message.content or "",
            model=response.model or model_fallback,
            usage=usage,
            finish_reason=choice.finish_reason or "",
            duration_ms=duration_ms,
            tool_calls=choice.message.tool_calls if hasattr(choice.message, "tool_calls") else None,
        )

    async def _complete_litellm(self, messages: list[LLMMessage], json_mode: bool = False) -> LLMResponse:
        import litellm

        kwargs = self._build_litellm_kwargs(json_mode=json_mode)
        kwargs["messages"] = self._messages_to_dicts(messages)

        start = monotonic()
        try:
            response = await litellm.acompletion(**kwargs)
        except Exception:
            logger.exception("llm_completion_failed", model=self.model, provider=self.provider)
            raise

        return self._parse_litellm_response(response, self.model, start)

    async def _stream_litellm(self, messages: list[LLMMessage]) -> AsyncGenerator[str, None]:
        import litellm

        kwargs = self._build_litellm_kwargs()
        kwargs["messages"] = self._messages_to_dicts(messages)
        kwargs["stream"] = True

        try:
            response = await litellm.acompletion(**kwargs)
            async for chunk in response:
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    yield delta.content
        except Exception:
            logger.exception("llm_stream_failed", model=self.model, provider=self.provider)
            raise

    async def _complete_litellm_with_tools(
        self,
        messages: list[LLMMessage],
        tools: list[dict],
        tool_choice: dict | str | None = None,
    ) -> LLMResponse:
        import litellm

        kwargs = self._build_litellm_kwargs()
        kwargs["messages"] = self._messages_to_dicts(messages)
        kwargs["tools"] = tools
        if tool_choice is not None:
            kwargs["tool_choice"] = tool_choice

        start = monotonic()
        try:
            response = await litellm.acompletion(**kwargs)
        except Exception:
            logger.exception("llm_tool_completion_failed", model=self.model, provider=self.provider)
            raise

        return self._parse_litellm_response(response, self.model, start)

    # ------------------------------------------------------------------
    # Public API — dispatches to the correct backend
    # ------------------------------------------------------------------

    @staticmethod
    def _messages_to_dicts(messages: list[LLMMessage]) -> list[dict]:
        result = []
        for m in messages:
            d: dict = {"role": m.role, "content": m.content}
            if m.tool_call_id:
                d["tool_call_id"] = m.tool_call_id
            if m.tool_calls:
                d["tool_calls"] = m.tool_calls
            result.append(d)
        return result

    def _is_openai_compat(self) -> bool:
        return self.provider in _OPENAI_COMPAT_PROVIDERS

    async def complete(self, messages: list[LLMMessage], json_mode: bool = False) -> LLMResponse:
        """Single completion request."""
        if self._is_openai_compat():
            return await self._complete_openai(messages, json_mode)
        return await self._complete_litellm(messages, json_mode)

    async def stream(self, messages: list[LLMMessage]) -> AsyncGenerator[str, None]:
        """Streaming completion, yields content chunks."""
        if self._is_openai_compat():
            async for chunk in self._stream_openai(messages):
                yield chunk
        else:
            async for chunk in self._stream_litellm(messages):
                yield chunk

    async def complete_with_tools(
        self,
        messages: list[LLMMessage],
        tools: list[dict],
        tool_choice: dict | str | None = None,
    ) -> LLMResponse:
        """Completion with tool/function calling support (for AI Agent node).

        ``tool_choice`` can force a specific tool call:
        - OpenAI format: ``{"type": "function", "function": {"name": "tool_name"}}``
        - Anthropic/litellm: ``{"type": "tool", "name": "tool_name"}``
        """
        if self._is_openai_compat():
            return await self._complete_openai_with_tools(messages, tools, tool_choice)
        return await self._complete_litellm_with_tools(messages, tools, tool_choice)

    async def stream_with_tools(
        self,
        messages: list[LLMMessage],
        tools: list[dict],
        tool_choice: dict | str | None = None,
        on_content: Callable[[str], Awaitable[None]] | None = None,
    ) -> LLMResponse:
        """Streaming completion with tools — broadcasts content deltas via callback.

        For OpenAI-compat providers, uses streaming to capture intermediate text
        that non-streaming mode drops when tool_calls are present.
        Falls back to non-streaming ``complete_with_tools`` for litellm providers.
        """
        if self._is_openai_compat():
            return await self._stream_openai_with_tools(messages, tools, tool_choice, on_content)
        return await self._complete_litellm_with_tools(messages, tools, tool_choice)
