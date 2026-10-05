"""Find a seating chart that follows the teacher's rules.

Each rule has a penalty. "Never" rules carry large penalties and are listed
as problems if they can't be met; "when possible" rules carry small ones.
Simulated annealing swaps seats (including empty ones, which make natural
buffers) to find the arrangement with the lowest total penalty.
"""

import math
import random
from dataclasses import dataclass

from .model import SeatingClass

APART = 1000  # a keep-apart pair seated next to each other
FRONT = 500  # a student who can't see the board isn't in the front rows
SPECIAL = 300  # a special-needs student next to someone not marked tolerant
LOUD = 200  # two loud students next to each other
BACK = 20  # (preference) special-needs students toward the back
QUIET = 5  # (preference) a loud student has no quiet neighbor

_ITERATIONS_PER_SEAT = 600
_RESTARTS = 3


class SeatingError(Exception):
    """The chart can't be made at all, worded for a teacher."""


@dataclass
class Arrangement:
    chart: dict[str, str]  # seat id -> student id
    problems: list[str]  # rules that couldn't be met, in plain language


def arrange(cls: SeatingClass, seed: int | None = None) -> Arrangement:
    seats = cls.layout.seats()
    if len(cls.students) > len(seats):
        raise SeatingError(
            f"{len(cls.students)} students but only {len(seats)} seats. Add rows, columns, or tables."
        )
    problem = _Problem(cls)
    rng = random.Random(seed)
    best = None
    for _ in range(_RESTARTS):
        placement, cost = problem.anneal(rng)
        if best is None or cost < best[1]:
            best = (placement, cost)
        if cost == 0:
            break
    chart = problem.to_chart(best[0])
    return Arrangement(chart=chart, problems=find_problems(cls, chart))


def find_problems(cls: SeatingClass, chart: dict[str, str]) -> list[str]:
    """Every "never" rule the chart breaks, most serious first. Also used after manual swaps."""
    by_id = {s.id: s for s in cls.students}
    chart = {seat: sid for seat, sid in chart.items() if sid in by_id}
    rows = {s.id: s.row for s in cls.layout.seats()}
    seat_of = {sid: seat for seat, sid in chart.items()}
    neighbors = cls.layout.neighbors()
    adjacent = set()
    for seat, sid in chart.items():
        for other in neighbors.get(seat, ()):
            if other in chart:
                adjacent.add(frozenset((sid, chart[other])))

    apart, front, special, loud = [], [], [], []
    for a, b in cls.keep_apart:
        if frozenset((a, b)) in adjacent and a in by_id and b in by_id:
            apart.append(f"{by_id[a].name} and {by_id[b].name} are seated next to each other.")

    needs_front = [s for s in cls.students if s.needs_front]
    front_seats = sum(1 for r in rows.values() if r in cls.layout.front_rows())
    if len(needs_front) > front_seats:
        front.append(
            f"Not enough front seats for everyone who needs to see the board "
            f"({len(needs_front)} students, {front_seats} front seats)."
        )
    for s in needs_front:
        if s.id in seat_of and rows[seat_of[s.id]] not in cls.layout.front_rows():
            front.append(f"{s.name} needs to see the board but isn't in the front rows.")

    for pair in sorted(adjacent, key=lambda p: sorted(by_id[i].name for i in p)):
        x, y = sorted((by_id[i] for i in pair), key=lambda s: s.name)
        if x.special_needs and y.special_needs:
            special.append(f"{x.name} and {y.name} both have special needs and are seated next to each other.")
        elif x.special_needs or y.special_needs:
            needy, other = (x, y) if x.special_needs else (y, x)
            if not other.tolerant:
                special.append(f"{needy.name} (special needs) is next to {other.name}, who isn't marked tolerant.")
        if x.behavior == "loud" and y.behavior == "loud":
            loud.append(f"{x.name} and {y.name} are both loud and are seated next to each other.")

    unseated = [s.name for s in cls.students if s.id not in seat_of]
    missing = []
    if unseated:
        count = f"{len(unseated)} student{'s' if len(unseated) != 1 else ''}"
        verb = "doesn't" if len(unseated) == 1 else "don't"
        missing.append(f"{count} {verb} have a seat yet: {', '.join(unseated)}.")
    return missing + apart + front + special + loud


class _Problem:
    """The class compiled into plain lists and indexes, so scoring a swap is fast."""

    def __init__(self, cls: SeatingClass):
        layout = cls.layout
        self.seats = layout.seats()
        seat_index = {s.id: i for i, s in enumerate(self.seats)}
        nbr_ids = layout.neighbors()
        self.nbrs = [[seat_index[n] for n in nbr_ids[s.id]] for s in self.seats]
        front, back = layout.front_rows(), layout.back_rows()
        self.in_front = [s.row in front for s in self.seats]
        self.in_back = [s.row in back for s in self.seats]

        self.students = cls.students
        index = {s.id: i for i, s in enumerate(cls.students)}
        self.loud = [s.behavior == "loud" for s in cls.students]
        self.quiet = [s.behavior == "quiet" for s in cls.students]
        self.any_quiet = any(self.quiet)
        self.front = [s.needs_front for s in cls.students]
        self.special = [s.special_needs for s in cls.students]
        self.tolerant = [s.tolerant for s in cls.students]
        self.apart = {frozenset((index[a], index[b])) for a, b in cls.keep_apart if a in index and b in index}

        # Pinned seats keep their student; everyone else is free to move.
        self.fixed: dict[int, int] = {
            seat_index[seat]: index[sid]
            for seat, sid in cls.chart.items()
            if seat in cls.pinned and seat in seat_index and sid in index
        }
        self.movable = [i for i in range(len(self.seats)) if i not in self.fixed]

    def to_chart(self, placement: list[int]) -> dict[str, str]:
        return {self.seats[i].id: self.students[p].id for i, p in enumerate(placement) if p >= 0}

    def _random_start(self, rng: random.Random) -> list[int]:
        placement = [-1] * len(self.seats)
        for seat, student in self.fixed.items():
            placement[seat] = student
        free_students = [i for i in range(len(self.students)) if i not in set(self.fixed.values())]
        spots = rng.sample(self.movable, len(free_students))
        for seat, student in zip(spots, free_students):
            placement[seat] = student
        return placement

    # --- scoring --------------------------------------------------------------

    def _node(self, placement, seat) -> int:
        """Penalties that depend on one student's seat (and, for QUIET, its neighbors)."""
        s = placement[seat]
        if s < 0:
            return 0
        cost = 0
        if self.front[s] and not self.in_front[seat]:
            cost += FRONT
        if self.special[s] and not self.front[s] and not self.in_back[seat]:
            cost += BACK
        if self.loud[s] and self.any_quiet:
            if not any(placement[n] >= 0 and self.quiet[placement[n]] for n in self.nbrs[seat]):
                cost += QUIET
        return cost

    def _edge(self, x: int, y: int) -> int:
        """Penalties for students x and y sitting next to each other."""
        if x < 0 or y < 0:
            return 0
        cost = APART if frozenset((x, y)) in self.apart else 0
        if self.special[x] and self.special[y]:
            cost += SPECIAL
        elif (self.special[x] and not self.tolerant[y]) or (self.special[y] and not self.tolerant[x]):
            cost += SPECIAL
        if self.loud[x] and self.loud[y]:
            cost += LOUD
        return cost

    def total(self, placement) -> int:
        cost = sum(self._node(placement, i) for i in range(len(placement)))
        for i, nbrs in enumerate(self.nbrs):
            cost += sum(self._edge(placement[i], placement[j]) for j in nbrs if j > i)
        return cost

    def _local(self, placement, a, b) -> int:
        """The part of the total a swap of seats a and b can change."""
        touched = {a, b, *self.nbrs[a], *self.nbrs[b]}
        cost = sum(self._node(placement, i) for i in touched)
        edges = {frozenset((i, j)) for i in (a, b) for j in self.nbrs[i]}
        return cost + sum(self._edge(placement[i], placement[j]) for i, j in map(tuple, edges))

    def anneal(self, rng: random.Random) -> tuple[list[int], int]:
        placement = self._random_start(rng)
        cost = self.total(placement)
        best, best_cost = placement[:], cost
        if len(self.movable) < 2:
            return best, best_cost

        steps = _ITERATIONS_PER_SEAT * len(self.seats)
        hot, cold = 300.0, 0.5
        for step in range(steps):
            temp = hot * (cold / hot) ** (step / steps)
            a, b = rng.sample(self.movable, 2)
            if placement[a] < 0 and placement[b] < 0:
                continue
            before = self._local(placement, a, b)
            placement[a], placement[b] = placement[b], placement[a]
            delta = self._local(placement, a, b) - before
            if delta <= 0 or rng.random() < math.exp(-delta / temp):
                cost += delta
                if cost < best_cost:
                    best, best_cost = placement[:], cost
                    if cost == 0:
                        break
            else:
                placement[a], placement[b] = placement[b], placement[a]
        return best, best_cost
