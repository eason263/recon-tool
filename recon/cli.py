"""recon command-line interface."""

import sys
from datetime import datetime
from pathlib import Path

import click
from rich.console import Console

from .core import CompareError, compare_paths
from .formatters import PRETTY_FORMATTERS
from .loaders import LoadError
from .recondiff import ReconError, ReconResult
from .report import render_diff_terminal, render_recon_terminal, write_html

EXIT_SAME = 0
EXIT_DIFF = 1
EXIT_ERROR = 2


@click.group()
@click.version_option(package_name="recon-tool")
def main():
    """Compare and reconcile files: txt, java, json, xml, docx, csv, xlsx."""


@main.command()
@click.argument("job_file", type=click.Path(exists=True, dir_okay=False))
@click.option("--html", "html_out", type=click.Path(dir_okay=False),
              help="Write an HTML report to this path.")
@click.option("--show-matched", "-m", is_flag=True,
              help="Show all fields of mismatched records, not just differing columns.")
@click.option("--save/--no-save", default=True, show_default=True,
              help="Save the run to the history database.")
def run(job_file, html_out, show_matched, save):
    """Run a reconciliation job defined in JOB_FILE (YAML)."""
    from .jobconfig import JobConfigError, load_job
    from . import store

    console = Console()
    try:
        job = load_job(job_file)
    except JobConfigError as e:
        raise click.ClickException(str(e))

    key_str = ",".join(job.key) if job.key else None
    ignore_str = ",".join(job.ignore) if job.ignore else None

    try:
        result = compare_paths(
            job.source_path, job.target_path,
            key=key_str, ignore=ignore_str, tolerance=job.tolerance,
            column_map=job.column_map or None,
            column_rules=job.matching.per_column or None,
            case_sensitive=job.matching.case_sensitive,
            null_equals_empty=job.matching.null_equals_empty,
        )
    except (LoadError, ReconError, CompareError) as e:
        raise click.ClickException(str(e))

    if isinstance(result, ReconResult):
        render_recon_terminal(result, console, show_matched=show_matched)
        same = result.reconciled
        if save:
            run_id = store.save_run(result, job.name)
            console.print(f"[dim]Run saved as #{run_id}  (recon serve → /runs/{run_id})[/]")
    else:
        render_diff_terminal(result, console)
        same = result.identical

    if html_out:
        write_html(result, html_out, show_matched=show_matched)
        console.print(f"[dim]HTML report written to {html_out}[/]")

    sys.exit(EXIT_SAME if same else EXIT_DIFF)


@main.group()
def users():
    """Manage web UI users."""


@users.command("add")
@click.argument("username")
@click.password_option(prompt="Password", confirmation_prompt="Confirm password")
def users_add(username, password):
    """Create a new web UI user and print their API key."""
    from .auth import create_user
    try:
        api_key = create_user(username, password)
    except Exception as e:
        raise click.ClickException(str(e))
    click.echo(f"User '{username}' created.")
    click.echo(f"API key: {api_key}")


@main.command()
@click.argument("file_a", type=click.Path(exists=True, dir_okay=False))
@click.argument("file_b", type=click.Path(exists=True, dir_okay=False))
@click.option("--key", "-k", help="Comma-separated key column(s); enables record reconciliation for tabular files.")
@click.option("--ignore", "-i", help="Comma-separated columns to skip when comparing records.")
@click.option("--tolerance", "-t", type=float, default=0.0, show_default=True,
              help="Numeric tolerance for field comparison in reconciliation mode.")
@click.option("--show-matched", "-m", is_flag=True,
              help="For mismatched records, show all fields (matched ones too), not just the differing columns.")
@click.option("--html", "html_out", type=click.Path(dir_okay=False),
              help="Also write an HTML report to this path.")
def compare(file_a, file_b, key, ignore, tolerance, show_matched, html_out):
    """Compare FILE_A with FILE_B.

    Tabular files (csv/xlsx) with --key are reconciled record-by-record;
    everything else gets a pretty-formatted text diff.
    """
    console = Console()
    try:
        result = compare_paths(file_a, file_b, key=key, ignore=ignore,
                               tolerance=tolerance)
    except (LoadError, ReconError, CompareError) as e:
        raise click.ClickException(str(e))

    if isinstance(result, ReconResult):
        render_recon_terminal(result, console, show_matched=show_matched)
        same = result.reconciled
    else:
        render_diff_terminal(result, console)
        same = result.identical

    if html_out:
        write_html(result, html_out, show_matched=show_matched)
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


@main.command()
@click.argument("manifest", type=click.Path(exists=True, dir_okay=False))
@click.option("--key", "-k", help="Key column(s) for tabular pairs; non-tabular pairs fall back to text diff.")
@click.option("--ignore", "-i", help="Comma-separated columns to skip when comparing records.")
@click.option("--tolerance", "-t", type=float, default=0.0, show_default=True,
              help="Numeric tolerance for field comparison in reconciliation mode.")
@click.option("--show-matched", "-m", is_flag=True,
              help="In per-pair HTML reports, show all fields of mismatched records.")
@click.option("--html-dir", type=click.Path(file_okay=False),
              help="Write an index.html summary plus one report per pair into this directory.")
def batch(manifest, key, ignore, tolerance, show_matched, html_dir):
    """Batch-compare file pairs listed in MANIFEST (.xlsx or .csv).

    Manifest columns: index (informational, auto-renumbered), source path,
    target path. Relative paths resolve against the manifest's directory.
    Generate a starter file with `recon batch-template`.
    """
    from .batch import ManifestError, load_manifest, run_batch
    from .report import render_html, render_template

    console = Console()
    try:
        pairs = load_manifest(manifest)
    except ManifestError as e:
        raise click.ClickException(str(e))

    items = run_batch(pairs, key=key, ignore=ignore, tolerance=tolerance,
                      base_dir=Path(manifest).parent)

    from . import store
    for item in items:
        if isinstance(item.result, ReconResult):
            store.save_run(item.result, job_name=f"batch:{Path(manifest).name}")

    from rich.table import Table
    styles = {"MATCH": "green", "DIFF": "yellow", "ERROR": "red"}
    table = Table(title=f"Batch comparison: {manifest} ({len(items)} pairs)")
    table.add_column("#", justify="right")
    table.add_column("Source")
    table.add_column("Target")
    table.add_column("Status")
    table.add_column("Detail")
    for item in items:
        table.add_row(str(item.index), item.source, item.target,
                      f"[{styles[item.status]}]{item.status}[/]", item.detail)
    console.print(table)
    counts = {s: sum(1 for i in items if i.status == s) for s in styles}
    console.print(f"[green]{counts['MATCH']} match[/] · "
                  f"[yellow]{counts['DIFF']} differ[/] · "
                  f"[red]{counts['ERROR']} error[/]")

    if html_dir:
        out = Path(html_dir)
        out.mkdir(parents=True, exist_ok=True)
        links = {}
        for item in items:
            if item.result is None:
                continue
            name = f"{item.index:03d}_{Path(item.source).stem}_vs_{Path(item.target).stem}.html"
            (out / name).write_text(
                render_html(item.result, show_matched=show_matched, back_url="index.html"),
                encoding="utf-8")
            links[item.index] = name
        (out / "index.html").write_text(
            render_template("batch_report.html.j2", items=items, links=links,
                            manifest=str(manifest),
                            generated=datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
            encoding="utf-8")
        console.print(f"[dim]HTML reports written to {out}/index.html[/]")

    if counts["ERROR"]:
        sys.exit(EXIT_ERROR)
    sys.exit(EXIT_SAME if counts["DIFF"] == 0 else EXIT_DIFF)


@main.command("batch-template")
@click.argument("output", type=click.Path(dir_okay=False), default="manifest.xlsx")
def batch_template(output):
    """Create a starter batch manifest (.xlsx with auto-numbering index column)."""
    from .batch import write_template_xlsx

    if Path(output).exists():
        raise click.ClickException(f"{output} already exists; not overwriting")
    write_template_xlsx(output)
    click.echo(f"Template written to {output} (columns: index | source | target)")


@main.command()
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8765, show_default=True, type=int)
def serve(host, port):
    """Start the web UI: upload two files and configure the comparison in a browser."""
    from .webapp import create_app

    click.echo(f"recon web UI: http://{host}:{port}")
    create_app().run(host=host, port=port)


if __name__ == "__main__":
    main()
