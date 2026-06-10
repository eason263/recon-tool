"""Key-based record reconciliation engine."""

from dataclasses import dataclass, field


class ReconError(Exception):
    pass


@dataclass
class FieldMismatch:
    key: tuple
    column: str
    a_value: str
    b_value: str


@dataclass
class ReconResult:
    a_name: str
    b_name: str
    key_columns: list[str]
    compared_columns: list[str]
    total_a: int = 0
    total_b: int = 0
    matched: int = 0
    mismatched_keys: list[tuple] = field(default_factory=list)
    mismatches: list[FieldMismatch] = field(default_factory=list)
    only_in_a: list[tuple] = field(default_factory=list)
    only_in_b: list[tuple] = field(default_factory=list)
    duplicate_keys_a: list[tuple] = field(default_factory=list)
    duplicate_keys_b: list[tuple] = field(default_factory=list)
    records_a: dict = field(default_factory=dict)
    records_b: dict = field(default_factory=dict)

    @property
    def reconciled(self) -> bool:
        return not (self.mismatches or self.only_in_a or self.only_in_b
                    or self.duplicate_keys_a or self.duplicate_keys_b)


def reconcile(
    a: tuple[list[str], list[dict]],
    b: tuple[list[str], list[dict]],
    a_name: str,
    b_name: str,
    key_columns: list[str],
    ignore_columns: list[str] | None = None,
    tolerance: float = 0.0,
) -> ReconResult:
    a_headers, a_rows = a
    b_headers, b_rows = b
    ignore = set(ignore_columns or [])

    for col in key_columns:
        if col not in a_headers:
            raise ReconError(f"key column {col!r} not in {a_name} (columns: {a_headers})")
        if col not in b_headers:
            raise ReconError(f"key column {col!r} not in {b_name} (columns: {b_headers})")

    compared = [
        c for c in a_headers
        if c in b_headers and c not in key_columns and c not in ignore
    ]

    result = ReconResult(
        a_name=a_name, b_name=b_name,
        key_columns=key_columns, compared_columns=compared,
        total_a=len(a_rows), total_b=len(b_rows),
    )

    map_a = _index_by_key(a_rows, key_columns, result.duplicate_keys_a)
    map_b = _index_by_key(b_rows, key_columns, result.duplicate_keys_b)
    result.records_a = map_a
    result.records_b = map_b

    for key, row_a in map_a.items():
        row_b = map_b.get(key)
        if row_b is None:
            result.only_in_a.append(key)
            continue
        result.matched += 1
        row_had_mismatch = False
        for col in compared:
            va, vb = _norm(row_a.get(col)), _norm(row_b.get(col))
            if not _values_equal(va, vb, tolerance):
                result.mismatches.append(FieldMismatch(key, col, va, vb))
                row_had_mismatch = True
        if row_had_mismatch:
            result.mismatched_keys.append(key)

    result.only_in_b = [k for k in map_b if k not in map_a]
    return result


def _index_by_key(rows: list[dict], key_columns: list[str], duplicates: list[tuple]) -> dict:
    indexed: dict[tuple, dict] = {}
    for row in rows:
        key = tuple(_norm(row.get(c)) for c in key_columns)
        if key in indexed:
            if key not in duplicates:
                duplicates.append(key)
        else:
            indexed[key] = row
    return indexed


def _norm(value) -> str:
    return "" if value is None else str(value).strip()


def _values_equal(a: str, b: str, tolerance: float) -> bool:
    if a == b:
        return True
    if tolerance > 0:
        try:
            return abs(float(a) - float(b)) <= tolerance
        except ValueError:
            return False
    return False
