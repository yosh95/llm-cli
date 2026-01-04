#!/usr/bin/env python3

import argparse
import json
import sys
import time
from functools import reduce
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple

from rich.markup import escape
from tqdm import tqdm

from llm_cli.clients.base import BaseLlmClient, console
from llm_cli.clients.gemini import GeminiClient
from llm_cli.clients.openai import OpenAIClient


def get_llm_client(provider: str, model_alias: str) -> Optional[BaseLlmClient]:
    """Initializes and returns a client instance for the specified provider."""
    provider_map = {"google": GeminiClient, "openai": OpenAIClient}
    ClientClass = provider_map.get(provider)
    if not ClientClass:
        console.print(
            f"[bold red]Error: Invalid provider '{escape(provider)}'.[/bold red]"
        )
        return None
    # stdout=True ensures the client returns the response directly
    return ClientClass(initial_model_alias=model_alias, stdout=True)


def extract_paths_and_values(
    data: Any, target_keys: List[List[str]], current_path: List[str] = []
) -> Generator[Tuple[List[str], str], None, None]:
    """
    Recursively traverses JSON data to find values for given key paths.
    Yields tuples of (path, value).
    """
    if isinstance(data, dict):
        for key, value in data.items():
            new_path = current_path + [key]
            # Check if the current path suffix matches any target key path
            for target_key_path in target_keys:
                if new_path[-len(target_key_path) :] == target_key_path:
                    if isinstance(value, str) and value.strip():
                        yield (new_path, value)
            # Continue traversal
            yield from extract_paths_and_values(value, target_keys, new_path)
    elif isinstance(data, list):
        for index, item in enumerate(data):
            new_path = current_path + [str(index)]
            yield from extract_paths_and_values(item, target_keys, new_path)


def set_nested_value(data: Dict, path: List[str], value: str):
    """Sets a value in a nested dictionary using a path list."""
    try:
        # Convert numeric path segments to integers for list indexing
        path_keys = [int(p) if p.isdigit() else p for p in path]
        reduce(lambda d, k: d[k], path_keys[:-1], data)[path_keys[-1]] = value
    except (KeyError, IndexError, TypeError) as e:
        console.print(
            "[bold yellow]Warning: Could not set value for path "
            f"{escape(str(path))}. Error: {escape(str(e))}"
            "[/bold yellow]"
        )


def create_translation_prompt(text: str) -> str:
    """
    Creates a structured prompt for the LLM to translate a single text.
    """
    prompt = f"""
# Instructions
You are an expert translator.
Translate the following English text to Japanese.
Maintain the original meaning, context, and any special formatting like
Markdown (`<code>`, links, newlines).
Return only the translated Japanese text and nothing else.

# Text to Translate
{text}
"""
    return prompt


def translate_data(
    input_path: Path,
    output_path: Path,
    keys_to_translate: List[str],
    provider: str,
    model: str,
    interval: float,
):
    """Main function to handle the JSON translation process."""
    try:
        with open(input_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        console.print(
            f"[bold red]Error reading input file: {escape(str(e))}[/bold red]"
        )
        sys.exit(1)

    client = get_llm_client(provider, model)
    if not client:
        sys.exit(1)

    target_key_paths = [k.split(".") for k in keys_to_translate]

    console.print(f"Extracting values for keys: {keys_to_translate}...")
    items_to_translate = list(extract_paths_and_values(data, target_key_paths))

    if not items_to_translate:
        console.print(
            "[yellow]No values found for the specified keys. "
            "Writing original data to output.[/yellow]"
        )
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        return

    num_texts = len(items_to_translate)
    console.print(f"Found {num_texts} text snippets to translate.")

    with tqdm(total=num_texts, desc="Translating", unit="item") as pbar:
        for i, (path, original_text) in enumerate(items_to_translate):
            prompt_str = create_translation_prompt(original_text)

            translated_text = None
            retries = 3
            for attempt in range(retries):
                response_text, _ = client._send(
                    [{"content": prompt_str, "content_type": "text/plain"}]
                )
                # Clear conversation history for the next independent request.
                client.conversation.clear()

                if response_text and response_text.strip():
                    translated_text = response_text.strip()
                    break  # Success
                else:
                    console.print(
                        f"\n[yellow]Warning: LLM returned an empty response "
                        f"(attempt {attempt + 1}/{retries}). Retrying..."
                        "[/yellow]"
                    )
                    if attempt < retries - 1:
                        time.sleep(5)  # Wait before retrying

            if translated_text:
                set_nested_value(data, list(path), translated_text)
            else:
                console.print(
                    f"\n[bold red]Failed to translate text for path "
                    f"{escape(str(path))} after {retries} attempts. "
                    "Skipping.[/bold red]"
                )

            pbar.update(1)

            # Wait for the specified interval before the next request,
            # but not after the last item.
            is_last_item = (i + 1) == num_texts
            if interval > 0 and not is_last_item:
                time.sleep(interval)

    console.print(f"\nTranslation complete. Saving to {output_path}...")
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        console.print("[green]Successfully saved the translated file.[/green]")
    except IOError as e:
        console.print(
            f"[bold red]Error writing to output file: {escape(str(e))}[/bold red]"
        )


def main():
    parser = argparse.ArgumentParser(
        description="Translate specific key values in a large JSON file using an LLM.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("input_file", type=Path, help="Path to the input JSON file.")
    parser.add_argument(
        "output_file", type=Path, help="Path to save the translated JSON file."
    )
    parser.add_argument(
        "-k",
        "--key",
        required=True,
        action="append",
        dest="keys",
        help="Key to translate. Use dot notation for nested keys "
        "(e.g., 'mitigations.description').\n"
        "Can be specified multiple times for different keys.",
    )
    parser.add_argument(
        "-p",
        "--provider",
        default="google",
        choices=["google", "openai"],
        help="Specify the LLM provider to use. Default: 'google'.",
    )
    parser.add_argument(
        "-m",
        "--model",
        default="default",
        help="Specify the model alias for the provider. Default: 'default'.",
    )
    parser.add_argument(
        "-i",
        "--interval",
        type=float,
        default=0,
        help="Interval in seconds between API requests. Default: 0.",
    )
    args = parser.parse_args()

    translate_data(
        args.input_file,
        args.output_file,
        args.keys,
        args.provider,
        args.model,
        args.interval,
    )


if __name__ == "__main__":
    main()
