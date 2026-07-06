import asyncio
import logging
from contextlib import AsyncExitStack
from typing import Any, Dict, List, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.config.settings import settings


logger = logging.getLogger(__name__)


class NodeMCPClient:
    def __init__(self) -> None:
        self._session: Optional[ClientSession] = None
        self._exit_stack: Optional[AsyncExitStack] = None
        self._tools: List[Dict[str, Any]] = []
        self._connect_lock = asyncio.Lock()

    async def connect(self) -> ClientSession:
        if self._session is not None:
            return self._session

        async with self._connect_lock:
            if self._session is not None:
                return self._session

            exit_stack = AsyncExitStack()
            try:
                server_params = StdioServerParameters(
                    command=settings.node_mcp_server_command,
                    args=[settings.node_mcp_server_path],
                    cwd=settings.node_mcp_server_cwd,
                )
                read_stream, write_stream = await exit_stack.enter_async_context(stdio_client(server_params))
                session = await exit_stack.enter_async_context(ClientSession(read_stream, write_stream))
                await session.initialize()
                self._session = session
                self._exit_stack = exit_stack
                await self._refresh_tools()
                logger.info("Connected to Node MCP server with %s tools", len(self._tools))
                return session
            except Exception:
                await exit_stack.aclose()
                logger.exception("Failed to connect to Node MCP server")
                raise RuntimeError("Could not connect to the local MCP analytics server.")

    async def _refresh_tools(self) -> None:
        session = await self.connect() if self._session is None else self._session
        tools_result = await session.list_tools()
        self._tools = [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.inputSchema,
            }
            for tool in tools_result.tools
        ]

    async def list_tools(self) -> List[Dict[str, Any]]:
        if self._session is None:
            await self.connect()
        return self._tools

    async def call_tool(self, tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        session = await self.connect()
        try:
            result = await session.call_tool(tool_name, arguments or {})
            return {
                "tool": tool_name,
                "content": [item.model_dump() if hasattr(item, "model_dump") else item for item in result.content],
                "is_error": getattr(result, "isError", False),
            }
        except Exception as exc:
            logger.exception("MCP tool call failed: %s", tool_name)
            raise RuntimeError(f"MCP tool call failed: {tool_name}") from exc

    async def close(self) -> None:
        if self._exit_stack is not None:
            await self._exit_stack.aclose()
        self._session = None
        self._exit_stack = None
        self._tools = []


node_mcp_client = NodeMCPClient()
