"""Bewerbungsunterlagen als PDF: Anschreiben, Lebenslauf, Projektseite, Deckblatt und Mappe.

Gesetzt wird mit HTML-Vorlagen und gedruckt mit dem Chromium, der ohnehin auf dem
Rechner liegt (Edge unter Windows). Fehlt er, faellt das Anschreiben auf das alte
fpdf2-Layout zurueck; Lebenslauf und Mappe gibt es dann nicht.
"""
from __future__ import annotations

import hashlib
import json
import re
import tempfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from . import drucker, pdf, render
from . import lebenslauf as lv
from .anschreiben import Anschreiben
from .config import Config
from .profil import Profil
from .stelle import Stelle

QUELLE_BA = "ba"


@dataclass
class Ergebnis:
    pfad: Path | None
    seiten: int = 0
    passt: bool = True
    schriftgrad: float | None = None
    engine: str = "fpdf"
    hinweise: list[str] = field(default_factory=list)


def ohne_mwd(titel: str) -> str:
    return re.sub(r"\s*\((?:m/w/d|w/m/d|m/f/d|d/m/w|m/w/x|w/m/x|all genders?)\)", "", titel or "", flags=re.I).strip()


def empfaenger(stelle: Stelle) -> list[str]:
    zeilen = [stelle.firma]
    if stelle.ansprechpartner:
        person = stelle.ansprechpartner
        zeilen.append("Herrn " + person[5:] if person.startswith("Herr ") else person)
    zeilen += stelle.firmen_adresse or [z for z in (f"{stelle.plz} {stelle.ort}".strip(),) if z]
    return zeilen[:6]


class Unterlagen:
    def __init__(self, cfg: Config, profil: Profil):
        self.cfg = cfg
        self.profil = profil
        self.wurzel = cfg.wurzel
        self.ablage = cfg.daten / "unterlagen"

    # ---------------------------------------------------------------- Grundlagen

    @property
    def browser(self) -> str | None:
        if self.cfg.dokumente.engine.lower() == "fpdf":
            return None
        return drucker.finde_browser(self.cfg.dokumente.browser)

    @property
    def html_aktiv(self) -> bool:
        return self.browser is not None

    @property
    def hat_lebenslauf(self) -> bool:
        return lv.pfad(self.wurzel).exists()

    def daten(self) -> dict:
        """Lebenslaufdaten; Kopfdaten fehlen dort, nimmt sie das Profil."""
        d = lv.lade(self.wurzel, self.profil)
        person = d["person"]
        for feld, wert in (("name", self.profil.name), ("strasse", self.profil.strasse),
                           ("plz_ort", self.profil.plz_ort), ("telefon", self.profil.telefon),
                           ("email", self.profil.email), ("web", self.profil.portfolio)):
            if not person.get(feld) and wert:
                person[feld] = wert
        return d

    def daten_fuer(self, eintrag: dict | None = None) -> dict:
        """Lebenslauf fuer eine bestimmte Bewerbung: mit zugeschnittenem Kurzprofil, falls gesetzt."""
        d = self.daten()
        if eintrag and eintrag.get("kurzprofil"):
            d["kurzprofil"] = eintrag["kurzprofil"]
        return d

    def _drucke(self, html: str, ziel: Path) -> drucker.Druck:
        browser = self.browser
        if not browser:
            raise drucker.DruckFehler("Kein Chromium-Browser gefunden")
        return drucker.drucke_bericht(html, ziel, browser, basis=self.wurzel)

    def anlagen_namen(self, anlagen: list[Path]) -> list[str]:
        namen = []
        if self.html_aktiv and self.hat_lebenslauf and self.cfg.dokumente.lebenslauf:
            namen.append("Lebenslauf")
            if self.cfg.dokumente.projektseite:
                namen.append("Projektübersicht")
        for a in self.anlagen_ohne_doppelten_lebenslauf(anlagen):
            name = a.stem.split("_")[0].replace("-", " ")
            if name not in namen:
                namen.append(name)
        return namen

    def anlagen_ohne_doppelten_lebenslauf(self, anlagen: list[Path]) -> list[Path]:
        """Wird der Lebenslauf erzeugt, faellt ein alter Lebenslauf aus den Anlagen weg."""
        if not (self.html_aktiv and self.hat_lebenslauf and self.cfg.dokumente.lebenslauf):
            return list(anlagen)
        return [a for a in anlagen if "lebenslauf" not in a.stem.lower() and "cv" != a.stem.lower()]

    # ---------------------------------------------------------------- Anschreiben

    def brief(self, stelle: Stelle, a: Anschreiben, anlagen: list[str], heute: date | None = None) -> dict:
        heute = heute or date.today()
        ort = self.profil.plz_ort.split(" ", 1)[-1] if self.profil.plz_ort else ""
        return {
            "empfaenger": empfaenger(stelle),
            "betreff": a.betreff.split(" - Ref.")[0].strip(),
            "referenz": f"Referenznummer {stelle.refnr}" if stelle.quelle == QUELLE_BA else "",
            "anrede": a.anrede,
            "absaetze": list(a.absaetze),
            "gruss": a.gruss,
            "ort_datum": f"{ort}, {render.datum_deutsch(heute)}" if ort else render.datum_deutsch(heute),
            "anlagen": anlagen,
            "unterschrift": str(self.cfg.unterschrift) if self.cfg.unterschrift else "",
        }

    def anschreiben_html(self, stelle: Stelle, a: Anschreiben, anlagen: list[str], modus: str = "druck") -> str:
        return render.anschreiben(self.daten(), self.wurzel, self.brief(stelle, a, anlagen), modus)

    def anschreiben(self, ziel: Path, stelle: Stelle, a: Anschreiben, anlagen: list[str]) -> Ergebnis:
        hinweis = ""
        if self.html_aktiv:
            try:
                druck = self._drucke(self.anschreiben_html(stelle, a, anlagen), ziel)
                return Ergebnis(druck.pfad, druck.seiten, not druck.ueberlauf, druck.schriftgrad, "chromium")
            except drucker.DruckFehler as fehler:
                hinweis = f"HTML-Druck fehlgeschlagen, einfaches Layout genutzt: {fehler}"
        passt = pdf.anschreiben_pdf(ziel, self.profil, stelle, a, anlagen)
        return Ergebnis(ziel, 1, passt, None, "fpdf", [hinweis] if hinweis else [])

    # ---------------------------------------------------------------- Lebenslauf und Projekte

    def _schluessel(self, art: str, d: dict) -> str:
        roh = json.dumps(d, sort_keys=True, ensure_ascii=False, default=str)
        bilder = [d["person"].get("foto", "")] + [p.get("bild", "") for p in d["projekte"]]
        for b in bilder:
            datei = self.wurzel / b if b and not b.startswith(("data:", "http")) else None
            if datei and datei.exists():
                roh += f"{b}:{datei.stat().st_mtime_ns}"
        quellen = sorted((Path(render.__file__).parent / "vorlagen").glob("*"))
        roh += "".join(f"{q.name}:{q.stat().st_mtime_ns}" for q in quellen)
        return hashlib.sha1(f"{art}|{date.today()}|{roh}".encode()).hexdigest()[:12]

    def _zwischengespeichert(self, art: str, d: dict, html_fn, ziel: Path | None) -> Ergebnis:
        name = re.sub(r"[^\w-]+", "_", self.profil.name).strip("_") or "Bewerbung"
        schluessel = self._schluessel(art, d)
        cache = self.ablage / f"{art}_{name}_{schluessel}.pdf"
        if not cache.exists():
            for alt in self.ablage.glob(f"{art}_{name}_*.pdf"):
                alt.unlink(missing_ok=True)
            druck = self._drucke(html_fn(), cache)
            meta = {"seiten": druck.seiten, "ueberlauf": druck.ueberlauf}
            cache.with_suffix(".json").write_text(json.dumps(meta), encoding="utf-8")
        meta = json.loads(cache.with_suffix(".json").read_text(encoding="utf-8")) \
            if cache.with_suffix(".json").exists() else {"seiten": drucker.seiten(cache), "ueberlauf": False}
        pfad = cache
        if ziel:
            ziel.parent.mkdir(parents=True, exist_ok=True)
            ziel.write_bytes(cache.read_bytes())
            pfad = ziel
        hinweise = ["Ein Block ist laenger als eine Seite und wurde abgeschnitten"] if meta.get("ueberlauf") else []
        return Ergebnis(pfad, int(meta.get("seiten") or 0), not meta.get("ueberlauf"), None, "chromium", hinweise)

    def lebenslauf(self, ziel: Path | None = None, d: dict | None = None) -> Ergebnis:
        d = d or self.daten()
        return self._zwischengespeichert("Lebenslauf", d, lambda: render.lebenslauf(d, self.wurzel), ziel)

    def lebenslauf_direkt(self, ziel: Path, d: dict) -> Ergebnis:
        """Ohne Zwischenspeicher - fuer einen auf eine Stelle zugeschnittenen Lebenslauf."""
        druck = self._drucke(render.lebenslauf(d, self.wurzel), ziel)
        hinweise = ["Ein Block ist laenger als eine Seite und wurde abgeschnitten"] if druck.ueberlauf else []
        return Ergebnis(druck.pfad, druck.seiten, not druck.ueberlauf, None, "chromium", hinweise)

    def projektseite(self, ziel: Path | None = None, d: dict | None = None) -> Ergebnis:
        d = d or self.daten()
        return self._zwischengespeichert("Projekte", d, lambda: render.portfolio(d, self.wurzel), ziel)

    # ---------------------------------------------------------------- Mappe

    def mappe(self, ziel: Path, stelle: Stelle, a: Anschreiben, anlagen: list[Path],
              anschreiben_pdf: Path | None = None, d: dict | None = None,
              lebenslauf_pdf: Path | None = None) -> Ergebnis:
        """Deckblatt, Anschreiben, Lebenslauf, Projekte und PDF-Anlagen in einer Datei."""
        if not self.html_aktiv:
            raise drucker.DruckFehler("Die Mappe braucht Edge, Chrome oder Chromium")
        d = d or self.daten()
        teile: list[tuple[str, Path]] = []
        hinweise: list[str] = []
        anlagen = self.anlagen_ohne_doppelten_lebenslauf(anlagen)
        pdf_anlagen = [x for x in anlagen if x.suffix.lower() == ".pdf" and x.exists()]
        with tempfile.TemporaryDirectory(prefix="mappe_") as tmp:
            tmp_pfad = Path(tmp)
            if anschreiben_pdf and anschreiben_pdf.exists():
                teile.append(("Anschreiben", anschreiben_pdf))
            else:
                e = self.anschreiben(tmp_pfad / "anschreiben.pdf", stelle, a, self.anlagen_namen(anlagen))
                teile.append(("Anschreiben", e.pfad))
                hinweise += e.hinweise
            if lebenslauf_pdf and lebenslauf_pdf.exists():
                teile.append(("Lebenslauf", lebenslauf_pdf))
            elif self.cfg.dokumente.lebenslauf:
                e = self.lebenslauf(None, d)
                teile.append(("Lebenslauf", e.pfad))
                hinweise += e.hinweise
            if self.cfg.dokumente.projektseite and d["projekte"]:
                teile.append(("Projekte", self.projektseite(None, d).pfad))
            for x in pdf_anlagen:
                teile.append((x.stem.split("_")[0].replace("-", " "), x))

            if self.cfg.dokumente.deckblatt:
                inhalt, seite = [], 2
                for name, pfad in teile:
                    inhalt.append((name, seite))
                    seite += drucker.seiten(pfad) or 1
                angaben = {
                    "position": ohne_mwd(stelle.titel),
                    "art": "Ausbildung" if stelle.art == "ausbildung" else "",
                    "firma": stelle.firma,
                    "inhalt": inhalt,
                }
                deck = self._drucke(render.deckblatt(d, self.wurzel, angaben), tmp_pfad / "deckblatt.pdf")
                teile.insert(0, ("Deckblatt", deck.pfad))
            drucker.zusammenfuegen([p for _, p in teile], ziel)
        return Ergebnis(ziel, drucker.seiten(ziel), True, None, "chromium", hinweise)

    # ---------------------------------------------------------------- Mail-Anhaenge

    def anhaenge(self, eintrag: dict, anlagen: list[Path]) -> list[tuple[Path, str]]:
        """(Datei, Name im Mailprogramm) in der Reihenfolge, in der sie verschickt werden."""
        name = re.sub(r"[^\w-]+", "_", self.profil.name).strip("_")
        firma = re.sub(r"[^\w-]+", "_", eintrag["stelle"].get("firma", "")).strip("_")[:40]
        if eintrag.get("mappe") and Path(eintrag["mappe"]).exists():
            liste = [(Path(eintrag["mappe"]), f"Bewerbung_{name}_{firma}.pdf")]
            liste += [(x, x.name) for x in self.anlagen_ohne_doppelten_lebenslauf(anlagen) if x.suffix.lower() != ".pdf"]
            return liste
        liste = [(Path(eintrag["pdf"]), f"Anschreiben_{name}_{firma}.pdf")]
        if self.html_aktiv and self.hat_lebenslauf and self.cfg.dokumente.lebenslauf:
            eigen = Path(eintrag["lebenslauf"]) if eintrag.get("lebenslauf") else None
            pfad = eigen if eigen and eigen.exists() else self.lebenslauf().pfad
            liste.append((pfad, f"Lebenslauf_{name}.pdf"))
            if self.cfg.dokumente.projektseite and self.daten()["projekte"]:
                liste.append((self.projektseite().pfad, f"Projekte_{name}.pdf"))
        liste += [(x, x.name) for x in self.anlagen_ohne_doppelten_lebenslauf(anlagen)]
        return liste
