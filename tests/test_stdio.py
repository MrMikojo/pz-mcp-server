"""End to end: start the server over stdio with the MCP client and call two tools (needs mcp and PZ)."""
import asyncio
import os
import sys

import pytest

mcp = pytest.importorskip("mcp")
from pz_modding_mcp import paths  # noqa: E402

pytestmark = pytest.mark.skipif(not paths.pz_dir(), reason="PZ not installed (set PZ_DIR)")


def _text(result):
    return "".join(getattr(c, "text", "") for c in result.content)


async def _session_run():
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    params = StdioServerParameters(command=sys.executable, args=["-m", "pz_modding_mcp"],
                                   env=dict(os.environ), cwd=os.path.dirname(os.path.dirname(__file__)))
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            names = {t.name for t in (await s.list_tools()).tools}
            check = _text(await s.call_tool("pz_check", {"query": "global getPlayer"}))
            api = _text(await s.call_tool("pz_api", {"name": "IsoPlayer.getStats"}))
            return names, check, api


def test_stdio_roundtrip():
    names, check, api = asyncio.run(_session_run())
    assert {"pz_status", "pz_check", "pz_api", "pz_items", "pz_lua_search", "show_lua_function",
            "pz_source", "pz_rebuild_indexes"} <= names
    assert check.startswith("YES")
    assert "getStats()" in api
