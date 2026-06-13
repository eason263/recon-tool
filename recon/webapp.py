"""Web UI: upload two files, configure the comparison, view the report."""

import os
import secrets
import tempfile
import uuid
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

from flask import Flask, abort, redirect, request, session
from werkzeug.utils import secure_filename

from . import store
from .api import api
from .auth import check_login, create_user, has_users, require_login
from .batch import BatchItem, run_batch
from .core import CompareError, compare_paths
from .loaders import LoadError
from .recondiff import ReconError, ReconResult
from .report import render_html, render_template

MAX_UPLOAD_MB = 50
MAX_STORED_BATCHES = 20


def _secret_key() -> str:
    key_file = Path(os.environ.get("RECON_DB", Path.home() / ".recon" / "recon.db")).parent / "secret_key"
    key_file.parent.mkdir(parents=True, exist_ok=True)
    if key_file.exists():
        return key_file.read_text().strip()
    key = secrets.token_hex(32)
    key_file.write_text(key)
    return key


def create_app() -> Flask:
    app = Flask(__name__)
    app.secret_key = _secret_key()
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024
    app.register_blueprint(api)

    batches: OrderedDict[str, dict] = OrderedDict()

    # ── Auth ──────────────────────────────────────────────────────────────────

    @app.get("/setup")
    def setup_form():
        if has_users():
            return redirect("/")
        return render_template("setup.html.j2")

    @app.post("/setup")
    def setup_post():
        if has_users():
            return redirect("/")
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        password2 = request.form.get("password2", "")
        if not username:
            return render_template("setup.html.j2", error="Username is required."), 400
        if not password:
            return render_template("setup.html.j2", error="Password is required."), 400
        if password != password2:
            return render_template("setup.html.j2", error="Passwords do not match."), 400
        create_user(username, password)
        session["user"] = username
        return redirect("/")

    @app.get("/login")
    def login_form():
        if not has_users():
            return redirect("/setup")
        return render_template("login.html.j2")

    @app.post("/login")
    def login_post():
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if check_login(username, password):
            session["user"] = username
            return redirect("/")
        return render_template("login.html.j2", error="Invalid username or password."), 401

    @app.get("/logout")
    def logout():
        session.pop("user", None)
        return redirect("/login")

    # ── Single comparison ─────────────────────────────────────────────────────

    @app.get("/")
    @require_login
    def index():
        return render_template("index.html.j2", form={},
                               user=session.get("user"), active="compare")

    @app.post("/compare")
    @require_login
    def compare_view():
        form = request.form.to_dict()
        file_a = request.files.get("file_a")
        file_b = request.files.get("file_b")
        if not file_a or not file_a.filename or not file_b or not file_b.filename:
            return render_template("index.html.j2", form=form,
                                   error="Please choose both files.",
                                   user=session.get("user"), active="compare"), 400

        try:
            tolerance = float(form.get("tolerance") or 0.0)
        except ValueError:
            return render_template("index.html.j2", form=form,
                                   error="Tolerance must be a number.",
                                   user=session.get("user"), active="compare"), 400
        show_matched = bool(form.get("show_matched"))

        with tempfile.TemporaryDirectory() as tmpdir:
            path_a = Path(tmpdir) / ("a_" + secure_filename(file_a.filename))
            path_b = Path(tmpdir) / ("b_" + secure_filename(file_b.filename))
            file_a.save(path_a)
            file_b.save(path_b)
            try:
                result = compare_paths(
                    path_a, path_b,
                    key=form.get("key", "").strip() or None,
                    ignore=form.get("ignore", "").strip() or None,
                    tolerance=tolerance,
                    a_name=file_a.filename,
                    b_name=file_b.filename,
                )
            except (LoadError, ReconError, CompareError) as e:
                return render_template("index.html.j2", form=form, error=str(e),
                                       user=session.get("user"), active="compare"), 400

        if isinstance(result, ReconResult):
            store.save_run(result, job_name="web-compare")

        return render_html(result, show_matched=show_matched, back_url="/")

    # ── Batch ─────────────────────────────────────────────────────────────────

    @app.get("/batch")
    @require_login
    def batch_form():
        return render_template("batch.html.j2", form={},
                               user=session.get("user"), active="batch")

    @app.get("/batch/template")
    @require_login
    def batch_template():
        from flask import Response
        csv_content = (
            "trade_id,trade_date,counterparty,instrument,notional,currency,status\n"
            "T001,2024-01-15,Goldman Sachs,AAPL US Equity,1000000.00,USD,confirmed\n"
            "T002,2024-01-15,JPMorgan,EUR/USD Spot,2500000.00,EUR,confirmed\n"
            "T003,2024-01-15,Barclays,US 10Y Bond,5000000.00,USD,pending\n"
            "T004,2024-01-15,Citibank,GBP/USD Spot,750000.00,GBP,confirmed\n"
        )
        return Response(
            csv_content, mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=recon_template.csv"},
        )

    @app.post("/batch")
    @require_login
    def batch_run():
        form = request.form.to_dict()
        source_files = request.files.getlist("source")
        target_files = request.files.getlist("target")
        file_pairs = [
            (sf, tf) for sf, tf in zip(source_files, target_files)
            if sf and sf.filename and tf and tf.filename
        ]

        def form_error(message, status=400):
            return render_template("batch.html.j2", form=form, error=message,
                                   user=session.get("user"), active="batch"), status

        if not file_pairs:
            return form_error("Please upload at least one source/target file pair.")
        try:
            tolerance = float(form.get("tolerance") or 0.0)
        except ValueError:
            return form_error("Tolerance must be a number.")

        key = form.get("key", "").strip() or None
        ignore = form.get("ignore", "").strip() or None

        with tempfile.TemporaryDirectory() as tmpdir:
            items = []
            for n, (sf, tf) in enumerate(file_pairs, start=1):
                sub = Path(tmpdir) / str(n)
                sub.mkdir()
                path_a = sub / secure_filename(sf.filename)
                path_b = sub / secure_filename(tf.filename)
                sf.save(path_a)
                tf.save(path_b)
                item = BatchItem(index=n, source=sf.filename, target=tf.filename)
                try:
                    try:
                        item.result = compare_paths(
                            path_a, path_b,
                            key=key, ignore=ignore, tolerance=tolerance,
                            a_name=sf.filename, b_name=tf.filename,
                        )
                    except CompareError:
                        item.result = compare_paths(
                            path_a, path_b,
                            a_name=sf.filename, b_name=tf.filename,
                        )
                except (LoadError, ReconError, OSError) as e:
                    item.error = str(e)
                items.append(item)

        for item in items:
            if isinstance(item.result, ReconResult):
                store.save_run(item.result, job_name="web-batch")

        bid = uuid.uuid4().hex[:12]
        batches[bid] = {
            "items": items,
            "show_matched": bool(form.get("show_matched")),
            "generated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        while len(batches) > MAX_STORED_BATCHES:
            batches.popitem(last=False)
        return redirect(f"/batch/{bid}")

    @app.get("/batch/<bid>")
    @require_login
    def batch_summary(bid):
        stored = batches.get(bid)
        if stored is None:
            abort(404)
        links = {item.index: f"/batch/{bid}/{item.index}"
                 for item in stored["items"] if item.result is not None}
        return render_template("batch_report.html.j2", items=stored["items"],
                               links=links, manifest=None, back_url="/batch",
                               generated=stored["generated"],
                               user=session.get("user"), active="batch")

    @app.get("/batch/<bid>/<int:index>")
    @require_login
    def batch_detail(bid, index):
        stored = batches.get(bid)
        if stored is None:
            abort(404)
        item = next((i for i in stored["items"] if i.index == index), None)
        if item is None or item.result is None:
            abort(404)
        return render_html(item.result, show_matched=stored["show_matched"],
                           back_url=f"/batch/{bid}")

    # ── Run history ───────────────────────────────────────────────────────────

    @app.get("/runs")
    @require_login
    def runs_list():
        runs = store.list_runs(limit=200)
        return render_template("runs.html.j2", runs=runs,
                               user=session.get("user"), active="runs")

    @app.get("/runs/<int:run_id>")
    @require_login
    def run_detail(run_id):
        try:
            run, breaks = store.get_run(run_id)
        except KeyError:
            abort(404)
        status_filter = request.args.get("status", "")
        return render_template(
            "run_detail.html.j2",
            run=run, breaks=breaks, user=session.get("user"),
            status_filter=status_filter, active="runs",
        )

    @app.get("/runs/<int:run_id>/export")
    @require_login
    def run_export(run_id):
        import csv
        import io
        from flask import Response
        try:
            _, breaks = store.get_run(run_id)
        except KeyError:
            abort(404)
        fmt = request.args.get("format", "json")
        if fmt == "csv":
            output = io.StringIO()
            fields = ["id", "break_type", "key_json", "column", "a_value", "b_value",
                      "status", "assigned_to", "note", "resolved_at"]
            w = csv.writer(output)
            w.writerow(fields)
            for b in breaks:
                w.writerow([getattr(b, f) for f in fields])
            return Response(output.getvalue(), mimetype="text/csv",
                            headers={"Content-Disposition":
                                     f"attachment; filename=run_{run_id}_breaks.csv"})
        from flask import jsonify
        return jsonify([{
            "id": b.id, "break_type": b.break_type, "key_display": b.key_display,
            "column": b.column, "a_value": b.a_value, "b_value": b.b_value,
            "status": b.status, "assigned_to": b.assigned_to, "note": b.note,
        } for b in breaks])

    @app.get("/runs/<int:run_id>/breaks/<int:break_id>")
    @require_login
    def break_detail(run_id, break_id):
        try:
            _, breaks = store.get_run(run_id)
        except KeyError:
            abort(404)
        brk = next((b for b in breaks if b.id == break_id), None)
        if brk is None:
            abort(404)
        saved = request.args.get("saved") == "1"
        return render_template("break_detail.html.j2", brk=brk,
                               user=session.get("user"), saved=saved, active="runs")

    @app.post("/runs/<int:run_id>/breaks/<int:break_id>")
    @require_login
    def break_update(run_id, break_id):
        status = request.form.get("status", "open")
        assigned_to = request.form.get("assigned_to", "").strip() or None
        note = request.form.get("note", "").strip() or None
        store.update_break(break_id, status=status, assigned_to=assigned_to, note=note)
        return redirect(f"/runs/{run_id}/breaks/{break_id}?saved=1")

    return app
