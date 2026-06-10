from recon.textdiff import diff_lines


def test_identical():
    result = diff_lines(["a", "b"], ["a", "b"], "a", "b")
    assert result.identical
    assert result.unified == []
    assert result.rows == []


def test_insert_delete_replace():
    a = ["one", "two", "three", "four"]
    b = ["one", "TWO", "three", "five", "four"]
    result = diff_lines(a, b, "a", "b")
    assert not result.identical
    assert result.changed == 1  # two -> TWO
    assert result.added == 1    # five
    assert result.removed == 0

    tags = [row.tag for row in result.rows]
    assert tags == ["equal", "replace", "equal", "insert", "equal"]

    replace_row = result.rows[1]
    assert (replace_row.left, replace_row.right) == ("two", "TWO")
    insert_row = result.rows[3]
    assert (insert_row.left_no, insert_row.right) == (None, "five")


def test_unified_output_has_headers():
    result = diff_lines(["x"], ["y"], "left.txt", "right.txt")
    assert result.unified[0].startswith("--- left.txt")
    assert result.unified[1].startswith("+++ right.txt")
