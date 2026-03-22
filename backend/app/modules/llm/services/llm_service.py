"""
Provider-agnostic LLM service.

Uses the ``openai`` SDK directly for OpenAI-compatible providers (openai,
lm_studio, azure_openai) and ``litellm`` for everything else (anthropic,
ollama, bedrock, vertex).  This avoids litellm response-parsing issues with
non-standard OpenAI-compatible servers such as LM Studio.
"""

from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from time import monotonic

import structlog

logger = structlog.get_logger(__name__)

# Providers that speak the OpenAI chat-completions protocol natively.
_OPENAI_COMPAT_PROVIDERS = {"openai", "lm_studio", "azure_openai"}


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
    # OpenAI SDK path (openai, lm_studio, azure_openai)
    # ------------------------------------------------------------------

    def _get_openai_client(self):
        """Create an ``openai.AsyncOpenAI`` client for OpenAI-compatible providers."""
        from openai import AsyncOpenAI

        kwargs: dict = {"api_key": self.api_key}
        if self.base_url:
            # Ensure the base URL ends with /v1 — LM Studio and other
            # OpenAI-compatible servers expose /v1/chat/completions, but
            # users often enter just http://localhost:1234.
            base = self.base_url.rstrip("/")
            if not base.endswith("/v1"):
                base = f"{base}/v1"
            kwargs["base_url"] = base
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
        self, messages: list[LLMMessage], tools: list[dict], tool_choice: dict | str | None = None,
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
        choice = response.choices[0]
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
        self, messages: list[LLMMessage], tools: list[dict], tool_choice: dict | str | None = None,
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
