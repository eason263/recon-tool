"""recon command-line interface."""

import sys
from pathlib import Path

import click
from rich.console import Console

from .formatters import PRETTY_FORMATTERS
from .loaders import LoadError, load
from .recondiff import ReconError, reconcile
from .report import render_diff_terminal, render_recon_terminal, write_html
from .textdiff import diff_lines

EXIT_SAME = 0
EXIT_DIFF = 1
EXIT_ERROR = 2


@click.group()
@click.version_option(package_name="recon-tool")
def main():
    """Compare and reconcile files: txt, java, json, xml, docx, csv, xlsx."""


@main.command()
@click.argument("file_a", type=click.Path(exists=True, dir_okay=False))
@click.argument("file_b", type=click.Path(exists=True, dir_okay=False))
@click.option("--key", "-k", help="Comma-separated key column(s); enables record reconciliation for tabular files.")
@click.option("--ignore", "-i", help="Comma-separated columns to skip when comparing records.")
@click.option("--tolerance", "-t", type=float, default=0.0, show_default=True,
              help="Numeric tolerance for field comparison in reconciliation mode.")
@click.option("--html", "html_out", type=click.Path(dir_okay=False),
              help="Also write an HTML report to this path.")
def compare(file_a, file_b, key, ignore, tolerance, html_out):
    """Compare FILE_A with FILE_B.

    Tabular files (csv/xlsx) with --key are reconciled record-by-record;
    everything else gets a pretty-formatted text diff.
    """
    console = Console()
    a_name, b_name = Path(file_a).name, Path(file_b).name
    if a_name == b_name:
        a_name, b_name = str(file_a), str(file_b)

    try:
        kind_a, data_a = load(file_a)
        kind_b, data_b = load(file_b)
    except LoadError as e:
        raise click.ClickException(str(e))

    if key:
        if kind_a != "records" or kind_b != "records":
            raise click.ClickException(
                "--key requires two tabular files (csv/xlsx); "
                f"got {a_name} ({kind_a}) and {b_name} ({kind_b})"
            )
        keys = [c.strip() for c in key.split(",") if c.strip()]
        ignores = [c.strip() for c in ignore.split(",")] if ignore else []
        try:
            result = reconcile(data_a, data_b, a_name, b_name,
                               key_columns=keys, ignore_columns=ignores,
                               tolerance=tolerance)
        except ReconError as e:
            raise click.ClickException(str(e))
        render_recon_terminal(result, console)
        same = result.reconciled
    else:
        if kind_a == "records":
            data_a = _records_to_lines(data_a)
        if kind_b == "records":
            data_b = _records_to_lines(data_b)
        result = diff_lines(data_a, data_b, a_name, b_name)
        render_diff_terminal(result, console)
        same = result.identical

    if html_out:
        write_html(result, html_out)
        console.print(f"[dim]HTML report written to {html_out}[/]")

    sys.exit(EXIT_SAME if same else EXIT_DIFF)


@main.command()
@click.argument("file", type=click.Path(exists=True, dir_okay=False))
@click.option("--output", "-o", type=click.Path(dir_okay=False),
              help="Write formatted output to a file instead of stdout.")
def fmt(file, output):
    """Pretty-print a JSON or XML file."""
    path = Path(file)
    formatter = PRETTY_FORMATTERS.get(path.suffix.lower())
    if formatter is None:
        raise click.ClickException(
            f"fmt supports {', '.join(sorted(PRETTY_FORMATTERS))}; got {path.suffix or 'no extension'}"
        )
    try:
        pretty = formatter(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise click.ClickException(f"{path}: {e}")
    if output:
        Path(output).write_text(pretty + "\n", encoding="utf-8")
        click.echo(f"Formatted output written to {output}")
    else:
        click.echo(pretty)


def _records_to_lines(data: tuple[list[str], list[dict]]) -> list[str]:
    headers, rows = data
    lines = [",".join(headers)]
    lines += [",".join(str(row.get(h, "")) for h in headers) for row in rows]
    return lines


if __name__ == "__main__":
    main()
