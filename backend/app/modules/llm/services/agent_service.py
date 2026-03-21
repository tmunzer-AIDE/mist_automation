"""
AI Agent service: LLM + MCP tool-calling loop.

The agent receives a task, connects to MCP servers for tools, and iteratively
calls the LLM with tool results until the task is complete or the iteration
limit is reached.
"""

import json
from dataclasses import dataclass, field

import structlog

from app.modules.llm.services.llm_service import LLMMessage, LLMService
from app.modules.llm.services.mcp_client import MCPClientWrapper, MCPTool

logger = structlog.get_logger(__name__)


@dataclass
class ToolCallRecord:
    """Record of a single tool call made by the agent."""

    tool: str
    arguments: dict
    result: str
    server: str


@dataclass
class AgentResult:
    """Result of an AI agent execution."""

    status: str  # "completed", "max_iterations", "error"
    result: str  # Final text response from the LLM
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    iterations: int = 0
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "result": self.result,
            "tool_calls": [{"tool": tc.tool, "arguments": tc.arguments, "result": tc.result} for tc in self.tool_calls],
            "iterations": self.iterations,
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

    async def run(self, task: str, system_prompt: str = "", context: dict | None = None) -> AgentResult:
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

        for iteration in range(self.max_iterations):
            logger.info("agent_iteration", iteration=iteration + 1, max=self.max_iterations)

            response = await self.llm.complete_with_tools(messages, all_tools)

            # Check if the LLM wants to call tools
            raw_tool_calls = response.tool_calls
            if not raw_tool_calls:
                # No tool calls — agent is done
                return AgentResult(
                    status="completed",
                    result=response.content,
                    tool_calls=tool_calls,
                    iterations=iteration + 1,
                )

            # Append the assistant message preserving raw tool_calls for the API protocol
            raw_tc_dicts = [
                {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
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
                    arguments = {}

                client = tool_server_map.get(tool_name)
                if not client:
                    result_text = f"Error: tool '{tool_name}' not found"
                else:
                    try:
                        result_text = await client.call_tool(tool_name, arguments)
                    except Exception as e:
                        logger.warning("agent_tool_call_failed", tool=tool_name, error=str(e))
                        result_text = f"Error: tool '{tool_name}' failed to execute"

                tool_calls.append(ToolCallRecord(
                    tool=tool_name,
                    arguments=arguments,
                    result=result_text[:2000],
                    server=client.config.name if client else "unknown",
                ))

                messages.append(LLMMessage(
                    role="tool",
                    content=result_text[:2000],
                    tool_call_id=tc.id,
                ))

        # Iteration limit reached — get final response without tools
        response = await self.llm.complete(messages)
        return AgentResult(
            status="max_iterations",
            result=response.content,
            tool_calls=tool_calls,
            iterations=self.max_iterations,
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
