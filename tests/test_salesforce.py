from sf_connector.salesforce import _clean, build_soql


def test_build_soql_minimal():
    assert build_soql("Account", ["Id", "Name"]) == "SELECT Id, Name FROM Account"


def test_build_soql_with_where_and_limit():
    soql = build_soql("Contact", ["Id"], where="Email != null", limit=50)
    assert soql == "SELECT Id FROM Contact WHERE Email != null LIMIT 50"


def test_clean_strips_attributes():
    record = {"attributes": {"type": "Account"}, "Id": "1", "Name": "Acme"}
    assert _clean(record) == {"Id": "1", "Name": "Acme"}
