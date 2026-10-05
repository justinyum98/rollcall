"""The Seating chart tab: students and rules on the left, the room on the right."""

import queue
import random
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont

import customtkinter as ctk

from . import pdf
from .roster import RosterError, load_roster
from .seating.export import save_chart_docx
from .seating.importing import import_roster
from .seating.model import BEHAVIORS, Layout, SeatingClass, Student, list_classes
from .seating.solver import SeatingError, arrange, find_problems
from .settings import settings_path
from .widgets import GREEN, MUTED, ORANGE, PAD, RED, TEXT, open_path

# Student table columns: (key, heading, width). Clicking a cell changes it.
COLUMNS = (
    ("name", "Student", 170),
    ("behavior", "Behavior", 80),
    ("needs_front", "Needs front", 85),
    ("special_needs", "Special needs", 95),
    ("tolerant", "Tolerant", 70),
)
CHECK = "✓"
LAYOUT_LABELS = {"Rows": "rows", "Pairs": "pairs", "Tables": "tables"}
# Number fields shown for each layout: (label, Layout attribute).
LAYOUT_FIELDS = {
    "rows": (("Rows", "rows"), ("Desks per row", "cols")),
    "pairs": (("Rows", "rows"), ("Pairs per row", "cols")),
    "tables": (("Rows of tables", "rows"), ("Tables per row", "cols"), ("Seats per table", "table_size")),
}
MAX_SIZE = 20
# macOS reports the right mouse button as Button-2; Windows and Linux as Button-3.
RIGHT_CLICK = ("<Button-2>", "<Control-Button-1>") if sys.platform == "darwin" else ("<Button-3>",)


def classes_dir() -> Path:
    return settings_path().parent / "classes"


class SeatingTab(ctk.CTkFrame):
    def __init__(self, master, settings: dict, converters: list[pdf.Converter], folder: Path | None = None):
        super().__init__(master, fg_color="transparent")
        self.settings = settings
        self.converters = converters
        self.folder = folder or classes_dir()
        self.classes: list[SeatingClass] = list_classes(self.folder)
        self.cls: SeatingClass | None = None
        self.selected_seat: str | None = None
        self.messages: queue.Queue = queue.Queue()

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._build_class_bar().grid(row=0, column=0, columnspan=2, sticky="ew", padx=PAD, pady=(4, 8))
        self._build_left().grid(row=1, column=0, sticky="nsew", padx=(PAD, 8))
        self._build_right().grid(row=1, column=1, sticky="nsew", padx=(8, PAD))

        last = settings.get("seating_class")
        start = next((c for c in self.classes if c.id == last), self.classes[0] if self.classes else None)
        self._select_class(start)

    # --- layout ---------------------------------------------------------------

    def _build_class_bar(self):
        bar = ctk.CTkFrame(self, fg_color="transparent")
        ctk.CTkLabel(bar, text="Class:", font=ctk.CTkFont(size=15, weight="bold")).pack(side="left")
        self.class_menu = ctk.CTkOptionMenu(bar, values=["(none)"], width=200, command=self._on_class_menu)
        self.class_menu.pack(side="left", padx=8)
        for text, command in (("New class", self._new_class), ("Rename", self._rename_class), ("Delete", self._delete_class)):
            ctk.CTkButton(bar, text=text, width=80, fg_color="transparent", border_width=1,
                          text_color=TEXT, command=command).pack(side="left", padx=(0, 6))
        ctk.CTkButton(bar, text="Import from spreadsheet…", command=self._import).pack(side="left", padx=(10, 0))
        return bar

    def _build_left(self):
        left = ctk.CTkFrame(self)
        left.grid_columnconfigure(0, weight=1)
        left.grid_rowconfigure(2, weight=1)
        ctk.CTkLabel(left, text="Students", font=ctk.CTkFont(size=16, weight="bold"), anchor="w").grid(
            row=0, column=0, sticky="w", padx=12, pady=(10, 0))
        ctk.CTkLabel(
            left, text="Click a cell to change it. Double-click a name to rename.",
            text_color=MUTED, anchor="w",
        ).grid(row=1, column=0, sticky="w", padx=12)

        table_frame = tk.Frame(left)
        table_frame.grid(row=2, column=0, sticky="nsew", padx=12, pady=(4, 0))
        table_frame.grid_columnconfigure(0, weight=1)
        table_frame.grid_rowconfigure(0, weight=1)
        self.table = ttk.Treeview(table_frame, columns=[c[0] for c in COLUMNS], show="headings",
                                  selectmode="browse", style="RollCall.Treeview")
        for key, heading, width in COLUMNS:
            self.table.heading(key, text=heading)
            self.table.column(key, width=width, anchor="w" if key == "name" else "center", stretch=key == "name")
        self.table.grid(row=0, column=0, sticky="nsew")
        scroll = ctk.CTkScrollbar(table_frame, command=self.table.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.table.configure(yscrollcommand=scroll.set)
        self.table.bind("<Button-1>", self._on_table_click)
        # Tk sends a quick second (or third) click as a double/triple-click
        # *instead of* a click, so route those to the same handler.
        self.table.bind("<Double-Button-1>", self._on_table_double_click)
        self.table.bind("<Triple-Button-1>", self._on_table_double_click)
        self.table.bind("<Delete>", lambda e: self._remove_selected())
        self.table.bind("<BackSpace>", lambda e: self._remove_selected())

        add = ctk.CTkFrame(left, fg_color="transparent")
        add.grid(row=3, column=0, sticky="ew", padx=12, pady=6)
        self.new_first = ctk.CTkEntry(add, placeholder_text="First name", width=120)
        self.new_last = ctk.CTkEntry(add, placeholder_text="Last name", width=120)
        self.new_first.pack(side="left")
        self.new_last.pack(side="left", padx=6)
        self.new_last.bind("<Return>", lambda e: self._add_student())
        ctk.CTkButton(add, text="Add student", width=100, command=self._add_student).pack(side="left")
        ctk.CTkButton(add, text="Remove", width=70, fg_color="transparent", border_width=1, text_color=TEXT,
                      command=self._remove_selected).pack(side="left", padx=(6, 0))

        ctk.CTkLabel(left, text="Keep apart", font=ctk.CTkFont(size=16, weight="bold"), anchor="w").grid(
            row=4, column=0, sticky="w", padx=12, pady=(8, 0))
        pick = ctk.CTkFrame(left, fg_color="transparent")
        pick.grid(row=5, column=0, sticky="ew", padx=12)
        self.apart_a = ctk.CTkOptionMenu(pick, values=["—"], width=150)
        self.apart_b = ctk.CTkOptionMenu(pick, values=["—"], width=150)
        self.apart_a.pack(side="left")
        ctk.CTkLabel(pick, text="and").pack(side="left", padx=6)
        self.apart_b.pack(side="left")
        ctk.CTkButton(pick, text="Add", width=50, command=self._add_keep_apart).pack(side="left", padx=(6, 0))
        self.apart_list = tk.Listbox(left, height=5, activestyle="none", borderwidth=0, highlightthickness=0)
        self.apart_list.grid(row=6, column=0, sticky="ew", padx=12, pady=(6, 0))
        ctk.CTkButton(left, text="Remove selected rule", width=150, fg_color="transparent", border_width=1,
                      text_color=TEXT, command=self._remove_keep_apart).grid(row=7, column=0, sticky="w", padx=12, pady=(4, 12))
        return left

    def _build_right(self):
        right = ctk.CTkFrame(self)
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(2, weight=1)

        room = ctk.CTkFrame(right, fg_color="transparent")
        room.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 0))
        ctk.CTkLabel(room, text="Room", font=ctk.CTkFont(size=16, weight="bold")).pack(side="left")
        self.layout_kind = ctk.CTkSegmentedButton(room, values=list(LAYOUT_LABELS), command=self._on_layout_kind)
        self.layout_kind.pack(side="left", padx=10)
        self.size_frame = ctk.CTkFrame(room, fg_color="transparent")
        self.size_frame.pack(side="left")
        self.size_vars: dict[str, ctk.StringVar] = {}
        self.seat_count = ctk.CTkLabel(room, text="", text_color=MUTED)
        self.seat_count.pack(side="left", padx=10)

        actions = ctk.CTkFrame(right, fg_color="transparent")
        actions.grid(row=1, column=0, sticky="ew", padx=12, pady=8)
        self.make_button = ctk.CTkButton(actions, text="Make seating chart", height=36,
                                         font=ctk.CTkFont(size=14, weight="bold"), command=self._make_chart)
        self.make_button.pack(side="left")
        self.pin_button = ctk.CTkButton(actions, text="Pin seat", width=90, fg_color="transparent", border_width=1,
                                        text_color=TEXT, command=self._toggle_pin)
        self.pin_button.pack(side="left", padx=8)
        self.show_details = ctk.BooleanVar(value=bool(self.settings.get("seating_details", True)))
        ctk.CTkCheckBox(actions, text="Show details", variable=self.show_details,
                        command=self._on_details_toggle).pack(side="left", padx=8)
        ctk.CTkButton(actions, text="Save as Word…", width=120, command=self._export).pack(side="right")
        self.want_pdf = ctk.BooleanVar(value=bool(self.converters))
        pdf_box = ctk.CTkCheckBox(actions, text="Also PDF", variable=self.want_pdf)
        pdf_box.pack(side="right", padx=8)
        if not self.converters:
            pdf_box.configure(state="disabled")

        self.canvas = tk.Canvas(right, highlightthickness=0)
        self.canvas.grid(row=2, column=0, sticky="nsew", padx=12)
        self.canvas.bind("<Configure>", lambda e: self._draw_room())
        self.canvas.bind("<Button-1>", self._on_seat_click)
        for event in RIGHT_CLICK:
            self.canvas.bind(event, self._on_seat_right_click)

        self.hint = ctk.CTkLabel(
            right, text="Click two seats to swap them. Right-click a seat (or use Pin seat) to keep it in place when shuffling.",
            text_color=MUTED, anchor="w", justify="left", wraplength=560,
        )
        self.hint.grid(row=3, column=0, sticky="ew", padx=12, pady=(4, 0))
        self.status = ctk.CTkLabel(right, text="", anchor="nw", justify="left", wraplength=560)
        self.status.grid(row=4, column=0, sticky="ew", padx=12, pady=(4, 12))
        return right

    # --- classes --------------------------------------------------------------

    def _select_class(self, cls: SeatingClass | None):
        self.cls = cls
        self.selected_seat = None
        if cls is not None:
            self.settings["seating_class"] = cls.id
        names = [c.name for c in self.classes] or ["(none)"]
        self.class_menu.configure(values=names)
        self.class_menu.set(cls.name if cls else "(none)")
        self.make_button.configure(text="Shuffle" if cls and cls.chart else "Make seating chart")
        self._show_layout()
        self._refresh_students()
        self._refresh_keep_apart()
        self._update_problems()
        self._draw_room()

    def _on_class_menu(self, name: str):
        self._select_class(next((c for c in self.classes if c.name == name), None))

    def _ask_name(self, title: str, prompt: str) -> str | None:
        name = ctk.CTkInputDialog(title=title, text=prompt).get_input()
        name = (name or "").strip()
        if name and any(c.name.casefold() == name.casefold() and c is not self.cls for c in self.classes):
            messagebox.showinfo("Name taken", f'There is already a class called "{name}".')
            return None
        return name or None

    def _new_class(self) -> SeatingClass | None:
        name = self._ask_name("New class", "Name for the new class (for example, Period 3):")
        if not name:
            return None
        cls = SeatingClass(name=name)
        self.classes.append(cls)
        self.classes.sort(key=lambda c: c.name.casefold())
        self._save(cls)
        self._select_class(cls)
        return cls

    def _rename_class(self):
        if self.cls and (name := self._ask_name("Rename class", f'New name for "{self.cls.name}":')):
            self.cls.name = name
            self.classes.sort(key=lambda c: c.name.casefold())
            self._save()
            self._select_class(self.cls)

    def _delete_class(self):
        if self.cls and messagebox.askyesno(
            "Delete class", f'Delete "{self.cls.name}" and its seating chart? This can\'t be undone.'
        ):
            self.cls.delete(self.folder)
            self.classes.remove(self.cls)
            self._select_class(self.classes[0] if self.classes else None)

    def _save(self, cls: SeatingClass | None = None):
        cls = cls or self.cls
        if cls is None:
            return
        try:
            cls.save(self.folder)
        except OSError as e:
            self._set_status(f"Couldn't save the class: {e}", RED)

    def _require_class(self) -> SeatingClass | None:
        return self.cls or self._new_class()

    # --- students -------------------------------------------------------------

    def _import(self):
        path = filedialog.askopenfilename(
            title="Choose your student list",
            filetypes=[("Spreadsheets", "*.xlsx *.csv"), ("All files", "*.*")],
        )
        if path:
            self._import_path(Path(path))

    def _import_path(self, path: Path):
        try:
            roster = load_roster(path)
        except (RosterError, OSError) as e:
            messagebox.showerror("Couldn't import", str(e))
            return
        if self.cls is None:
            self.cls = SeatingClass(name=self._unique_class_name(path.stem))
            self.classes.append(self.cls)
            self.classes.sort(key=lambda c: c.name.casefold())
        summary = import_roster(self.cls, roster)
        self._save()
        self._select_class(self.cls)
        message = f"Added {summary.added} student{'s' if summary.added != 1 else ''}"
        if summary.updated:
            message += f" and updated {summary.updated}"
        message += "."
        if summary.warnings:
            shown = summary.warnings[:12]
            more = f"\n…and {len(summary.warnings) - 12} more." if len(summary.warnings) > 12 else ""
            messagebox.showwarning("Imported, with some notes", message + "\n\n" + "\n".join(shown) + more)
        else:
            self._set_status("✓ " + message, GREEN)

    def _unique_class_name(self, base: str) -> str:
        names = {c.name.casefold() for c in self.classes}
        name, n = base, 2
        while name.casefold() in names:
            name, n = f"{base} ({n})", n + 1
        return name

    def _refresh_students(self):
        self.table.delete(*self.table.get_children())
        for student in self.cls.students if self.cls else []:
            self.table.insert("", "end", iid=student.id, values=self._row_values(student))
        self._apply_table_style()
        names = self._student_choices()
        for menu in (self.apart_a, self.apart_b):
            menu.configure(values=list(names) or ["—"])
            menu.set(next(iter(names), "—"))

    @staticmethod
    def _row_values(s: Student) -> list[str]:
        return [s.name, s.behavior, CHECK if s.needs_front else "", CHECK if s.special_needs else "", CHECK if s.tolerant else ""]

    def _on_table_click(self, event):
        if self.table.identify_region(event.x, event.y) != "cell":
            return
        row, column = self.table.identify_row(event.y), self.table.identify_column(event.x)
        key = COLUMNS[int(column[1:]) - 1][0]
        if not row or key == "name":
            return
        student = self.cls.student(row)
        if key == "behavior":
            student.behavior = BEHAVIORS[(BEHAVIORS.index(student.behavior) + 1) % len(BEHAVIORS)]
        else:
            setattr(student, key, not getattr(student, key))
        self.table.item(row, values=self._row_values(student))
        self._changed()

    def _on_table_double_click(self, event):
        row = self.table.identify_row(event.y)
        if not row:
            return
        if self.table.identify_column(event.x) != "#1":
            # A fast repeat click on a setting: treat it as another click.
            self._on_table_click(event)
            return "break"
        student = self.cls.student(row)
        text = ctk.CTkInputDialog(title="Rename student", text=f'New name for "{student.name}":').get_input()
        if text and text.strip():
            student.first, _, student.last = text.strip().partition(" ")
            self.table.item(row, values=self._row_values(student))
            self._refresh_keep_apart()
            self._changed()
        return "break"

    def _add_student(self):
        first, last = self.new_first.get().strip(), self.new_last.get().strip()
        if not first and not last:
            self._set_status("Type a first name (and last name) to add a student.", ORANGE)
            return
        cls = self._require_class()
        if cls is None:
            return
        cls.students.append(Student(first=first, last=last))
        self.new_first.delete(0, "end")
        self.new_last.delete(0, "end")
        self.new_first.focus_set()
        self._refresh_students()
        self._changed()

    def _remove_selected(self):
        selected = self.table.selection()
        if not selected:
            self._set_status("Click a student in the list first, then Remove.", ORANGE)
            return
        name = self.cls.student(selected[0]).name
        if messagebox.askyesno("Remove student", f"Remove {name} from this class?"):
            self.cls.remove_student(selected[0])
            self._refresh_students()
            self._refresh_keep_apart()
            self._changed()

    # --- keep-apart rules -------------------------------------------------------

    def _student_choices(self) -> dict[str, str]:
        """Menu label -> student id. Repeated names get a number so each label is unique."""
        choices: dict[str, str] = {}
        for s in self.cls.students if self.cls else []:
            label, n = s.name, 2
            while label in choices:
                label, n = f"{s.name} ({n})", n + 1
            choices[label] = s.id
        return choices

    def _add_keep_apart(self):
        choices = self._student_choices()
        a, b = choices.get(self.apart_a.get()), choices.get(self.apart_b.get())
        if not a or not b or a == b:
            self._set_status("Pick two different students to keep apart.", ORANGE)
            return
        if not any({a, b} == set(p) for p in self.cls.keep_apart):
            self.cls.keep_apart.append((a, b))
        self._refresh_keep_apart()
        self._changed()

    def _remove_keep_apart(self):
        selected = self.apart_list.curselection()
        if selected:
            del self.cls.keep_apart[selected[0]]
            self._refresh_keep_apart()
            self._changed()

    def _refresh_keep_apart(self):
        self.apart_list.delete(0, "end")
        for a, b in self.cls.keep_apart if self.cls else []:
            self.apart_list.insert("end", f"  {self.cls.student(a).name}  ↔  {self.cls.student(b).name}")

    # --- room ---------------------------------------------------------------------

    def _show_layout(self):
        layout = self.cls.layout if self.cls else Layout()
        label = next(k for k, v in LAYOUT_LABELS.items() if v == layout.kind)
        self.layout_kind.set(label)
        for child in self.size_frame.winfo_children():
            child.destroy()
        self.size_vars = {}
        for text, attr in LAYOUT_FIELDS[layout.kind]:
            ctk.CTkLabel(self.size_frame, text=text).pack(side="left", padx=(6, 4))
            var = ctk.StringVar(value=str(getattr(layout, attr)))
            ctk.CTkEntry(self.size_frame, textvariable=var, width=40).pack(side="left")
            var.trace_add("write", lambda *_: self._on_size_change())
            self.size_vars[attr] = var
        self._update_seat_count()

    def _on_layout_kind(self, label: str):
        cls = self._require_class()
        if cls is None:
            self._show_layout()
            return
        old = cls.layout
        cls.set_layout(Layout(LAYOUT_LABELS[label], old.rows, old.cols, old.table_size))
        self._show_layout()
        self._changed()

    def _on_size_change(self):
        if self.cls is None:
            return
        values = {}
        for attr, var in self.size_vars.items():
            text = var.get().strip()
            if not text.isdigit() or not 1 <= int(text) <= MAX_SIZE:
                self.seat_count.configure(text=f"Use a number from 1 to {MAX_SIZE}.", text_color=RED)
                return
            values[attr] = int(text)
        try:
            layout = Layout(**{**self.cls.layout.to_json(), **values})
        except ValueError as e:
            self.seat_count.configure(text=str(e), text_color=RED)
            return
        if layout != self.cls.layout:
            self.cls.set_layout(layout)
            self._changed()
        self._update_seat_count()

    def _update_seat_count(self):
        if self.cls is None:
            self.seat_count.configure(text="")
            return
        seats, students = len(self.cls.layout.seats()), len(self.cls.students)
        color = RED if students > seats else MUTED
        self.seat_count.configure(text=f"{seats} seats for {students} students", text_color=color)

    # --- chart --------------------------------------------------------------------

    def _make_chart(self):
        if self.cls is None or not self.cls.students:
            self._set_status("Add students first (type them in, or Import from spreadsheet).", ORANGE)
            return
        try:
            result = arrange(self.cls, seed=random.randrange(1 << 30))
        except SeatingError as e:
            self._set_status(str(e), RED)
            return
        self.cls.chart = result.chart
        self.selected_seat = None
        self._changed()
        self.make_button.configure(text="Shuffle")

    def _seat_at(self, event) -> str | None:
        for item in self.canvas.find_overlapping(event.x, event.y, event.x, event.y):
            for tag in self.canvas.gettags(item):
                if tag.startswith("seat:"):
                    return tag[5:]
        return None

    def _on_seat_click(self, event):
        seat = self._seat_at(event)
        if seat is None or self.cls is None:
            self.selected_seat = None
        elif self.selected_seat is None or self.selected_seat == seat:
            self.selected_seat = None if self.selected_seat == seat else seat
        else:
            self._swap(self.selected_seat, seat)
            self.selected_seat = None
        self._update_pin_button()
        self._draw_room()

    def _swap(self, a: str, b: str):
        chart = self.cls.chart
        sa, sb = chart.pop(a, None), chart.pop(b, None)
        if sb is not None:
            chart[a] = sb
        if sa is not None:
            chart[b] = sa
        # A pin belongs to the student, so it moves with them.
        pinned_a, pinned_b = a in self.cls.pinned, b in self.cls.pinned
        self.cls.pinned -= {a, b}
        if pinned_a and sa is not None:
            self.cls.pinned.add(b)
        if pinned_b and sb is not None:
            self.cls.pinned.add(a)
        self._changed()

    def _on_seat_right_click(self, event):
        seat = self._seat_at(event)
        if seat:
            self.selected_seat = seat
            self._toggle_pin()

    def _toggle_pin(self):
        seat = self.selected_seat
        if self.cls is None or seat is None or seat not in self.cls.chart:
            self._set_status("Click a seat with a student in it first, then Pin seat.", ORANGE)
            return
        self.cls.pinned ^= {seat}
        self.selected_seat = None
        self._update_pin_button()
        self._changed()

    def _update_pin_button(self):
        pinned = self.cls is not None and self.selected_seat in self.cls.pinned
        self.pin_button.configure(text="Unpin seat" if pinned else "Pin seat")

    def _on_details_toggle(self):
        self.settings["seating_details"] = self.show_details.get()
        self._draw_room()

    def _draw_room(self):
        canvas = self.canvas
        canvas.delete("all")
        dark = ctk.get_appearance_mode() == "Dark"
        colors = _palette(dark)
        canvas.configure(bg=colors["bg"])
        width, height = canvas.winfo_width(), canvas.winfo_height()
        if self.cls is None or width < 50:
            canvas.create_text(width / 2, height / 2, fill=colors["muted"], font=_font(13),
                               text="Create a class or import a spreadsheet to get started.")
            return

        margin, banner = 10, 28
        canvas.create_rectangle(margin, margin, width - margin, margin + banner, fill=colors["banner"], outline="")
        canvas.create_text(width / 2, margin + banner / 2, text="Front of room", fill=colors["text"],
                           font=_font(12, bold=True))
        top = margin + banner + 12
        names = {s.id: s for s in self.cls.students}
        for seat, box in _seat_boxes(self.cls.layout, margin, top, width - margin, height - margin).items():
            if box[0] == "table":
                canvas.create_rectangle(*box[1], fill=colors["table"], outline=colors["outline"], width=1)
                continue
            x0, y0, x1, y1 = box[1]
            student = names.get(self.cls.chart.get(seat))
            selected = seat == self.selected_seat
            canvas.create_rectangle(
                x0, y0, x1, y1, tags=(f"seat:{seat}",),
                fill=colors["desk"] if student else colors["empty"],
                outline=colors["select"] if selected else colors["outline"],
                width=3 if selected else 1, dash=() if student else (3, 3),
            )
            if student:
                lines = [student.name]
                if self.show_details.get():
                    lines.append(_details(student))
                canvas.create_text((x0 + x1) / 2, (y0 + y1) / 2, text="\n".join(lines), width=max(20, x1 - x0 - 6),
                                   fill=colors["text"], font=_font(11), justify="center",
                                   tags=(f"seat:{seat}",))
            if seat in self.cls.pinned:
                canvas.create_oval(x1 - 12, y0 + 4, x1 - 4, y0 + 12, fill=colors["pin"], outline="",
                                   tags=(f"seat:{seat}",))

    # --- problems, saving, export -------------------------------------------------

    def _changed(self):
        """Save, then refresh everything that depends on the class."""
        self._save()
        self._update_seat_count()
        self._update_problems()
        self._draw_room()

    def _update_problems(self):
        if self.cls is None or not self.cls.chart:
            self._set_status("")
            return
        problems = find_problems(self.cls, self.cls.chart)
        if problems:
            shown = problems[:8]
            more = f"\n…and {len(problems) - 8} more." if len(problems) > 8 else ""
            self._set_status(f"⚠ {len(problems)} rule{'s' if len(problems) != 1 else ''} not met:\n• "
                             + "\n• ".join(shown) + more, ORANGE)
        else:
            self._set_status("✓ All rules met.", GREEN)

    def _export(self):
        if self.cls is None or not self.cls.chart:
            self._set_status("Make a seating chart first.", ORANGE)
            return
        path = filedialog.asksaveasfilename(
            title="Save seating chart as",
            initialdir=str(Path.home() / "Documents"),
            initialfile=f"{self.cls.name} seating chart.docx",
            defaultextension=".docx",
            filetypes=[("Word documents", "*.docx")],
        )
        if path:
            self._export_to(Path(path))

    def _export_to(self, path: Path):
        try:
            saved = save_chart_docx(self.cls, path)
        except OSError as e:
            self._set_status(f"Couldn't save the chart: {e}", RED)
            return
        if not (self.want_pdf.get() and self.converters):
            self._set_status(f'✓ Saved "{saved.name}".', GREEN)
            open_path(saved)
            return
        self._set_status("Saving PDF…", MUTED)
        threading.Thread(target=self._make_pdf, args=(saved,), daemon=True).start()
        self.after(100, self._poll_pdf)

    def _make_pdf(self, docx_path: Path):
        try:
            result, used = pdf.convert_with_fallback([docx_path], self.converters)
            self.messages.put((docx_path, result))
        except Exception as e:
            self.messages.put((docx_path, pdf.PdfResult(errors=[(docx_path.name, str(e))])))

    def _poll_pdf(self):
        try:
            docx_path, result = self.messages.get_nowait()
        except queue.Empty:
            self.after(100, self._poll_pdf)
            return
        if result.created:
            self._set_status(f'✓ Saved "{docx_path.name}" and "{result.created[0].name}".', GREEN)
            open_path(result.created[0])
        else:
            why = result.errors[0][1] if result.errors else "unknown error"
            self._set_status(f'Saved "{docx_path.name}", but the PDF failed: {why}', ORANGE)
            open_path(docx_path)

    def _set_status(self, text: str, color=None):
        self.status.configure(text=text, text_color=color or TEXT)

    def _apply_table_style(self):
        dark = ctk.get_appearance_mode() == "Dark"
        colors = _palette(dark)
        style = ttk.Style(self)
        # macOS's native "aqua" theme ignores custom Treeview colors (so dark
        # mode wouldn't apply); "clam" honors them everywhere. Nothing else in
        # RollCall uses ttk, so switching themes is safe.
        style.theme_use("clam")
        style.configure("RollCall.Treeview", background=colors["bg"], fieldbackground=colors["bg"],
                        foreground=colors["text"], rowheight=26, borderwidth=0)
        style.configure("RollCall.Treeview.Heading", font=_font(11, bold=True),
                        background=colors["banner"], foreground=colors["text"])
        style.map("RollCall.Treeview", background=[("selected", colors["select"])],
                  foreground=[("selected", "white")])
        self.apart_list.configure(bg=colors["bg"], fg=colors["text"], selectbackground=colors["select"])

    def on_close(self):
        self._save()


# --- drawing helpers (pure functions, so they're easy to reason about) ----------


def _font(size: int, bold: bool = False) -> tuple:
    """The system's UI font at a given size. "TkDefaultFont" is a named font, not a family."""
    family = tkfont.nametofont("TkDefaultFont").actual("family")
    return (family, size, "bold") if bold else (family, size)


def _palette(dark: bool) -> dict[str, str]:
    if dark:
        return {"bg": "#2b2b2b", "banner": "#3d3d3d", "desk": "#3a4a5c", "empty": "#2b2b2b", "table": "#333333",
                "outline": "#6b6b6b", "select": "#1f6aa5", "text": "#ececec", "muted": "#9a9a9a", "pin": "#ff7b72"}
    return {"bg": "#ffffff", "banner": "#e6e6e6", "desk": "#e8f0fb", "empty": "#ffffff", "table": "#f4f4f4",
            "outline": "#9a9a9a", "select": "#1f6aa5", "text": "#1a1a1a", "muted": "#777777", "pin": "#cf222e"}


def _details(s: Student) -> str:
    """Short markers shown under a name in the app only (never printed)."""
    marks = []
    if s.behavior != "normal":
        marks.append(s.behavior)
    if s.needs_front:
        marks.append("front")
    if s.special_needs:
        marks.append("special")
    if s.tolerant:
        marks.append("tolerant")
    return " · ".join(marks)


def _seat_boxes(layout: Layout, left: float, top: float, right: float, bottom: float) -> dict:
    """Screen rectangles for every seat (and each table's outline) within the given area.

    Returns {seat_id: ("seat", (x0, y0, x1, y1))}, plus {"table:<group>": ("table", box)}
    entries for the tables layout, which are drawn first, under the seats.
    """
    gap = 8
    boxes: dict = {}
    seats = layout.seats()
    if layout.kind == "tables":
        cols_per_table = 2
        rows_per_table = -(-layout.table_size // cols_per_table)
        tw = (right - left - gap * 2 * (layout.cols - 1)) / layout.cols
        th = min((bottom - top - gap * 2 * (layout.rows - 1)) / layout.rows, rows_per_table * 60 + 12)
        for seat in seats:
            index = int(seat.id.rsplit("s", 1)[1])
            tx, ty = left + seat.col * (tw + gap * 2), top + seat.row * (th + gap * 2)
            boxes.setdefault(f"table:{seat.group}", ("table", (tx, ty, tx + tw, ty + th)))
            sw = (tw - 12 - 4) / cols_per_table
            sh = (th - 12 - 4 * (rows_per_table - 1)) / rows_per_table
            x = tx + 6 + (index % cols_per_table) * (sw + 4)
            y = ty + 6 + (index // cols_per_table) * (sh + 4)
            boxes[seat.id] = ("seat", (x, y, x + sw, y + sh))
        # Tables first, so they're drawn underneath their seats.
        return dict(sorted(boxes.items(), key=lambda kv: kv[1][0] != "table"))

    seat_cols = layout.cols * 2 if layout.kind == "pairs" else layout.cols
    aisles = layout.cols - 1 if layout.kind == "pairs" else 0
    aisle = gap * 3
    sw = (right - left - gap * (seat_cols - 1 - aisles) - aisle * aisles) / seat_cols
    sh = min((bottom - top - gap * (layout.rows - 1)) / layout.rows, 64)
    for seat in seats:
        extra = (seat.col // 2) * (aisle - gap) if layout.kind == "pairs" else 0
        x = left + seat.col * (sw + gap) + extra
        y = top + seat.row * (sh + gap)
        boxes[seat.id] = ("seat", (x, y, x + sw, y + sh))
    return boxes
