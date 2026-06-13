"""YAML job configuration loader."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path

from .matching import ColumnRule


class JobConfigError(Exception):
    pass


@dataclass
class MatchingConfig:
    case_sensitive: bool = True
    null_equals_empty: bool = False
    per_column: dict[str, ColumnRule] = field(default_factory=dict)


@dataclass
class JobConfig:
    name: str
    source: str
    target: str
    key: list[str] = field(default_factory=list)
    ignore: list[str] = field(default_factory=list)
    tolerance: float = 0.0
    column_map: dict[str, str] = field(default_factory=dict)
    matching: MatchingConfig = field(default_factory=MatchingConfig)
    path: Path | None = None

    @property
    def source_path(self) -> Path:
        p = Path(self.source)
        if not p.is_absolute() and self.path:
            return self.path.parent / p
        return p

    @property
    def target_path(self) -> Path:
        p = Path(self.target)
        if not p.is_absolute() and self.path:
            return self.path.parent / p
        return p


def load_job(path: str | Path) -> JobConfig:
    try:
        import yaml
    except ImportError:
        raise JobConfigError(
            "pyyaml is required for YAML job configs: pip install pyyaml"
        )

    path = Path(path)
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except OSError as e:
        raise JobConfigError(f"{path}: {e}") from e
    except Exception as e:
        raise JobConfigError(f"{path}: invalid YAML: {e}") from e

    if not isinstance(data, dict):
        raise JobConfigError(f"{path}: must be a YAML mapping")

    source = data.get("source")
    target = data.get("target")
    if not source:
        raise JobConfigError(f"{path}: 'source' is required")
    if not target:
        raise JobConfigError(f"{path}: 'target' is required")

    name = data.get("name") or path.stem
    key = _to_str_list(data.get("key", []))
    ignore = _to_str_list(data.get("ignore", []))
    tolerance = float(data.get("tolerance", 0.0))
    column_map = {str(k): str(v) for k, v in (data.get("column_map") or {}).items()}

    matching_raw = data.get("matching") or {}
    global_case = bool(matching_raw.get("case_sensitive", True))
    global_null = bool(matching_raw.get("null_equals_empty", False))
    per_column = {
        col: ColumnRule(
            tolerance=float(cfg.get("tolerance", tolerance)),
            case_sensitive=bool(cfg.get("case_sensitive", global_case)),
            null_equals_empty=bool(cfg.get("null_equals_empty", global_null)),
        )
        for col, cfg in (matching_raw.get("per_column") or {}).items()
    }
    matching = MatchingConfig(
        case_sensitive=global_case,
        null_equals_empty=global_null,
        per_column=per_column,
    )

    return JobConfig(
        name=str(name), source=str(source), target=str(target),
        key=key, ignore=ignore, tolerance=tolerance,
        column_map=column_map, matching=matching, path=path,
    )


def _to_str_list(val) -> list[str]:
    if isinstance(val, str):
        return [s.strip() for s in val.split(",") if s.strip()]
    return [str(v) for v in (val or [])]
