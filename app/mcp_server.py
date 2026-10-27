"""MCP server that exposes the agent tools to Claude Code (used by the claude_code backend).

Claude Code starts it itself through the --mcp-config file that ClaudeCodeAgent writes.
"""
import asyncio
import logging
import sys

import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from . import config, db
from .tools import TOOLS, Toolbox


def build_server(toolbox: Toolbox) -> Server:
    async def list_tools(ctx, params) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[
            types.Tool(name=t["name"], description=t["description"], input_schema=t["input_schema"])
            for t in TOOLS
        ])

    async def call_tool(ctx, params: types.CallToolRequestParams) -> types.CallToolResult:
        try:
            out = toolbox.run(params.name, params.arguments or {})
            return types.CallToolResult(content=[types.TextContent(type="text", text=out)])
        except Exception as e:  # errors go back to Claude so it can fix the call
            return types.CallToolResult(content=[types.TextContent(type="text", text=f"error: {e}")],
                                        is_error=True)

    return Server("health", on_list_tools=list_tools, on_call_tool=call_tool)


async def main():
    # stdout is the MCP channel, so logs go to stderr only
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    s = config.load(server=False)
    server = build_server(Toolbox(db.connect(s.db_path), s.tz))
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
