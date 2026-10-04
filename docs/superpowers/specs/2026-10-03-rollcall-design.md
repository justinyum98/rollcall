# RollCall: fill in a document for every student

## Context
Teachers often make the same document for every student: certificates, progress letters, permission slips, name tags. Copying and pasting names by hand takes a lot of time, especially for teachers who aren't comfortable with technology. RollCall is a desktop app with a simple window. A teacher picks a spreadsheet of students and a Word template that contains placeholders like `{{first_name}}`. RollCall then creates one filled-in document per student, and optionally a PDF of each.

Decisions already made with the user:
- **Templates:** Word `.docx` files with `{{placeholder}}` tags.
- **Output:** always `.docx`. "Also save as PDF" is optional and is enabled only when Microsoft Word or LibreOffice is installed.
- **Placeholders:** every spreadsheet column becomes one.
- **Platforms:** Windows `.exe` and macOS `.app`.
- **GUI toolkit:** CustomTkinter.

Starting state: the project directory is empty and is not a git repo. The only system Python is 3.9.6, and its Tk is too old, so we'll use **uv** (already installed) with a uv-managed Python 3.12.

## Tech stack
| Need | Library | Why |
|---|---|---|
| Template filling | `docxtpl` | Uses Jinja2 on top of python-docx. It handles placeholders that Word splits across formatting "runs", which is the usual pitfall with plain find-and-replace. `get_undeclared_template_variables()` lets us check a template before generating anything. |
| Spreadsheets | `openpyxl` + stdlib `csv` | Reads `.xlsx` and `.csv`. Avoids pandas, which would add about 30 MB to the executable. |
| PDF (optional) | Our own Word automation (JXA on macOS, pywin32 COM on Windows), with a LibreOffice `soffice --headless` fallback | docx2pdf was dropped: it always quits Word, which could close a teacher's unsaved work, and it calls `sys.exit` on errors. |
| GUI | `customtkinter` | Modern look and a small executable. |
| Packaging | PyInstaller, built with GitHub Actions on `windows-latest` and `macos-latest` | |
| Tests | pytest | |

## Project layout
```
rollcall/
  pyproject.toml            # uv project; console entry point `rollcall`
  src/rollcall/
    __main__.py             # entry point; fixes sys.stdout=None in windowed builds; --self-test flag
    roster.py               # read xlsx/csv -> Roster(columns, rows); normalize header names
    merge.py                # check template, render one document per student, safe unique file names
    pdf.py                  # find a converter (Word or LibreOffice) and convert a folder
    starter.py              # build a starter .docx from the roster's columns
    settings.py             # remember last-used paths (JSON file in the user's config folder)
    gui.py                  # CustomTkinter window; runs the work in a background thread
  tests/                    # conftest builds xlsx/csv/docx fixtures in tmp_path
  rollcall.spec             # PyInstaller config
  .github/workflows/build.yml
  docs/superpowers/specs/2026-10-03-rollcall-design.md
  README.md                 # teacher guide (with screenshots placeholder) + developer guide
```

## Core behavior

**`roster.py`: `load_roster(path) -> Roster`**
- `.xlsx`: open with `openpyxl.load_workbook(read_only=True, data_only=True)` and use the active sheet. The first non-empty row is the header row. Fully blank rows are skipped.
- `.csv`: decode as `utf-8-sig` (handles the byte-order mark Excel adds) and fall back to `cp1252`.
- `.xls` or anything else: show a friendly error, e.g. "Please save as .xlsx or .csv".
- Cell values are converted to text for documents:
  - `None` becomes an empty string.
  - `12.0` becomes `"12"`.
  - Dates become `"March 5, 2026"`, built by hand because `%-d` doesn't work on Windows.
  - Leading and trailing spaces are trimmed.
- Header names become placeholder keys:
  - `"First Name"` becomes `first_name`: lowercase, with runs of non-alphanumeric characters replaced by `_`.
  - A key that starts with a digit gets a `col_` prefix.
  - Empty headers become `column_3`, and so on.
  - Duplicate headers get `_2`, `_3`, and so on.
  - `Roster.columns` keeps both the original label and the key so the GUI can show both.

**`merge.py`**
- `inspect_template(path, roster) -> TemplateCheck`: compares the template's variables with `roster.keys` and reports them as matched, unknown, or unused. A Jinja `TemplateSyntaxError` becomes a plain-English message, such as "A placeholder is broken. Check that every `{{` has a matching `}}`."
- `generate(roster, template_path, out_dir, filename_pattern, on_progress, cancel_event) -> MergeResult`:
  - Reads the template bytes once, then builds a fresh `DocxTemplate(BytesIO(...))` for each row.
  - If one row fails, the error is recorded and the run continues.
- Output goes in a new subfolder, `<out_dir>/<template name> - 2026-10-03 1530/`, so earlier runs are never overwritten.
- `make_filename(pattern, row)`:
  - The default pattern is `{last_name}, {first_name}` when both columns exist; otherwise the first column is used.
  - Characters that are illegal in file names are removed: `<>:"/\|?*` and control characters.
  - Trailing dots and spaces are trimmed, and reserved Windows names (CON, NUL and so on) are avoided.
  - Names are capped at 120 characters.
  - Duplicates become `Name (2).docx`.

**`pdf.py`**
- `find_converter() -> "word" | "libreoffice" | None`:
  - Word on macOS: check that `/Applications/Microsoft Word.app` exists.
  - Word on Windows: look for the `Word.Application` registry key with `winreg`.
  - LibreOffice: use `shutil.which("soffice")` plus the standard install paths.
- `convert_to_pdf(files, converter, on_progress, cancel_event)`:
  - **macOS Word:** one inline JXA script (`osascript -l JavaScript -e`) converts all files, printing one JSON line per file to stderr for progress. Word is quit only if RollCall launched it.
  - **Windows Word:** `DispatchEx` starts a separate hidden Word, so quitting it can't touch the teacher's documents.
  - **LibreOffice:** runs `soffice --headless --convert-to pdf` with a throwaway profile, so it works even while LibreOffice is open.
  - Cancel kills a Word that is stuck behind a dialog.
  - Word errors are translated into plain language: View Only mode (`-1708`), automation blocked (`-1743`), timeouts (`-1712`).
- On Windows, the worker thread must call `pythoncom.CoInitialize()` before Word automation, or it fails with "CoInitialize has not been called".

**`starter.py`**: the "Create a starter template" button builds a `.docx` with a short heading, one line per column (`First Name: {{first_name}}`), and brief instructions. This gives a teacher who isn't confident with tech a working template to edit instead of a blank page.

## GUI (one window, three numbered steps)
1. **Student list** `[Choose file…]`
   - Shows "28 students loaded" and a preview of the first few names.
   - Lists the available placeholders, each with a **Copy** button.
2. **Template** `[Choose file…]` `[Create a starter template]`
   - Shows the template check: ✓ "All placeholders match", or ⚠ "Your template uses {{grade}}, but your spreadsheet has no 'grade' column".
3. **Save to** `[Choose folder…]` (defaults to Documents)
   - A file name pattern field.
   - An "Also save as PDF" checkbox. It is disabled when no converter is found, with a hint: "Install Microsoft Word or LibreOffice to enable".

**[Create documents]** shows a progress bar and a status line. When it finishes, it says "Created 28 documents (0 problems)" and offers an **[Open folder]** button (`os.startfile` on Windows, `open` on macOS). Any per-student errors are listed in a scrollable box.

**Threading:** the merge runs in a `threading.Thread`, which posts progress to a `queue.Queue`. The GUI reads the queue with `after(100, …)` because Tk is not thread-safe. The window is disabled while a run is in progress, and a Cancel button sets a `threading.Event`. The last-used paths are saved and restored through `settings.py`.

## Packaging
- In `rollcall.spec`:
  - Use `--windowed`.
  - Bundle the theme JSON and font files with `collect_data_files("customtkinter")`.
  - Bundle python-docx's and docxtpl's data files.
  - Add `NSAppleEventsUsageDescription` so macOS can ask permission to control Word.
- **Windows:** `--onefile` produces a single `RollCall.exe`, which is easiest for teachers. The CustomTkinter wiki recommends `--onedir`, but `--collect-data` makes onefile work. If the CI self-test fails, fall back to a zipped onedir build.
- **macOS:** build `RollCall.app` and zip it.
- **`__main__.py`:** windowed builds have `sys.stdout`/`sys.stderr` set to `None`. Point them at `os.devnull` so any library that prints doesn't crash.
- **`--self-test` flag:** imports everything, loads the theme, merges a built-in sample in a temporary folder, then exits 0 or 1. CI runs this against the built executable.
- **`build.yml`:** a matrix over `windows-latest` and `macos-latest`. Each job installs uv, runs `uv sync`, runs `pytest`, runs `pyinstaller rollcall.spec`, runs the self-test on the built output, and uploads the artifacts. It triggers on tags and manual dispatch.
- **Unsigned builds:** the README explains the first-launch warnings ("More info → Run anyway" on Windows; "Open Anyway" in System Settings on macOS) and the macOS one-time "allow RollCall to control Microsoft Word" prompt. Code signing is out of scope.

## Implementation order (test-driven, per superpowers)
1. Run `git init`, add `.gitignore`, run `uv init --package` and pin Python 3.12 with `uv python pin 3.12`, then add the dependencies. Write the spec doc and commit.
2. `roster.py` with its tests.
3. `merge.py` with its tests (filename, inspect, generate).
4. `starter.py` with its tests.
5. `pdf.py`: test detection with monkeypatching; add an integration test that is skipped when Word or LibreOffice is absent. Word is installed on this Mac, so it will run here.
6. `settings.py`, then `gui.py`, then `__main__.py` with `--self-test`.
7. Write `rollcall.spec`, build the macOS app locally, and smoke-test it.
8. Write `build.yml` and the README.

## Verification
- `uv run pytest`: every core module is covered using generated xlsx, csv and docx fixtures. Edge cases include names split across runs, unicode names (José, 李), blank rows, duplicate students, illegal characters, and unknown placeholders.
- `uv run python -m rollcall`: manual end-to-end run on this Mac with a sample roster of about 25 students and a template that uses bold/colored placeholders. Check that the documents open in Word with formatting kept, the PDF checkbox produces matching PDFs, and Cancel and Open folder work.
- `uv run pyinstaller rollcall.spec`, then `dist/RollCall.app/Contents/MacOS/RollCall --self-test` exits 0, and double-clicking the .app launches the window.
- The Windows `.exe` is verified by the CI self-test. A manual check on a Windows machine is still recommended before handing it to teachers.

## Findings during implementation
- **docx2pdf was replaced.** It always quits Word, and calls `sys.exit()` on errors, which would silently kill a worker thread.
- **Word for Mac in "View Only" mode** (an unlicensed account) can open documents but can't save them. `saveAs` fails with "Message not understood". This was confirmed on the development Mac. RollCall explains this and suggests LibreOffice.
- **Inside the PyInstaller bundle**, touching a missing header makes python-docx load `docx/parts/../templates/…`, which can't be resolved. Template inspection now skips headers and footers that don't exist. The CI `--self-test` caught this.
- **lxml's `itertext()`** repeats run text on python-docx elements, so paragraph text is read from `w:t` nodes instead.
- **Old uv Python builds** (3.12.11) couldn't find Tcl from inside a venv. Python 3.12.13 or later works.
