# llm_cli/apps/ollama_models.py

import sys
from urllib.parse import urlparse

import requests
from rich.console import Console
from rich.table import Table

from llm_cli.clients.config import get_setting


def main() -> None:
    console = Console()
    try:
        # Load API URL from config
        api_url = get_setting("api_url", "ollama")
        if not api_url:
            api_url = "http://localhost:11434/v1/chat/completions"

        # Extract base URL (e.g., http://localhost:11434)
        # Assuming api_url is like http://host:port/v1/chat/completions
        parsed = urlparse(api_url)
        host = f"{parsed.scheme}://{parsed.netloc}"

        response = requests.get(
            f"{host}/api/tags", headers={"Connection": "close"}, timeout=5
        )
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
                m.get("name"), f"{m.get('size', 0) / 1e9:.2f} GB", m.get("modified_at")
            )
        console.print(table)
    except Exception as e:
        console.print(f"[bold red]Error fetching Ollama models: {e}[/bold red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
