from vodin.storage import JsonStore


def test_json_store_roundtrip(tmp_path):
    store = JsonStore(tmp_path / "state.json")
    payload = {"hostname": {"ip": "10.0.0.10"}}
    store.write(payload)

    assert store.read() == payload
