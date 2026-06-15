from sf_connector.sync import _apply_modified_since


def test_modified_since_is_a_no_op_when_absent():
    assert _apply_modified_since(None, None) is None
    assert _apply_modified_since("Email != null", None) == "Email != null"


def test_modified_since_becomes_the_whole_clause_when_no_where():
    assert (
        _apply_modified_since(None, "2026-06-01T00:00:00Z")
        == "SystemModstamp >= 2026-06-01T00:00:00Z"
    )


def test_modified_since_is_anded_onto_an_existing_where():
    assert (
        _apply_modified_since("Email != null", "2026-06-01T00:00:00Z")
        == "(Email != null) AND SystemModstamp >= 2026-06-01T00:00:00Z"
    )
