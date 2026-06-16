import inspect

from sf_connector.adapter import CanonicalType, SourceAdapter
from sf_connector.salesforce import build_soql
from sf_connector.salesforce_adapter import SalesforceAdapter, canonical_type


def test_canonical_type_mapping_covers_the_spec_table():
    assert canonical_type("string") is CanonicalType.STRING
    assert canonical_type("picklist") is CanonicalType.STRING
    assert canonical_type("id") is CanonicalType.STRING
    assert canonical_type("int") is CanonicalType.INTEGER
    assert canonical_type("double") is CanonicalType.DECIMAL
    assert canonical_type("currency") is CanonicalType.DECIMAL
    assert canonical_type("boolean") is CanonicalType.BOOLEAN
    assert canonical_type("datetime") is CanonicalType.TIMESTAMP


def test_unknown_type_falls_back_to_string():
    assert canonical_type("some_future_type") is CanonicalType.STRING


def test_salesforce_capabilities():
    caps = SalesforceAdapter.__new__(SalesforceAdapter).capabilities()
    assert caps.filter_pushdown is True
    assert caps.paging is True
    assert caps.incremental is True
    assert caps.catalogs is False  # Salesforce is a flat object model


def test_contract_is_read_only_by_shape():
    # The whole point of the contract: no method can mutate a source.
    methods = {name for name, _ in inspect.getmembers(SourceAdapter, inspect.isfunction)}
    forbidden = {"write_rows", "insert", "update", "delete", "execute", "ddl"}
    assert methods.isdisjoint(forbidden)


def test_read_request_builds_soql_with_order_and_filter():
    soql = build_soql(
        "Account",
        ["Id", "Name"],
        where="Industry = 'Tech'",
        limit=100,
        order_by="Name ASC",
    )
    assert soql == (
        "SELECT Id, Name FROM Account WHERE Industry = 'Tech' "
        "ORDER BY Name ASC LIMIT 100"
    )
