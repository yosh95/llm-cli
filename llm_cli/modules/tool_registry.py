# llm_cli/modules/tool_registry.py

from typing import Any, Dict, List, Callable
from llm_cli.modules.agent_tools import TOOL_FUNCTIONS


class ToolRegistry:
    """Central registry for tools with exporters for LLM providers."""

    def __init__(self):
        self.tools: Dict[str, Dict[str, Any]] = {}
        self._load_default_tools()

    def _load_default_tools(self):
        # This metadata would ideally be closer to the function implementation
        # For now, we define the schema here for consistency.
        self.register(
            name="list_files",
            description="Get a list of all files in the project to "
                        "understand the structure.",
            parameters={
                "type": "object",
                "properties": {
                    "directory": {
                        "type": "string",
                        "description": "The root directory to start listing."
                    }
                }
            },
            func=TOOL_FUNCTIONS["list_files"]
        )
        self.register(
            name="read_file",
            description="Read the content of a file to analyze its "
                        "code or text.",
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "The relative path to the file."
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
            description="Run shell commands for tasks like testing, "
                        "linting, or checking environment state.",
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
