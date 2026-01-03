# llm_cli/apps/ollama_models.py

import requests
import sys
from rich.console import Console
from rich.table import Table


def main():
    console = Console()
    try:
        # Default host
        host = "http://localhost:11434"
        response = requests.get(f"{host}/api/tags", timeout=5)
        response.raise_for_status()
        models = response.json().get("models", [])

        if not models:
            console.print("[yellow]No Ollama models found.[/yellow]")
            return

        table = Table(title="Ollama Models")
        table.add_column("Name", style="cyan", overflow="fold")
        table.add_column("Size", style="magenta")
        table.add_column("Modified", style="green")

        for m in models:
            table.add_row(
                m.get("name"),
                f"{m.get('size', 0) / 1e9:.2f} GB",
                m.get("modified_at")
            )
        console.print(table)
    except Exception as e:
        console.print(
            f"[bold red]Error fetching Ollama models: {e}[/bold red]"
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
