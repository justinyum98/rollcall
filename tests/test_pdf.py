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
