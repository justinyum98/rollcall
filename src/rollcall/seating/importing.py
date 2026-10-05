"""Add students (and their details) to a class from a spreadsheet."""

import re
from dataclasses import dataclass, field

from ..roster import Roster
from .model import SeatingClass, Student

# Spreadsheet column keys (see roster.make_key) that RollCall understands.
FIRST = ("first_name", "first", "given_name")
LAST = ("last_name", "last", "surname", "family_name")
FULL = ("name", "student", "student_name", "full_name")
BEHAVIOR = ("behavior", "behaviour", "behavior_level", "behaviour_level")
VISION = ("vision", "needs_front", "front", "sits_front", "eyesight")
SPECIAL = ("special_needs", "special_need", "special")
TOLERANT = ("tolerant", "tolerance")
NOT_NEXT_TO = ("not_next_to", "keep_apart", "keep_away_from", "avoid", "not_near")

_BEHAVIOR_WORDS = {
    "loud": "loud", "high": "loud", "talkative": "loud",
    "normal": "normal", "average": "normal", "medium": "normal", "ok": "normal",
    "quiet": "quiet", "low": "quiet", "calm": "quiet",
}
_YES = {"yes", "y", "x", "true", "1", "✓", "✔", "high", "front", "needs front",
        "poor", "can't see", "cannot see", "cant see", "glasses"}
_NO = {"no", "n", "false", "0", "low", "fine", "ok", "good", "can see"}


@dataclass
class ImportSummary:
    added: int = 0
    updated: int = 0
    warnings: list[str] = field(default_factory=list)


def import_roster(cls: SeatingClass, roster: Roster) -> ImportSummary:
    """Add new students to `cls` and update existing ones (matched by name).

    Only columns present in the spreadsheet are applied, so details the
    teacher set in the app survive a re-import.
    """
    keys = set(roster.keys)

    def col(options: tuple[str, ...]) -> str | None:
        """The spreadsheet column matching any of these names, if there is one."""
        return next((k for k in options if k in keys), None)

    first_col, last_col, full_col = col(FIRST), col(LAST), col(FULL)
    summary = ImportSummary()
    if not first_col and not full_col:
        summary.warnings.append(
            "Couldn't find a name column. Name a column \"First Name\" (and \"Last Name\"), or \"Name\"."
        )
        return summary

    existing = {s.name.casefold(): s for s in cls.students}
    avoid_lists: list[tuple[Student, str]] = []
    for row in roster.rows:
        first, last = _name_from(row, first_col, last_col, full_col)
        if not first and not last:
            continue
        student = existing.get(f"{first} {last}".strip().casefold())
        if student is None:
            student = Student(first=first, last=last)
            cls.students.append(student)
            existing[student.name.casefold()] = student
            summary.added += 1
        else:
            summary.updated += 1
        _apply_details(student, row, col, summary.warnings)
        if (avoid_col := col(NOT_NEXT_TO)) and row.get(avoid_col):
            avoid_lists.append((student, row[avoid_col]))

    for student, text in avoid_lists:
        _add_keep_apart(cls, student, text, summary.warnings)
    return summary


def _name_from(row, first_col, last_col, full_col) -> tuple[str, str]:
    if first_col:
        return row.get(first_col, "").strip(), (row.get(last_col, "") if last_col else "").strip()
    full = row.get(full_col, "").strip()
    if "," in full:  # "Lovelace, Ada"
        last, _, first = full.partition(",")
        return first.strip(), last.strip()
    first, _, last = full.partition(" ")
    return first.strip(), last.strip()


def _apply_details(student: Student, row: dict, col, warnings: list[str]) -> None:
    if (key := col(BEHAVIOR)) is not None:
        value = row.get(key, "").strip().casefold()
        if value in _BEHAVIOR_WORDS:
            student.behavior = _BEHAVIOR_WORDS[value]
        elif value:
            warnings.append(
                f'{student.name}: "{row[key]}" isn\'t a behavior level, so it was left as '
                f'"{student.behavior}". Use loud, normal, or quiet.'
            )
    for options, attr, label in (
        (VISION, "needs_front", "vision"),
        (SPECIAL, "special_needs", "special needs"),
        (TOLERANT, "tolerant", "tolerance"),
    ):
        if (key := col(options)) is None:
            continue
        value = row.get(key, "").strip().casefold()
        if not value or value in _NO:
            setattr(student, attr, False)
        elif value in _YES:
            setattr(student, attr, True)
        else:
            warnings.append(f'{student.name}: didn\'t understand "{row[key]}" for {label}. Use yes or no.')


def _add_keep_apart(cls: SeatingClass, student: Student, text: str, warnings: list[str]) -> None:
    for wanted in filter(None, (w.strip() for w in re.split(r"[,;\n]", text))):
        matches = _find_students(cls, wanted)
        if not matches:
            warnings.append(f'{student.name}: "{wanted}" (in "not next to") doesn\'t match any student.')
            continue
        if len(matches) > 1:
            names = ", ".join(m.name for m in matches)
            warnings.append(f'{student.name}: "{wanted}" could mean {names}. Use the full name.')
            continue
        other = matches[0]
        if other.id == student.id:
            continue
        pair = {student.id, other.id}
        if not any(set(p) == pair for p in cls.keep_apart):
            cls.keep_apart.append((student.id, other.id))


def _find_students(cls: SeatingClass, wanted: str) -> list[Student]:
    wanted = wanted.casefold()
    exact = [s for s in cls.students if s.name.casefold() == wanted]
    return exact or [s for s in cls.students if s.first.casefold() == wanted]
