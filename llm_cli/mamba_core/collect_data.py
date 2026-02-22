import argparse
import json
from pathlib import Path
from typing import Any

from llm_cli.apps.unified import UnifiedClient
from llm_cli.modules.models import ContentPart, DataSource, Message, Role
from llm_cli.modules.tool_registry import registry


def run_task(client: Any, task_description: str) -> list[Message]:
    """
    Run a single task through the ReAct loop and return the full conversation.
    Simplified version of ChatSession.process_and_print.
    """
    data = [DataSource(content=task_description, content_type="text/plain")]

    # We need to manage the loop manually to capture everything
    while True:
        # 1. Send to model
        res = client._send(data)
        (response_text, thought_text), _ = res if res else ((None, None), None)

        # Check if model message was added to client.conversation
        if not client.conversation or client.conversation[-1].role != Role.MODEL:
            # Something went wrong
            break

        last_msg = client.conversation[-1]

        # 2. Check for tool calls
        has_tool_calls = False
        tool_results_parts: list[str | ContentPart] = []

        for part in last_msg.parts:
            if isinstance(part, ContentPart) and part.function_call:
                has_tool_calls = True
                name = part.function_call["name"]
                args = part.function_call.get("args", {})
                tool_id = part.function_call.get("id")

                print(f"Executing tool: {name} with args {args}")

                if name in registry.tools:
                    try:
                        result = registry.tools[name]["func"](**args)
                        tool_results_parts.append(
                            ContentPart(
                                function_response={
                                    "id": tool_id,
                                    "name": name,
                                    "response": {"result": result},
                                }
                            )
                        )
                    except Exception as e:
                        tool_results_parts.append(
                            ContentPart(
                                function_response={
                                    "id": tool_id,
                                    "name": name,
                                    "response": {"result": f"Error: {e}"},
                                }
                            )
                        )
                else:
                    tool_results_parts.append(
                        ContentPart(
                            function_response={
                                "id": tool_id,
                                "name": name,
                                "response": {
                                    "result": f"Error: Tool {name} not found."
                                },
                            }
                        )
                    )

        if has_tool_calls:
            # Add tool results to conversation
            client.conversation.append(
                Message(role=Role.TOOL, parts=tool_results_parts)
            )
            data = []  # Next iteration will use the history
        else:
            # No tool calls, we are done with this task
            break

    return list(client.conversation)


def collect_training_data(
    output_file: str,
    tasks: list[str],
    provider: str = "ollama",
    model_alias: str = "default",
) -> None:
    client = UnifiedClient(
        initial_provider=provider, initial_model_alias=model_alias, stdout=False
    )

    with Path(output_file).open("a", encoding="utf-8") as f:
        for task in tasks:
            print(f"Starting task: {task} using {provider} ({client.model})")
            client.clear_history()
            conversation = run_task(client, task)

            # Convert conversation to JSONL format
            serialized_conv = []
            for msg in conversation:
                # Basic serialization for SFT
                content = ""
                for p in msg.parts:
                    if isinstance(p, str):
                        content += p
                    elif isinstance(p, ContentPart):
                        if p.text:
                            content += p.text
                        if p.thought:
                            content = f"<thought>{p.thought}</thought>\n" + content
                        if p.function_call:
                            call_str = json.dumps(p.function_call)
                            content += f"\n<tool_call>{call_str}</tool_call>"
                        if p.function_response:
                            resp_str = json.dumps(p.function_response)
                            content += f"\n<tool_response>{resp_str}</tool_response>"

                serialized_conv.append({"role": msg.role.value, "content": content})

            f.write(
                json.dumps({"messages": serialized_conv}, ensure_ascii=False) + "\n"
            )
            f.flush()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Collect training data for distillation."
    )
    parser.add_argument(
        "--provider",
        type=str,
        default="openai",
        help="LLM provider to use (e.g., openai, anthropic, xai).",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="default",
        help="Model alias to use.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="mamba_distill_data.jsonl",
        help="Output file path.",
    )

    args = parser.parse_args()

    tasks = [
        "Find the current weather in Tokyo and tell me if I should bring an umbrella.",
        "Create a file named hello.py that prints 'Hello World' and execute it.",
        "Search for the latest version of PyTorch and check if it's "
        "compatible with CUDA 12.1.",
        "List all files in the current directory and find the largest one.",
        "Write a summary of the project's mamba implementation based on "
        "llm_cli/mamba_core/mamba.py.",
        "Check the available disk space and report it in GB.",
        "Search for 'how to use trapezoidal discretization in mamba' and "
        "explain it to me.",
        "Create a directory named 'test_mamba', create 3 empty files inside it, "
        "and then list the directory.",
        "Find the current time in New York and London.",
        "Read the content of llm_cli/consts.py and tell me what's inside.",
        "Search for the price of Bitcoin today.",
        "Execute a python script that calculates the first 10 Fibonacci numbers.",
        "List all python files in the current directory recursively.",
        "Search for the latest news about AI Agents.",
        "Write a shell script that backups the llm_cli/mamba_core directory "
        "to a zip file.",
    ]
    collect_training_data(
        args.output, tasks, provider=args.provider, model_alias=args.model
    )
