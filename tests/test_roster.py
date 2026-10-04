from datetime import date, datetime

import pytest

from rollcall.roster import RosterError, load_roster, make_key


@pytest.mark.parametrize(
    "header, expected",
    [
        ("First Name", "first_name"),
        ("  Last-Name  ", "last_name"),
        ("Student's Grade (%)", "student_s_grade"),
        ("2nd Period", "col_2nd_period"),
        ("José", "josé"),
        ("", ""),
        ("???", ""),
        ("Not", "not_"),
        ("Class", "class"),
        ("None", "none_"),
    ],
)
def test_make_key(header, expected):
    assert make_key(header) == expected


def test_load_xlsx_basic(make_xlsx):
    path = make_xlsx([["First Name", "Last Name"], ["Ada", "Lovelace"], ["Alan", "Turing"]])
    roster = load_roster(path)
    assert roster.keys == ["first_name", "last_name"]
    assert [c.label for c in roster.columns] == ["First Name", "Last Name"]
    assert roster.rows == [
        {"first_name": "Ada", "last_name": "Lovelace"},
        {"first_name": "Alan", "last_name": "Turing"},
    ]


def test_load_xlsx_skips_leading_and_blank_rows(make_xlsx):
    path = make_xlsx(
        [
            [None, None],
            ["First", "Last"],
            ["Ada", "Lovelace"],
            [None, None],
            ["  ", None],
            ["Alan", "Turing"],
        ]
    )
    roster = load_roster(path)
    assert [r["first"] for r in roster.rows] == ["Ada", "Alan"]


def test_xlsx_value_formatting(make_xlsx):
    path = make_xlsx(
        [
            ["Name", "Grade", "Score", "Birthday", "Due", "Note"],
            ["  Ada ", 5.0, 92.5, date(2015, 3, 5), datetime(2026, 10, 3, 0, 0), None],
        ]
    )
    row = load_roster(path).rows[0]
    assert row == {
        "name": "Ada",
        "grade": "5",
        "score": "92.5",
        "birthday": "March 5, 2015",
        "due": "October 3, 2026",
        "note": "",
    }


def test_header_edge_cases(make_xlsx):
    path = make_xlsx([["Name", None, "Name", "#"], ["a", "b", "c", "d"]])
    roster = load_roster(path)
    assert roster.keys == ["name", "column_2", "name_2", "column_4"]
    assert roster.rows[0] == {"name": "a", "column_2": "b", "name_2": "c", "column_4": "d"}


def test_short_rows_are_padded(make_csv):
    path = make_csv([["First", "Last", "Grade"], ["Ada", "Lovelace"]])
    assert load_roster(path).rows[0] == {"first": "Ada", "last": "Lovelace", "grade": ""}


def test_load_csv_utf8_with_bom(make_csv):
    path = make_csv([["First Name", "Last Name"], ["José", "Núñez"], ["李", "小龍"]])
    roster = load_roster(path)
    assert roster.keys == ["first_name", "last_name"]
    assert roster.rows[1] == {"first_name": "李", "last_name": "小龍"}


def test_load_csv_cp1252_fallback(make_csv):
    path = make_csv([["First", "Last"], ["Zoë", "Brontë"]], encoding="cp1252")
    assert load_roster(path).rows[0] == {"first": "Zoë", "last": "Brontë"}


def test_unsupported_extension(tmp_path):
    path = tmp_path / "old.xls"
    path.write_bytes(b"whatever")
    with pytest.raises(RosterError, match="Save As"):
        load_roster(path)


def test_empty_spreadsheet(make_xlsx):
    with pytest.raises(RosterError, match="empty"):
        load_roster(make_xlsx([]))


def test_headers_but_no_students(make_xlsx):
    with pytest.raises(RosterError, match="no students"):
        load_roster(make_xlsx([["First", "Last"]]))


def test_display_name(make_xlsx):
    roster = load_roster(make_xlsx([["Last Name", "First Name"], ["Lovelace", "Ada"]]))
    assert roster.display_name(roster.rows[0]) == "Ada Lovelace"

    roster = load_roster(make_xlsx([["Student", "Grade"], ["Ada L.", "5"]]))
    assert roster.display_name(roster.rows[0]) == "Ada L."


def test_trailing_blank_columns(make_xlsx):
    path = make_xlsx([["First", None, None, None], ["Ada", None, "note", None]])
    roster = load_roster(path)
    assert [c.label for c in roster.columns] == ["First", "Column 2", "Column 3"]
    assert roster.rows[0] == {"first": "Ada", "column_2": "", "column_3": "note"}
