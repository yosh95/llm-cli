import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from llm_cli.mcp_lib import (
    ClientSession,
    JSONRPCProtocol,
    ListToolsResult,
    StdioServerParameters,
    ToolResult,
    stdio_client,
)
from llm_cli.mcp_server_lib import FastMCP


class TestJSONRPCProtocol:
    def test_create_request(self) -> None:
        protocol = JSONRPCProtocol()
        req = protocol.create_request("test_method", {"param": 1})
        assert req["jsonrpc"] == "2.0"
        assert req["method"] == "test_method"
        assert req["params"] == {"param": 1}
        assert isinstance(req["id"], int)

    def test_create_response(self) -> None:
        protocol = JSONRPCProtocol()
        resp = protocol.create_response(123, "result_value")
        assert resp["jsonrpc"] == "2.0"
        assert resp["id"] == 123
        assert resp["result"] == "result_value"

    def test_create_error(self) -> None:
        protocol = JSONRPCProtocol()
        err = protocol.create_error(123, -1, "error message")
        assert err["jsonrpc"] == "2.0"
        assert err["id"] == 123
        assert err["error"]["code"] == -1
        assert err["error"]["message"] == "error message"


@pytest.mark.asyncio
class TestClientSession:
    @pytest.fixture
    def mock_streams(self) -> tuple[AsyncMock, AsyncMock]:
        read_stream = AsyncMock(spec=asyncio.StreamReader)
        write_stream = AsyncMock(spec=asyncio.StreamWriter)
        return read_stream, write_stream

    async def test_listen_loop(self, mock_streams: tuple[AsyncMock, AsyncMock]) -> None:
        read_stream, write_stream = mock_streams
        # Create a pending request
        session = ClientSession(read_stream, write_stream)
        session._connected = True

        future = asyncio.Future()  # type: ignore
        session.protocol._pending_requests[1] = future

        # Responses: successful result, error result, empty string (EOF)
        responses = [
            json.dumps({"jsonrpc": "2.0", "id": 1, "result": "success"}).encode()
            + b"\n",
            b"",
        ]
        read_stream.readline.side_effect = responses

        await session._listen_loop()

        assert future.done()
        assert future.result() == "success"

    async def test_listen_loop_error(
        self, mock_streams: tuple[AsyncMock, AsyncMock]
    ) -> None:
        read_stream, write_stream = mock_streams
        session = ClientSession(read_stream, write_stream)
        session._connected = True

        future = asyncio.Future()  # type: ignore
        session.protocol._pending_requests[2] = future

        responses = [
            json.dumps(
                {"jsonrpc": "2.0", "id": 2, "error": {"code": -1, "message": "fail"}}
            ).encode()
            + b"\n",
            b"",
        ]
        read_stream.readline.side_effect = responses

        await session._listen_loop()

        assert future.done()
        with pytest.raises(Exception, match="fail"):
            future.result()

    async def test_initialize(self, mock_streams: tuple[AsyncMock, AsyncMock]) -> None:
        read_stream, write_stream = mock_streams

        # Setup read_stream to return response for initialize
        response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"protocolVersion": "2024-11-05"},
        }
        read_stream.readline.side_effect = [json.dumps(response).encode() + b"\n", b""]

        async with ClientSession(read_stream, write_stream) as session:
            # Manually set next id to match response
            session.protocol._msg_id = 0
            result = await session.initialize()
            assert result["protocolVersion"] == "2024-11-05"

            # Check write
            write_stream.write.assert_called()
            args = write_stream.write.call_args[0][0]
            sent_req = json.loads(args)
            assert sent_req["method"] == "initialize"

    async def test_list_tools(self, mock_streams: tuple[AsyncMock, AsyncMock]) -> None:
        read_stream, write_stream = mock_streams
        response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"tools": [{"name": "tool1", "description": "desc1"}]},
        }
        read_stream.readline.side_effect = [json.dumps(response).encode() + b"\n", b""]

        async with ClientSession(read_stream, write_stream) as session:
            session.protocol._msg_id = 0
            result = await session.list_tools()
            assert isinstance(result, ListToolsResult)
            assert len(result.tools) == 1
            assert result.tools[0].name == "tool1"

    async def test_call_tool(self, mock_streams: tuple[AsyncMock, AsyncMock]) -> None:
        read_stream, write_stream = mock_streams
        response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"content": [{"type": "text", "text": "tool output"}]},
        }
        read_stream.readline.side_effect = [json.dumps(response).encode() + b"\n", b""]

        async with ClientSession(read_stream, write_stream) as session:
            session.protocol._msg_id = 0
            result = await session.call_tool("tool1", {})
            assert isinstance(result, ToolResult)
            assert result.content[0].text == "tool output"

    async def test_error_response(
        self, mock_streams: tuple[AsyncMock, AsyncMock]
    ) -> None:
        read_stream, write_stream = mock_streams
        response = {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -1, "message": "Failed"},
        }
        read_stream.readline.side_effect = [json.dumps(response).encode() + b"\n", b""]

        async with ClientSession(read_stream, write_stream) as session:
            session.protocol._msg_id = 0
            with pytest.raises(Exception, match="Failed"):
                await session._send_request("method")


@pytest.mark.asyncio
class TestFastMCP:
    async def test_handle_message_initialize(self) -> None:
        server = FastMCP("test_server")
        write_stream = AsyncMock(spec=asyncio.StreamWriter)

        msg = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        await server._handle_message(msg, write_stream)

        write_stream.write.assert_called()
        sent_data = json.loads(write_stream.write.call_args[0][0])
        assert sent_data["result"]["serverInfo"]["name"] == "test_server"

    async def test_handle_message_list_tools(self) -> None:
        server = FastMCP("test_server")

        @server.tool()
        def my_tool(arg: int) -> None:
            """My Tool Doc"""
            pass

        write_stream = AsyncMock(spec=asyncio.StreamWriter)
        msg = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        await server._handle_message(msg, write_stream)

        sent_data = json.loads(write_stream.write.call_args[0][0])
        tools = sent_data["result"]["tools"]
        assert len(tools) == 1
        assert tools[0]["name"] == "my_tool"
        assert tools[0]["description"] == "My Tool Doc"
        assert "arg" in tools[0]["inputSchema"]["properties"]

    async def test_handle_message_call_tool(self) -> None:
        server = FastMCP("test_server")

        @server.tool()
        def echo(text: str) -> str:
            return f"Echo: {text}"

        write_stream = AsyncMock(spec=asyncio.StreamWriter)
        msg = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "echo", "arguments": {"text": "hello"}},
        }
        await server._handle_message(msg, write_stream)

        sent_data = json.loads(write_stream.write.call_args[0][0])
        content = sent_data["result"]["content"]
        assert content[0]["text"] == "Echo: hello"

    async def test_handle_message_call_unknown_tool(self) -> None:
        server = FastMCP("test_server")
        write_stream = AsyncMock(spec=asyncio.StreamWriter)
        msg = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "unknown", "arguments": {}},
        }
        await server._handle_message(msg, write_stream)

        sent_data = json.loads(write_stream.write.call_args[0][0])
        assert "error" in sent_data
        assert "Tool not found" in sent_data["error"]["message"]

    async def test_handle_message_unknown_method(self) -> None:
        server = FastMCP("test_server")
        write_stream = AsyncMock(spec=asyncio.StreamWriter)
        msg = {"jsonrpc": "2.0", "id": 1, "method": "unknown/method"}
        await server._handle_message(msg, write_stream)

        sent_data = json.loads(write_stream.write.call_args[0][0])
        assert "error" in sent_data
        assert sent_data["error"]["code"] == -32601


@pytest.mark.asyncio
async def test_stdio_client_context() -> None:
    params = StdioServerParameters(command="echo", args=["hello"])

    # Mock asyncio.create_subprocess_exec
    proc_mock = AsyncMock()
    proc_mock.stdout = AsyncMock(spec=asyncio.StreamReader)
    proc_mock.stdin = AsyncMock(spec=asyncio.StreamWriter)
    proc_mock.returncode = None
    proc_mock.wait = AsyncMock()
    # Fix: terminate is a sync method on Process, so mock it as MagicMock to avoid await warning
    proc_mock.terminate = MagicMock()

    with patch("asyncio.create_subprocess_exec", return_value=proc_mock) as mock_exec:
        async with stdio_client(params) as (stdout, stdin):
            assert stdout == proc_mock.stdout
            assert stdin == proc_mock.stdin

        mock_exec.assert_called_once()
        proc_mock.terminate.assert_called()


@pytest.mark.asyncio
async def test_fastmcp_run_loop() -> None:
    server = FastMCP("test")

    # Mock loop and streams
    mock_loop = MagicMock()
    mock_reader = AsyncMock(spec=asyncio.StreamReader)
    mock_writer = AsyncMock(spec=asyncio.StreamWriter)

    # Simulate one message then EOF
    mock_reader.readline.side_effect = [
        json.dumps({"jsonrpc": "2.0", "method": "initialize", "id": 1}).encode()
        + b"\n",
        b"",
    ]

    # Mock transport/protocol for writer creation
    mock_transport = MagicMock()
    mock_protocol = MagicMock()

    with (
        patch("asyncio.get_running_loop", return_value=mock_loop),
        patch("asyncio.StreamReader", return_value=mock_reader),
        patch("asyncio.StreamWriter", return_value=mock_writer),
        patch("asyncio.StreamReaderProtocol"),
    ):
        mock_loop.connect_read_pipe = AsyncMock()
        mock_loop.connect_write_pipe = AsyncMock(
            return_value=(mock_transport, mock_protocol)
        )

        await server._run_loop()

        # Verify message handling called
        mock_reader.readline.assert_called()
        # Verify handle_message indirectly by checking if writer was used
        mock_writer.write.assert_called()


def test_fastmcp_run() -> None:
    server = FastMCP("test")
    with patch("asyncio.run") as mock_run:
        server.run()
        mock_run.assert_called_once()

        # Clean up the coroutine created by server.run() passed to asyncio.run
        # to avoid "coroutine ... was never awaited" warning
        coro = mock_run.call_args[0][0]
        if asyncio.iscoroutine(coro):
            coro.close()
