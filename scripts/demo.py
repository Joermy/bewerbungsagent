"""Legt eine Vorfuehr-Umgebung mit erfundenen Daten an - fuer Bildschirmfotos und Vorfuehrungen.

Kein Netz, kein Modell, keine echten Firmen, kein echtes Profil. Alles unter <ziel>/ (Standard: demo/).

  python scripts/demo.py            Daten anlegen
  python scripts/demo.py --app      anlegen und die Oberflaeche auf Port 8767 starten
"""
from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL))

from fpdf import FPDF

from bewerbungsagent import config
from bewerbungsagent.dienst import Dienst

PROFIL = """---
name: Max Beispiel
strasse: Musterweg 12
plz_ort: 12345 Musterstadt
telefon: "0000 123456"
email: max.beispiel@example.org
wohnort: Musterstadt
suchbegriffe:
  - Mediengestalter
  - Fachinformatiker
  - Kaufmann Büromanagement
ausschluss:
  - Studium
arbeitszeit: egal
schulabschluss: realschule
arbeitsproben:
  - https://example.org/arbeiten/
---

# Erfahrung

- Websites für kleine Betriebe mit HTML, CSS und JavaScript
- Flyer und Visitenkarten für einen Friseursalon
- Praktikum am Empfang einer Arztpraxis: Telefon, Termine, Verwaltung

# Fähigkeiten

- MS Office, Grafikdesign, Grundkenntnisse in Python
"""

KONFIG = """profil: profil/profil.md
anlagen:
  - profil/anlagen/Lebenslauf.pdf
daten: daten
suche:
  anzahl: 7
  angebotsart: ausbildung
  umkreis_km: 20
llm:
  backend: lmstudio
mail:
  sachbearbeitung: sachbearbeitung@example.org
app:
  port: 8767
"""

BETRIEBE = [
    ("Druckhaus Nordlicht GmbH", "Ausbildung Mediengestalter Digital und Print (m/w/d)", "Musterstadt", 2, "2027-08-01", "mail"),
    ("Pixelwerk Agentur GmbH", "Ausbildung Mediengestalter/in – Gestaltung und Technik", "Braunschweig", 18, "2027-08-01", "mail"),
    ("Systemhaus Fuhse IT GmbH", "Ausbildung Fachinformatiker Systemintegration (m/w/d)", "Musterstadt", 4, "2027-08-01", "mail"),
    ("Stadtwerke Beispielstadt", "Auszubildende Kaufleute für Büromanagement (m/w/d)", "Ilsede", 9, "2026-10-01", "mail"),
    ("Praxis am Marktplatz", "Ausbildung Kaufmann/-frau für Büromanagement", "Lehrte", 16, "2027-08-01", "mail"),
    ("Logistik Nord Musterfirma KG", "2027 Ausbildung Fachinformatiker Digitale Vernetzung", "Vechelde", 11, "2027-08-01", "mail"),
    ("Möbelhaus Beispiel GmbH & Co. KG", "Ausbildung Mediengestalter (m/w/d) im Marketing", "Salzgitter", 19, "2027-09-01", "mail"),
    ("Autohaus Muster GmbH", "Ausbildung Kaufmann Büromanagement 2027", "Musterstadt", 3, "2027-08-01", "portal"),
    ("Musterbank eG", "Ausbildung Fachinformatiker Anwendungsentwicklung", "Braunschweig", 19, "2027-08-01", "portal"),
    ("Werkstatt Beispiel e. V.", "Ausbildung Mediengestalter Bild und Ton", "Hildesheim", 20, "2027-08-01", "fragen"),
]


def _anzeige(i: int, firma: str, titel: str, ort: str, km: int, beginn: str, weg: str) -> dict:
    domain = firma.split()[0].lower().replace("ö", "oe") + ".example"
    schluss = {
        "mail": f"Bitte sende deine Bewerbungsunterlagen per E-Mail an bewerbung@{domain}.",
        "portal": f"Bewirb dich bitte über unser Bewerbungsportal. Bei Fragen erreichst du uns unter info@{domain}.",
        "fragen": f"Bewerbungen nur online. Für Fragen zur Ausbildung: ausbildung@{domain}.",
    }[weg]
    text = (f"{firma} bildet seit vielen Jahren aus. Du gestaltest, organisierst und lernst im Team.\n"
            f"Wir bieten eine feste Ansprechperson und gute Übernahmechancen.\n{schluss}")
    zeile = {
        "referenznummer": f"DEMO-{i:04d}-S", "stellenangebotsTitel": titel, "firma": firma,
        "hauptberuf": titel, "stellenlokationen": [{"adresse": {"ort": ort}}],
        "entfernung": km, "arbeitszeitVollzeit": True, "datumErsteVeroeffentlichung": "2026-09-20",
    }
    details = {**zeile, "stellenangebotsart": "AUSBILDUNG", "eintrittszeitraum": {"von": beginn},
               "stellenangebotsBeschreibung": text, "geforderterBildungsabschluss": "HAUPTSCHULABSCHLUSS"}
    return {"zeile": zeile, "details": details}


class DemoQuelle:
    def __init__(self):
        self.anzeigen = [_anzeige(i, *b) for i, b in enumerate(BETRIEBE)]

    def suche(self, was, wo, umkreis_km=25, veroeffentlicht_seit_tage=14, ohne_zeitarbeit=True,
              max_treffer=50, angebotsart=1):
        return iter([a["zeile"] for a in self.anzeigen] if was == "Mediengestalter" else [])

    def details(self, refnr):
        return next(a["details"] for a in self.anzeigen if a["zeile"]["referenznummer"] == refnr)


class DemoModell:

    def bereit(self):
        return True, "Demo-Modell"

    def frage_json(self, system: str, nutzer: str) -> dict:
        firma = next((z.split(": ", 1)[1] for z in nutzer.splitlines() if z.startswith("Firma: ")), "Ihr Betrieb")
        titel = next((z.split(": ", 1)[1] for z in nutzer.splitlines() if z.startswith("Titel: ")), "")
        if "bewertest" in system:
            punkte = 52 + int(hashlib.md5(nutzer.split("# Stelle")[-1][:200].encode()).hexdigest(), 16) % 41
            return {"punkte": punkte, "begruendung": "Eigene Projekte passen zu den Aufgaben der Anzeige."}
        beruf = titel.split("Ausbildung")[-1].strip(" :-") or titel
        return {
            "betreff": f"Bewerbung um einen Ausbildungsplatz als {beruf}",
            "absaetze": [
                f"Gestalten und Organisieren mache ich schon heute aus eigenem Antrieb. Bei {firma} möchte ich das "
                "jetzt von Grund auf lernen und einen anerkannten Berufsabschluss machen.",
                "Für einen Friseursalon habe ich Flyer, Visitenkarten und die Website gestaltet und umgesetzt. "
                "Dabei habe ich gelernt, Wünsche aufzunehmen, Entwürfe zu erklären und Termine zu halten. "
                "Meine Arbeiten finden Sie unter https://example.org/arbeiten/.",
                "Im Praktikum am Empfang einer Arztpraxis habe ich Telefonate angenommen, Termine vergeben und "
                "Verwaltungsaufgaben übernommen. Ich arbeite sorgfältig und behalte auch unter Zeitdruck den Überblick.",
                "Mit MS Office arbeite ich sicher, Grundkenntnisse in Python habe ich mir selbst beigebracht. "
                "Neue Werkzeuge arbeite ich mir schnell an, und was ich einrichte, dokumentiere ich so, dass "
                "andere darauf aufbauen können.",
                "Ich kann zum gewünschten Termin beginnen und freue mich über die Einladung zu einem Gespräch.",
            ],
        }


def anlegen(ziel: Path) -> Path:
    if ziel.exists():
        shutil.rmtree(ziel)
    (ziel / "profil" / "anlagen").mkdir(parents=True)
    (ziel / "profil" / "profil.md").write_text(PROFIL, encoding="utf-8")
    (ziel / "config.yaml").write_text(KONFIG, encoding="utf-8")
    (ziel / ".env").write_text("SMTP_HOST=127.0.0.1\nSMTP_PORT=2525\nSMTP_USER=max.beispiel@example.org\n"
                              "SMTP_PASSWORD=demo\n", encoding="utf-8")
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=14)
    pdf.cell(0, 10, "Lebenslauf Max Beispiel (Demo)")
    pdf.output(str(ziel / "profil" / "anlagen" / "Lebenslauf.pdf"))

    cfg = config.lade(ziel)
    d = Dienst(cfg, quelle=DemoQuelle(), llm=DemoModell())
    batch = d.lauf(melde=lambda _: None)
    d.als_beworben(batch["id"], 2, "portal")
    return ziel


def main():
    args = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    args.add_argument("--ziel", default=str(WURZEL / "demo"))
    args.add_argument("--app", action="store_true")
    a = args.parse_args()
    ziel = anlegen(Path(a.ziel).resolve())
    print(f"Demo-Daten unter {ziel}")
    if a.app:
        from bewerbungsagent.app import starte
        starte(config.lade(ziel), oeffnen=False)


if __name__ == "__main__":
    main()
