import os
import sys
import threading
import time

import pytest

from rollcall import pdf
from rollcall.merge import generate
from rollcall.pdf import convert_to_pdf, find_converter
from rollcall.roster import load_roster


def nothing_exists(path):
    return False


def no_which(name):
    return None


def test_word_on_mac():
    exists = lambda p: p == "/Applications/Microsoft Word.app"
    conv = find_converter("darwin", exists=exists, which=no_which)
    assert conv.kind == "word"


def test_word_on_windows():
    conv = find_converter("win32", exists=nothing_exists, which=no_which, word_registered=lambda: True)
    assert conv.kind == "word"


def test_libreoffice_fallback_on_windows():
    path = r"C:\Program Files\LibreOffice\program\soffice.exe"
    conv = find_converter("win32", exists=lambda p: p == path, which=no_which, word_registered=lambda: False)
    assert conv.kind == "libreoffice"
    assert conv.path == path


def test_libreoffice_on_path():
    conv = find_converter("linux", exists=nothing_exists, which=lambda n: "/usr/bin/soffice" if n == "soffice" else None)
    assert conv.kind == "libreoffice"
    assert conv.path == "/usr/bin/soffice"


def test_nothing_installed():
    assert find_converter("darwin", exists=nothing_exists, which=no_which) is None
    assert find_converter("win32", exists=nothing_exists, which=no_which, word_registered=lambda: False) is None


@pytest.mark.skipif(
    not os.environ.get("ROLLCALL_TEST_PDF"),
    reason="Opens Word/LibreOffice; set ROLLCALL_TEST_PDF=1 to run",
)
def test_real_conversion(tmp_path, make_xlsx, make_docx):
    converter = find_converter()
    if converter is None:
        pytest.skip("No Word or LibreOffice installed")
    roster = load_roster(make_xlsx([["First Name", "Last Name"], ["Ada", "Lovelace"], ["José", "Núñez"]]))
    merged = generate(roster, make_docx(["Hello {{first_name}}"]), tmp_path / "out", "{last_name}, {first_name}")
    progress = []

    result = convert_to_pdf(merged.created, converter, lambda d, t, n: progress.append(d))

    assert result.errors == []
    assert sorted(p.name for p in result.created) == ["Lovelace, Ada.pdf", "Núñez, José.pdf"]
    assert all(p.read_bytes().startswith(b"%PDF") for p in result.created)
    assert progress[-1] == 2


# --- macOS Word driver, with osascript replaced by a fake script --------------

FAKE_OSASCRIPT = r"""
import json, sys, time
args = sys.argv[1:]
for i in range(0, len(args), 2):
    time.sleep(float(%r))
    ok = "Bad" not in args[i]
    if ok:
        open(args[i + 1], "wb").write(b"%%PDF-fake")
    msg = {"input": args[i], "ok": ok}
    if not ok:
        msg["error"] = "Error: Message not understood."
    print(json.dumps(msg), file=sys.stderr, flush=True)
"""


def fake_osascript(delay=0.0):
    return [sys.executable, "-c", FAKE_OSASCRIPT % delay]


def docx_files(tmp_path, *names):
    paths = [tmp_path / f"{n}.docx" for n in names]
    for p in paths:
        p.write_bytes(b"")
    return paths


def test_mac_driver_reports_progress_and_friendly_errors(tmp_path):
    files = docx_files(tmp_path, "Ada", "Bad", "Alan")
    progress = []
    result = pdf._convert_word_mac(files, lambda d, t, n: progress.append((d, t, n)), None, fake_osascript())
    assert [p.name for p in result.created] == ["Ada.pdf", "Alan.pdf"]
    assert result.errors[0][0] == "Bad.docx"
    assert "View Only" in result.errors[0][1]
    assert progress == [(1, 3, "Ada"), (2, 3, "Bad"), (3, 3, "Alan")]


def test_mac_driver_cancel_stops_a_stuck_word(tmp_path):
    files = docx_files(tmp_path, "Ada", "Alan")
    cancel = threading.Event()
    threading.Timer(0.3, cancel.set).start()
    start = time.monotonic()
    result = pdf._convert_word_mac(files, None, cancel, fake_osascript(delay=30))
    assert time.monotonic() - start < 5
    assert result.created == [] and result.errors == []


def test_mac_driver_failure_before_any_file(tmp_path):
    files = docx_files(tmp_path, "Ada")
    command = [sys.executable, "-c", "import sys; print('execution error: Not authorized to send Apple events to Microsoft Word. (-1743)', file=sys.stderr); sys.exit(1)"]
    result = pdf._convert_word_mac(files, None, None, command)
    assert result.errors[0][0] == "All files"
    assert "Automation" in result.errors[0][1]


# --- choosing and falling back between converters ---------------------------

WORD = pdf.Converter("word", "Microsoft Word")
LIBRE = pdf.Converter("libreoffice", "LibreOffice", "/bin/soffice")


def test_find_converters_lists_word_then_libreoffice():
    soffice = "/Applications/LibreOffice.app/Contents/MacOS/soffice"
    exists = lambda p: p in ("/Applications/Microsoft Word.app", soffice)
    convs = pdf.find_converters("darwin", exists=exists, which=no_which)
    assert [c.kind for c in convs] == ["word", "libreoffice"]
    assert find_converter("darwin", exists=exists, which=no_which).kind == "word"


def fake_converters(monkeypatch, outcomes):
    """Make convert_to_pdf return a canned result per converter kind."""
    calls = []

    def fake(files, converter, on_progress=None, cancel_event=None):
        calls.append(converter.kind)
        return outcomes[converter.kind](files)

    monkeypatch.setattr(pdf, "convert_to_pdf", fake)
    return calls


def all_fail(files):
    return pdf.PdfResult(errors=[(f.name, "Word is View Only") for f in files])


def all_ok(files):
    return pdf.PdfResult(created=[f.with_suffix(".pdf") for f in files])


def test_falls_back_when_word_makes_nothing(tmp_path, monkeypatch):
    calls = fake_converters(monkeypatch, {"word": all_fail, "libreoffice": all_ok})
    result, used = pdf.convert_with_fallback(docx_files(tmp_path, "Ada", "Alan"), [WORD, LIBRE])
    assert calls == ["word", "libreoffice"]
    assert used == LIBRE
    assert len(result.created) == 2 and result.errors == []


def test_no_fallback_after_partial_success(tmp_path, monkeypatch):
    def some_ok(files):
        return pdf.PdfResult(created=[files[0].with_suffix(".pdf")], errors=[(files[1].name, "oops")])

    calls = fake_converters(monkeypatch, {"word": some_ok, "libreoffice": all_ok})
    result, used = pdf.convert_with_fallback(docx_files(tmp_path, "Ada", "Alan"), [WORD, LIBRE])
    assert calls == ["word"] and used == WORD


def test_no_fallback_after_cancel(tmp_path, monkeypatch):
    calls = fake_converters(monkeypatch, {"word": lambda files: pdf.PdfResult(), "libreoffice": all_ok})
    cancel = threading.Event()
    cancel.set()
    pdf.convert_with_fallback(docx_files(tmp_path, "Ada"), [WORD, LIBRE], cancel_event=cancel)
    assert calls == ["word"]


def test_all_converters_fail_reports_the_first_error(tmp_path, monkeypatch):
    fake_converters(monkeypatch, {"word": all_fail, "libreoffice": lambda files: pdf.PdfResult(errors=[("x", "libre broke")])})
    result, used = pdf.convert_with_fallback(docx_files(tmp_path, "Ada"), [WORD, LIBRE])
    assert used == WORD
    assert result.errors == [("Ada.docx", "Word is View Only")]


# --- LibreOffice driver, with soffice replaced by a fake script --------------

FAKE_SOFFICE = r"""
import sys, time
from pathlib import Path
args = sys.argv[1:]
outdir = Path(args[args.index("--outdir") + 1])
print("Fontconfig warning: noise", flush=True)
for f in [a for a in args if a.endswith(".docx")]:
    time.sleep(float(%r))
    if "Bad" in f:
        print(f"Error: source file could not be loaded", flush=True)
        continue
    pdf = outdir / (Path(f).stem + ".pdf")
    pdf.write_bytes(b"%%PDF-fake")
    print(f"convert {f} -> {pdf} using filter : writer_pdf_Export", flush=True)
"""


def fake_soffice(tmp_path, delay=0.0):
    script = tmp_path / "fake_soffice.py"
    script.write_text(FAKE_SOFFICE % delay)
    return [sys.executable, str(script)]


def test_libreoffice_reports_progress_per_file(tmp_path):
    files = docx_files(tmp_path, "Ada", "Bad", "Alan")
    progress = []
    result = pdf._convert_libreoffice(files, fake_soffice(tmp_path), lambda d, t, n: progress.append((d, n)), None)
    assert sorted(p.name for p in result.created) == ["Ada.pdf", "Alan.pdf"]
    assert [who for who, _ in result.errors] == ["Bad.docx"]
    assert progress == [(1, "Ada"), (2, "Alan"), (3, "")]


def test_libreoffice_cancel(tmp_path):
    files = docx_files(tmp_path, "Ada", "Alan")
    cancel = threading.Event()
    threading.Timer(0.3, cancel.set).start()
    start = time.monotonic()
    result = pdf._convert_libreoffice(files, fake_soffice(tmp_path, delay=30), None, cancel)
    assert time.monotonic() - start < 5
    assert result.created == []
