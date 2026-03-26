import asyncio
import inspect
import json
import logging
import sys
from collections.abc import Callable
from typing import Any

from llm_cli.mcp_lib import EXPLANATION, TRACE_ID, JSONRPCProtocol

logger = logging.getLogger(__name__)


class FastMCP:
    """
    Simplified MCP Server implementation (FastAPI-like).
    Allows easy creation of MCP servers with tool decorators.
    """

    def __init__(self, name: str):
        self.name = name
        self.tools: dict[str, Callable] = {}
        self.protocol = JSONRPCProtocol()

    def tool(self, name: str | None = None) -> Callable[[Callable], Callable]:
        def decorator(func: Callable) -> Callable:
            tool_name = name or func.__name__
            self.tools[tool_name] = func
            return func

        return decorator

    def _generate_schema(self, func: Callable) -> dict[str, Any]:
        sig = inspect.signature(func)
        properties = {}
        required = []

        for param_name, param in sig.parameters.items():
            if param.default == inspect.Parameter.empty:
                required.append(param_name)

            param_type = "string"
            if param.annotation is int:
                param_type = "integer"
            elif param.annotation is bool:
                param_type = "boolean"
            elif param.annotation is dict:
                param_type = "object"
            elif param.annotation is list:
                param_type = "array"

            properties[param_name] = {
                "type": param_type,
                "description": f"Parameter {param_name}",
            }

        return {"type": "object", "properties": properties, "required": required}

    async def _handle_message(
        self, message: dict[str, Any], write_stream: asyncio.StreamWriter
    ) -> None:
        if "method" not in message:
            return

        method = message["method"]
        msg_id = message.get("id")
        params = message.get("params", {})
        response: dict[str, Any] | None = None

        try:
            if method == "initialize":
                response = {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": self.name, "version": "0.1.0"},
                }
            elif method == "notifications/initialized":
                return
            elif method == "tools/list":
                tools_list = []
                for name, func in self.tools.items():
                    tools_list.append(
                        {
                            "name": name,
                            "description": func.__doc__ or "",
                            "inputSchema": self._generate_schema(func),
                        }
                    )
                response = {"tools": tools_list}
            elif method == "tools/call":
                tool_name = params.get("name")
                args = params.get("arguments", {})

                token = None
                exp_token = None
                if "_meta" in args and isinstance(args["_meta"], dict):
                    meta = args.pop("_meta")
                    trace_id = meta.get("trace_id")
                    if trace_id:
                        token = TRACE_ID.set(trace_id)

                    explanation = meta.get("explanation")
                    if explanation:
                        exp_token = EXPLANATION.set(explanation)

                try:
                    if tool_name not in self.tools:
                        raise Exception(f"Tool not found: {tool_name}")

                    func = self.tools[tool_name]

                    # Filter arguments based on function signature
                    sig = inspect.signature(func)
                    has_kwargs = any(
                        p.kind == inspect.Parameter.VAR_KEYWORD
                        for p in sig.parameters.values()
                    )

                    if not has_kwargs:
                        # Only keep arguments that the function actually accepts
                        filtered_args = {
                            k: v for k, v in args.items() if k in sig.parameters
                        }
                    else:
                        filtered_args = args

                    if inspect.iscoroutinefunction(func):
                        result = await func(**filtered_args)
                    else:
                        result = func(**filtered_args)

                    if isinstance(result, dict):
                        text_content = json.dumps(result)
                    else:
                        text_content = str(result)

                    response = {
                        "content": [{"type": "text", "text": text_content}],
                        "isError": False,
                    }
                finally:
                    if token:
                        TRACE_ID.reset(token)
                    if exp_token:
                        EXPLANATION.reset(exp_token)
            else:
                if msg_id:
                    error_resp = self.protocol.create_error(
                        msg_id, -32601, "Method not found"
                    )
                    write_stream.write(json.dumps(error_resp).encode() + b"\n")
                    await write_stream.drain()
                return

            if msg_id is not None:
                resp_obj = self.protocol.create_response(msg_id, response)
                write_stream.write(json.dumps(resp_obj).encode() + b"\n")
                await write_stream.drain()

        except Exception as e:
            logger.error(f"Error handling message: {e}")
            if msg_id is not None:
                error_resp = self.protocol.create_error(msg_id, -32000, str(e))
                write_stream.write(json.dumps(error_resp).encode() + b"\n")
                await write_stream.drain()

    async def _run_loop(self) -> None:
        """Internal async loop for processing messages."""
        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)

        # Connect writer to the ACTUAL stdout before we redirect sys.stdout
        original_stdout = sys.stdout
        w_transport, w_protocol = await loop.connect_write_pipe(
            asyncio.streams.FlowControlMixin, original_stdout
        )
        writer = asyncio.StreamWriter(w_transport, w_protocol, reader, loop)

        # Redirect sys.stdout to sys.stderr so tool-internal print() calls
        # don't corrupt the JSON-RPC stream.
        sys.stdout = sys.stderr

        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    message = json.loads(line)
                    await self._handle_message(message, writer)
                except Exception:
                    continue
        finally:
            # Restore stdout
            sys.stdout = original_stdout

    def run(self) -> None:
        """Run the server using stdio (blocking)."""
        try:
            asyncio.run(self._run_loop())
        except (KeyboardInterrupt, EOFError, asyncio.CancelledError):
            # Suppress stack trace on exit
            pass
