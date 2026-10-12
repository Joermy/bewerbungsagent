"""Legt eine Vorfuehr-Umgebung mit erfundenen Daten an - fuer Bildschirmfotos und Vorfuehrungen.

Kein Netz, kein Modell, keine echten Firmen, kein echtes Profil. Alles unter <ziel>/ (Standard: demo/).

  python scripts/demo.py            Daten anlegen
  python scripts/demo.py --app      anlegen und die Oberflaeche auf Port 8767 starten
                                    (mit einem Schein-Modellserver auf Port 8768 fuer das Prompt-Labor)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
  - profil/anlagen/Zeugnis.pdf
daten: daten
suche:
  anzahl: 7
  angebotsart: ausbildung
  umkreis_km: 20
llm:
  backend: lmstudio
  basis_url: http://127.0.0.1:8768/v1
  modell: demo-llama-3.1-8b
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
    pdf.cell(0, 10, "Zeugnis Max Beispiel (Demo)")
    pdf.output(str(ziel / "profil" / "anlagen" / "Zeugnis.pdf"))
    # Lebenslauf mit erfundenen Daten und Bildern aus beispiel/
    shutil.copytree(WURZEL / "beispiel", ziel / "beispiel")
    shutil.copy(WURZEL / "beispiel" / "lebenslauf.yaml", ziel / "profil" / "lebenslauf.yaml")

    cfg = config.lade(ziel)
    d = Dienst(cfg, quelle=DemoQuelle(), llm=DemoModell())
    batch = d.lauf(melde=lambda _: None)
    d.als_beworben(batch["id"], 2, "portal")
    return ziel


class ScheinModell(BaseHTTPRequestHandler):
    """Antwortet wie ein OpenAI-kompatibler Server mit festen, erfundenen Texten - nur fuer die Vorfuehrung."""

    def log_message(self, *_):
        pass

    def _json(self, daten):
        roh = json.dumps(daten, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(roh)))
        self.end_headers()
        self.wfile.write(roh)

    def do_GET(self):
        self._json({"data": [{"id": "demo-llama-3.1-8b"}]})

    def do_POST(self):
        anfrage = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        felder = (((anfrage.get("response_format") or {}).get("json_schema") or {}).get("schema") or {}).get("properties", {})
        nutzer = anfrage.get("messages", [{}])[-1].get("content", "")
        if "punkte" in felder:
            antwort = {"punkte": 78, "begruendung": "Eigene Webprojekte passen zu den Aufgaben, SQL fehlt noch."}
        elif "anforderungen" in felder:
            antwort = {"firma": "Muster Software GmbH", "anforderungen": ["Webanwendungen mit JavaScript", "Teamarbeit", "Interesse an Programmierung"],
                       "belege": ["Drei Firmenwebsites mit HTML, CSS und JavaScript", "Kunden in Pflege eingewiesen", "Eigene Projekte"],
                       "motivation": "Software für Handwerksbetriebe", "arbeitsprobe": True}
        elif "fach" in felder:
            antwort = {"fach": ["Webanwendungen", "Datenbanken"], "werkzeuge": ["JavaScript", "TypeScript", "SQL"],
                       "persoenlich": ["Teamfähigkeit", "Zuverlässigkeit"], "formal": ["Mittlere Reife oder Abitur"]}
        elif "kurzprofil" in felder:
            antwort = {"kurzprofil": "Baut seit 2025 Websites und kleine Werkzeuge mit HTML, CSS, JavaScript und Python. "
                                     "Bringt Programmierung aus eigenen Projekten mit und sucht eine Ausbildung zum "
                                     "Fachinformatiker für Anwendungsentwicklung.", "genutzt": ["JavaScript", "Programmierung"]}
        else:
            antwort = {"betreff": "Bewerbung um einen Ausbildungsplatz als Fachinformatiker für Anwendungsentwicklung",
                       "absaetze": [
                           "Sie entwickeln Software für Handwerksbetriebe – genau für solche Betriebe habe ich meine ersten Websites gebaut. "
                           "Deshalb möchte ich meine Ausbildung zum Fachinformatiker für Anwendungsentwicklung bei Ihnen machen.",
                           "Seit 2025 plane, gestalte und programmiere ich Websites für kleine Firmen mit HTML, CSS und JavaScript. "
                           "Dabei habe ich gelernt, Wünsche von Kunden in klare Schritte zu übersetzen und Ergebnisse verständlich zu erklären.",
                           "Wie ich arbeite, zeigen meine Projekte unter example.org/max – darunter eine 3D-Uhr im Browser und eine lokale "
                           "Python-App. Programmieren habe ich mir selbst beigebracht; in der Ausbildung möchte ich die Grundlagen sauber lernen.",
                           "Im Praktikum am Empfang einer Arztpraxis habe ich Termine vergeben und Patienten betreut. Dort habe ich gemerkt, "
                           "wie viel gute Software im Alltag eines kleinen Betriebs ausmacht.",
                           "Die Ausbildung kann ich zum 1. August 2027 beginnen. Über eine Einladung zu einem Gespräch freue ich mich.",
                       ]}
        time.sleep(0.8)
        text = json.dumps(antwort, ensure_ascii=False)
        self._json({"choices": [{"message": {"role": "assistant", "content": text}}],
                    "usage": {"prompt_tokens": len(nutzer) // 4, "completion_tokens": len(text) // 3}})


def schein_modell(port: int = 8768) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", port), ScheinModell)
    threading.Thread(target=server.serve_forever, daemon=True).start()


def main():
    args = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    args.add_argument("--ziel", default=str(WURZEL / "demo"))
    args.add_argument("--app", action="store_true")
    a = args.parse_args()
    ziel = anlegen(Path(a.ziel).resolve())
    print(f"Demo-Daten unter {ziel}")
    if a.app:
        from bewerbungsagent.app import starte
        schein_modell()
        starte(config.lade(ziel), oeffnen=False)


if __name__ == "__main__":
    main()
