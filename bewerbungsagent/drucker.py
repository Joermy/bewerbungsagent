"""HTML -> PDF ueber einen vorhandenen Chromium-Browser (Edge, Chrome, Chromium).

Edge liegt auf jedem Windows 10/11 bei, es muss also nichts installiert werden.
Reihenfolge: dokumente.browser in config.yaml, Umgebungsvariable
BEWERBUNGSAGENT_BROWSER, bekannte Installationspfade, PATH, Playwright.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


class DruckFehler(RuntimeError):
    pass


@dataclass
class Druck:
    pfad: Path
    seiten: int = 1
    ueberlauf: bool = False
    schriftgrad: float | None = None


def _kandidaten() -> list[str]:
    pfade: list[str] = []
    if os.environ.get("BEWERBUNGSAGENT_BROWSER"):
        pfade.append(os.environ["BEWERBUNGSAGENT_BROWSER"])
    if os.name == "nt":
        for basis in (os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                      os.environ.get("ProgramFiles", r"C:\Program Files"),
                      os.environ.get("LOCALAPPDATA", "")):
            if not basis:
                continue
            pfade += [str(Path(basis) / "Microsoft" / "Edge" / "Application" / "msedge.exe"),
                      str(Path(basis) / "Google" / "Chrome" / "Application" / "chrome.exe"),
                      str(Path(basis) / "Chromium" / "Application" / "chrome.exe")]
    elif sys.platform == "darwin":
        pfade += ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                  "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                  "/Applications/Chromium.app/Contents/MacOS/Chromium"]
    for name in ("msedge", "microsoft-edge", "google-chrome", "google-chrome-stable", "chrome", "chromium",
                 "chromium-browser"):
        gefunden = shutil.which(name)
        if gefunden:
            pfade.append(gefunden)
    try:  # Playwright, falls installiert (Entwicklung, Tests)
        from playwright.sync_api import sync_playwright  # noqa: WPS433

        with sync_playwright() as p:
            pfade.append(p.chromium.executable_path)
    except Exception:
        pass
    return pfade


def finde_browser(eigener: str = "") -> str | None:
    if eigener and Path(eigener).exists():
        return eigener
    return _erster_kandidat()


@lru_cache(maxsize=1)
def _erster_kandidat() -> str | None:
    for pfad in _kandidaten():
        if pfad and Path(pfad).exists():
            return pfad
    return None


_MARKE = re.compile(r"\s*\[\[(.*?)\]\]\s*$")


def _bericht(ziel: Path) -> Druck:
    """Liest die Statusmarke aus dem PDF-Titel (gesetzt von seiten.js) und entfernt sie wieder."""
    druck = Druck(ziel, seiten(ziel) or 1)
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError:
        return druck
    leser = PdfReader(str(ziel))
    titel = str((leser.metadata or {}).get("/Title") or "")
    treffer = _MARKE.search(titel)
    if not treffer:
        return druck
    werte = dict(t.split("=", 1) for t in treffer.group(1).split(";") if "=" in t)
    druck.ueberlauf = werte.get("ueberlauf") == "1"
    try:
        druck.schriftgrad = float(werte["grad"]) if werte.get("grad") else None
    except ValueError:
        pass
    schreiber = PdfWriter(clone_from=leser)
    schreiber.add_metadata({"/Title": _MARKE.sub("", titel), "/Producer": "Bewerbungsagent", "/Creator": "Bewerbungsagent"})
    with open(ziel, "wb") as f:
        schreiber.write(f)
    return druck


def drucke(html: str, ziel: Path, browser: str = "", basis: Path | None = None, timeout_s: int = 90) -> Path:
    return drucke_bericht(html, ziel, browser, basis, timeout_s).pfad


def drucke_bericht(html: str, ziel: Path, browser: str = "", basis: Path | None = None, timeout_s: int = 90) -> Druck:
    """Schreibt html in eine Temp-Datei (neben `basis`, damit relative Pfade gelten) und druckt sie."""
    programm = finde_browser(browser)
    if not programm:
        raise DruckFehler("Kein Chromium-Browser gefunden (Edge, Chrome oder Chromium). "
                          "Pfad unter dokumente.browser in config.yaml eintragen.")
    ziel = Path(ziel).resolve()
    ziel.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bewerbung_") as tmp:
        quelle = Path(basis or tmp) / f".druck_{os.getpid()}_{ziel.stem}.html"
        quelle.write_text(html, encoding="utf-8")
        befehl = [programm, "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
                  "--disable-extensions", "--hide-scrollbars", "--no-pdf-header-footer",
                  "--run-all-compositor-stages-before-draw", "--virtual-time-budget=6000",
                  f"--user-data-dir={tmp}", f"--print-to-pdf={ziel}", quelle.resolve().as_uri()]
        if os.name != "nt" and hasattr(os, "geteuid") and os.geteuid() == 0:
            befehl.insert(1, "--no-sandbox")
        try:
            ziel.unlink(missing_ok=True)
            lauf = subprocess.run(befehl, capture_output=True, text=True, timeout=timeout_s)
        except subprocess.TimeoutExpired as fehler:
            raise DruckFehler(f"Browser antwortet nicht ({timeout_s} s)") from fehler
        finally:
            if basis:
                quelle.unlink(missing_ok=True)
        if not ziel.exists() or ziel.stat().st_size < 500:
            raise DruckFehler(f"PDF nicht erzeugt: {(lauf.stderr or lauf.stdout).strip()[-300:]}")
    return _bericht(ziel)


def seiten(pdf: Path) -> int:
    try:
        from pypdf import PdfReader

        return len(PdfReader(str(pdf)).pages)
    except Exception:
        return 0


def zusammenfuegen(teile: list[Path], ziel: Path) -> Path:
    from pypdf import PdfWriter

    schreiber = PdfWriter()
    for teil in teile:
        if Path(teil).exists():
            schreiber.append(str(teil))
    ziel.parent.mkdir(parents=True, exist_ok=True)
    with open(ziel, "wb") as f:
        schreiber.write(f)
    return ziel
