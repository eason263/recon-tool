"""Web UI: upload two files, configure the comparison, view the report."""

import tempfile
import uuid
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

from flask import Flask, abort, redirect, request
from werkzeug.utils import secure_filename

from .batch import run_batch
from .core import CompareError, compare_paths
from .loaders import LoadError
from .recondiff import ReconError
from .report import render_html, render_template

MAX_UPLOAD_MB = 50
MAX_STORED_BATCHES = 20


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024
    batches: OrderedDict[str, dict] = OrderedDict()

    @app.get("/")
    def index():
        return render_template("index.html.j2", form={})

    @app.post("/compare")
    def compare_view():
        form = request.form.to_dict()
        file_a = request.files.get("file_a")
        file_b = request.files.get("file_b")
        if not file_a or not file_a.filename or not file_b or not file_b.filename:
            return render_template("index.html.j2", form=form,
                                   error="Please choose both files."), 400

        try:
            tolerance = float(form.get("tolerance") or 0.0)
        except ValueError:
            return render_template("index.html.j2", form=form,
                                   error="Tolerance must be a number."), 400
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
                return render_template("index.html.j2", form=form, error=str(e)), 400

        return render_html(result, show_matched=show_matched, back_url="/")

    @app.get("/batch")
    def batch_form():
        return render_template("batch.html.j2", form={}, form_rows=None)

    @app.post("/batch")
    def batch_run():
        form = request.form.to_dict()
        sources = request.form.getlist("source")
        targets = request.form.getlist("target")
        rows = [(s.strip(), t.strip()) for s, t in zip(sources, targets)]
        pairs = [(s, t) for s, t in rows if s or t]

        def form_error(message, status=400):
            return render_template("batch.html.j2", form=form,
                                   form_rows=rows, error=message), status

        if not pairs:
            return form_error("Please enter at least one source/target pair.")
        for n, (s, t) in enumerate(pairs, start=1):
            if not s or not t:
                return form_error(f"Row {n} needs both a source and a target path.")
        try:
            tolerance = float(form.get("tolerance") or 0.0)
        except ValueError:
            return form_error("Tolerance must be a number.")

        items = run_batch(pairs,
                          key=form.get("key", "").strip() or None,
                          ignore=form.get("ignore", "").strip() or None,
                          tolerance=tolerance)
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
    def batch_summary(bid):
        stored = batches.get(bid)
        if stored is None:
            abort(404)
        links = {item.index: f"/batch/{bid}/{item.index}"
                 for item in stored["items"] if item.result is not None}
        return render_template("batch_report.html.j2", items=stored["items"],
                               links=links, manifest=None, back_url="/batch",
                               generated=stored["generated"])

    @app.get("/batch/<bid>/<int:index>")
    def batch_detail(bid, index):
        stored = batches.get(bid)
        if stored is None:
            abort(404)
        item = next((i for i in stored["items"] if i.index == index), None)
        if item is None or item.result is None:
            abort(404)
        return render_html(item.result, show_matched=stored["show_matched"],
                           back_url=f"/batch/{bid}")

    return app
