from sf_connector.transform import records_to_csv


def test_empty_records_produce_empty_bytes():
    assert records_to_csv([]) == b""


def test_header_is_union_of_keys_in_first_seen_order():
    records = [
        {"Id": "1", "Name": "Acme"},
        {"Id": "2", "Industry": "Tech"},
    ]
    csv = records_to_csv(records).decode()
    header = csv.splitlines()[0]
    assert header == "Id,Name,Industry"


def test_missing_field_becomes_empty_cell():
    records = [
        {"Id": "1", "Name": "Acme"},
        {"Id": "2"},
    ]
    rows = records_to_csv(records).decode().splitlines()
    assert rows[2] == "2,"


def test_none_becomes_empty_and_nested_is_json():
    records = [{"Id": "1", "Owner": {"Name": "Sam"}, "Note": None}]
    csv = records_to_csv(records).decode()
    assert '"{""Name"":""Sam""}"' in csv  # JSON, csv-quoted
    assert csv.strip().endswith(",")  # trailing empty cell for Note
