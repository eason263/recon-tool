"""Tests for jobconfig, store, matching, auth, and API."""
import json
import os
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


# ── matching.py ───────────────────────────────────────────────────────────────

from recon.matching import ColumnRule, apply_column_map, compare_values, norm


def test_norm_strips_whitespace():
    assert norm("  hello  ") == "hello"


def test_norm_none_to_empty():
    assert norm(None) == ""


def test_norm_null_equiv_when_enabled():
    assert norm("N/A", null_equals_empty=True) == ""
    assert norm("NULL", null_equals_empty=True) == ""
    assert norm("N/A", null_equals_empty=False) == "N/A"


def test_norm_case_insensitive():
    assert norm("HELLO", case_sensitive=False) == "hello"
    assert norm("HELLO", case_sensitive=True) == "HELLO"


def test_compare_values_exact():
    rule = ColumnRule()
    assert compare_values("100", "100", rule)
    assert not compare_values("100", "200", rule)


def test_compare_values_tolerance():
    rule = ColumnRule(tolerance=0.01)
    assert compare_values("100.005", "100.000", rule)
    assert not compare_values("100.02", "100.00", rule)


def test_apply_column_map_renames_target():
    headers = ["TradeID", "amount"]
    rows = [{"TradeID": "T1", "amount": "100"}]
    column_map = {"trade_id": "TradeID", "notional": "amount"}
    new_headers, new_rows = apply_column_map(headers, rows, column_map)
    assert new_headers == ["trade_id", "notional"]
    assert new_rows[0] == {"trade_id": "T1", "notional": "100"}


# ── recondiff.py with new matching params ─────────────────────────────────────

from recon.recondiff import reconcile


def _make_data(headers, rows):
    return headers, [dict(zip(headers, r)) for r in rows]


def test_case_insensitive_matching():
    a = _make_data(["id", "name"], [["1", "Alice"]])
    b = _make_data(["id", "name"], [["1", "ALICE"]])
    result = reconcile(a, b, "A", "B", ["id"], case_sensitive=False)
    assert result.reconciled


def test_null_equals_empty():
    a = _make_data(["id", "note"], [["1", ""]])
    b = _make_data(["id", "note"], [["1", "N/A"]])
    result = reconcile(a, b, "A", "B", ["id"], null_equals_empty=True)
    assert result.reconciled


def test_column_map_renames_target_before_matching():
    a = _make_data(["trade_id", "amount"], [["T1", "100"]])
    b = _make_data(["TradeID", "notional"], [["T1", "100"]])
    result = reconcile(a, b, "A", "B", ["trade_id"],
                       column_map={"trade_id": "TradeID", "amount": "notional"})
    assert result.reconciled


def test_per_column_tolerance():
    a = _make_data(["id", "price", "qty"], [["1", "100.005", "10.005"]])
    b = _make_data(["id", "price", "qty"], [["1", "100.000", "10.000"]])
    per_col = {
        "price": ColumnRule(tolerance=0.01),
        "qty": ColumnRule(tolerance=0.01),
    }
    result = reconcile(a, b, "A", "B", ["id"], column_rules=per_col)
    assert result.reconciled

    # qty diff 0.005 > 0.001 tight tolerance → break
    per_col_tight = {"price": ColumnRule(tolerance=0.01), "qty": ColumnRule(tolerance=0.001)}
    result2 = reconcile(a, b, "A", "B", ["id"], column_rules=per_col_tight)
    assert not result2.reconciled


# ── jobconfig.py ──────────────────────────────────────────────────────────────

from recon.jobconfig import JobConfigError, load_job


def test_load_job_minimal(tmp_path):
    f = tmp_path / "job.yaml"
    f.write_text("source: a.csv\ntarget: b.csv\n")
    job = load_job(f)
    assert job.source == "a.csv"
    assert job.target == "b.csv"
    assert job.name == "job"


def test_load_job_full(tmp_path):
    f = tmp_path / "trades.yaml"
    f.write_text("""
name: Daily Trade Recon
source: data/a.csv
target: data/b.csv
key: [trade_id, date]
ignore: [updated_at]
tolerance: 0.01
column_map:
  trade_id: TradeID
matching:
  case_sensitive: false
  null_equals_empty: true
  per_column:
    amount: {tolerance: 0.005}
""")
    job = load_job(f)
    assert job.name == "Daily Trade Recon"
    assert job.key == ["trade_id", "date"]
    assert job.ignore == ["updated_at"]
    assert job.tolerance == 0.01
    assert job.column_map == {"trade_id": "TradeID"}
    assert not job.matching.case_sensitive
    assert job.matching.null_equals_empty
    assert job.matching.per_column["amount"].tolerance == 0.005


def test_load_job_missing_source_raises(tmp_path):
    f = tmp_path / "bad.yaml"
    f.write_text("target: b.csv\n")
    with pytest.raises(JobConfigError, match="source"):
        load_job(f)


def test_load_job_relative_paths_resolve_against_job_file(tmp_path):
    f = tmp_path / "job.yaml"
    f.write_text("source: a.csv\ntarget: b.csv\n")
    job = load_job(f)
    assert job.source_path == tmp_path / "a.csv"


# ── store.py ──────────────────────────────────────────────────────────────────

from recon.recondiff import ReconResult, FieldMismatch


def test_store_save_and_retrieve(tmp_path, monkeypatch):
    monkeypatch.setenv("RECON_DB", str(tmp_path / "test.db"))
    from recon import store

    result = ReconResult(
        a_name="A", b_name="B",
        key_columns=["id"], compared_columns=["amount"],
        total_a=2, total_b=2, matched=1,
    )
    result.mismatches = [FieldMismatch(("T1",), "amount", "100", "200")]
    result.mismatched_keys = [("T1",)]
    result.only_in_a = [("T2",)]

    run_id = store.save_run(result, "test-job")
    assert run_id > 0

    summary, breaks = store.get_run(run_id)
    assert summary.job_name == "test-job"
    assert summary.status == "DIFF"
    assert summary.mismatches == 1
    assert summary.only_in_a == 1

    mismatch_breaks = [b for b in breaks if b.break_type == "field_mismatch"]
    assert len(mismatch_breaks) == 1
    assert mismatch_breaks[0].column == "amount"
    assert mismatch_breaks[0].a_value == "100"


def test_store_update_break(tmp_path, monkeypatch):
    monkeypatch.setenv("RECON_DB", str(tmp_path / "test.db"))
    from recon import store

    result = ReconResult(
        a_name="A", b_name="B",
        key_columns=["id"], compared_columns=["val"],
        total_a=1, total_b=1, matched=0,
    )
    result.mismatches = [FieldMismatch(("K1",), "val", "x", "y")]
    result.mismatched_keys = [("K1",)]
    run_id = store.save_run(result, "job")

    _, breaks = store.get_run(run_id)
    brk = breaks[0]
    assert brk.status == "open"

    store.update_break(brk.id, status="resolved", assigned_to="alice", note="checked")
    _, breaks2 = store.get_run(run_id)
    updated = breaks2[0]
    assert updated.status == "resolved"
    assert updated.assigned_to == "alice"
    assert updated.note == "checked"
    assert updated.resolved_at is not None


# ── auth.py ───────────────────────────────────────────────────────────────────

def test_create_and_verify_user(tmp_path, monkeypatch):
    monkeypatch.setenv("RECON_DB", str(tmp_path / "test.db"))
    from recon.auth import check_login, create_user, has_users, verify_api_key

    assert not has_users()
    api_key = create_user("bob", "secret")
    assert has_users()
    assert check_login("bob", "secret")
    assert not check_login("bob", "wrong")
    assert verify_api_key(api_key) == "bob"
    assert verify_api_key("badkey") is None


# ── REST API ──────────────────────────────────────────────────────────────────

from recon.webapp import create_app


@pytest.fixture
def api_client(tmp_path, monkeypatch):
    monkeypatch.setenv("RECON_DB", str(tmp_path / "test.db"))
    from recon.auth import create_user
    api_key = create_user("admin", "pass")
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c, api_key


def test_api_unauthorized(api_client):
    c, _ = api_client
    resp = c.get("/api/v1/runs")
    assert resp.status_code == 401


def test_api_list_runs_empty(api_client):
    c, key = api_client
    resp = c.get("/api/v1/runs", headers={"X-API-Key": key})
    assert resp.status_code == 200
    assert resp.json == []


def test_api_trigger_job_and_list(api_client):
    c, key = api_client
    headers = {"X-API-Key": key}
    resp = c.post("/api/v1/jobs", json={
        "name": "test-job",
        "source": str(FIXTURES / "a.csv"),
        "target": str(FIXTURES / "b.csv"),
        "key": "trade_id",
        "ignore": "updated_at",
    }, headers=headers)
    assert resp.status_code == 201
    data = resp.json
    assert data["status"] == "DIFF"
    run_id = data["run_id"]

    runs = c.get("/api/v1/runs", headers=headers).json
    assert len(runs) == 1
    assert runs[0]["id"] == run_id

    detail = c.get(f"/api/v1/runs/{run_id}", headers=headers).json
    assert detail["run"]["job_name"] == "test-job"
    assert len(detail["breaks"]) > 0


def test_api_update_break(api_client):
    c, key = api_client
    headers = {"X-API-Key": key}
    c.post("/api/v1/jobs", json={
        "source": str(FIXTURES / "a.csv"),
        "target": str(FIXTURES / "b.csv"),
        "key": "trade_id",
    }, headers=headers)
    runs = c.get("/api/v1/runs", headers=headers).json
    run_id = runs[0]["id"]

    breaks = c.get(f"/api/v1/runs/{run_id}/breaks", headers=headers).json
    bid = breaks[0]["id"]

    resp = c.patch(f"/api/v1/runs/{run_id}/breaks/{bid}",
                   json={"status": "resolved", "note": "confirmed"},
                   headers=headers)
    assert resp.status_code == 200

    updated = c.get(f"/api/v1/runs/{run_id}/breaks", headers=headers).json
    assert updated[0]["status"] == "resolved"


def test_api_export_csv(api_client):
    c, key = api_client
    headers = {"X-API-Key": key}
    c.post("/api/v1/jobs", json={
        "source": str(FIXTURES / "a.csv"),
        "target": str(FIXTURES / "b.csv"),
        "key": "trade_id",
    }, headers=headers)
    run_id = c.get("/api/v1/runs", headers=headers).json[0]["id"]
    resp = c.get(f"/api/v1/runs/{run_id}/export?format=csv", headers=headers)
    assert resp.status_code == 200
    assert resp.content_type.startswith("text/csv")
    assert b"break_type" in resp.data
