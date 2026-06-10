"""Web UI: upload two files, configure the comparison, view the report."""

import tempfile
from pathlib import Path

from flask import Flask, request
from werkzeug.utils import secure_filename

from .core import CompareError, compare_paths
from .loaders import LoadError
from .recondiff import ReconError
from .report import render_html, render_template

MAX_UPLOAD_MB = 50


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024

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

    return app
