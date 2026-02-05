# Traceability in LLM Tool Use: Implementing ID Propagation over Model Context Protocol

## Abstract
As Large Language Models (LLMs) increasingly act as agents interacting with external tools, debugging and auditing these interactions become critical. The Model Context Protocol (MCP) standardizes how LLMs connect to data and tools, but it lacks a built-in mechanism for distributed tracing. This paper presents a method to implement ID propagation within MCP by leveraging JSON-RPC metadata and Python's context variables. We demonstrate that injecting trace IDs into protocol messages enables end-to-end traceability from the LLM client to the tool execution server, facilitating better observability in agentic systems.

## 1. Introduction
LLM agents often perform complex tasks by invoking multiple tools sequentially or in parallel. When a failure occurs—such as an API timeout or an incorrect data retrieval—it is often difficult to pinpoint the source of the error within the chain of calls. 

Distributed tracing is a standard solution in microservices, where a Trace ID is propagated across service boundaries. The Model Context Protocol (MCP) is emerging as a standard for LLM-tool connectivity, utilizing JSON-RPC 2.0. However, the base specification does not explicitly mandate how tracing context should be carried.

This report proposes a lightweight extension to MCP implementations that adds support for ID propagation without breaking protocol compatibility.

## 2. Methodology

### 2.1 Trace ID Management
We utilize Python's `contextvars` module to manage Trace IDs in an asynchronous, thread-safe manner. This allows the Trace ID to be implicitly available to loggers and helper functions without passing it as an explicit argument through every function call.

```python
TRACE_ID: ContextVar[Optional[str]] = ContextVar("trace_id", default=None)
```

### 2.2 Protocol Extension
Since JSON-RPC 2.0 does not have a dedicated header section like HTTP, we inject metadata into the `params` object of the `tools/call` method. We reserve a `_meta` field for this purpose.

**Request Structure:**
```json
{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {
    "name": "calculator",
    "arguments": {
      "a": 1,
      "b": 2,
      "_meta": {
        "trace_id": "550e8400-e29b-41d4-a716-446655440000"
      }
    }
  },
  "id": 1
}
```

## 3. Implementation

We implemented this approach in a Python-based MCP library (`llm-cli`). The implementation consists of two main components: the Client and the Server.

### 3.1 Client-Side Injection
The Client automatically retrieves the current Trace ID from the context variable and injects it into the `arguments` of the tool call.

```python
# ClientSession.call_tool
trace_id = get_current_trace_id()
args_with_meta = arguments.copy()
args_with_meta["_meta"] = {"trace_id": trace_id}
```

### 3.2 Server-Side Extraction
The Server intercepts the message, extracts the `_meta` field, sets the `trace_id` context variable, and then executes the tool function. The `_meta` field is removed from arguments before calling the actual tool function to ensure signature compatibility.

```python
# FastMCP._handle_message
if "_meta" in args:
    meta = args.pop("_meta")
    trace_id = meta.get("trace_id")
    token = TRACE_ID.set(trace_id)
try:
    result = await tool_func(**args)
finally:
    TRACE_ID.reset(token)
```

## 4. Evaluation
We verified the implementation with a set of automated tests.

1.  **Injection Test**: Confirmed that the client correctly adds the `_meta` field to outgoing JSON-RPC requests.
2.  **Propagation Test**: Confirmed that the server correctly extracts the ID and makes it available via `get_current_trace_id()` within the tool function.
3.  **Fallback Test**: Verified that the server generates a new Trace ID if one is not provided by the client.

Tests were executed using `pytest` and all passed successfully, demonstrating reliable context propagation.

## 5. Conclusion
We successfully implemented ID propagation for MCP by piggybacking on the JSON-RPC payload. This approach provides immediate value for debugging LLM agent interactions with minimal overhead and without requiring changes to the core MCP specification. Future work includes aligning this metadata format with the W3C Trace Context standard and integrating with OpenTelemetry exporters.
