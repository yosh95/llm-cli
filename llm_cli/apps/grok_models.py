#!/usr/bin/env python3

import sys

from llm_cli.apps.model_listing import main as unified_main


def main() -> None:
    """Wrapper for unified model listing."""
    sys.argv.insert(1, "grok")
    unified_main()


if __name__ == "__main__":
    main()
