from conftest import docx_text
from rollcall.merge import generate, inspect_template
from rollcall.roster import load_roster
from rollcall.starter import create_starter_template, placeholder_for


def test_starter_uses_every_column(tmp_path, make_xlsx):
    roster = load_roster(make_xlsx([["First Name", "Last Name", "Name", "Name", None], ["Ada", "Lovelace", "x", "y", "z"]]))
    path = create_starter_template(roster, tmp_path / "Starter.docx")

    check = inspect_template(path, roster)
    assert check.ok
    assert check.unused == []

    text = docx_text(path)
    assert "First Name: {{First Name}}" in text
    assert "Name: {{name_2}}" in text  # duplicate header falls back to the key
    assert "Column 5: {{Column 5}}" in text


def test_starter_round_trip(tmp_path, make_xlsx):
    roster = load_roster(make_xlsx([["First Name", "Last Name"], ["José", "Núñez"]]))
    template = create_starter_template(roster, tmp_path / "Starter.docx")
    result = generate(roster, template, tmp_path / "out", "{first_name}")
    text = docx_text(result.created[0])
    assert "First Name: José" in text
    assert "Last Name: Núñez" in text
    assert "{{" not in text


def test_placeholder_for(make_xlsx):
    roster = load_roster(make_xlsx([["First Name", "First Name"], ["a", "b"]]))
    first, second = roster.columns
    assert placeholder_for(first) == "{{First Name}}"
    assert placeholder_for(second) == "{{first_name_2}}"
