import asyncio
import dataclasses
import json
import logging
import os
import sys
import uuid
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from contextvars import ContextVar
from typing import Any

logger = logging.getLogger(__name__)

# --- Context Propagation ---

TRACE_ID: ContextVar[str | None] = ContextVar("trace_id", default=None)


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
        name: str,
        level: int,
        fn: str,
        lno: int,
        msg: object,
        args: Any,
        exc_info: Any,
        func: str | None = None,
        extra: Mapping[str, object] | None = None,
        sinfo: str | None = None,
    ) -> logging.LogRecord:
        if extra is None:
            extra = {}
        extra_dict = dict(extra)
        extra_dict["trace_id"] = TRACE_ID.get() or "-"
        return super().makeRecord(
            name, level, fn, lno, msg, args, exc_info, func, extra_dict, sinfo
        )


# --- Data Structures (Mocking mcp types) ---


@dataclasses.dataclass
class StdioServerParameters:
    command: str
    args: list[str]
    env: dict[str, str] | None = None


@dataclasses.dataclass
class Content:
    type: str
    text: str | None = None
    data: str | None = None
    mimeType: str | None = None


@dataclasses.dataclass
class ToolResult:
    content: list[Content]
    isError: bool = False


@dataclasses.dataclass
class ToolDescription:
    name: str
    description: str
    inputSchema: dict[str, Any]


@dataclasses.dataclass
class ListToolsResult:
    tools: list[ToolDescription]


# --- Protocol Helpers ---


class JSONRPCProtocol:
    def __init__(self) -> None:
        self._msg_id = 0
        self._pending_requests: dict[int, asyncio.Future] = {}

    def _next_id(self) -> int:
        self._msg_id += 1
        return self._msg_id

    def create_request(
        self, method: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
            "id": self._next_id(),
        }

    def create_response(self, request_id: int, result: Any) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "result": result,
            "id": request_id,
        }

    def create_error(
        self, request_id: int | None, code: int, message: str, data: Any = None
    ) -> dict[str, Any]:
        error = {"code": code, "message": message}
        if data:
            error["data"] = data
        return {
            "jsonrpc": "2.0",
            "error": error,
            "id": request_id,
        }


class PQCEncryptionHelper:
    """Assists in secure data exchange via MCP by using ML-KEM."""

    @classmethod
    def encrypt_data(cls, data: Any, recipient_public_key_b64: str) -> dict:
        """Encrypts a data object using ML-KEM for the specific recipient."""
        import base64

        from llm_cli.security.pqc import SecureStorage

        pub_kem = base64.b64decode(recipient_public_key_b64)
        data_bytes = json.dumps(data).encode()
        return SecureStorage.encrypt(data_bytes, pub_kem)

    @classmethod
    def decrypt_data(cls, encrypted_packet: dict) -> Any:
        """Decrypts an incoming ML-KEM encrypted packet using local private key."""
        from llm_cli.security.identity import IdentityManager
        from llm_cli.security.pqc import SecureStorage

        priv_kem = IdentityManager._get_kem_private_key_content()
        decrypted_bytes = SecureStorage.decrypt(encrypted_packet, priv_kem)
        return json.loads(decrypted_bytes.decode())


# --- Client Implementation ---


class ClientSession:
    def __init__(
        self, read_stream: asyncio.StreamReader, write_stream: asyncio.StreamWriter
    ):
        self.read_stream = read_stream
        self.write_stream = write_stream
        self.protocol = JSONRPCProtocol()
        self._listener_task: asyncio.Task | None = None
        self._connected = False

    async def __aenter__(self) -> "ClientSession":
        self._connected = True
        self._listener_task = asyncio.create_task(self._listen_loop())
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        self._connected = False
        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass

    async def _listen_loop(self) -> None:
        try:
            while self._connected:
                line = await self.read_stream.readline()
                if not line:
                    break

                # Skip empty lines or whitespace
                clean_line = line.strip()
                if not clean_line:
                    continue

                try:
                    # Basic check if it looks like a JSON object
                    if not clean_line.startswith(b"{"):
                        # If it doesn't start with '{', it's likely noise or
                        # a log message. We log it as a debug message instead
                        # of an error.
                        logger.debug(f"Skipping non-JSON line: {clean_line!r}")
                        continue

                    message = json.loads(clean_line)
                    if "id" in message and ("result" in message or "error" in message):
                        req_id = message["id"]
                        if req_id in self.protocol._pending_requests:
                            future = self.protocol._pending_requests.pop(req_id)
                            if "error" in message:
                                future.set_exception(
                                    Exception(message["error"]["message"])
                                )
                            else:
                                future.set_result(message["result"])
                except Exception as e:
                    logger.error(
                        f"Error in client loop parsing line {clean_line!r}: {e}"
                    )
        except asyncio.CancelledError:
            pass
        finally:
            # Resolve any pending requests when the loop ends
            self._connected = False
            for future in self.protocol._pending_requests.values():
                if not future.done():
                    future.set_exception(Exception("Connection closed"))
            self.protocol._pending_requests.clear()

    async def _send_request(self, method: str, params: dict | None = None) -> Any:
        req = self.protocol.create_request(method, params)
        req_id = req["id"]
        future: asyncio.Future[Any] = asyncio.Future()
        self.protocol._pending_requests[req_id] = future
        self.write_stream.write(json.dumps(req).encode() + b"\n")
        await self.write_stream.drain()
        return await future

    async def initialize(self) -> Any:
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
        tools = [
            ToolDescription(
                name=t["name"],
                description=t.get("description", ""),
                inputSchema=t.get("inputSchema", {}),
            )
            for t in response.get("tools", [])
        ]
        return ListToolsResult(tools=tools)

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        trace_id = get_current_trace_id()
        args_with_meta = arguments.copy()
        if "_meta" not in args_with_meta:
            args_with_meta["_meta"] = {"trace_id": trace_id}
        response = await self._send_request(
            "tools/call", {"name": name, "arguments": args_with_meta}
        )
        content_list = (
            [Content(**c) for c in response.get("content", [])]
            if isinstance(response, dict)
            else []
        )
        return ToolResult(content=content_list)


@asynccontextmanager
async def stdio_client(
    params: StdioServerParameters,
) -> AsyncIterator[tuple[asyncio.StreamReader, asyncio.StreamWriter]]:
    env = os.environ.copy()
    if params.env:
        env.update(params.env)
    proc = await asyncio.create_subprocess_exec(
        params.command,
        *params.args,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=sys.stderr,
        env=env,
        limit=32 * 1024 * 1024,
    )
    if proc.stdout is None or proc.stdin is None:
        raise RuntimeError("Failed to open stdin/stdout for MCP server process")
    try:
        yield proc.stdout, proc.stdin
    finally:
        if proc.stdin:
            try:
                proc.stdin.close()
            except Exception:
                pass
        if proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=2.0)
            except TimeoutError:
                proc.kill()
                await proc.wait()
