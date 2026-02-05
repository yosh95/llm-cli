import asyncio
import dataclasses
import inspect
import json
import logging
import os
import sys
import uuid
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# --- Context Propagation ---

TRACE_ID: ContextVar[Optional[str]] = ContextVar("trace_id", default=None)


def get_current_trace_id() -> str:
    """Get current trace id or generate a new one if not present."""
    tid = TRACE_ID.get()
    if tid is None:
        tid = str(uuid.uuid4())
        TRACE_ID.set(tid)
    return tid


class TraceLogger(logging.Logger):
    """Logger that includes trace_id in records."""
    def makeRecord(
        self,
        name,
        level,
        fn,
        lno,
        msg,
        args,
        exc_info,
        func=None,
        extra=None,
        sinfo=None,
    ):
        if extra is None:
            extra = {}
        extra["trace_id"] = TRACE_ID.get() or "-"
        return super().makeRecord(
            name, level, fn, lno, msg, args, exc_info, func, extra, sinfo
        )

# Replace default logger class for this module context (optional, but good for demo)
# logging.setLoggerClass(TraceLogger)


# --- Data Structures (Mocking mcp types) ---


@dataclasses.dataclass
class StdioServerParameters:
    command: str
    args: List[str]
    env: Optional[Dict[str, str]] = None


@dataclasses.dataclass
class Content:
    type: str
    text: Optional[str] = None
    data: Optional[str] = None
    mimeType: Optional[str] = None


@dataclasses.dataclass
class ToolResult:
    content: List[Content]
    isError: bool = False


@dataclasses.dataclass
class ToolDescription:
    name: str
    description: str
    inputSchema: Dict[str, Any]


@dataclasses.dataclass
class ListToolsResult:
    tools: List[ToolDescription]


# --- Protocol Helpers ---


class JSONRPCProtocol:
    def __init__(self) -> None:
        self._msg_id = 0
        self._pending_requests: Dict[int, asyncio.Future] = {}

    def _next_id(self) -> int:
        self._msg_id += 1
        return self._msg_id

    def create_request(self, method: str, params: Optional[Dict] = None) -> Dict:
        return {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
            "id": self._next_id(),
        }

    def create_response(self, request_id: int, result: Any) -> Dict:
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def create_error(self, request_id: int, code: int, message: str) -> Dict:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": code, "message": message},
        }


# --- Client Implementation ---


class ClientSession:
    def __init__(
        self, read_stream: asyncio.StreamReader, write_stream: asyncio.StreamWriter
    ):
        self.read_stream = read_stream
        self.write_stream = write_stream
        self.protocol = JSONRPCProtocol()
        self._listener_task: Optional[asyncio.Task] = None
        self._connected = False

    async def __aenter__(self):
        self._connected = True
        self._listener_task = asyncio.create_task(self._listen_loop())
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self._connected = False
        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass

    async def _listen_loop(self):
        try:
            while self._connected:
                line = await self.read_stream.readline()
                if not line:
                    break
                try:
                    message = json.loads(line)
                    if "id" in message and ("result" in message or "error" in message):
                        # Response
                        req_id = message["id"]
                        if req_id in self.protocol._pending_requests:
                            future = self.protocol._pending_requests.pop(req_id)
                            if "error" in message:
                                future.set_exception(
                                    Exception(message["error"]["message"])
                                )
                            else:
                                future.set_result(message["result"])
                except json.JSONDecodeError:
                    continue
                except Exception as e:
                    logger.error(f"Error in client loop: {e}")
        except asyncio.CancelledError:
            pass

    async def _send_request(self, method: str, params: Optional[Dict] = None) -> Any:
        req = self.protocol.create_request(method, params)
        req_id = req["id"]

        future: asyncio.Future[Any] = asyncio.Future()
        self.protocol._pending_requests[req_id] = future

        data = json.dumps(req).encode("utf-8") + b"\n"
        self.write_stream.write(data)
        await self.write_stream.drain()

        return await future

    async def initialize(self):
        return await self._send_request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "llm-cli-client", "version": "0.1.0"},
            },
        )

    async def list_tools(self) -> ListToolsResult:
        response = await self._send_request("tools/list")
        tools_data = response.get("tools", [])
        tools = []
        for t in tools_data:
            tools.append(
                ToolDescription(
                    name=t["name"],
                    description=t.get("description", ""),
                    inputSchema=t.get("inputSchema", {}),
                )
            )
        return ListToolsResult(tools=tools)

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> ToolResult:
        # Inject trace id into arguments as _meta
        trace_id = get_current_trace_id()
        args_with_meta = arguments.copy()
        if "_meta" not in args_with_meta:
            args_with_meta["_meta"] = {"trace_id": trace_id}

        response = await self._send_request(
            "tools/call", {"name": name, "arguments": args_with_meta}
        )

        content_list = []
        # Support both new and old MCP response formats roughly
        if isinstance(response, dict) and "content" in response:
            for c in response["content"]:
                content_list.append(Content(**c))

        return ToolResult(content=content_list)


@asynccontextmanager
async def stdio_client(params: StdioServerParameters):
    # Prepare environment
    env = os.environ.copy()
    if params.env:
        env.update(params.env)

    # Start subprocess
    proc = await asyncio.create_subprocess_exec(
        params.command,
        *params.args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=sys.stderr,  # Pass stderr through to console
        env=env,
        limit=32 * 1024 * 1024,  # 32MB limit for large MCP messages
    )

    try:
        yield proc.stdout, proc.stdin
    finally:
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                proc.kill()


# --- Server Implementation ---


class FastMCP:
    def __init__(self, name: str):
        self.name = name
        self.tools: Dict[str, Callable] = {}
        self.protocol = JSONRPCProtocol()

    def tool(self, name: Optional[str] = None):
        def decorator(func):
            tool_name = name or func.__name__
            self.tools[tool_name] = func
            return func

        return decorator

    def _generate_schema(self, func: Callable) -> Dict:
        # Very basic schema generation using inspect
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

    async def _handle_message(self, message: Dict, write_stream: asyncio.StreamWriter):
        if "method" not in message:
            return

        method = message["method"]
        msg_id = message.get("id")
        params = message.get("params", {})

        response: Dict[str, Any] | None = None

        try:
            if method == "initialize":
                response = {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": self.name, "version": "0.1.0"},
                }

            elif method == "notifications/initialized":
                # No response needed
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

                # Extract trace info
                token = None
                if "_meta" in args and isinstance(args["_meta"], dict):
                    # Remove _meta so it doesn't affect tool signature
                    meta = args.pop("_meta")
                    trace_id = meta.get("trace_id")
                    if trace_id:
                        token = TRACE_ID.set(trace_id)

                try:
                    if tool_name not in self.tools:
                        raise Exception(f"Tool not found: {tool_name}")

                    func = self.tools[tool_name]

                    # Check if coroutine
                    if inspect.iscoroutinefunction(func):
                        result = await func(**args)
                    else:
                        result = func(**args)

                    # Convert result to Content
                    text_content = str(result)
                    response = {
                        "content": [{"type": "text", "text": text_content}],
                        "isError": False,
                    }
                finally:
                    # Reset trace context
                    if token:
                        TRACE_ID.reset(token)

            else:
                # Unknown method, ignore or error
                if msg_id:
                    error_resp = self.protocol.create_error(
                        msg_id, -32601, "Method not found"
                    )
                    data = json.dumps(error_resp).encode("utf-8") + b"\n"
                    write_stream.write(data)
                    await write_stream.drain()
                return

            # Send success response if id present
            if msg_id is not None:
                resp_obj = self.protocol.create_response(msg_id, response)
                data = json.dumps(resp_obj).encode("utf-8") + b"\n"
                write_stream.write(data)
                await write_stream.drain()

        except Exception as e:
            logger.error(f"Error handling message: {e}")
            if msg_id is not None:
                error_resp = self.protocol.create_error(msg_id, -32000, str(e))
                data = json.dumps(error_resp).encode("utf-8") + b"\n"
                write_stream.write(data)
                await write_stream.drain()

    async def _run_loop(self):
        loop = asyncio.get_running_loop()

        # Setup stdin/stdout for async IO
        try:
            reader = asyncio.StreamReader()
            protocol = asyncio.StreamReaderProtocol(reader)
            await loop.connect_read_pipe(lambda: protocol, sys.stdin)

            w_transport, w_protocol = await loop.connect_write_pipe(
                asyncio.streams.FlowControlMixin, sys.stdout
            )
            writer = asyncio.StreamWriter(w_transport, w_protocol, reader, loop)

            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    message = json.loads(line)
                    await self._handle_message(message, writer)
                except json.JSONDecodeError:
                    continue
                except Exception as e:
                    logger.error(f"Server loop error: {e}")

        except Exception as e:
            logger.error(f"Fatal server error: {e}")

    def run(self):
        try:
            asyncio.run(self._run_loop())
        except KeyboardInterrupt:
            pass
