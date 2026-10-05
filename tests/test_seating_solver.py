import random
import time

import pytest

from rollcall.seating.model import Layout, SeatingClass, Student
from rollcall.seating.solver import SeatingError, arrange, find_problems


def adjacent_pairs(cls, chart):
    """Every pair of student ids seated next to each other (independent of the solver)."""
    pairs = set()
    for seat, nbrs in cls.layout.neighbors().items():
        for other in nbrs:
            if seat in chart and other in chart:
                pairs.add(frozenset((chart[seat], chart[other])))
    return pairs


def row_of(cls, chart, student_id):
    rows = {s.id: s.row for s in cls.layout.seats()}
    return next(rows[seat] for seat, sid in chart.items() if sid == student_id)


def assert_all_rules_met(cls, chart):
    pairs = adjacent_pairs(cls, chart)
    by_id = {s.id: s for s in cls.students}
    assert sorted(chart.values()) == sorted(by_id), "every student seated exactly once"
    for a, b in cls.keep_apart:
        assert frozenset((a, b)) not in pairs
    for s in cls.students:
        if s.needs_front:
            assert row_of(cls, chart, s.id) in cls.layout.front_rows()
    for pair in pairs:
        x, y = (by_id[i] for i in pair)
        assert not (x.behavior == "loud" and y.behavior == "loud")
        for a, b in ((x, y), (y, x)):
            if a.special_needs:
                assert b.tolerant and not b.special_needs


def busy_class(layout=None):
    names = ["Ada", "Alan", "Grace", "Mei", "José", "Priya", "Liam", "Zoë", "Kwame", "Sofia", "Noah", "Hana"]
    students = [Student(n, "X") for n in names]
    s = {st.first: st for st in students}
    s["Ada"].behavior = s["Alan"].behavior = s["Liam"].behavior = "loud"
    s["Grace"].behavior = s["Mei"].behavior = s["Hana"].behavior = "quiet"
    s["José"].needs_front = s["Priya"].needs_front = True
    s["Kwame"].special_needs = True
    for name in ("Sofia", "Noah", "Hana", "Grace"):
        s[name].tolerant = True
    cls = SeatingClass(name="P1", students=students, layout=layout or Layout("rows", rows=3, cols=4))
    cls.keep_apart = [(s["Ada"].id, s["Grace"].id), (s["Mei"].id, s["Zoë"].id), (s["Noah"].id, s["Sofia"].id)]
    return cls, s


@pytest.mark.parametrize(
    "layout",
    [Layout("rows", rows=3, cols=4), Layout("pairs", rows=3, cols=2), Layout("tables", rows=2, cols=2, table_size=4)],
    ids=["rows", "pairs", "tables"],
)
def test_solvable_class_meets_every_rule(layout):
    cls, _ = busy_class(layout)
    result = arrange(cls, seed=1)
    assert result.problems == []
    assert_all_rules_met(cls, result.chart)


def test_same_seed_same_chart_and_shuffle_differs():
    cls, _ = busy_class()
    assert arrange(cls, seed=7).chart == arrange(cls, seed=7).chart
    charts = {tuple(sorted(arrange(cls, seed=n).chart.items())) for n in range(5)}
    assert len(charts) > 1


def test_pinned_seats_never_move():
    cls, s = busy_class()
    seat = "r2c3"
    cls.chart = {seat: s["Ada"].id}
    cls.pinned = {seat}
    for n in range(5):
        assert arrange(cls, seed=n).chart[seat] == s["Ada"].id


def test_empty_seats_become_buffers():
    special = Student("Kwame", "M", special_needs=True)
    other = Student("Liam", "O")  # not tolerant
    cls = SeatingClass(name="P1", students=[special, other], layout=Layout("rows", rows=1, cols=3))
    result = arrange(cls, seed=3)
    assert result.problems == []
    assert frozenset((special.id, other.id)) not in adjacent_pairs(cls, result.chart)


def test_special_needs_prefer_the_back():
    special = Student("Kwame", "M", special_needs=True)
    others = [Student(f"T{i}", "", tolerant=True) for i in range(5)]
    cls = SeatingClass(name="P1", students=[special, *others], layout=Layout("rows", rows=3, cols=2))
    result = arrange(cls, seed=2)
    assert row_of(cls, result.chart, special.id) in cls.layout.back_rows()


def test_vision_outranks_back_preference():
    both = Student("Kwame", "M", special_needs=True, needs_front=True)
    others = [Student(f"T{i}", "", tolerant=True) for i in range(5)]
    cls = SeatingClass(name="P1", students=[both, *others], layout=Layout("rows", rows=3, cols=2))
    result = arrange(cls, seed=2)
    assert row_of(cls, result.chart, both.id) in cls.layout.front_rows()
    assert result.problems == []


def test_too_few_front_seats_is_explained():
    students = [Student(f"V{i}", "", needs_front=True) for i in range(3)] + [Student("N", "")]
    cls = SeatingClass(name="P1", students=students, layout=Layout("rows", rows=3, cols=2))  # 2 front seats
    problems = arrange(cls, seed=1).problems
    assert any("3 students" in p and "2 front seats" in p for p in problems)


def test_impossible_loud_rule_is_reported():
    students = [Student(f"L{i}", "", behavior="loud") for i in range(4)]
    cls = SeatingClass(name="P1", students=students, layout=Layout("rows", rows=2, cols=2))
    problems = arrange(cls, seed=1).problems
    assert problems and all("loud" in p for p in problems)


def test_manual_swap_problems_are_found():
    a, b = Student("Ada", "L"), Student("Alan", "T")
    cls = SeatingClass(name="P1", students=[a, b], layout=Layout("rows", rows=1, cols=3))
    cls.keep_apart = [(a.id, b.id)]
    problems = find_problems(cls, {"r0c0": a.id, "r0c1": b.id})
    assert problems == ["Ada L and Alan T are seated next to each other."]
    assert find_problems(cls, {"r0c0": a.id, "r0c2": b.id}) == []


def test_unseated_students_are_mentioned():
    cls = SeatingClass(name="P1", students=[Student("Ada", "L"), Student("Alan", "T")], layout=Layout("rows", rows=1, cols=3))
    problems = find_problems(cls, {"r0c0": cls.students[0].id})
    assert problems == ["1 student doesn't have a seat yet: Alan T."]


def test_more_students_than_seats():
    cls = SeatingClass(name="P1", students=[Student(str(i)) for i in range(5)], layout=Layout("rows", rows=2, cols=2))
    with pytest.raises(SeatingError, match="5 students but only 4 seats"):
        arrange(cls)


def test_forty_students_is_fast():
    rng = random.Random(0)
    students = [
        Student(
            f"S{i}", "",
            behavior=rng.choice(["loud", "normal", "normal", "quiet"]),
            needs_front=rng.random() < 0.1,
            special_needs=rng.random() < 0.05,
            tolerant=rng.random() < 0.4,
        )
        for i in range(40)
    ]
    cls = SeatingClass(name="Big", students=students, layout=Layout("rows", rows=5, cols=8))
    cls.keep_apart = [(students[i].id, students[i + 1].id) for i in range(0, 20, 2)]
    start = time.monotonic()
    arrange(cls, seed=0)
    assert time.monotonic() - start < 2


@pytest.mark.parametrize(
    "layout",
    [Layout("rows", rows=5, cols=8), Layout("pairs", rows=5, cols=4), Layout("tables", rows=2, cols=4, table_size=5)],
    ids=["rows", "pairs", "tables"],
)
def test_incremental_scoring_matches_a_full_recount(layout):
    # A class that can't reach zero runs the whole schedule, so any drift between
    # the per-swap score and the true score would show up here.
    from rollcall.seating.solver import _Problem

    rng = random.Random(3)
    students = [
        Student(
            f"S{i}", "",
            behavior=rng.choices(["loud", "normal", "quiet"], [0.6, 0.3, 0.1])[0],
            needs_front=rng.random() < 0.25,
            special_needs=rng.random() < 0.15,
            tolerant=rng.random() < 0.2,
        )
        for i in range(38)
    ]
    cls = SeatingClass(name="Hard", students=students, layout=layout)
    cls.keep_apart = [(students[i].id, students[i + 1].id) for i in range(0, 30, 2)]
    problem = _Problem(cls)
    placement, cost = problem.anneal(random.Random(1))
    assert cost == problem.total(placement) > 0
