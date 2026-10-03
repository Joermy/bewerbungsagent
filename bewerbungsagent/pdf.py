from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from fpdf import FPDF

from .anschreiben import Anschreiben
from .mail import kanal_text
from .profil import Profil
from .stelle import Stelle

MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli",
          "August", "September", "Oktober", "November", "Dezember"]

TINTE = (17, 24, 39)
GRAU = (107, 114, 128)
HELL = (209, 213, 219)
AKZENT = (37, 99, 235)


@dataclass
class Schrift:
    familie: str
    regular: str | None
    medium: str | None
    fett: str | None


def _schriftordner() -> list[Path]:
    ordner = [Path(__file__).parent / "schriften"]
    if os.name == "nt":
        ordner.append(Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts")
        ordner.append(Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Windows" / "Fonts")
    ordner += [Path("/usr/share/fonts/truetype/inter"), Path("/usr/share/fonts/truetype/dejavu"),
               Path("/Library/Fonts"), Path.home() / "Library" / "Fonts"]
    return ordner


KANDIDATEN = [
    ("Inter", "Inter-Regular.ttf", "Inter-Medium.ttf", "Inter-SemiBold.ttf"),
    ("Segoe", "segoeui.ttf", "seguisb.ttf", "segoeuib.ttf"),
    ("Calibri", "calibri.ttf", "calibri.ttf", "calibrib.ttf"),
    ("DejaVu", "DejaVuSans.ttf", "DejaVuSans.ttf", "DejaVuSans-Bold.ttf"),
]


def finde_schrift() -> Schrift:
    for familie, *dateien in KANDIDATEN:
        pfade = []
        for datei in dateien:
            treffer = next((o / datei for o in _schriftordner() if (o / datei).exists()), None)
            pfade.append(str(treffer) if treffer else None)
        if pfade[0] and pfade[2]:
            return Schrift(familie, pfade[0], pfade[1] or pfade[0], pfade[2])
    return Schrift("Helvetica", None, None, None)


def datum_deutsch(tag: date) -> str:
    return f"{tag.day}. {MONATE[tag.month - 1]} {tag.year}"


class _Dokument(FPDF):
    def __init__(self, schrift: Schrift):
        super().__init__(format="A4", unit="mm")
        self.set_auto_page_break(False)
        self.set_margins(25, 20, 20)
        self.s = schrift
        self.c_margin = 0
        if schrift.regular:
            self.add_font(schrift.familie, "", schrift.regular)
            self.add_font(schrift.familie, "B", schrift.fett)
            self.add_font(schrift.familie + "M", "", schrift.medium)

    def f(self, groesse: float, stil: str = "", farbe=TINTE):
        familie = self.s.familie
        if stil == "M":
            familie, stil = (familie + "M", "") if self.s.regular else (familie, "")
        self.set_font(familie, stil, groesse)
        self.set_text_color(*farbe)

    def text_sicher(self, text: str) -> str:
        if self.s.regular:
            return text
        ersatz = {"–": "-", "—": "-", "„": '"', "“": '"', "”": '"', "‚": "'", "‘": "'", "’": "'", "…": "...", "€": "EUR", "·": "|"}
        for alt, neu in ersatz.items():
            text = text.replace(alt, neu)
        return text.encode("latin-1", "replace").decode("latin-1")

    def kopf(self, profil: Profil):
        self.set_xy(25, 18)
        self.f(21, "B")
        self.cell(0, 9, self.text_sicher(profil.name))
        web = re.sub(r"^https?://|/$", "", profil.portfolio)
        kontakt = "  ·  ".join(z for z in (f"{profil.strasse}, {profil.plz_ort}", profil.telefon, profil.email, web)
                               if z.strip(", "))
        self.set_xy(25, 28)
        self.f(8.5, "", GRAU)
        self.cell(0, 5, self.text_sicher(kontakt))
        self.set_fill_color(*AKZENT)
        self.rect(25, 36, 14, 0.9, style="F")


def _anschreiben_seite(pdf: _Dokument, profil: Profil, stelle: Stelle, a: Anschreiben,
                       anlagen: list[str], heute: date, groesse: float) -> bool:
    pdf.add_page()
    pdf.kopf(profil)

    pdf.set_xy(25, 50)
    pdf.f(7, "", GRAU)
    pdf.cell(0, 4, pdf.text_sicher(f"{profil.name} · {profil.strasse} · {profil.plz_ort}"))
    zeilen = [stelle.firma]
    if stelle.ansprechpartner:
        person = stelle.ansprechpartner
        zeilen.append("Herrn " + person[5:] if person.startswith("Herr ") else person)
    zeilen += stelle.firmen_adresse or [z for z in (f"{stelle.plz} {stelle.ort}".strip(),) if z]
    pdf.set_xy(25, 56)
    pdf.f(10.5)
    for z in zeilen[:6]:
        pdf.set_x(25)
        pdf.cell(85, 5.2, pdf.text_sicher(z), new_x="LMARGIN", new_y="NEXT")

    pdf.set_xy(25, 92)
    pdf.f(9.5, "", GRAU)
    ort = profil.plz_ort.split(" ", 1)[-1]
    pdf.cell(0, 5, pdf.text_sicher(f"{ort}, {datum_deutsch(heute)}"), align="R")
    pdf.set_xy(25, 101)
    pdf.f(12, "B")
    pdf.multi_cell(0, 6, pdf.text_sicher(a.betreff.split(" - Ref.")[0]), align="L")
    pdf.set_x(25)
    pdf.f(8.5, "", GRAU)
    if stelle.quelle != "manuell":
        pdf.cell(0, 5, pdf.text_sicher(f"Referenznummer {stelle.refnr}"), new_x="LMARGIN", new_y="NEXT")
    else:
        pdf.ln(5)

    zeile = groesse * 0.5
    pdf.set_y(pdf.get_y() + 6)
    pdf.f(groesse)
    for absatz in [a.anrede, *a.absaetze]:
        pdf.set_x(25)
        pdf.multi_cell(0, zeile, pdf.text_sicher(absatz), align="L")
        pdf.set_y(pdf.get_y() + zeile * 0.75)
    pdf.set_x(25)
    pdf.multi_cell(0, zeile, pdf.text_sicher(a.gruss), align="L")
    unterschrift = Path(profil_unterschrift_pfad(profil)) if profil_unterschrift_pfad(profil) else None
    if unterschrift and unterschrift.exists():
        pdf.image(str(unterschrift), x=25, y=pdf.get_y() + 1, h=12)
        pdf.set_y(pdf.get_y() + 14)
    else:
        pdf.set_y(pdf.get_y() + 8)
    pdf.set_x(25)
    pdf.f(groesse, "M")
    pdf.cell(0, zeile, pdf.text_sicher(profil.name), new_x="LMARGIN", new_y="NEXT")

    if anlagen:
        pdf.set_y(pdf.get_y() + 6)
        pdf.set_x(25)
        pdf.f(8.5, "", GRAU)
        pdf.multi_cell(0, 4.5, pdf.text_sicher("Anlagen: " + ", ".join(anlagen)), align="L")

    passt = pdf.get_y() < 280
    pdf.set_draw_color(*HELL)
    pdf.set_line_width(0.2)
    pdf.line(25, 285, 190, 285)
    pdf.set_xy(25, 286.5)
    pdf.f(7, "", GRAU)
    pdf.cell(0, 4, pdf.text_sicher(f"{profil.name}  ·  {profil.email}"))
    return passt


_UNTERSCHRIFT: dict[str, str] = {}


def profil_unterschrift_pfad(profil: Profil) -> str:
    return _UNTERSCHRIFT.get(profil.email, "")


def setze_unterschrift(profil: Profil, pfad: Path | None):
    if pfad and pfad.exists():
        _UNTERSCHRIFT[profil.email] = str(pfad)


def anschreiben_pdf(ziel: Path, profil: Profil, stelle: Stelle, a: Anschreiben,
                    anlagen: list[str], heute: date | None = None) -> bool:
    heute = heute or date.today()
    schrift = finde_schrift()
    for groesse in (10.5, 10.0, 9.5):
        pdf = _Dokument(schrift)
        pdf.set_title(a.betreff)
        pdf.set_author(profil.name)
        passt = _anschreiben_seite(pdf, profil, stelle, a, anlagen, heute, groesse)
        if passt:
            break
    ziel.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(ziel))
    return passt


def nachweis_pdf(ziel: Path, profil: Profil, eintraege: list[dict], heute: date | None = None) -> Path:
    heute = heute or date.today()
    pdf = _Dokument(finde_schrift())
    pdf.set_auto_page_break(True, margin=20)
    pdf.set_title("Bewerbungsnachweis")
    pdf.set_author(profil.name)
    pdf.add_page()
    pdf.kopf(profil)

    pdf.set_xy(25, 46)
    pdf.f(15, "B")
    pdf.cell(0, 8, "Bewerbungsnachweis", new_x="LMARGIN", new_y="NEXT")
    pdf.f(9, "", GRAU)
    pdf.cell(0, 5, pdf.text_sicher(f"{len(eintraege)} Bewerbungen · Stand {datum_deutsch(heute)}"),
             new_x="LMARGIN", new_y="NEXT")
    pdf.set_y(pdf.get_y() + 6)

    spalten = [(22, "Datum"), (50, "Arbeitgeber"), (56, "Stelle"), (37, "Kontakt")]
    pdf.f(8, "M", GRAU)
    pdf.set_x(25)
    for breite, titel in spalten:
        pdf.cell(breite, 6, titel)
    pdf.ln(6)
    pdf.set_draw_color(*HELL)
    pdf.set_line_width(0.2)

    def zelle(x: float, y: float, breite: float, text: str, groesse: float, farbe=TINTE) -> float:
        pdf.set_xy(x, y)
        pdf.f(groesse, "", farbe)
        pdf.multi_cell(breite - 3, 4.4, pdf.text_sicher(text), align="L")
        return pdf.get_y()

    for e in eintraege:
        y = pdf.get_y()
        if y > 265:
            pdf.add_page()
            y = 20
        pdf.line(25, y, 190, y)
        y += 2.5
        roh = e.get("datum", "")
        datum = f"{roh[8:10]}.{roh[5:7]}.{roh[:4]}" if len(roh) >= 10 else roh
        titel = re.sub(r"\s*\((?:m/w/d|w/m/d|m/f/d|d/m/w)\)", "", e.get("titel", ""), flags=re.I)
        unten = max(
            zelle(25, y, 22, datum, 9),
            zelle(47, y, 50, f"{e.get('firma', '')}\n{e.get('ort', '')}", 9),
            zelle(97, y, 56, titel + ("" if e.get("quelle") == "manuell" else f"\nRef. {e.get('refnr', '')}"), 9),
            zelle(153, y, 40, kanal_text(e.get("kanal"), e.get("email", "")).replace(" an ", " an\n"), 7.5, GRAU),
        )
        pdf.set_y(unten + 2.5)
    pdf.line(25, pdf.get_y(), 190, pdf.get_y())
    ziel.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(ziel))
    return ziel
