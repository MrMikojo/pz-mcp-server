"""The MCP server (stdio). Start it with:  python -m pz_modding_mcp   (or the pz-modding-mcp command)."""
from . import __version__, tools

INSTRUCTIONS = (
    "Project Zomboid (Build 42) modding tools that read the user's installed game. Never guess a PZ name: "
    "pz_check or pz_api for any Java class, method, field, event or global; pz_items for item and recipe names; "
    "pz_lua_search to see how PZ's own Lua does something; show_lua_function to read ONE function instead of a "
    "whole file; pz_source (if enabled) for what a Java method does. If a tool says something is missing, call "
    "pz_status.")


def _server_class():
    try:                                         # mcp 2.x
        from mcp.server.mcpserver import MCPServer
        return MCPServer
    except ImportError:                          # mcp 1.x
        from mcp.server.fastmcp import FastMCP
        return FastMCP


def build():
    server = _server_class()("pz-modding", instructions=INSTRUCTIONS)
    for fn in tools.ALL:
        server.tool()(fn)
    return server


def main():
    import sys
    if "--version" in sys.argv:
        print(__version__)
        return
    if "--check" in sys.argv:                    # a setup check without an MCP client
        print(tools.pz_status())
        return
    build().run()


if __name__ == "__main__":
    main()
