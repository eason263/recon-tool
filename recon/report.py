"""Render diff / reconciliation results to the terminal (rich) and to HTML (jinja2)."""

from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from rich.console import Console
from rich.table import Table
from rich.text import Text

from .recondiff import ReconResult
from .textdiff import DiffResult

_DIFF_STYLES = {"+": "green", "-": "red", "@": "cyan"}

MAX_TERMINAL_MISMATCHES = 50


def render_diff_terminal(result: DiffResult, console: Console) -> None:
    if result.identical:
        console.print(f"[bold green]✓ Identical[/]  {result.a_name} == {result.b_name}")
        return
    console.print(
        f"[bold]Diff[/] {result.a_name} → {result.b_name}  "
        f"[green]+{result.added}[/] [red]-{result.removed}[/] [yellow]~{result.changed}[/]"
    )
    for line in result.unified:
        style = _DIFF_STYLES.get(line[:1], "")
        if line.startswith(("+++", "---")):
            style = "bold"
        console.print(Text(line, style=style))


def render_recon_terminal(result: ReconResult, console: Console) -> None:
    summary = Table(title=f"Reconciliation: {result.a_name} vs {result.b_name}")
    summary.add_column("Metric")
    summary.add_column("Count", justify="right")
    summary.add_row("Records in A", str(result.total_a))
    summary.add_row("Records in B", str(result.total_b))
    summary.add_row("Matched keys", str(result.matched))
    summary.add_row("Keys with mismatched fields", str(len(result.mismatched_keys)))
    summary.add_row("Only in A", str(len(result.only_in_a)))
    summary.add_row("Only in B", str(len(result.only_in_b)))
    summary.add_row("Duplicate keys (A / B)",
                    f"{len(result.duplicate_keys_a)} / {len(result.duplicate_keys_b)}")
    console.print(summary)

    if result.mismatches:
        table = Table(title="Field mismatches")
        table.add_column("Key")
        table.add_column("Column")
        table.add_column(result.a_name, style="red")
        table.add_column(result.b_name, style="green")
        for m in result.mismatches[:MAX_TERMINAL_MISMATCHES]:
            table.add_row(_fmt_key(m.key), m.column, m.a_value, m.b_value)
        console.print(table)
        if len(result.mismatches) > MAX_TERMINAL_MISMATCHES:
            console.print(
                f"[dim]… {len(result.mismatches) - MAX_TERMINAL_MISMATCHES} more "
                f"(use --html for the full report)[/]"
            )

    for label, keys in (("Only in A", result.only_in_a), ("Only in B", result.only_in_b)):
        if keys:
            shown = ", ".join(_fmt_key(k) for k in keys[:MAX_TERMINAL_MISMATCHES])
            extra = "" if len(keys) <= MAX_TERMINAL_MISMATCHES else f" … +{len(keys) - MAX_TERMINAL_MISMATCHES}"
            console.print(f"[bold]{label}:[/] {shown}{extra}")

    if result.reconciled:
        console.print("[bold green]✓ Fully reconciled[/]")
    else:
        console.print("[bold red]✗ Differences found[/]")


def write_html(result: DiffResult | ReconResult, out_path: str | Path) -> None:
    env = Environment(
        loader=FileSystemLoader(Path(__file__).parent / "templates"),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("report.html.j2")
    mode = "diff" if isinstance(result, DiffResult) else "recon"
    html = template.render(
        mode=mode,
        r=result,
        generated=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        fmt_key=_fmt_key,
    )
    Path(out_path).write_text(html, encoding="utf-8")


def _fmt_key(key: tuple) -> str:
    return " / ".join(key)
