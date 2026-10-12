"""HTML-Vorlagen und PDF-Druck ueber Chromium. Ohne Browser werden die Drucktests uebersprungen."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from bewerbungsagent import drucker, render
from bewerbungsagent import lebenslauf as lv
from bewerbungsagent.anschreiben import Anschreiben
from bewerbungsagent.dienst import Dienst
from bewerbungsagent.stelle import Stelle
from bewerbungsagent.unterlagen import Unterlagen

from conftest import FalscheQuelle, FalschesModell, anzeige, baue_config

WURZEL = Path(__file__).resolve().parent.parent
BEISPIEL = yaml.safe_load((WURZEL / "beispiel" / "lebenslauf.yaml").read_text(encoding="utf-8"))
BROWSER = drucker.finde_browser()
braucht_browser = pytest.mark.skipif(not BROWSER, reason="kein Chromium/Edge/Chrome gefunden")


@pytest.fixture
def mit_lebenslauf(projekt):
    shutil.copytree(WURZEL / "beispiel", projekt / "beispiel")
    shutil.copy(WURZEL / "beispiel" / "lebenslauf.yaml", projekt / "profil" / "lebenslauf.yaml")
    return projekt


def _stelle():
    return Stelle(quelle="ba", refnr="10000-1-S", titel="Fachinformatiker (m/w/d)", firma="Muster GmbH",
                  ansprechpartner="Frau Petra Klein", firmen_adresse=["Hafenstraße 4", "12345 Musterstadt"])


def test_vorlagen_rendern_ohne_browser():
    d = lv.normalisiere(BEISPIEL)
    for vorlage in lv.VORLAGEN:
        d["design"]["vorlage"] = vorlage
        html = render.lebenslauf(d, WURZEL)
        assert "Max Beispiel" in html and "<svg" in html and 'data-modus="druck"' in html
        assert "@font-face" in html and "data:font/woff2;base64," in html   # Schriften eingebettet
    vorschau = render.lebenslauf(d, WURZEL, "vorschau")
    assert "/statisch/schriften/inter.woff2" in vorschau
    brief = {"empfaenger": ["Muster GmbH"], "betreff": "Bewerbung", "referenz": "", "anrede": "Hallo,",
             "absaetze": ["Eins."], "gruss": "Gruß", "ort_datum": "Ort", "anlagen": ["Lebenslauf"], "unterschrift": ""}
    assert "Anlagen" in render.anschreiben(d, WURZEL, brief)
    assert "Inhalt" in render.deckblatt(d, WURZEL, {"position": "Koch", "firma": "F", "inhalt": [("Anschreiben", 2)]})
    assert "Projekte" in render.portfolio(d, WURZEL)


def test_html_wird_escaped():
    d = lv.normalisiere(BEISPIEL)
    d["kurzprofil"] = "<script>alert(1)</script>"
    html = render.lebenslauf(d, WURZEL)
    assert "<script>alert(1)" not in html and "&lt;script&gt;" in html


@braucht_browser
def test_lebenslauf_pdf_mehrseitig_und_zwischengespeichert(mit_lebenslauf):
    d = Dienst(baue_config(mit_lebenslauf, engine="auto"), quelle=FalscheQuelle([]), llm=FalschesModell())
    u = d.unterlagen
    assert u.html_aktiv and u.hat_lebenslauf
    erst = u.lebenslauf()
    assert erst.seiten == 2 and erst.passt and erst.pfad.read_bytes().startswith(b"%PDF")
    zeit = erst.pfad.stat().st_mtime_ns
    assert u.lebenslauf().pfad.stat().st_mtime_ns == zeit       # aus dem Zwischenspeicher
    from pypdf import PdfReader
    meta = PdfReader(str(erst.pfad)).metadata
    assert "[[" not in meta["/Title"] and meta["/Title"].startswith("Lebenslauf")


@braucht_browser
def test_anschreiben_meldet_ueberlauf(mit_lebenslauf):
    d = Dienst(baue_config(mit_lebenslauf, engine="auto"), quelle=FalscheQuelle([]), llm=FalschesModell())
    u = d.unterlagen
    kurz = Anschreiben("Bewerbung als Fachinformatiker", "Sehr geehrte Frau Klein,", ["Ein Absatz. " * 30] * 3)
    erg = u.anschreiben(mit_lebenslauf / "a.pdf", _stelle(), kurz, ["Lebenslauf"])
    assert erg.engine == "chromium" and erg.passt and erg.seiten == 1
    lang = Anschreiben("Betreff", "Hallo,", ["Sehr langer Absatz mit vielen Worten. " * 70] * 3)
    assert not u.anschreiben(mit_lebenslauf / "b.pdf", _stelle(), lang, []).passt


@braucht_browser
def test_mappe_mit_deckblatt_und_anlagen(mit_lebenslauf):
    cfg = baue_config(mit_lebenslauf, engine="auto")
    cfg.dokumente.anhang = "mappe"
    cfg.dokumente.projektseite = True
    d = Dienst(cfg, quelle=FalscheQuelle([anzeige(1)]), llm=FalschesModell())
    batch = d.lauf(melde=lambda _: None)
    e = batch["eintraege"][0]
    assert e["layout"] == "chromium" and e["mappe"] and not e["fehler"]
    # Deckblatt + Anschreiben + Lebenslauf (2) + Projekte; die alte Lebenslauf-PDF faellt weg
    assert drucker.seiten(Path(e["mappe"])) == 5
    anhaenge = d.unterlagen.anhaenge(e, d.anlagen())
    assert len(anhaenge) == 1 and anhaenge[0][1].startswith("Bewerbung_Erika_Beispiel_")


@braucht_browser
def test_kurzprofil_je_stelle_erzeugt_eigenen_lebenslauf(mit_lebenslauf):
    d = Dienst(baue_config(mit_lebenslauf, engine="auto"), quelle=FalscheQuelle([anzeige(1)]), llm=FalschesModell())
    batch = d.lauf(melde=lambda _: None)
    e = d.setze_kurzprofil(batch["id"], 0, "Zugeschnitten auf IT-Support.")
    assert e["lebenslauf"] and Path(e["lebenslauf"]).exists()
    namen = [n for _, n in d.unterlagen.anhaenge(e, d.anlagen())]
    assert namen[0].startswith("Anschreiben_") and namen[1] == "Lebenslauf_Erika_Beispiel.pdf"
    assert "Lebenslauf.pdf" not in namen                         # alter Lebenslauf aus anlagen faellt weg
