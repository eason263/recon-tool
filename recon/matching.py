"""Type-aware, per-column field comparison engine."""
from dataclasses import dataclass

_NULL_VALUES = frozenset({"null", "none", "n/a", "na", "nil", "-"})


@dataclass
class ColumnRule:
    tolerance: float = 0.0
    case_sensitive: bool = True
    null_equals_empty: bool = False


def norm(value, *, case_sensitive: bool = True, null_equals_empty: bool = False) -> str:
    s = "" if value is None else str(value).strip()
    if null_equals_empty and s.lower() in _NULL_VALUES:
        s = ""
    return s if case_sensitive else s.lower()


def compare_values(a: str, b: str, rule: ColumnRule) -> bool:
    if a == b:
        return True
    if rule.tolerance > 0:
        try:
            return abs(float(a) - float(b)) <= rule.tolerance
        except ValueError:
            pass
    return False


def apply_column_map(
    headers: list[str],
    rows: list[dict],
    column_map: dict[str, str],
) -> tuple[list[str], list[dict]]:
    """Rename target headers/row keys so they match source column names.

    column_map maps source_col → target_col.
    We invert it to rename target columns to their source equivalents.
    """
    if not column_map:
        return headers, rows
    reverse = {v: k for k, v in column_map.items()}
    new_headers = [reverse.get(h, h) for h in headers]
    new_rows = [{reverse.get(k, k): v for k, v in row.items()} for row in rows]
    return new_headers, new_rows
