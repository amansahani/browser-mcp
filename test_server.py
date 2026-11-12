"""
Quick smoke test — verifies the MCP server can start and list its tools.
Run: .venv/bin/python test_server.py
"""

import asyncio
from server import mcp


async def main():
    # List registered tools
    tools = await mcp.list_tools()
    print("=" * 60)
    print(f" Browser MCP Server — {len(tools)} tools registered")
    print("=" * 60)
    for tool in tools:
        print(f"  • {tool.name:25s} {(tool.description or '')[:60]}")
    print()
    print("✅ Server is ready. Run it with:")
    print("   python server.py                   # stdio (for MCP clients)")
    print("   python server.py --transport sse    # HTTP SSE transport")


if __name__ == "__main__":
    asyncio.run(main())
