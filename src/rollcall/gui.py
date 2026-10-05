"""The RollCall window: a Documents tab and a Seating chart tab."""

import queue
import threading
from collections import Counter
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from . import merge, pdf, starter
from .roster import Roster, RosterError, load_roster
from .seating_gui import SeatingTab
from .settings import load_settings, save_settings
from .widgets import GREEN, MUTED, ORANGE, PAD, RED, TEXT, Step, open_path


class DocumentsTab(ctk.CTkFrame):
    """Three numbered steps and a big "Create documents" button."""

    def __init__(self, master, settings: dict, converters: list[pdf.Converter]):
        super().__init__(master, fg_color="transparent")
        self.settings = settings  # shared with the other tab; saved by the window
        self.roster: Roster | None = None
        self.roster_path: Path | None = None
        self.template_path: Path | None = None
        self.check: merge.TemplateCheck | None = None
        self.out_dir = Path(self.settings.get("out_dir") or Path.home() / "Documents")
        self.converters = converters  # best first; later ones are fallbacks
        self.messages: queue.Queue = queue.Queue()
        self.cancel_event = threading.Event()
        # Only the main thread changes this, so it can't race with the worker.
        self.running = False
        self.result_folder: Path | None = None

        self._build()
        self._restore_last_session()
        self._refresh()

    # --- layout -------------------------------------------------------------

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        body.grid(row=0, column=0, sticky="nsew")
        body.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        ctk.CTkLabel(body, text="RollCall", font=ctk.CTkFont(size=28, weight="bold"), anchor="w").grid(
            row=0, column=0, sticky="w", padx=PAD, pady=(PAD, 0)
        )
        ctk.CTkLabel(
            body,
            text="Make a filled-in document for every student on your list.",
            text_color=MUTED,
            anchor="w",
        ).grid(row=1, column=0, sticky="w", padx=PAD, pady=(0, 8))

        self._build_roster_step(body).grid(row=2, column=0, sticky="ew", padx=PAD, pady=8)
        self._build_template_step(body).grid(row=3, column=0, sticky="ew", padx=PAD, pady=8)
        self._build_output_step(body).grid(row=4, column=0, sticky="ew", padx=PAD, pady=8)
        self._build_run_area().grid(row=1, column=0, sticky="ew", padx=PAD, pady=PAD)

    def _build_roster_step(self, master):
        step = Step(master, 1, "Choose your student list")
        row = ctk.CTkFrame(step, fg_color="transparent")
        row.grid(row=1, column=0, sticky="ew", padx=PAD)
        ctk.CTkButton(row, text="Choose spreadsheet…", command=self._choose_roster).pack(side="left")
        self.roster_file_label = ctk.CTkLabel(row, text="Excel (.xlsx) or .csv", text_color=MUTED)
        self.roster_file_label.pack(side="left", padx=12)

        self.roster_status = ctk.CTkLabel(step, text="", anchor="w", justify="left", wraplength=640)
        self.roster_status.grid(row=2, column=0, sticky="w", padx=PAD, pady=(6, 0))

        self.placeholder_hint = ctk.CTkLabel(
            step,
            text="Placeholders you can type in your template (click one to copy it):",
            text_color=MUTED,
            anchor="w",
        )
        self.placeholder_box = ctk.CTkFrame(step, fg_color="transparent")
        self.placeholder_hint.grid(row=3, column=0, sticky="w", padx=PAD, pady=(6, 0))
        self.placeholder_box.grid(row=4, column=0, sticky="ew", padx=PAD, pady=(2, 12))
        return step

    def _build_template_step(self, master):
        step = Step(master, 2, "Choose your Word template")
        row = ctk.CTkFrame(step, fg_color="transparent")
        row.grid(row=1, column=0, sticky="ew", padx=PAD)
        ctk.CTkButton(row, text="Choose template…", command=self._choose_template).pack(side="left")
        self.starter_button = ctk.CTkButton(
            row, text="Create a starter template", fg_color="transparent", border_width=1,
            text_color=TEXT, command=self._create_starter,
        )
        self.starter_button.pack(side="left", padx=12)

        self.template_file_label = ctk.CTkLabel(step, text="", text_color=MUTED, anchor="w")
        self.template_file_label.grid(row=2, column=0, sticky="w", padx=PAD, pady=(6, 0))
        self.template_status = ctk.CTkLabel(step, text="", anchor="w", justify="left", wraplength=640)
        self.template_status.grid(row=3, column=0, sticky="w", padx=PAD, pady=(0, 12))
        return step

    def _build_output_step(self, master):
        step = Step(master, 3, "Choose where to save")
        row = ctk.CTkFrame(step, fg_color="transparent")
        row.grid(row=1, column=0, sticky="ew", padx=PAD)
        ctk.CTkButton(row, text="Choose folder…", command=self._choose_out_dir).pack(side="left")
        self.out_dir_label = ctk.CTkLabel(row, text="", text_color=MUTED)
        self.out_dir_label.pack(side="left", padx=12)

        names = ctk.CTkFrame(step, fg_color="transparent")
        names.grid(row=2, column=0, sticky="ew", padx=PAD, pady=(10, 0))
        names.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(names, text="File names:").grid(row=0, column=0, sticky="w")
        self.pattern = ctk.StringVar()
        ctk.CTkEntry(names, textvariable=self.pattern).grid(row=0, column=1, sticky="ew", padx=(8, 0))
        self.pattern_example = ctk.CTkLabel(names, text="", text_color=MUTED, anchor="w")
        self.pattern_example.grid(row=1, column=1, sticky="w", padx=(8, 0))
        self.pattern.trace_add("write", lambda *_: self._update_pattern_example())

        self.want_pdf = ctk.BooleanVar(value=bool(self.settings.get("pdf")) and bool(self.converters))
        self.pdf_checkbox = ctk.CTkCheckBox(step, text="Also save each one as a PDF", variable=self.want_pdf)
        self.pdf_checkbox.grid(row=3, column=0, sticky="w", padx=PAD, pady=(10, 0))
        if self.converters:
            hint = f"PDFs are made with {self.converters[0].label}"
            if len(self.converters) > 1:
                hint += f" (or {self.converters[1].label}, if {self.converters[0].label} can't)"
            hint += "."
        else:
            self.pdf_checkbox.configure(state="disabled")
            hint = "To make PDFs, install Microsoft Word or LibreOffice (free), then reopen RollCall."
        ctk.CTkLabel(step, text=hint, text_color=MUTED, anchor="w").grid(
            row=4, column=0, sticky="w", padx=PAD + 32, pady=(0, 12)
        )
        return step

    def _build_run_area(self):
        area = ctk.CTkFrame(self, fg_color="transparent")
        area.grid_columnconfigure(0, weight=1)

        buttons = ctk.CTkFrame(area, fg_color="transparent")
        buttons.grid(row=0, column=0, sticky="ew")
        buttons.grid_columnconfigure(0, weight=1)
        self.create_button = ctk.CTkButton(
            buttons, text="Create documents", height=44,
            font=ctk.CTkFont(size=16, weight="bold"), command=self._start,
        )
        self.create_button.grid(row=0, column=0, sticky="ew")
        self.cancel_button = ctk.CTkButton(buttons, text="Cancel", height=44, width=100, command=self._cancel)
        self.open_button = ctk.CTkButton(buttons, text="Open folder", height=44, width=140, command=self._open_result)

        self.progress = ctk.CTkProgressBar(area)
        self.progress.set(0)
        self.status = ctk.CTkLabel(area, text="", anchor="w", justify="left", wraplength=700)
        self.status.grid(row=2, column=0, sticky="w", pady=(6, 0))
        self.problems = ctk.CTkTextbox(area, height=110)
        return area

    # --- step 1: student list -----------------------------------------------

    def _choose_roster(self):
        path = filedialog.askopenfilename(
            title="Choose your student list",
            filetypes=[("Spreadsheets", "*.xlsx *.csv"), ("All files", "*.*")],
            initialdir=self._initial_dir("roster"),
        )
        if path:
            self._load_roster(Path(path))
            self._refresh()

    def _load_roster(self, path: Path, quiet: bool = False) -> bool:
        try:
            roster = load_roster(path)
        except (RosterError, OSError) as e:
            if not quiet:
                self.roster, self.roster_path = None, None
                self.roster_file_label.configure(text=path.name)
                self.roster_status.configure(text=str(e), text_color=RED)
            return False

        keys_changed = self.roster is None or self.roster.keys != roster.keys
        self.roster, self.roster_path = roster, path
        self.settings["roster"] = str(path)
        self.roster_file_label.configure(text=path.name)
        names = ", ".join(roster.display_name(r) for r in roster.rows[:3])
        more = ", …" if len(roster.rows) > 3 else ""
        count = len(roster.rows)
        self.roster_status.configure(
            text=f"✓ {count} student{'s' if count != 1 else ''} found: {names}{more}", text_color=GREEN
        )
        if keys_changed:
            self.pattern.set(merge.default_filename_pattern(roster))
            self._show_placeholders()
        if self.template_path:
            self._check_template()
        return True

    def _show_placeholders(self):
        for child in self.placeholder_box.winfo_children():
            child.destroy()
        per_row = 3
        for i, column in enumerate(self.roster.columns):
            text = starter.placeholder_for(column)
            ctk.CTkButton(
                self.placeholder_box, text=text, height=26, fg_color=("gray85", "gray25"),
                text_color=TEXT, hover_color=("gray75", "gray35"),
                command=lambda t=text: self._copy(t),
            ).grid(row=i // per_row, column=i % per_row, sticky="w", padx=(0, 8), pady=3)

    def _copy(self, text: str):
        self.clipboard_clear()
        self.clipboard_append(text)
        self._set_status(f"Copied {text}. Paste it into your Word template where it should go.")

    # --- step 2: template ---------------------------------------------------

    def _choose_template(self):
        path = filedialog.askopenfilename(
            title="Choose your Word template",
            filetypes=[("Word documents", "*.docx"), ("All files", "*.*")],
            initialdir=self._initial_dir("template"),
        )
        if path:
            self._set_template(Path(path))

    def _set_template(self, path: Path):
        self.template_path = path
        self.settings["template"] = str(path)
        self.template_file_label.configure(text=path.name)
        self._check_template()
        self._refresh()

    def _check_template(self):
        if not self.template_path:
            return
        if not self.template_path.exists():
            self.check = merge.TemplateCheck(error=f'Couldn\'t find "{self.template_path.name}". Was it moved?')
        elif self.template_path.suffix.lower() != ".docx":
            self.check = merge.TemplateCheck(
                error="Templates must be Word documents (.docx). In Word, use File > Save As and choose .docx."
            )
        elif self.roster is None:
            self.check = None
            self.template_status.configure(text="Choose your student list to check this template.", text_color=MUTED)
            return
        else:
            self.check = merge.inspect_template(self.template_path, self.roster)

        check = self.check
        if check.error:
            self.template_status.configure(text=f"✗ {check.error}", text_color=RED)
        elif check.unknown:
            self.template_status.configure(text="⚠ " + self._unknown_message(check.unknown), text_color=ORANGE)
        else:
            used = len(check.placeholders)
            self.template_status.configure(
                text=f"✓ Looks good. {used} placeholder{'s' if used != 1 else ''} will be filled in.",
                text_color=GREEN,
            )

    @staticmethod
    def _unknown_message(unknown: list[str]) -> str:
        tags = ", ".join("{{%s}}" % u for u in unknown)
        return (
            f"Your template uses {tags}, but your spreadsheet has no matching column. "
            "Those spots will be left blank. Check the spelling, or add the column to your spreadsheet."
        )

    def _create_starter(self):
        if self.roster is None:
            self._set_status("Choose your student list first, so the starter template can include its columns.")
            return
        stem = self.roster_path.stem if self.roster_path else "My"
        path = filedialog.asksaveasfilename(
            title="Save starter template as",
            initialdir=str(self.roster_path.parent if self.roster_path else self.out_dir),
            initialfile=f"{stem} template.docx",
            defaultextension=".docx",
            filetypes=[("Word documents", "*.docx")],
        )
        if not path:
            return
        try:
            starter.create_starter_template(self.roster, path)
        except OSError as e:
            self._set_status(f"Couldn't save the starter template: {e}", RED)
            return
        self._set_template(Path(path))
        open_path(Path(path))
        self._set_status(
            "Starter template created and opened. Edit it however you like, save it, "
            "then come back here and click Create documents."
        )

    # --- step 3: output -----------------------------------------------------

    def _choose_out_dir(self):
        path = filedialog.askdirectory(title="Choose where to save", initialdir=str(self.out_dir))
        if path:
            self.out_dir = Path(path)
            self.settings["out_dir"] = path
            self._refresh()

    def _update_pattern_example(self):
        if self.roster and self.roster.rows:
            example = merge.make_filename(self.pattern.get(), self.roster.rows[0])
            self.pattern_example.configure(text=f"For example: {example}.docx")
        self._refresh()

    # --- running ------------------------------------------------------------

    def _start(self):
        # Reload both files: the teacher may have edited them since choosing.
        if not self._load_roster(self.roster_path):
            self._refresh()
            return
        self._check_template()
        if self.check is None or self.check.error:
            self._refresh()
            return
        if self.check.unknown and not messagebox.askyesno(
            "Some placeholders don't match",
            self._unknown_message(self.check.unknown) + "\n\nCreate the documents anyway?",
        ):
            return

        self.settings["pdf"] = self.want_pdf.get()
        save_settings(self.settings)
        self.cancel_event.clear()
        self.result_folder = None
        self._set_running(True)
        threading.Thread(
            target=self._work,
            args=(self.roster, self.template_path, self.out_dir, self.pattern.get(),
                  self.converters if self.want_pdf.get() else []),
            daemon=True,
        ).start()
        self.after(100, self._poll)

    def _work(self, roster, template_path, out_dir, pattern, converters):
        """Runs on a background thread. Talks to the window only through self.messages."""
        try:
            merged = merge.generate(
                roster, template_path, out_dir, pattern,
                on_progress=lambda d, t, n: self.messages.put(("progress", "Creating", d, t, n)),
                cancel_event=self.cancel_event,
            )
            pdfs, used = None, None
            if converters and merged.created and not merged.cancelled:
                self.messages.put(("progress", "Saving PDFs of", 0, len(merged.created), ""))
                pdfs, used = pdf.convert_with_fallback(
                    merged.created, converters,
                    on_progress=lambda d, t, n: self.messages.put(("progress", "Saving PDFs of", d, t, n)),
                    cancel_event=self.cancel_event,
                )
            self.messages.put(("done", merged, pdfs, used))
        except Exception as e:
            self.messages.put(("failed", str(e)))

    def _poll(self):
        try:
            while True:
                kind, *data = self.messages.get_nowait()
                if kind == "progress":
                    stage, done, total, name = data
                    self.progress.set(done / total if total else 0)
                    suffix = f": {name}" if name else ""
                    self._set_status(f"{stage} document {done} of {total}{suffix}")
                elif kind == "done":
                    self._finish(*data)
                    return
                elif kind == "failed":
                    self._set_running(False)
                    self._set_status(f"Something went wrong: {data[0]}", RED)
                    return
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _finish(self, merged: merge.MergeResult, pdfs: pdf.PdfResult | None, used: pdf.Converter | None = None):
        self._set_running(False)
        self.result_folder = merged.folder
        created = len(merged.created)
        message = f"Created {created} document{'s' if created != 1 else ''}"
        if pdfs is not None:
            message += f" and {len(pdfs.created)} PDF{'s' if len(pdfs.created) != 1 else ''}"
        message += f' in the folder "{merged.folder.name}".'
        if merged.cancelled or self.cancel_event.is_set():
            message = "Stopped. " + message
        if pdfs and pdfs.created and used and used != self.converters[0]:
            message += f" The PDFs were made with {used.label}, because {self.converters[0].label} couldn't save them."

        problems = [f"{who}: {why}" for who, why in merged.errors]
        if pdfs:
            # The same Word error for every file is one problem, not thirty.
            for why, count in Counter(why for _, why in pdfs.errors).items():
                files = [who for who, w in pdfs.errors if w == why]
                who = files[0] if count == 1 else f"{count} PDFs"
                problems.append(f"{who}: {why}")

        if problems:
            self._set_status(message + f" {len(problems)} problem(s) are listed below.", ORANGE)
            self.problems.configure(state="normal")
            self.problems.delete("1.0", "end")
            self.problems.insert("1.0", "\n\n".join(problems))
            self.problems.configure(state="disabled")
            self.problems.grid(row=3, column=0, sticky="ew", pady=(6, 0))
        else:
            self._set_status("✓ " + message, GREEN)
        if created:
            self.open_button.grid(row=0, column=1, padx=(8, 0))

    def _cancel(self):
        self.cancel_event.set()
        self.cancel_button.configure(state="disabled")
        self._set_status("Stopping…")

    def _open_result(self):
        if self.result_folder:
            open_path(self.result_folder)

    def _set_running(self, running: bool):
        self.running = running
        self.problems.grid_remove()
        self.open_button.grid_remove()
        if running:
            self.progress.set(0)
            self.progress.grid(row=1, column=0, sticky="ew", pady=(10, 0))
            self.create_button.configure(state="disabled")
            self.cancel_button.configure(state="normal")
            self.cancel_button.grid(row=0, column=1, padx=(8, 0))
        else:
            self.progress.grid_remove()
            self.cancel_button.grid_remove()
            self._refresh()

    # --- helpers ------------------------------------------------------------

    def _refresh(self):
        """Enable "Create documents" only when everything needed is in place."""
        self.out_dir_label.configure(text=str(self.out_dir))
        has_roster = self.roster is not None
        for widget in (self.placeholder_hint, self.placeholder_box):
            if has_roster:
                widget.grid()
            else:
                widget.grid_remove()
        ready = (
            has_roster
            and self.template_path is not None
            and self.check is not None
            and self.check.error is None
            and self.pattern.get().strip() != ""
            and not self.running
        )
        self.create_button.configure(state="normal" if ready else "disabled")

    def _set_status(self, text: str, color=None):
        self.status.configure(text=text, text_color=color or TEXT)

    def _initial_dir(self, key: str) -> str:
        last = self.settings.get(key)
        return str(Path(last).parent) if last else str(Path.home())

    def _restore_last_session(self):
        roster = self.settings.get("roster")
        if roster and Path(roster).exists():
            self._load_roster(Path(roster), quiet=True)
        template = self.settings.get("template")
        if template and Path(template).exists():
            self.template_path = Path(template)
            self.template_file_label.configure(text=self.template_path.name)
            self._check_template()

    def on_close(self):
        self.cancel_event.set()


class RollCallApp(ctk.CTk):
    TABS = ("Documents", "Seating chart")

    def __init__(self):
        super().__init__()
        self.title("RollCall")
        self.geometry("1100x820")
        self.minsize(760, 640)
        self.settings = load_settings()
        converters = pdf.find_converters()

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.tabs = ctk.CTkTabview(self, command=self._remember_tab)
        self.tabs.grid(row=0, column=0, sticky="nsew", padx=8, pady=(0, 8))
        for name in self.TABS:
            self.tabs.add(name)
            self.tabs.tab(name).grid_columnconfigure(0, weight=1)
            self.tabs.tab(name).grid_rowconfigure(0, weight=1)
        self.documents = DocumentsTab(self.tabs.tab("Documents"), self.settings, converters)
        self.documents.grid(row=0, column=0, sticky="nsew")
        self.seating = SeatingTab(self.tabs.tab("Seating chart"), self.settings, converters)
        self.seating.grid(row=0, column=0, sticky="nsew")
        if self.settings.get("tab") in self.TABS:
            self.tabs.set(self.settings["tab"])
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _remember_tab(self):
        self.settings["tab"] = self.tabs.get()

    def _on_close(self):
        self.documents.on_close()
        self.seating.on_close()
        save_settings(self.settings)
        self.destroy()


def run() -> None:
    ctk.set_appearance_mode("system")
    ctk.set_default_color_theme("blue")
    RollCallApp().mainloop()
