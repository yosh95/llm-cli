import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from llm_cli.mcp_lib import (
    TRACE_ID,
    ClientSession,
    FastMCP,
    get_current_trace_id,
)


@pytest.mark.asyncio
async def test_client_injects_trace_id():
    read_stream = AsyncMock(spec=asyncio.StreamReader)
    write_stream = AsyncMock(spec=asyncio.StreamWriter)

    # Mock response
    response = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"content": [{"type": "text", "text": "ok"}]},
    }
    read_stream.readline.side_effect = [json.dumps(response).encode() + b"\n", b""]

    # Set a specific trace id in context
    test_trace_id = "test-trace-123"
    token = TRACE_ID.set(test_trace_id)

    try:
        async with ClientSession(read_stream, write_stream) as session:
            session.protocol._msg_id = 0
            await session.call_tool("my_tool", {"arg": 1})

            # Verify request contains _meta with trace_id
            write_stream.write.assert_called()
            call_args = write_stream.write.call_args[0][0]
            req = json.loads(call_args)

            assert req["method"] == "tools/call"
            args = req["params"]["arguments"]
            assert "_meta" in args
            assert args["_meta"]["trace_id"] == test_trace_id
            assert args["arg"] == 1
    finally:
        TRACE_ID.reset(token)


@pytest.mark.asyncio
async def test_server_propagates_trace_id():
    server = FastMCP("trace_server")
    captured_trace_id = None

    @server.tool()
    def check_trace():
        nonlocal captured_trace_id
        captured_trace_id = get_current_trace_id()
        return "done"

    write_stream = AsyncMock(spec=asyncio.StreamWriter)

    test_trace_id = "propagated-id-456"

    # Construct a request with _meta trace info
    msg = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "check_trace",
            "arguments": {"_meta": {"trace_id": test_trace_id}},
        },
    }

    await server._handle_message(msg, write_stream)

    # Verify that the tool function saw the trace id
    assert captured_trace_id == test_trace_id


@pytest.mark.asyncio
async def test_server_generates_trace_id_if_missing():
    server = FastMCP("trace_server")
    captured_trace_id = None

    @server.tool()
    def check_trace():
        nonlocal captured_trace_id
        captured_trace_id = get_current_trace_id()
        return "done"

    write_stream = AsyncMock(spec=asyncio.StreamWriter)

    # Request WITHOUT _meta
    msg = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "check_trace", "arguments": {}},
    }

    await server._handle_message(msg, write_stream)

    # Should have generated a random UUID
    assert captured_trace_id is not None
    assert isinstance(captured_trace_id, str)
    assert len(captured_trace_id) > 0
