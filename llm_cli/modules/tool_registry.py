# llm_cli/modules/tool_registry.py

from typing import Any, Dict, List, Callable
from llm_cli.modules.agent_tools import TOOL_FUNCTIONS


class ToolRegistry:
    """Central registry for tools with exporters for LLM providers."""

    def __init__(self):
        self.tools: Dict[str, Dict[str, Any]] = {}
        self._load_default_tools()

    def _load_default_tools(self):
        defs = [
            ("list_files", "List files and directories.", {
                "type": "object", "properties": {
                    "directory": {
                        "type": "string",
                        "description": "Root directory to start listing."
                    },
                    "depth": {
                        "type": "integer",
                        "description": "How deep to traverse (default 1).",
                        "default": 1
                    }
                }
            }),
            ("read_file", "Read the content of a file.", {
                "type": "object", "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path to the file."
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "First line (1-indexed).",
                        "default": 1
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "Last line (inclusive)."
                    }
                }, "required": ["path"]
            }),
            ("write_file", "Create or update a file.", {
                "type": "object", "properties": {
                    "path": {
                        "type": "string",
                        "description": "Save path."
                    },
                    "content": {
                        "type": "string",
                        "description": "Full content to write."
                    }
                }, "required": ["path", "content"]
            }),
            ("execute_command", "Run shell commands.", {
                "type": "object", "properties": {
                    "command": {
                        "type": "string",
                        "description": "Command to execute."
                    }
                }, "required": ["command"]
            }),
            ("google_search", "Search Google.", {
                "type": "object", "properties": {
                    "queries": {
                        "type": "array", "items": {"type": "string"},
                        "description": "Search queries."
                    }
                }, "required": ["queries"]
            }),
            ("fetch_url", "Fetch URL content.", {
                "type": "object", "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL to fetch."
                    }
                }, "required": ["url"]
            }),
        ]
        for name, desc, params in defs:
            self.register(name, desc, params, TOOL_FUNCTIONS[name])

    def register(
        self, name: str, description: str,
        parameters: Dict[str, Any], func: Callable
    ):
        self.tools[name] = {
            "name": name, "description": description,
            "parameters": parameters, "func": func
        }

    def register_remote_tools(self, mcp_manager):
        remote_tools = mcp_manager.initialize_servers()
        for t in remote_tools:
            srv, orig = t["server_name"], t["original_name"]
            self.register(
                t["name"], t["description"], t["parameters"],
                lambda s=srv, o=orig, **kw: mcp_manager.call_tool(s, o, kw)
            )
        return [t["name"] for t in remote_tools]

    def _get_active(self, names: List[str]):
        return [self.tools[n] for n in names if n in self.tools]

    def get_gemini_spec(self, names: List[str]):
        tools = [
            {"name": t["name"], "description": t["description"],
             "parameters": t["parameters"]}
            for t in self._get_active(names)
        ]
        return [{"function_declarations": tools}] if tools else []

    def get_openai_spec(self, names: List[str]):
        return [
            {"type": "function",
             "function": {"name": t["name"], "description": t["description"],
                          "parameters": t["parameters"]}}
            for t in self._get_active(names)
        ]

    def get_anthropic_spec(self, names: List[str]):
        return [
            {"name": t["name"], "description": t["description"],
             "input_schema": t["parameters"]}
            for t in self._get_active(names)
        ]


registry = ToolRegistry()
