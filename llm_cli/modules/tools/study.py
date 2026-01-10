# llm_cli/modules/tools/study.py

from typing import List, Optional

from prompt_toolkit import prompt
from prompt_toolkit.completion import WordCompleter
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

from llm_cli.modules.tool_registry import tool

console = Console()


@tool(
    name="present_quiz",
    desc=(
        "Provides an interactive quiz or practice problem interface. "
        "Use this tool when the user wants to 'take a test', 'do a quiz', 'challenge', or 'practice' knowledge interactively. "
        "It provides a dedicated CLI UI for selection or text input, helping the user study without seeing the answer immediately. "
        "CRITICAL: If you use this tool, do not include the answer or explanation in the same response. "
        "If the user just wants to see a question as normal text for reference, you can output it directly without this tool."
    ),
    params={
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": "The question text (Markdown supported).",
            },
            "quiz_type": {
                "type": "string",
                "enum": ["single", "multiple", "descriptive"],
                "description": "Type of the quiz.",
            },
            "options": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of options for single or multiple choice quizzes.",
            },
        },
        "required": ["question", "quiz_type"],
    },
    interactive=True,
    skip_approval=True,
)
def present_quiz(
    question: str,
    quiz_type: str,
    options: Optional[List[str]] = None,
) -> str:
    """
    Displays a quiz to the user and collects their answer.
    """
    # 1. Display Question
    console.print("\n")
    console.print(
        Panel(
            Markdown(question),
            title="[bold yellow]❓ Quiz Question[/bold yellow]",
            border_style="yellow",
        )
    )

    # 2. Display Options (if any)
    if quiz_type in ["single", "multiple"] and options:
        console.print("[bold cyan]Options:[/bold cyan]")
        for i, opt in enumerate(options, 1):
            # Using Markdown for each option to ensure correct wrapping and formatting
            console.print(Markdown(f"{i}. {opt}"))
        console.print("\n")

    # 3. Collect Answer
    try:
        if quiz_type == "single":
            if not options:
                return "Error: Options must be provided for single choice quizzes."
            
            valid_choices = [str(i) for i in range(1, len(options) + 1)]
            completer = WordCompleter(valid_choices)
            
            ans = prompt(
                f"Enter the number (1-{len(options)}): ", 
                completer=completer
            ).strip()
            
            if not ans:
                return "User provided no answer."
            
            try:
                idx = int(ans) - 1
                if 0 <= idx < len(options):
                    return f"User selected option {ans}: {options[idx]}"
                else:
                    return f"Invalid selection: {ans}"
            except ValueError:
                return f"Invalid input (not a number): {ans}"

        elif quiz_type == "multiple":
            if not options:
                return "Error: Options must be provided for multiple choice quizzes."
            
            console.print("[dim]Enter multiple numbers separated by commas (e.g., 1, 3)[/dim]")
            ans = prompt("Enter the numbers: ").strip()
            
            if not ans:
                return "User provided no answer."
                
            parts = [p.strip() for p in ans.split(",")]
            results = []
            for p in parts:
                try:
                    idx = int(p) - 1
                    if 0 <= idx < len(options):
                        results.append(f"{p}: {options[idx]}")
                    else:
                        results.append(f"Invalid:{p}")
                except ValueError:
                    results.append(f"Invalid:{p}")
            
            return f"User selected: {', '.join(results)}"

        elif quiz_type == "descriptive":
            console.print("[dim]Type your answer (Press Alt+Enter or Esc-Enter for multi-line if needed)[/dim]")
            ans = prompt("Your Answer: ", multiline=False).strip()
            if not ans:
                return "User provided no answer."
            return f"User's answer: {ans}"

        else:
            return f"Error: Unknown quiz type '{quiz_type}'."
            
    except (KeyboardInterrupt, EOFError):
        return "User cancelled the quiz."
