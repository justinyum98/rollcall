"""Read a spreadsheet of students into a list of rows keyed by placeholder name."""

import csv
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import openpyxl

# Names Jinja treats specially, so {{ none }} would not show the column's value.
# (Measured: everything else, e.g. "class" or "in", works fine as a placeholder.)
_RESERVED = {"not", "true", "false", "none", "self"}


class RosterError(Exception):
    """A problem with the spreadsheet, worded for a teacher to read."""


@dataclass(frozen=True)
class Column:
    label: str  # header as the teacher typed it, e.g. "First Name"
    key: str  # placeholder name, e.g. "first_name"


@dataclass
class Roster:
    columns: list[Column]
    rows: list[dict[str, str]] = field(default_factory=list)

    @property
    def keys(self) -> list[str]:
        return [c.key for c in self.columns]

    def display_name(self, row: dict[str, str]) -> str:
        """A human-friendly name for a row, used in progress and error messages."""
        if "first_name" in row and "last_name" in row:
            return f"{row['first_name']} {row['last_name']}".strip()
        return next((v for v in row.values() if v), "(blank row)")


def make_key(header: str) -> str:
    """Turn a column header into a placeholder name: "First Name" -> "first_name"."""
    key = re.sub(r"\W+", "_", header.strip().lower()).strip("_")
    if key and key[0].isdigit():
        key = f"col_{key}"
    if key in _RESERVED:
        key = f"{key}_"
    return key


def load_roster(path: str | Path) -> Roster:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".xlsx":
        raw_rows = _read_xlsx(path)
    elif suffix == ".csv":
        raw_rows = _read_csv(path)
    else:
        raise RosterError(
            f'RollCall can\'t read "{path.name}". In Excel or Google Sheets, '
            "use File > Save As (or Download) and choose .xlsx or .csv."
        )

    rows = [[_to_text(v) for v in r] for r in raw_rows]
    rows = [r for r in rows if any(r)]
    if not rows:
        raise RosterError(f'"{path.name}" looks empty. Put column names in the first row.')

    columns = _make_columns(rows[0])
    students = [
        {col.key: (r[i] if i < len(r) else "") for i, col in enumerate(columns)}
        for r in rows[1:]
    ]
    if not students:
        raise RosterError(
            f'"{path.name}" has column names but no students. Add one student per row.'
        )
    return Roster(columns=columns, rows=students)


def _make_columns(headers: list[str]) -> list[Column]:
    # Trim trailing empty headers (Excel often reports extra blank columns).
    while headers and not headers[-1]:
        headers = headers[:-1]
    columns, seen = [], set()
    for i, label in enumerate(headers, start=1):
        base = make_key(label) or f"column_{i}"
        key, n = base, 2
        while key in seen:
            key, n = f"{base}_{n}", n + 1
        seen.add(key)
        columns.append(Column(label=label or f"Column {i}", key=key))
    return columns


def _read_xlsx(path: Path) -> list[tuple]:
    try:
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    except Exception as e:
        raise RosterError(f'Couldn\'t open "{path.name}". Is it a real Excel file? ({e})')
    try:
        return list(wb.active.iter_rows(values_only=True))
    finally:
        wb.close()


def _read_csv(path: Path) -> list[list[str]]:
    data = path.read_bytes()
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        text = data.decode("latin-1")
    return list(csv.reader(text.splitlines()))


def _to_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        value = value.date()
    if isinstance(value, date):
        # Built by hand: strftime's "%-d" (no leading zero) doesn't work on Windows.
        return f"{value:%B} {value.day}, {value.year}"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()
