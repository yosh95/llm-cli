import asyncio
import sys

from llm_cli.mcp_lib import ClientSession, StdioServerParameters, stdio_client


async def test_mcp_server(command: str, args: list[str]) -> None:
    """
    Connect to an MCP server and list its tools.
    This can be used to test both our simple server and 3rd party servers.
    """
    print(f"Connecting to MCP server: {command} {' '.join(args)}...")

    params = StdioServerParameters(command=command, args=args, env={})

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            # Initialize the session
            print("Initializing session...")
            await session.initialize()

            # List tools
            print("Listing tools...")
            tools_result = await session.list_tools()

            print(f"\nFound {len(tools_result.tools)} tools:")
            for tool in tools_result.tools:
                print(f"- {tool.name}: {tool.description}")
                # print(f"  Schema: {json.dumps(tool.inputSchema, indent=2)}")

            if tools_result.tools:
                # Try calling the first tool if it's 'hello' or just the first one
                target_tool = next(
                    (t for t in tools_result.tools if t.name == "hello"),
                    tools_result.tools[0],
                )
                print(f"\nTesting tool call: {target_tool.name}...")

                # Prepare arguments based on the tool name for our simple server
                args_to_pass: dict[str, object] = {}
                if target_tool.name == "hello":
                    args_to_pass = {"name": "MCP Tester"}
                elif target_tool.name == "add":
                    args_to_pass = {"a": 10, "b": 20}

                try:
                    result = await session.call_tool(target_tool.name, args_to_pass)
                    content = result.content[0].text if result.content else "No content"
                    print(f"Result: {content}")
                except Exception as e:
                    print(f"Error calling tool: {e}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python examples/test_client.py <command> [args...]")
        print(
            "Example: python examples/test_client.py "
            "python examples/simple_mcp_server.py"
        )
        sys.exit(1)

    cmd = sys.argv[1]
    cmd_args = sys.argv[2:]

    try:
        asyncio.run(test_mcp_server(cmd, cmd_args))
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"\nFailed to connect or communicate: {e}")
