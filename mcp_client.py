import asyncio
import os

from dotenv import load_dotenv

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


load_dotenv()

MCP_SERVER_URL = os.getenv(
    "MCP_SERVER_URL",
    "http://127.0.0.1:8000/mcp"
)


async def get_tools():
    async with streamable_http_client(
        MCP_SERVER_URL
    ) as streams:

        async with ClientSession(
            streams[0],
            streams[1]
        ) as session:

            await session.initialize()

            result = await session.list_tools()

            return result.tools


async def call_tool(tool_name, arguments=None):

    if arguments is None:
        arguments = {}

    async with streamable_http_client(
        MCP_SERVER_URL
    ) as streams:

        async with ClientSession(
            streams[0],
            streams[1]
        ) as session:

            await session.initialize()

            result = await session.call_tool(
                tool_name,
                arguments
            )

            return result


async def main():

    print("=" * 60)
    print("MCP CLIENT TEST")
    print("=" * 60)

    tools = await get_tools()

    print("\nAVAILABLE MCP TOOLS:\n")

    for tool in tools:
        print(f"✓ {tool.name}")

    print("\n" + "=" * 60)
    print("TESTING get_dashboard")
    print("=" * 60)

    result = await call_tool(
        "get_dashboard"
    )

    print(result)

    print("\n" + "=" * 60)
    print("MCP CLIENT TEST COMPLETED")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())