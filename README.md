# recon-tool

Compare and reconcile files of many types from the command line, with pretty
terminal output and shareable HTML reports.

| Type | Extensions | How it's compared |
|---|---|---|
| Plain text / code | `.txt`, `.log`, `.java`, anything unknown | line-by-line diff |
| JSON | `.json` | canonicalized (sorted keys, 2-space indent) then diffed — key order and whitespace don't produce noise |
| XML | `.xml` | pretty-printed with normalized whitespace, then diffed |
| Word | `.docx` | paragraph and table text extracted, then diffed |
| CSV / Excel | `.csv`, `.xlsx` | text diff by default; record reconciliation with `--key` |

## Install

```bash
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
```

## Usage

```bash
# Structural diff (any file types)
recon compare a.json b.json
recon compare old.docx new.docx
recon compare A.java B.java --html diff.html

# Record reconciliation for tabular files: match rows by key column(s),
# report only-in-A / only-in-B / duplicate keys / field-level mismatches
recon compare a.csv b.csv --key trade_id
recon compare a.xlsx b.xlsx --key trade_id,date --ignore updated_at --tolerance 0.01 --html report.html

# --show-matched: for mismatched records, display ALL fields (matched ones too),
# with the mismatching cells highlighted
recon compare a.csv b.csv --key trade_id --show-matched

# Web UI: upload files and set options in the browser at http://127.0.0.1:8765
recon serve

# Pretty-print a JSON or XML file
recon fmt messy.json
recon fmt messy.xml -o pretty.xml
```

Exit codes: `0` identical / fully reconciled, `1` differences found, `2` error —
script-friendly for pipelines.

## Adding a new file or message type

Add a loader function in `recon/loaders.py` that returns either a `list[str]`
(lines) or `(headers, rows)` (records), and register its extension in the
`LOADERS` dict. Nothing else needs to change.

## Development

```bash
.venv/bin/pytest                          # run tests
.venv/bin/python tests/fixtures/make_fixtures.py   # regenerate binary fixtures (run inside tests/fixtures)
```
