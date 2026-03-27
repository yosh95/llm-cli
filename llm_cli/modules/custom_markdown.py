from typing import Any

from rich import box
from rich.console import Console, ConsoleOptions, RenderResult
from rich.markdown import Markdown, TableElement
from rich.table import Table
from rich.text import Text


class CustomTableElement(TableElement):
    def __rich_console__(self, console: Console, options: ConsoleOptions) -> RenderResult:
        table = Table(box=box.SIMPLE_HEAVY)

        if self.header is not None and self.header.row is not None:
            for column in self.header.row.cells:
                table.add_column(column.content, overflow="fold")

        if self.body is not None:
            for row in self.body.rows:
                row_content: list[Markdown | Text | str] = []
                for element in row.cells:
                    content = element.content
                    if isinstance(content, str):
                        row_content.append(Markdown(content))
                    elif hasattr(content, "plain") and any(
                        m in content.plain for m in ("*", "_", "[", "`")
                    ):
                        # If Text object still contains markdown markers,
                        # re-parse it
                        row_content.append(Markdown(content.plain))
                    else:
                        row_content.append(content)
                table.add_row(*row_content)

        yield table


class CustomMarkdown(Markdown):
    elements = Markdown.elements.copy()
    elements["table_open"] = CustomTableElement

    def __init__(self, markup: str, *args: Any, **kwargs: Any) -> None:
        """Initialize CustomMarkdown with custom table element."""
        super().__init__(markup, *args, **kwargs)
