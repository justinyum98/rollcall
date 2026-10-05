# RollCall

**Make a filled-in document for every student on your list, and a seating chart that follows your rules, in a few clicks.**

- **Documents:** certificates, progress letters, permission slips, name tags. Write it once in Word, and RollCall makes a copy for each student with their name (and anything else from your spreadsheet) filled in. It can also save each copy as a PDF.
- **Seating chart:** tell RollCall who's loud, who needs to see the board, and who shouldn't sit together, and it suggests a chart you can adjust and print.

---

## For teachers

### What you need
- **A spreadsheet of students.** Excel (`.xlsx`) or `.csv`. Put column names in the first row, such as **First Name** and **Last Name**, and one student per row. Using Google Sheets? Choose *File → Download → Microsoft Excel (.xlsx)*.
- **A Word document to use as the template** (`.docx`). Google Docs works too: choose *File → Download → Microsoft Word (.docx)*.

### Step by step
1. **Open RollCall** and click **Choose spreadsheet…**. RollCall shows how many students it found, plus buttons for every column, such as `{{First Name}}`.
2. **Make your template.** Wherever a student's information should go, type the column name inside double curly braces:

   > This certificate is proudly presented to **{{First Name}} {{Last Name}}** for a wonderful year in grade {{Grade}}.

   Click a placeholder button in RollCall to copy it, then paste it into Word. You can make placeholders bold, colored, larger, and so on, and the student's information keeps that look.
   *Not sure where to start?* Click **Create a starter template**. RollCall makes a Word document with all of your columns already in it.
3. Click **Choose template…** and pick your Word document. RollCall checks it right away:
   - ✓ **Looks good.** You're ready.
   - ⚠ **A placeholder doesn't match a column.** Usually a typo. Fix it in Word, or the spot is left blank.
   - ✗ **Something is broken**, such as a missing curly brace. RollCall shows you which one.
4. **Choose where to save.** Each run creates its own new folder, so earlier documents are never overwritten. Tick **Also save each one as a PDF** if you'd like PDFs too.
5. Click **Create documents**, then **Open folder** to see them.

RollCall remembers your spreadsheet, template, and folder for next time. If you change the spreadsheet or template, just click **Create documents** again; RollCall rereads both every time.

### Saving as PDF
PDFs are made with **Microsoft Word** if it's installed, or **LibreOffice** (free, from libreoffice.org) if not. If Word is installed but can't make PDFs, RollCall switches to LibreOffice automatically when it's installed. If neither is installed, the PDF option is greyed out.
- **Mac:** the first time, macOS asks whether RollCall may control Microsoft Word. Click **OK**.
- If Word says **"View Only"** (your Office account can't edit on this computer), Word can't make PDFs. Install LibreOffice and RollCall will use it instead, or sign in to Word with an account that can edit.
- RollCall never closes a copy of Word you already had open.

### Opening RollCall for the first time
RollCall isn't signed by Apple or Microsoft, so your computer warns you the first time:
- **Windows:** "Windows protected your PC" → click **More info** → **Run anyway**.
- **Mac:** double-click RollCall, then go to *System Settings → Privacy & Security* and click **Open Anyway**.

If your school manages your computer, you may need to ask IT to allow it.

### Seating charts
Open the **Seating chart** tab.

1. **Add your students.** Click **Import from spreadsheet…**, or type names in and click **Add student**. Each class (Period 1, Period 2, …) is saved separately; use **New class** to add another.
2. **Mark each student** by clicking the cells in the list:
   - **Behavior**: click to cycle *loud → normal → quiet*.
   - **Needs front**: can't see the board from far away.
   - **Special needs**: serious behavior needs; only "tolerant" students are seated next to them.
   - **Tolerant**: fine sitting next to special-needs students.

   Your spreadsheet can also include these as columns (**Behavior**, **Vision**, **Special Needs**, **Tolerant**, and **Not Next To** with names separated by commas). RollCall reads them when you import.
3. **Keep apart:** choose two students and click **Add** for each pair who shouldn't sit together.
4. **Set up the room:** *Rows* of single desks, *Pairs* of desks, or *Tables*, and how many.
5. Click **Make seating chart**. RollCall follows these rules:
   - Students who need to see the board sit in the front rows.
   - "Keep apart" pairs and two loud students are never seated next to each other.
   - Special-needs students sit only next to tolerant students, toward the back of the room.
   - Loud students are seated next to quiet ones when possible.

   ("Next to" means beside, in front, or behind; everyone at a table counts as next to each other.) If some rules can't all be met, RollCall makes the best chart it can and lists what it couldn't do.
6. **Adjust it:** click two seats to swap them. Right-click a seat (or select it and click **Pin seat**) to keep that student there, then click **Shuffle** to rearrange everyone else.
7. Click **Save as Word…** (and tick **Also PDF**) to print it.

**Privacy:** classifications like *special needs* stay on your computer, and never appear on the printed chart, which shows names only.

### Try it out
The `examples` folder has a class list of 25 students and a certificate template for the Documents tab, plus `Seating example.xlsx` (24 students with behavior, vision, and "not next to" columns) for the Seating chart tab.

---

## For developers

RollCall is a Python 3.12 desktop app: [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter) for the window, [docxtpl](https://docxtpl.readthedocs.io/) (Jinja2 + python-docx) for filling templates, and openpyxl for spreadsheets. Packaged with PyInstaller.

```bash
uv sync                                  # install (uv manages Python 3.12)
uv run python -m rollcall                # run the app
uv run pytest                            # run tests
ROLLCALL_TEST_PDF=1 uv run pytest        # also convert real PDFs (opens Word/LibreOffice)
uv run pyinstaller --noconfirm rollcall.spec   # build dist/RollCall.app or dist/RollCall.exe
dist/RollCall.app/Contents/MacOS/RollCall --self-test   # check the built app works
uv run python scripts/make_examples.py   # regenerate examples/
```

| Module | What it does |
|---|---|
| `roster.py` | Reads `.xlsx`/`.csv` into rows. Column headers become placeholder keys (`"First Name"` → `first_name`). Values become display text (`5.0` → `5`, dates → `June 12, 2026`). |
| `merge.py` | Checks templates (unknown or broken placeholders) and renders one `.docx` per student into a new timestamped folder. Lets teachers write `{{First Name}}` by rewriting it to `{{ first_name }}` in docxtpl's `patch_xml`, after Word's split runs are merged. |
| `pdf.py` | Converts to PDF with Word (JXA on macOS, COM on Windows) or headless LibreOffice, falling back to the next converter if one makes nothing. Only quits Word if RollCall started it. |
| `starter.py` | Builds a starter template from the spreadsheet's columns. |
| `gui.py` | The tabbed window and the Documents tab. Work runs on a background thread and reports back through a queue, because Tk isn't thread-safe. |
| `seating/model.py` | Students, room layouts (rows, pairs, tables) and who counts as "next to" whom, saved classes (JSON in the app's settings folder). |
| `seating/importing.py` | Reads students and classification columns from a spreadsheet, merging into an existing class. |
| `seating/solver.py` | Scores a chart with a penalty per rule ("never" rules weigh 200–1000, preferences 5–20) and searches for the best one by simulated annealing over seat swaps. `find_problems()` explains broken rules in plain language. |
| `seating/export.py` | The printable chart (names only) as a landscape Word document. |
| `seating_gui.py` | The Seating chart tab. The student list is a `ttk.Treeview`, because 40 rows of CustomTkinter widgets take about 5 s to build. |
| `__main__.py` | Entry point. `--self-test` exercises the packaged app in CI. |

**Releases:** `.github/workflows/build.yml` builds and self-tests the Windows `.exe` and the macOS `.app` on every push. Push a `v*` tag to publish both as a GitHub release. The macOS build runs on Apple Silicon runners, so it targets Apple Silicon Macs.
