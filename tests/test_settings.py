from rollcall.settings import load_settings, save_settings


def test_round_trip(tmp_path):
    path = tmp_path / "RollCall" / "settings.json"
    save_settings({"template": "C:/Users/me/Certificate.docx", "pdf": True}, path)
    assert load_settings(path) == {"template": "C:/Users/me/Certificate.docx", "pdf": True}


def test_missing_or_damaged_file(tmp_path):
    assert load_settings(tmp_path / "nope.json") == {}
    damaged = tmp_path / "settings.json"
    damaged.write_text("{not json")
    assert load_settings(damaged) == {}
    damaged.write_text("[1, 2]")
    assert load_settings(damaged) == {}
