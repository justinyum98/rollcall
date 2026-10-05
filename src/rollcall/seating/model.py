"""Students, room layouts, and saved classes for the seating chart."""

import json
import math
import uuid
from dataclasses import dataclass, field
from pathlib import Path

BEHAVIORS = ("loud", "normal", "quiet")
LAYOUT_KINDS = ("rows", "pairs", "tables")
FORMAT_VERSION = 1


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass
class Student:
    first: str
    last: str = ""
    behavior: str = "normal"  # one of BEHAVIORS
    needs_front: bool = False  # can't see the board from far away
    special_needs: bool = False  # serious behavior needs; neighbors should be tolerant
    tolerant: bool = False  # fine sitting next to special-needs students
    id: str = field(default_factory=_new_id)

    @property
    def name(self) -> str:
        return f"{self.first} {self.last}".strip()


@dataclass(frozen=True)
class Seat:
    id: str
    row: int  # 0 is the front of the room
    col: int  # left-to-right position for drawing (seat column, or table column)
    group: str  # desk pair or table this seat belongs to; a single desk is its own group


@dataclass(frozen=True)
class Layout:
    """How the desks are arranged.

    rows:   `rows` x `cols` single desks.
    pairs:  `rows` rows of `cols` pairs of desks, with an aisle between pairs.
    tables: `rows` x `cols` tables, each seating `table_size` students.
    """

    kind: str = "rows"
    rows: int = 5
    cols: int = 6
    table_size: int = 4

    def __post_init__(self):
        if self.kind not in LAYOUT_KINDS:
            raise ValueError(f"Unknown layout {self.kind!r}")
        if self.rows < 1 or self.cols < 1:
            raise ValueError("A room needs at least one row and one column")
        if self.kind == "tables" and self.table_size < 2:
            raise ValueError("Tables need at least two seats")

    def seats(self) -> list[Seat]:
        if self.kind == "rows":
            return [Seat(f"r{r}c{c}", r, c, f"r{r}c{c}") for r in range(self.rows) for c in range(self.cols)]
        if self.kind == "pairs":
            return [
                Seat(f"r{r}c{c}", r, c, f"r{r}p{c // 2}")
                for r in range(self.rows)
                for c in range(self.cols * 2)
            ]
        return [
            Seat(f"t{r}-{c}s{i}", r, c, f"t{r}-{c}")
            for r in range(self.rows)
            for c in range(self.cols)
            for i in range(self.table_size)
        ]

    def neighbors(self) -> dict[str, set[str]]:
        """Seats that count as "next to" each seat: beside, in front, or behind.

        Everyone at the same table counts as next to each other. The aisle
        between desk pairs breaks side-by-side adjacency.
        """
        seats = self.seats()
        result: dict[str, set[str]] = {s.id: set() for s in seats}
        if self.kind == "tables":
            for a in seats:
                result[a.id] = {b.id for b in seats if b.group == a.group and b.id != a.id}
            return result

        by_pos = {(s.row, s.col): s for s in seats}
        for s in seats:
            for dr, dc in ((0, -1), (0, 1), (-1, 0), (1, 0)):
                other = by_pos.get((s.row + dr, s.col + dc))
                if other is None:
                    continue
                if dr == 0 and self.kind == "pairs" and other.group != s.group:
                    continue  # across the aisle
                result[s.id].add(other.id)
        return result

    def front_rows(self) -> set[int]:
        """The front third of the room (at least one row)."""
        return set(range(max(1, math.ceil(self.rows / 3))))

    def back_rows(self) -> set[int]:
        """The back third of the room (at least one row)."""
        return set(range(self.rows - max(1, math.ceil(self.rows / 3)), self.rows))

    def to_json(self) -> dict:
        return {"kind": self.kind, "rows": self.rows, "cols": self.cols, "table_size": self.table_size}


@dataclass
class SeatingClass:
    name: str
    students: list[Student] = field(default_factory=list)
    keep_apart: list[tuple[str, str]] = field(default_factory=list)  # pairs of student ids
    layout: Layout = field(default_factory=Layout)
    chart: dict[str, str] = field(default_factory=dict)  # seat id -> student id
    pinned: set[str] = field(default_factory=set)  # seat ids the shuffle won't change
    id: str = field(default_factory=_new_id)

    def student(self, student_id: str) -> Student:
        return next(s for s in self.students if s.id == student_id)

    def remove_student(self, student_id: str) -> None:
        self.students = [s for s in self.students if s.id != student_id]
        self.keep_apart = [p for p in self.keep_apart if student_id not in p]
        for seat in [seat for seat, sid in self.chart.items() if sid == student_id]:
            del self.chart[seat]
            self.pinned.discard(seat)

    def set_layout(self, layout: Layout) -> None:
        self.layout = layout
        existing = {s.id for s in layout.seats()}
        self.chart = {seat: sid for seat, sid in self.chart.items() if seat in existing}
        self.pinned &= existing

    # --- saving -------------------------------------------------------------

    def to_json(self) -> dict:
        return {
            "format": FORMAT_VERSION,
            "id": self.id,
            "name": self.name,
            "students": [vars(s).copy() for s in self.students],
            "keep_apart": [list(p) for p in self.keep_apart],
            "layout": self.layout.to_json(),
            "chart": dict(self.chart),
            "pinned": sorted(self.pinned),
        }

    @classmethod
    def from_json(cls, data: dict) -> "SeatingClass":
        return cls(
            id=data["id"],
            name=data["name"],
            students=[Student(**s) for s in data.get("students", [])],
            keep_apart=[tuple(p) for p in data.get("keep_apart", [])],
            layout=Layout(**data.get("layout", {})),
            chart=dict(data.get("chart", {})),
            pinned=set(data.get("pinned", [])),
        )

    def save(self, folder: Path) -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{self.id}.json"
        # Write then rename, so a crash mid-save can't leave a half-written class.
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.to_json(), indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
        return path

    def delete(self, folder: Path) -> None:
        (folder / f"{self.id}.json").unlink(missing_ok=True)


def list_classes(folder: Path) -> list[SeatingClass]:
    """Every saved class in `folder`, sorted by name. Damaged files are skipped."""
    classes = []
    for path in sorted(Path(folder).glob("*.json")):
        try:
            classes.append(SeatingClass.from_json(json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return sorted(classes, key=lambda c: c.name.lower())
