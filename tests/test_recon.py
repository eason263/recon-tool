import pytest

from recon.recondiff import ReconError, reconcile

HEADERS = ["id", "name", "amount"]


def rows(*tuples):
    return [dict(zip(HEADERS, t)) for t in tuples]


def test_fully_reconciled():
    a = (HEADERS, rows(("1", "alice", "10"), ("2", "bob", "20")))
    b = (HEADERS, rows(("2", "bob", "20"), ("1", "alice", "10")))
    result = reconcile(a, b, "a", "b", key_columns=["id"])
    assert result.reconciled
    assert result.matched == 2


def test_missing_and_extra_records():
    a = (HEADERS, rows(("1", "alice", "10"), ("2", "bob", "20")))
    b = (HEADERS, rows(("2", "bob", "20"), ("3", "carol", "30")))
    result = reconcile(a, b, "a", "b", key_columns=["id"])
    assert not result.reconciled
    assert result.only_in_a == [("1",)]
    assert result.only_in_b == [("3",)]
    assert result.matched == 1


def test_field_mismatch_and_ignore():
    a = (HEADERS, rows(("1", "alice", "10")))
    b = (HEADERS, rows(("1", "ALICE", "10")))
    result = reconcile(a, b, "a", "b", key_columns=["id"])
    assert len(result.mismatches) == 1
    m = result.mismatches[0]
    assert (m.column, m.a_value, m.b_value) == ("name", "alice", "ALICE")

    ignored = reconcile(a, b, "a", "b", key_columns=["id"], ignore_columns=["name"])
    assert ignored.reconciled


def test_multi_column_key():
    headers = ["id", "date", "amount"]
    a = (headers, [{"id": "1", "date": "2026-01-01", "amount": "5"},
                   {"id": "1", "date": "2026-01-02", "amount": "6"}])
    b = (headers, [{"id": "1", "date": "2026-01-01", "amount": "5"},
                   {"id": "1", "date": "2026-01-02", "amount": "7"}])
    result = reconcile(a, b, "a", "b", key_columns=["id", "date"])
    assert result.matched == 2
    assert result.mismatched_keys == [("1", "2026-01-02")]


def test_numeric_tolerance():
    a = (HEADERS, rows(("1", "alice", "10.001")))
    b = (HEADERS, rows(("1", "alice", "10.002")))
    assert not reconcile(a, b, "a", "b", key_columns=["id"]).reconciled
    assert reconcile(a, b, "a", "b", key_columns=["id"], tolerance=0.01).reconciled


def test_duplicate_keys_reported():
    a = (HEADERS, rows(("1", "alice", "10"), ("1", "alice2", "11")))
    b = (HEADERS, rows(("1", "alice", "10")))
    result = reconcile(a, b, "a", "b", key_columns=["id"])
    assert result.duplicate_keys_a == [("1",)]
    assert not result.reconciled


def test_missing_key_column_raises():
    a = (HEADERS, rows(("1", "alice", "10")))
    b = (["other"], [{"other": "x"}])
    with pytest.raises(ReconError):
        reconcile(a, b, "a", "b", key_columns=["id"])
