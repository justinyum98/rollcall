import pytest

from rollcall.seating.model import Layout, SeatingClass, Student, list_classes


def neighbor_positions(layout, seat_id):
    seats = {s.id: s for s in layout.seats()}
    return sorted((seats[n].row, seats[n].col) for n in layout.neighbors()[seat_id])


def seat_at(layout, row, col):
    return next(s.id for s in layout.seats() if (s.row, s.col) == (row, col))


# --- layouts ------------------------------------------------------------------


def test_rows_layout():
    layout = Layout("rows", rows=3, cols=4)
    assert len(layout.seats()) == 12
    middle = seat_at(layout, 1, 1)
    assert neighbor_positions(layout, middle) == [(0, 1), (1, 0), (1, 2), (2, 1)]
    corner = seat_at(layout, 0, 0)
    assert neighbor_positions(layout, corner) == [(0, 1), (1, 0)]


def test_pairs_layout_aisles_break_adjacency():
    layout = Layout("pairs", rows=2, cols=2)  # 2 rows of 2 pairs = 8 seats
    assert len(layout.seats()) == 8
    # Seat columns 0-1 are pair 0, 2-3 are pair 1; columns 1 and 2 face each other across the aisle.
    right_of_first_pair = seat_at(layout, 0, 1)
    assert neighbor_positions(layout, right_of_first_pair) == [(0, 0), (1, 1)]
    seats = {s.id: s for s in layout.seats()}
    assert seats[seat_at(layout, 0, 0)].group == seats[seat_at(layout, 0, 1)].group
    assert seats[seat_at(layout, 0, 1)].group != seats[seat_at(layout, 0, 2)].group


def test_tables_layout_everyone_at_a_table_is_adjacent():
    layout = Layout("tables", rows=2, cols=3, table_size=4)
    seats = layout.seats()
    assert len(seats) == 24
    first = seats[0]
    table_mates = [s.id for s in seats if s.group == first.group and s.id != first.id]
    assert sorted(layout.neighbors()[first.id]) == sorted(table_mates)
    assert len(table_mates) == 3


@pytest.mark.parametrize(
    "rows, front, back",
    [(1, {0}, {0}), (2, {0}, {1}), (3, {0}, {2}), (5, {0, 1}, {3, 4}), (6, {0, 1}, {4, 5})],
)
def test_front_and_back_rows(rows, front, back):
    layout = Layout("rows", rows=rows, cols=2)
    assert layout.front_rows() == front
    assert layout.back_rows() == back


def test_invalid_layouts():
    with pytest.raises(ValueError):
        Layout("circle", rows=2, cols=2)
    with pytest.raises(ValueError):
        Layout("rows", rows=0, cols=2)
    with pytest.raises(ValueError):
        Layout("tables", rows=1, cols=1, table_size=1)


# --- class data -------------------------------------------------------------------


def make_class():
    ada = Student(first="Ada", last="Lovelace", behavior="loud", needs_front=True)
    alan = Student(first="Alan", last="Turing", special_needs=True)
    grace = Student(first="Grace", last="Hopper", tolerant=True, behavior="quiet")
    cls = SeatingClass(name="Period 3", students=[ada, alan, grace], layout=Layout("rows", rows=2, cols=2))
    cls.keep_apart.append((ada.id, alan.id))
    seats = [s.id for s in cls.layout.seats()]
    cls.chart = {seats[0]: ada.id, seats[1]: grace.id, seats[3]: alan.id}
    cls.pinned = {seats[0]}
    return cls


def test_student_names():
    assert Student(first="Ada", last="Lovelace").name == "Ada Lovelace"
    assert Student(first="Cher", last="").name == "Cher"


def test_json_round_trip():
    cls = make_class()
    again = SeatingClass.from_json(cls.to_json())
    assert again == cls


def test_remove_student_cleans_up_everything():
    cls = make_class()
    ada = cls.students[0]
    cls.remove_student(ada.id)
    assert ada.id not in [s.id for s in cls.students]
    assert ada.id not in cls.chart.values()
    assert cls.keep_apart == []
    assert cls.pinned == set()  # Ada's seat was the pinned one


def test_changing_layout_drops_seats_that_no_longer_exist():
    cls = make_class()
    cls.set_layout(Layout("rows", rows=1, cols=2))
    remaining = {s.id for s in cls.layout.seats()}
    assert set(cls.chart) <= remaining
    assert cls.pinned <= remaining


def test_save_load_and_list(tmp_path):
    cls = make_class()
    cls.save(tmp_path)
    other = SeatingClass(name="Homeroom")
    other.save(tmp_path)
    classes = list_classes(tmp_path)
    assert [c.name for c in classes] == ["Homeroom", "Period 3"]
    assert next(c for c in classes if c.name == "Period 3") == cls


def test_damaged_class_files_are_skipped(tmp_path):
    (tmp_path / "broken.json").write_text("{not json")
    make_class().save(tmp_path)
    assert [c.name for c in list_classes(tmp_path)] == ["Period 3"]
