"""Tool for dynamically connecting an MCP server at runtime."""

from contextlib import AsyncExitStack
from typing import Any

from loguru import logger

from nanobot.agent.tools.base import Tool, tool_parameters
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.schema import StringSchema, tool_parameters_schema


@tool_parameters(
    tool_parameters_schema(
        server_name=StringSchema("Unique name for this MCP server (e.g. 'google-calendar')"),
        command=StringSchema("Command to run (e.g. 'npx')"),
        args=StringSchema("JSON array of arguments (e.g. '[\"@cocal/google-calendar-mcp\"]')"),
        env=StringSchema("JSON object of extra environment variables (e.g. '{\"KEY\": \"value\"}')"),
        required=["server_name", "command"],
    )
)
class ConnectMcpTool(Tool):
    """Dynamically connect an MCP server and register its tools for this session."""

    def __init__(self, registry: ToolRegistry, stacks: dict[str, AsyncExitStack]):
        self._registry = registry
        self._stacks = stacks

    @property
    def name(self) -> str:
        return "connect_mcp"

    @property
    def description(self) -> str:
        return (
            "Connect an MCP server at runtime and register its tools for this session. "
            "Use this to load optional MCP integrations on demand (e.g. Google Calendar) "
            "without paying the context cost of having them always loaded."
        )

    async def execute(
        self,
        server_name: str,
        command: str,
        args: str = "[]",
        env: str = "{}",
        **kwargs: Any,
    ) -> str:
        import json

        from nanobot.agent.tools.mcp import connect_mcp_servers
        from nanobot.config.schema import MCPServerConfig

        if server_name in self._stacks:
            return f"MCP server '{server_name}' is already connected."

        try:
            args_list: list[str] = json.loads(args)
            env_dict: dict[str, str] = json.loads(env)
        except json.JSONDecodeError as e:
            return f"Invalid JSON in args or env: {e}"

        cfg = MCPServerConfig(command=command, args=args_list, env=env_dict)

        before = set(self._registry.names())
        try:
            new_stacks = await connect_mcp_servers({server_name: cfg}, self._registry)
        except Exception as e:
            logger.warning("Failed to connect MCP server '{}': {}", server_name, e)
            return f"Failed to connect MCP server '{server_name}': {e}"

        self._stacks.update(new_stacks)
        after = set(self._registry.names())
        new_tools = sorted(after - before)

        if not new_tools:
            return f"Connected MCP server '{server_name}' but no tools were registered."

        return f"Connected '{server_name}'. New tools available: {', '.join(new_tools)}"
