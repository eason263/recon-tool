import io
from pathlib import Path

import pytest

from recon.webapp import create_app

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


def _upload(name):
    return (io.BytesIO((FIXTURES / name).read_bytes()), name)


def test_index_form(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert b"File A" in resp.data and b"Key column" in resp.data


def test_recon_via_web(client):
    resp = client.post("/compare", data={
        "file_a": _upload("a.csv"),
        "file_b": _upload("b.csv"),
        "key": "trade_id",
        "ignore": "updated_at",
        "tolerance": "",
    }, content_type="multipart/form-data")
    assert resp.status_code == 200
    assert b"differences found" in resp.data
    assert b"Field mismatches" in resp.data
    assert b"T003" in resp.data and b"T004" in resp.data


def test_recon_show_matched_via_web(client):
    resp = client.post("/compare", data={
        "file_a": _upload("a.csv"),
        "file_b": _upload("b.csv"),
        "key": "trade_id",
        "show_matched": "1",
    }, content_type="multipart/form-data")
    assert resp.status_code == 200
    assert b"Mismatched records" in resp.data
    # matched field of a mismatched record is displayed too
    assert b"USD" in resp.data


def test_text_diff_via_web(client):
    resp = client.post("/compare", data={
        "file_a": _upload("a.txt"),
        "file_b": _upload("b.txt"),
        "key": "",
    }, content_type="multipart/form-data")
    assert resp.status_code == 200
    assert b"Side-by-side diff" in resp.data


def test_missing_file_is_an_error(client):
    resp = client.post("/compare", data={"key": ""},
                       content_type="multipart/form-data")
    assert resp.status_code == 400
    assert b"choose both files" in resp.data


def test_batch_form(client):
    resp = client.get("/batch")
    assert resp.status_code == 200
    assert b"Batch reconciliation" in resp.data


def test_batch_run_and_detail(client):
    resp = client.post("/batch", data={
        "source": [str(FIXTURES / "a.csv"), str(FIXTURES / "a.txt"), ""],
        "target": [str(FIXTURES / "b.csv"), str(FIXTURES / "b.txt"), ""],
        "key": "trade_id",
        "ignore": "updated_at",
    })
    assert resp.status_code == 302
    summary = client.get(resp.headers["Location"])
    assert summary.status_code == 200
    assert summary.data.count(b'class="badge DIFF"') == 2

    detail = client.get(resp.headers["Location"] + "/1")
    assert detail.status_code == 200
    assert b"Field mismatches" in detail.data


def test_batch_incomplete_row_is_an_error(client):
    resp = client.post("/batch", data={
        "source": [str(FIXTURES / "a.csv")],
        "target": [""],
    })
    assert resp.status_code == 400
    assert b"both a source and a target" in resp.data


def test_key_on_text_files_is_an_error(client):
    resp = client.post("/compare", data={
        "file_a": _upload("a.txt"),
        "file_b": _upload("b.txt"),
        "key": "id",
    }, content_type="multipart/form-data")
    assert resp.status_code == 400
    assert b"tabular" in resp.data
