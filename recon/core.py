"""Shared compare logic used by both the CLI and the web UI."""

from pathlib import Path

from .loaders import load
from .recondiff import ReconResult, reconcile
from .textdiff import DiffResult, diff_lines


class CompareError(Exception):
    pass


def compare_paths(
    file_a: str | Path,
    file_b: str | Path,
    key: str | None = None,
    ignore: str | None = None,
    tolerance: float = 0.0,
    a_name: str | None = None,
    b_name: str | None = None,
) -> DiffResult | ReconResult:
    """Compare two files; returns a ReconResult when key is given, else a DiffResult.

    key/ignore are comma-separated column lists as typed by the user.
    """
    if a_name is None:
        a_name, b_name = Path(file_a).name, Path(file_b).name
        if a_name == b_name:
            a_name, b_name = str(file_a), str(file_b)

    kind_a, data_a = load(file_a)
    kind_b, data_b = load(file_b)

    if key:
        if kind_a != "records" or kind_b != "records":
            raise CompareError(
                "key-based reconciliation requires two tabular files (csv/xlsx); "
                f"got {a_name} ({kind_a}) and {b_name} ({kind_b})"
            )
        keys = [c.strip() for c in key.split(",") if c.strip()]
        ignores = [c.strip() for c in ignore.split(",") if c.strip()] if ignore else []
        return reconcile(data_a, data_b, a_name, b_name,
                         key_columns=keys, ignore_columns=ignores,
                         tolerance=tolerance)

    if kind_a == "records":
        data_a = _records_to_lines(data_a)
    if kind_b == "records":
        data_b = _records_to_lines(data_b)
    return diff_lines(data_a, data_b, a_name, b_name)


def _records_to_lines(data: tuple[list[str], list[dict]]) -> list[str]:
    headers, rows = data
    lines = [",".join(headers)]
    lines += [",".join(str(row.get(h, "")) for h in headers) for row in rows]
    return lines
