"""Turn the generated .docx files into PDFs using Word or LibreOffice, if installed.

We drive Word ourselves instead of using docx2pdf: docx2pdf always quits Word
when it finishes (closing a teacher's unsaved work) and calls sys.exit() on
errors. Here Word is only quit if RollCall was the one that started it.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

ProgressCallback = Callable[[int, int, str], None]

_MAC_WORD = [Path("/Applications/Microsoft Word.app"), Path.home() / "Applications/Microsoft Word.app"]
_SOFFICE_CANDIDATES = {
    "darwin": ["/Applications/LibreOffice.app/Contents/MacOS/soffice"],
    "win32": [
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    ],
}

# Arguments are pairs of (input .docx, output .pdf). One JSON line per file is
# written to stderr (where osascript sends console.log) so we can show progress.
_MAC_WORD_SCRIPT = """
function run(argv) {
  const word = Application("Microsoft Word");
  const wasRunning = word.running();
  for (let i = 0; i < argv.length; i += 2) {
    let doc = null;
    try {
      word.open(Path(argv[i]));
      doc = word.activeDocument;
      doc.saveAs({ fileName: argv[i + 1], fileFormat: "format PDF" });
      console.log(JSON.stringify({ input: argv[i], ok: true }));
    } catch (e) {
      console.log(JSON.stringify({ input: argv[i], ok: false, error: e.toString() }));
    }
    try { if (doc) doc.close({ saving: "no" }); } catch (e) {}
  }
  if (!wasRunning) word.quit();
}
"""


@dataclass(frozen=True)
class Converter:
    kind: str  # "word" or "libreoffice"
    label: str  # shown to the teacher
    path: str | None = None  # soffice executable, for LibreOffice


@dataclass
class PdfResult:
    created: list[Path] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)  # (file name, message)


def find_converter(platform: str = sys.platform, exists=os.path.exists, which=shutil.which, word_registered=None) -> Converter | None:
    if platform == "darwin" and any(exists(str(p)) for p in _MAC_WORD):
        return Converter("word", "Microsoft Word")
    if platform == "win32" and (word_registered or _word_in_registry)():
        return Converter("word", "Microsoft Word")

    soffice = which("soffice") or which("libreoffice")
    soffice = soffice or next((p for p in _SOFFICE_CANDIDATES.get(platform, []) if exists(p)), None)
    if soffice:
        return Converter("libreoffice", "LibreOffice", soffice)
    return None


def _word_in_registry() -> bool:
    try:
        import winreg

        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Word.Application\CurVer"))
        return True
    except OSError:
        return False


def convert_to_pdf(
    files: list[Path],
    converter: Converter,
    on_progress: ProgressCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> PdfResult:
    """Write a .pdf next to each .docx. One failed file doesn't stop the others."""
    if not files:
        return PdfResult()
    if converter.kind == "libreoffice":
        return _convert_libreoffice(files, converter.path, on_progress)
    if sys.platform == "darwin":
        return _convert_word_mac(files, on_progress, cancel_event)
    return _convert_word_windows(files, on_progress, cancel_event)


def _convert_word_mac(files, on_progress, cancel_event, command=None) -> PdfResult:
    args = [str(arg) for f in files for arg in (f.resolve(), f.resolve().with_suffix(".pdf"))]
    command = command or ["/usr/bin/osascript", "-l", "JavaScript", "-e", _MAC_WORD_SCRIPT]
    proc = subprocess.Popen([*command, *args], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
    if cancel_event is not None:
        # If Word is stuck behind a dialog, no output arrives for minutes, so
        # Cancel has to stop the process directly rather than between lines.
        threading.Thread(target=_terminate_on_cancel, args=(proc, cancel_event), daemon=True).start()

    result, done, other_output = PdfResult(), 0, []
    for line in proc.stderr:
        try:
            msg = json.loads(line)
        except ValueError:
            other_output.append(line.strip())
            continue
        done += 1
        _record(result, Path(msg["input"]), msg["ok"], friendly_word_error(msg.get("error")))
        if on_progress:
            on_progress(done, len(files), Path(msg["input"]).stem)
    proc.wait()

    cancelled = cancel_event is not None and cancel_event.is_set()
    if done == 0 and proc.returncode != 0 and not cancelled:
        # osascript failed before converting anything.
        result.errors.append(("All files", friendly_word_error(" ".join(other_output) or f"exit code {proc.returncode}")))
    return result


def _terminate_on_cancel(proc: subprocess.Popen, cancel_event: threading.Event) -> None:
    while proc.poll() is None:
        if cancel_event.wait(0.2):
            proc.terminate()
            return


def friendly_word_error(raw: str | None) -> str | None:
    """Translate Word/AppleScript errors into something a teacher can act on."""
    if not raw:
        return raw
    if "-1743" in raw or "Not authorized" in raw:
        return (
            "macOS blocked RollCall from using Microsoft Word. Open System Settings > "
            "Privacy & Security > Automation and allow RollCall to control Microsoft Word."
        )
    if "Message not understood" in raw or "-1708" in raw:
        return (
            "Microsoft Word couldn't save a PDF. This usually means Word is in \"View Only\" "
            "mode because this computer's Office account can't edit documents. Sign in to "
            "Word with an account that can edit, or install LibreOffice (free) and try again."
        )
    if "timed out" in raw or "-1712" in raw:
        return (
            "Microsoft Word stopped responding. It may be showing a message. Switch to Word, "
            "close any messages, and try again."
        )
    return f"Microsoft Word reported an error: {raw}"


def _convert_word_windows(files, on_progress, cancel_event) -> PdfResult:
    import pythoncom
    import win32com.client

    wd_format_pdf = 17
    result = PdfResult()
    # Required before using Word from any thread other than the main one.
    pythoncom.CoInitialize()
    try:
        # DispatchEx starts a separate, hidden Word, so quitting it can't
        # close documents the teacher already has open.
        word = win32com.client.DispatchEx("Word.Application")
        word.Visible = False
        word.DisplayAlerts = 0
        try:
            for i, f in enumerate(files, start=1):
                if cancel_event is not None and cancel_event.is_set():
                    break
                try:
                    doc = word.Documents.Open(str(f.resolve()), ReadOnly=True, AddToRecentFiles=False)
                    try:
                        doc.SaveAs(str(f.resolve().with_suffix(".pdf")), FileFormat=wd_format_pdf)
                    finally:
                        doc.Close(0)
                    _record(result, f, True)
                except Exception as e:
                    _record(result, f, False, str(e))
                if on_progress:
                    on_progress(i, len(files), f.stem)
        finally:
            word.Quit()
    finally:
        pythoncom.CoUninitialize()
    return result


def _convert_libreoffice(files, soffice, on_progress) -> PdfResult:
    result = PdfResult()
    # A private profile lets this work even if the teacher has LibreOffice
    # open; otherwise the headless run silently does nothing.
    with tempfile.TemporaryDirectory() as profile:
        by_folder: dict[Path, list[Path]] = {}
        for f in files:
            by_folder.setdefault(f.parent, []).append(f)
        for folder, group in by_folder.items():
            proc = subprocess.run(
                [soffice, f"-env:UserInstallation={Path(profile).as_uri()}", "--headless",
                 "--convert-to", "pdf", "--outdir", str(folder), *map(str, group)],
                capture_output=True,
                text=True,
                **_no_console_window(),
            )
            for f in group:
                ok = f.with_suffix(".pdf").exists()
                _record(result, f, ok, None if ok else (proc.stderr.strip() or "LibreOffice didn't create the PDF"))
    if on_progress:
        on_progress(len(files), len(files), "")
    return result


def _record(result: PdfResult, docx: Path, ok: bool, error: str | None = None) -> None:
    if ok:
        result.created.append(docx.with_suffix(".pdf"))
    else:
        result.errors.append((docx.name, error or "Unknown error"))


def _no_console_window() -> dict:
    # Without this, a black console window flashes up on Windows.
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {}
