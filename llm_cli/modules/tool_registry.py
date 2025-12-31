# llm_cli/modules/tool_registry.py

from typing import Any, Dict, List, Callable
from llm_cli.modules.agent_tools import TOOL_FUNCTIONS


class ToolRegistry:
    """Central registry for tools with exporters for LLM providers."""

    def __init__(self):
        self.tools: Dict[str, Dict[str, Any]] = {}
        self._load_default_tools()

    def _load_default_tools(self):
        self.register(
            name="list_files",
            description="List files and directories in the project. "
                        "Use depth=1 for a quick overview of the root, "
                        "or increase depth for more detail.",
            parameters={
                "type": "object",
                "properties": {
                    "directory": {
                        "type": "string",
                        "description": "The root directory to start listing."
                    },
                    "depth": {
                        "type": "integer",
                        "description": "How deep to traverse the directory "
                                       "tree. Default is 1.",
                        "default": 1
                    }
                }
            },
            func=TOOL_FUNCTIONS["list_files"]
        )
        self.register(
            name="read_file",
            description="Read the content of a file. You can specify "
                        "start_line and end_line for large files.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The relative path to the file."
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "The first line to read (1-indexed).",
                        "default": 1
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "The last line to read (inclusive)."
                    }
                },
                "required": ["path"]
            },
            func=TOOL_FUNCTIONS["read_file"]
        )
        self.register(
            name="write_file",
            description="Create or update a file with new content. "
                        "Use this to apply code changes.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The path where the file will be saved."
                    },
                    "content": {
                        "type": "string",
                        "description": "The full content to write into "
                                       "the file."
                    }
                },
                "required": ["path", "content"]
            },
            func=TOOL_FUNCTIONS["write_file"]
        )
        self.register(
            name="execute_command",
            description="Run shell commands. Output is truncated if too long.",
            parameters={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to execute."
                    }
                },
                "required": ["command"]
            },
            func=TOOL_FUNCTIONS["execute_command"]
        )
        self.register(
            name="google_search",
            description="Search the web using Google to get "
                        "up-to-date information.",
            parameters={
                "type": "object",
                "properties": {
                    "queries": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "A list of search queries."
                    }
                },
                "required": ["queries"]
            },
            func=TOOL_FUNCTIONS["google_search"]
        )
        self.register(
            name="fetch_url",
            description="Fetch content from a URL (HTML, PDF, or images).",
            parameters={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "The URL to fetch."
                    }
                },
                "required": ["url"]
            },
            func=TOOL_FUNCTIONS["fetch_url"]
        )
        self.register(
            name="checkpoint_conversation",
            description=(
                "Summarize the conversation so far and clear the "
                "message history to keep the context window efficient. "
                "The summary MUST include: "
                "1) Original goal, 2) Current project state/structure, "
                "3) Completed tasks/code changes, 4) Remaining tasks."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "summary": {
                        "type": "string",
                        "description": "Detailed technical snapshot."
                    }
                },
                "required": ["summary"]
            },
            func=TOOL_FUNCTIONS["checkpoint_conversation"]
        )

    def register(
        self,
        name: str,
        description: str,
        parameters: Dict[str, Any],
        func: Callable
    ):
        self.tools[name] = {
            "name": name,
            "description": description,
            "parameters": parameters,
            "func": func
        }

    def register_remote_tools(self, mcp_manager):
        """Discover and register tools from external MCP servers."""
        remote_tools = mcp_manager.initialize_servers()
        for t in remote_tools:
            # Fix: Ensure srv and orig are captured correctly in the lambda
            server_name = t["server_name"]
            original_name = t["original_name"]

            def create_wrapper(srv, orig):
                return lambda **kwargs: mcp_manager.call_tool(
                    srv, orig, kwargs
                )

            self.register(
                name=t["name"],
                description=t["description"],
                parameters=t["parameters"],
                func=create_wrapper(server_name, original_name)
            )
        return [t["name"] for t in remote_tools]

    def get_gemini_spec(self, tool_names: List[str]) -> List[Dict[str, Any]]:
        declarations = []
        for name in tool_names:
            if name in self.tools:
                t = self.tools[name]
                declarations.append({
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["parameters"]
                })
        if not declarations:
            return []
        return [{"function_declarations": declarations}]

    def get_openai_spec(self, tool_names: List[str]) -> List[Dict[str, Any]]:
        specs = []
        for name in tool_names:
            if name in self.tools:
                t = self.tools[name]
                specs.append({
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t["description"],
                        "parameters": t["parameters"]
                    }
                })
        return specs

    def get_anthropic_spec(
        self, tool_names: List[str]
    ) -> List[Dict[str, Any]]:
        specs = []
        for name in tool_names:
            if name in self.tools:
                t = self.tools[name]
                specs.append({
                    "name": t["name"],
                    "description": t["description"],
                    "input_schema": t["parameters"]
                })
        return specs


# Global registry instance
registry = ToolRegistry()
