# RollCall

**Make a filled-in document for every student on your list, in a few clicks.**

Certificates, progress letters, permission slips, name tags: write it once in Word, and RollCall makes a copy for each student with their name (and anything else from your spreadsheet) filled in. It can also save each copy as a PDF.

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
PDFs are made with **Microsoft Word** if it's installed; if not, RollCall uses **LibreOffice** (free, from libreoffice.org). If neither is installed, the PDF option is greyed out.
- **Mac:** the first time, macOS asks whether RollCall may control Microsoft Word. Click **OK**.
- If Word says **"View Only"** (your Office account can't edit on this computer), Word can't make PDFs. Sign in with an account that can edit, or install LibreOffice.
- RollCall never closes a copy of Word you already had open.

### Opening RollCall for the first time
RollCall isn't signed by Apple or Microsoft, so your computer warns you the first time:
- **Windows:** "Windows protected your PC" → click **More info** → **Run anyway**.
- **Mac:** double-click RollCall, then go to *System Settings → Privacy & Security* and click **Open Anyway**.

If your school manages your computer, you may need to ask IT to allow it.

### Try it out
The `examples` folder has a class list of 25 students and a certificate template. Use them to see how RollCall works before using your own files.

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
| `pdf.py` | Converts to PDF with Word (JXA on macOS, COM on Windows) or headless LibreOffice. Only quits Word if RollCall started it. |
| `starter.py` | Builds a starter template from the spreadsheet's columns. |
| `gui.py` | The window. Work runs on a background thread and reports back through a queue, because Tk isn't thread-safe. |
| `__main__.py` | Entry point. `--self-test` exercises the packaged app in CI. |

**Releases:** `.github/workflows/build.yml` builds and self-tests the Windows `.exe` and the macOS `.app` on every push. Push a `v*` tag to publish both as a GitHub release. The macOS build runs on Apple Silicon runners, so it targets Apple Silicon Macs.
