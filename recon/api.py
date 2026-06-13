"""REST API blueprint — /api/v1/"""
from __future__ import annotations
import csv
import io

from flask import Blueprint, Response, abort, jsonify, request

from . import store
from .auth import verify_api_key

api = Blueprint("api", __name__, url_prefix="/api/v1")


def _auth() -> str:
    key = request.headers.get("X-API-Key", "")
    user = verify_api_key(key) if key else None
    if not user:
        abort(401, "Missing or invalid X-API-Key")
    return user


# ── Run history ───────────────────────────────────────────────────────────────

@api.get("/runs")
def list_runs():
    _auth()
    job = request.args.get("job") or None
    limit = min(int(request.args.get("limit", 100)), 1000)
    runs = store.list_runs(limit=limit, job_name=job)
    return jsonify([_run_dict(r) for r in runs])


@api.get("/runs/<int:run_id>")
def get_run(run_id: int):
    _auth()
    try:
        summary, breaks = store.get_run(run_id)
    except KeyError:
        abort(404)
    return jsonify({"run": _run_dict(summary), "breaks": [_break_dict(b) for b in breaks]})


# ── Break management ──────────────────────────────────────────────────────────

@api.get("/runs/<int:run_id>/breaks")
def get_breaks(run_id: int):
    _auth()
    try:
        _, breaks = store.get_run(run_id)
    except KeyError:
        abort(404)
    status = request.args.get("status")
    if status:
        breaks = [b for b in breaks if b.status == status]
    return jsonify([_break_dict(b) for b in breaks])


@api.patch("/runs/<int:run_id>/breaks/<int:break_id>")
def update_break(run_id: int, break_id: int):
    user = _auth()
    data = request.get_json(silent=True) or {}
    status = data.get("status", "open")
    if status not in ("open", "resolved", "false_positive"):
        abort(400, "status must be open, resolved, or false_positive")
    store.update_break(
        break_id,
        status=status,
        assigned_to=data.get("assigned_to") or user,
        note=data.get("note"),
    )
    return jsonify({"ok": True})


# ── Export ────────────────────────────────────────────────────────────────────

@api.get("/runs/<int:run_id>/export")
def export_breaks(run_id: int):
    _auth()
    try:
        _, breaks = store.get_run(run_id)
    except KeyError:
        abort(404)

    fmt = request.args.get("format", "json")
    if fmt == "csv":
        output = io.StringIO()
        fields = ["id", "break_type", "key_json", "column", "a_value", "b_value",
                  "status", "assigned_to", "note", "resolved_at"]
        w = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for b in breaks:
            w.writerow(_break_dict(b))
        return Response(
            output.getvalue(), mimetype="text/csv",
            headers={"Content-Disposition": f"attachment; filename=run_{run_id}_breaks.csv"},
        )
    return jsonify([_break_dict(b) for b in breaks])


# ── Trigger a job ─────────────────────────────────────────────────────────────

@api.post("/jobs")
def run_job():
    _auth()
    data = request.get_json(silent=True) or {}
    source = data.get("source")
    target = data.get("target")
    if not source or not target:
        abort(400, "source and target are required")

    from .core import CompareError, compare_paths
    from .loaders import LoadError
    from .recondiff import ReconError, ReconResult

    key = data.get("key") or None
    ignore = data.get("ignore") or None
    try:
        tolerance = float(data.get("tolerance", 0.0))
    except (TypeError, ValueError):
        abort(400, "tolerance must be a number")

    job_name = data.get("name") or "api-job"
    try:
        result = compare_paths(source, target, key=key, ignore=ignore, tolerance=tolerance)
    except (LoadError, ReconError, CompareError) as e:
        return jsonify({"error": str(e)}), 400

    if isinstance(result, ReconResult):
        run_id = store.save_run(result, job_name)
        return jsonify({
            "run_id": run_id,
            "status": "MATCH" if result.reconciled else "DIFF",
            "total_a": result.total_a, "total_b": result.total_b,
            "matched": result.matched,
            "mismatches": len(result.mismatches),
            "only_in_a": len(result.only_in_a),
            "only_in_b": len(result.only_in_b),
        }), 201
    return jsonify({"status": "MATCH" if result.identical else "DIFF"})


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run_dict(r: store.RunSummary) -> dict:
    return {
        "id": r.id, "job_name": r.job_name,
        "source": r.source, "target": r.target,
        "ran_at": r.ran_at, "status": r.status,
        "total_a": r.total_a, "total_b": r.total_b, "matched": r.matched,
        "mismatches": r.mismatches, "only_in_a": r.only_in_a, "only_in_b": r.only_in_b,
    }


def _break_dict(b: store.BreakRecord) -> dict:
    return {
        "id": b.id, "run_id": b.run_id, "break_type": b.break_type,
        "key_json": b.key_json, "key_display": b.key_display,
        "column": b.column, "a_value": b.a_value, "b_value": b.b_value,
        "status": b.status, "assigned_to": b.assigned_to,
        "note": b.note, "resolved_at": b.resolved_at,
    }
