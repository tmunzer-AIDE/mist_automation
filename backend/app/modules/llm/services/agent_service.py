"""
AI Agent service: LLM + MCP tool-calling loop.

The agent receives a task, connects to MCP servers for tools, and iteratively
calls the LLM with tool results until the task is complete or the iteration
limit is reached.
"""

import json
import re
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import structlog

from app.modules.llm.services.llm_service import LLMMessage, LLMService
from app.modules.llm.services.mcp_client import MCPClientWrapper, MCPTool

# Type alias for the optional progress callback
ToolCallCallback = Callable[[str, dict], Coroutine[Any, Any, None]]

logger = structlog.get_logger(__name__)


@dataclass
class ToolCallRecord:
    """Record of a single tool call made by the agent."""

    tool: str
    arguments: dict
    result: str
    server: str
    is_error: bool = False


@dataclass
class AgentResult:
    """Result of an AI agent execution."""

    status: str  # "completed", "max_iterations", "error"
    result: str  # Final text response from the LLM
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    iterations: int = 0
    error: str | None = None
    thinking_texts: list[str] = field(default_factory=list)  # Intermediate reasoning per iteration

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "result": self.result,
            "tool_calls": [
                {"tool": tc.tool, "arguments": tc.arguments, "result": tc.result, "is_error": tc.is_error}
                for tc in self.tool_calls
            ],
            "iterations": self.iterations,
            "thinking_texts": self.thinking_texts,
            "error": self.error,
        }


class AIAgentService:
    """Executes an AI agent loop: LLM decides which tools to call, MCP executes them."""

    def __init__(
        self,
        llm: LLMService,
        mcp_clients: list[MCPClientWrapper],
        max_iterations: int = 10,
    ):
        self.llm = llm
        self.mcp_clients = mcp_clients
        self.max_iterations = max_iterations

    async def run(
        self,
        task: str,
        system_prompt: str = "",
        context: dict | None = None,
        on_tool_call: ToolCallCallback | None = None,
    ) -> AgentResult:
        """Run the agent loop until task completion or iteration limit."""
        # Gather tools from all MCP servers
        all_tools: list[dict] = []
        tool_server_map: dict[str, MCPClientWrapper] = {}

        for client in self.mcp_clients:
            try:
                tools = await client.list_tools()
                for tool in tools:
                    openai_tool = _mcp_tool_to_openai(tool)
                    all_tools.append(openai_tool)
                    tool_server_map[tool.name] = client
            except Exception as e:
                logger.warning("mcp_list_tools_failed", server=client.config.name, error=str(e))

        if not all_tools:
            return AgentResult(
                status="error",
                result="No tools available from connected MCP servers.",
                error="No tools found",
            )

        # Build initial messages
        sys_content = system_prompt or "You are an AI agent that uses tools to accomplish tasks."
        if context:
            sys_content += f"\n\nContext:\n```json\n{json.dumps(context, default=str)[:3000]}\n```"

        messages = [
            LLMMessage(role="system", content=sys_content),
            LLMMessage(role="user", content=task),
        ]

        tool_calls: list[ToolCallRecord] = []
        thinking_texts: list[str] = []

        # Content callback for streaming intermediate thinking tokens
        async def _on_content(chunk: str) -> None:
            if on_tool_call:
                await on_tool_call("thinking", {"content": chunk})

        for iteration in range(self.max_iterations):
            logger.info("agent_iteration", iteration=iteration + 1, max=self.max_iterations)

            if on_tool_call:

                response = await self.llm.stream_with_tools(messages, all_tools, on_content=_on_content)
            else:
                response = await self.llm.complete_with_tools(messages, all_tools)

            # Check if the LLM wants to call tools
            raw_tool_calls = response.tool_calls
            if not raw_tool_calls:
                content = response.content or ""

                # Try to recover tool calls from special-token format used by some local LLMs
                # e.g. <|tool_call>call:func{key:<|"|>val<|"|>}<tool_call|>
                recovered = _try_parse_special_token_tool_calls(content)
                if recovered:
                    logger.info(
                        "llm_special_token_tool_calls_recovered",
                        count=len(recovered),
                        iteration=iteration + 1,
                    )
                    raw_tool_calls = recovered
                    response.content = _strip_tool_call_tokens(content).strip()

                # Detect XML tool_call format — LLM failed to use function calling API
                elif "<tool_call>" in content or "<function=" in content:
                    logger.warning("llm_xml_tool_call_detected", iteration=iteration + 1)
                    return AgentResult(
                        status="error",
                        result=(
                            "The LLM attempted to call tools using an unsupported XML format "
                            "instead of the native function calling API. This typically means "
                            "the model does not support tool/function calling, or has "
                            "'Enable Thinking' turned on (which breaks tool calling in LM Studio). "
                            "Please check your LLM configuration."
                        ),
                        tool_calls=tool_calls,
                        iterations=iteration + 1,
                        thinking_texts=thinking_texts,
                    )

                else:
                    # No tool calls — agent is done
                    return AgentResult(
                        status="completed",
                        result=content,
                        tool_calls=tool_calls,
                        iterations=iteration + 1,
                        thinking_texts=thinking_texts,
                    )

            # Collect intermediate thinking text before tool execution
            if response.content:
                thinking_texts.append(response.content)

            # Append the assistant message preserving raw tool_calls for the API protocol
            raw_tc_dicts = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in raw_tool_calls
            ]
            messages.append(LLMMessage(role="assistant", content=response.content or "", tool_calls=raw_tc_dicts))

            # Execute each tool call and append results with tool_call_id
            for tc in raw_tool_calls:
                func = tc.function
                tool_name = func.name
                try:
                    arguments = json.loads(func.arguments) if isinstance(func.arguments, str) else func.arguments
                except json.JSONDecodeError:
                    messages.append(
                        LLMMessage(
                            role="tool",
                            content="Error: tool arguments were not valid JSON",
                            tool_call_id=tc.id,
                        )
                    )
                    continue

                client = tool_server_map.get(tool_name)
                server_name = client.config.name if client else "unknown"

                if on_tool_call:
                    await on_tool_call("tool_start", {"tool": tool_name, "server": server_name, "arguments": arguments})

                tool_is_error = False
                if not client:
                    result_text = f"Error: tool '{tool_name}' not found"
                    tool_is_error = True
                else:
                    try:
                        result_text, tool_is_error = await client.call_tool(tool_name, arguments)
                    except Exception as e:
                        logger.warning("agent_tool_call_failed", tool=tool_name, error=str(e))
                        result_text = f"Error: tool '{tool_name}' failed to execute"
                        tool_is_error = True

                if on_tool_call:
                    await on_tool_call(
                        "tool_end",
                        {
                            "tool": tool_name,
                            "server": server_name,
                            "status": "error" if tool_is_error else "success",
                            "result_preview": result_text[:2000],
                        },
                    )

                tool_calls.append(
                    ToolCallRecord(
                        tool=tool_name,
                        arguments=arguments,
                        result=result_text[:2000],
                        server=client.config.name if client else "unknown",
                        is_error=tool_is_error,
                    )
                )

                messages.append(
                    LLMMessage(
                        role="tool",
                        content=result_text[:2000],
                        tool_call_id=tc.id,
                    )
                )

        # Iteration limit reached — get final response without tools
        response = await self.llm.complete(messages)
        return AgentResult(
            status="max_iterations",
            result=response.content,
            tool_calls=tool_calls,
            iterations=self.max_iterations,
            thinking_texts=thinking_texts,
        )


def _mcp_tool_to_openai(tool: MCPTool) -> dict:
    """Convert an MCP tool definition to OpenAI function-calling format."""
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.input_schema or {"type": "object", "properties": {}},
        },
    }


# Regex matching the special-token tool call format produced by some local LLMs:
#   <|tool_call>call:func_name{key:val,key:<|"|>string<|"|>}<tool_call|>
_SPECIAL_TOKEN_TC_RE = re.compile(
    r"<\|tool_call>call:(\w+)\{(.*?)\}<tool_call\|>",
    re.DOTALL,
)


def _try_parse_special_token_tool_calls(content: str) -> list | None:
    """Attempt to parse the special-token tool call format used by some local LLMs.

    Converts <|tool_call>call:func{key:<|"|>val<|"|>}<tool_call|> into a list of
    SimpleNamespace objects that match the OpenAI tool_calls structure so the normal
    agent loop can execute them without modification.

    Returns None if no matches are found or if argument parsing fails.
    """
    matches = _SPECIAL_TOKEN_TC_RE.findall(content)
    if not matches:
        return None

    result = []
    for func_name, raw_args in matches:
        try:
            # Replace <|"|> string delimiters with standard JSON quotes
            normalized = raw_args.replace('<|"|>', '"')
            # Quote any unquoted object keys (word chars followed by colon)
            normalized = re.sub(r"(\w+)\s*:", r'"\1":', normalized)
            args_dict = json.loads("{" + normalized + "}")
        except Exception:
            logger.warning("special_token_tool_call_parse_failed", func=func_name, raw_args=raw_args[:200])
            return None

        result.append(
            SimpleNamespace(
                id=f"call_{func_name}_{uuid.uuid4().hex[:8]}",
                type="function",
                function=SimpleNamespace(name=func_name, arguments=json.dumps(args_dict)),
            )
        )

    return result or None


def _strip_tool_call_tokens(content: str) -> str:
    """Remove special-token tool call patterns from response content."""
    return _SPECIAL_TOKEN_TC_RE.sub("", content)
