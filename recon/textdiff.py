"""Line-based diff engine built on difflib."""

import difflib
from dataclasses import dataclass, field


@dataclass
class SideBySideRow:
    """One row of a side-by-side diff. tag is 'equal', 'replace', 'delete', or 'insert'."""

    tag: str
    left_no: int | None
    left: str
    right_no: int | None
    right: str


@dataclass
class DiffResult:
    a_name: str
    b_name: str
    identical: bool
    unified: list[str] = field(default_factory=list)
    rows: list[SideBySideRow] = field(default_factory=list)
    added: int = 0
    removed: int = 0
    changed: int = 0


def diff_lines(a: list[str], b: list[str], a_name: str, b_name: str) -> DiffResult:
    matcher = difflib.SequenceMatcher(a=a, b=b, autojunk=False)
    result = DiffResult(a_name=a_name, b_name=b_name, identical=a == b)
    if result.identical:
        return result

    result.unified = list(
        difflib.unified_diff(a, b, fromfile=a_name, tofile=b_name, lineterm="")
    )

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            for offset in range(i2 - i1):
                result.rows.append(
                    SideBySideRow("equal", i1 + offset + 1, a[i1 + offset],
                                  j1 + offset + 1, b[j1 + offset])
                )
        elif tag == "replace":
            for offset in range(max(i2 - i1, j2 - j1)):
                ai, bj = i1 + offset, j1 + offset
                result.rows.append(
                    SideBySideRow(
                        "replace",
                        ai + 1 if ai < i2 else None,
                        a[ai] if ai < i2 else "",
                        bj + 1 if bj < j2 else None,
                        b[bj] if bj < j2 else "",
                    )
                )
            result.changed += max(i2 - i1, j2 - j1)
        elif tag == "delete":
            for ai in range(i1, i2):
                result.rows.append(SideBySideRow("delete", ai + 1, a[ai], None, ""))
            result.removed += i2 - i1
        elif tag == "insert":
            for bj in range(j1, j2):
                result.rows.append(SideBySideRow("insert", None, "", bj + 1, b[bj]))
            result.added += j2 - j1

    return result
