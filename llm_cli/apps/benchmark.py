import argparse
import logging
import sys
import time

from llm_cli.clients.config import config_manager
from llm_cli.clients.registry import client_registry
from llm_cli.security.dual_llm_verifier import verify_tool_call
from llm_cli.ui import console


def run_benchmark(provider: str, model: str, iterations: int = 5) -> None:
    """Run the Dual LLM latency benchmark with specific settings."""
    # Temporarily override config for the duration of this process
    # Note: verify_tool_call reads from config_manager
    original_provider = config_manager.get("security", "dual_llm_provider")
    original_model = config_manager.get("security", "dual_llm_model")

    config_manager.set("security", "dual_llm_provider", provider)
    config_manager.set("security", "dual_llm_model", model)

    console.print("[bold cyan]Benchmarking Dual LLM Verification...[/bold cyan]")
    console.print(f"Provider: [yellow]{provider}[/yellow]")
    console.print(f"Model:    [yellow]{model}[/yellow]")

    user_prompt = "Write a python script to list files in /etc"
    tool_name = "execute_python"
    args = {"code": "import os; os.listdir('/etc')"}

    latencies = []

    try:
        for i in range(iterations):
            console.print(f"  Iteration {i + 1}/{iterations}...", end="\r")
            start_time = time.time()
            # verify_tool_call uses the config we just set
            safe, reason = verify_tool_call(user_prompt, tool_name, args)
            elapsed = time.time() - start_time

            # Check if the reason indicates an API error or initialization failure
            # verify_tool_call typically returns True and an error message
            # on technical failures
            if (
                "error" in reason.lower()
                or "failed" in reason.lower()
                or "400" in reason
                or "401" in reason
            ):
                console.print(f"\n[red]  Iteration {i + 1} failed: {reason}[/red]")
            else:
                latencies.append(elapsed)
    except Exception as e:
        console.print(f"\n[red][ERROR] Error during benchmark execution: {e}[/red]")
        return
    finally:
        # Restore original config
        config_manager.set("security", "dual_llm_provider", original_provider)
        config_manager.set("security", "dual_llm_model", original_model)

    if not latencies:
        msg = "\n[bold red][ERROR] Benchmark failed: No successful requests.[/bold red]"
        console.print(msg)
        return

    avg_latency = sum(latencies) / len(latencies)
    console.print("\n[bold green][SUCCESS] Benchmark Results:[/bold green]")
    console.print(f"  Average Latency: [bold]{avg_latency:.2f}s[/bold]")
    console.print(f"  Min Latency:     {min(latencies):.2f}s")
    console.print(f"  Max Latency:     {max(latencies):.2f}s")

    if avg_latency > 2.0:
        console.print(
            "[yellow][WARNING] Latency is high (>2s). Consider using a faster model.[/yellow]"
        )


def main() -> None:
    """Entry point for the benchmark tool."""
    try:
        parser = argparse.ArgumentParser(
            description="Benchmark Dual LLM latency for specific providers and models.",
            add_help=True,
        )
        parser.add_argument("--debug", action="store_true", help="Enable debug logging")
        parser.add_argument(
            "provider",
            nargs="?",
            help="The LLM provider alias (e.g., google, openai, anthropic, ollama)",
        )
        parser.add_argument(
            "model",
            nargs="?",
            help="The model name or alias (e.g., lite, flash, gpt-4o-mini)",
        )
        parser.add_argument(
            "--iterations",
            "-n",
            type=int,
            default=5,
            help="Number of iterations (default: 5)",
        )

        args = parser.parse_args()

        # Set default log level (with debug support)
        log_level = logging.DEBUG if args.debug else logging.WARNING
        logging.basicConfig(level=log_level, stream=sys.stderr)

        if not args.provider or not args.model:
            parser.print_help()
            console.print("\n[bold]Available Providers (Aliases):[/bold]")
            info = client_registry.get_provider_info()
            for alias in sorted(info.keys()):
                console.print(f"  - [cyan]{alias}[/cyan]")
            sys.exit(0)

        run_benchmark(args.provider, args.model, args.iterations)
    except KeyboardInterrupt:
        console.print("\n[yellow]Benchmark cancelled by user.[/yellow]")
        sys.exit(0)


if __name__ == "__main__":
    main()
