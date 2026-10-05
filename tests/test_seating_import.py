from rollcall.roster import load_roster
from rollcall.seating.importing import import_roster
from rollcall.seating.model import SeatingClass, Student


def by_name(cls):
    return {s.name: s for s in cls.students}


def pair_names(cls):
    return sorted(tuple(sorted((cls.student(a).name, cls.student(b).name))) for a, b in cls.keep_apart)


def test_names_only(make_csv):
    cls = SeatingClass(name="P1")
    summary = import_roster(cls, load_roster(make_csv([["First Name", "Last Name"], ["Ada", "Lovelace"], ["Alan", "Turing"]])))
    assert summary.added == 2 and summary.warnings == []
    ada = by_name(cls)["Ada Lovelace"]
    assert (ada.behavior, ada.needs_front, ada.special_needs, ada.tolerant) == ("normal", False, False, False)


def test_single_name_column(make_csv):
    cls = SeatingClass(name="P1")
    import_roster(cls, load_roster(make_csv([["Student"], ["Ada Lovelace"], ["Turing, Alan"], ["Cher"]])))
    names = {(s.first, s.last) for s in cls.students}
    assert names == {("Ada", "Lovelace"), ("Alan", "Turing"), ("Cher", "")}


def test_classification_columns(make_csv):
    rows = [
        ["First Name", "Last Name", "Behavior", "Vision", "Special Needs", "Tolerance"],
        ["Ada", "Lovelace", "LOUD", "x", "", "yes"],
        ["Alan", "Turing", "Quiet", "can't see", "Yes", "no"],
        ["Grace", "Hopper", "average", "fine", "no", ""],
    ]
    cls = SeatingClass(name="P1")
    summary = import_roster(cls, load_roster(make_csv(rows)))
    assert summary.warnings == []
    s = by_name(cls)
    assert (s["Ada Lovelace"].behavior, s["Ada Lovelace"].needs_front, s["Ada Lovelace"].tolerant) == ("loud", True, True)
    assert (s["Alan Turing"].behavior, s["Alan Turing"].needs_front, s["Alan Turing"].special_needs) == ("quiet", True, True)
    assert (s["Grace Hopper"].behavior, s["Grace Hopper"].needs_front) == ("normal", False)


def test_unrecognized_values_warn_and_keep_the_old_value(make_csv):
    cls = SeatingClass(name="P1", students=[Student("Ada", "Lovelace", behavior="quiet")])
    summary = import_roster(cls, load_roster(make_csv([["First Name", "Last Name", "Behavior"], ["Ada", "Lovelace", "chatty"]])))
    assert by_name(cls)["Ada Lovelace"].behavior == "quiet"
    assert len(summary.warnings) == 1
    assert "chatty" in summary.warnings[0] and "Ada Lovelace" in summary.warnings[0]


def test_not_next_to_column(make_csv):
    rows = [
        ["First Name", "Last Name", "Not Next To"],
        ["Ada", "Lovelace", "Alan Turing; grace"],
        ["Alan", "Turing", "Ada Lovelace"],  # same pair again: not duplicated
        ["Grace", "Hopper", ""],
        ["Sam", "Lee", "Nobody Here"],
        ["Sam", "Ortiz", ""],
        ["Mei", "Chen", "Sam, Mei Chen"],  # ambiguous first name, and herself
    ]
    cls = SeatingClass(name="P1")
    summary = import_roster(cls, load_roster(make_csv(rows)))
    assert pair_names(cls) == [("Ada Lovelace", "Alan Turing"), ("Ada Lovelace", "Grace Hopper")]
    joined = "\n".join(summary.warnings)
    assert '"Nobody Here"' in joined
    assert '"Sam"' in joined and "Sam Lee" in joined and "Sam Ortiz" in joined


def test_reimport_updates_and_keeps_in_app_details(make_csv):
    ada = Student("Ada", "Lovelace", special_needs=True, behavior="loud")
    cls = SeatingClass(name="P1", students=[ada])
    summary = import_roster(
        cls,
        load_roster(make_csv([["First Name", "Last Name", "Vision"], ["ada", "LOVELACE", "yes"], ["Alan", "Turing", "no"]])),
    )
    assert (summary.added, summary.updated) == (1, 1)
    assert len(cls.students) == 2
    again = by_name(cls)["Ada Lovelace"]
    assert again.id == ada.id  # same student, so her seat and rules still apply
    assert again.needs_front is True
    assert again.special_needs is True and again.behavior == "loud"  # no column for these, so kept


def test_rows_without_a_name_are_skipped(make_csv):
    cls = SeatingClass(name="P1")
    summary = import_roster(cls, load_roster(make_csv([["First Name", "Last Name", "Behavior"], ["", "", "loud"], ["Ada", "L", ""]])))
    assert [s.name for s in cls.students] == ["Ada L"]
    assert summary.added == 1


def test_no_name_column(make_csv):
    cls = SeatingClass(name="P1")
    summary = import_roster(cls, load_roster(make_csv([["Grade", "Behavior"], ["5", "loud"]])))
    assert cls.students == []
    assert "name" in summary.warnings[0].lower()
