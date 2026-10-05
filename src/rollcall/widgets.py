"""Colors and small helpers shared by RollCall's tabs."""

import os
import subprocess
import sys
from pathlib import Path

import customtkinter as ctk

GREEN = ("#1a7f37", "#4ac26b")
ORANGE = ("#9a6700", "#d29922")
RED = ("#cf222e", "#ff7b72")
MUTED = ("gray40", "gray65")
TEXT = ("gray10", "gray90")
PAD = 16


def open_path(path: Path) -> None:
    """Open a file or folder the way double-clicking it would."""
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


class Step(ctk.CTkFrame):
    """A rounded card with a numbered heading."""

    def __init__(self, master, number: int, title: str):
        super().__init__(master)
        self.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            self, text=f"{number}   {title}", font=ctk.CTkFont(size=16, weight="bold"), anchor="w"
        ).grid(row=0, column=0, sticky="w", padx=PAD, pady=(12, 4))
