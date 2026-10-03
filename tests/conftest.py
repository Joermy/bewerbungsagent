from __future__ import annotations

import json
import socket
import subprocess
from pathlib import Path

import pytest

from bewerbungsagent.config import App, Config, LLM, Mail, Smtp, Suche, Vault

PROFIL = """---
name: Erika Beispiel
strasse: Teststraße 5
plz_ort: 12345 Musterstadt
telefon: "0000 000000"
email: erika@example.org
wohnort: Musterstadt
suchbegriffe:
  - Fachinformatiker
  - IT-Support
ausschluss:
  - Praktikum
arbeitszeit: vollzeit
---

# Abschluss
- Realschulabschluss

# Erfahrung
- Windows-Clients eingerichtet, Support für Anwender, Netzwerk, Python-Skripte
"""


def freier_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def anzeige(i: int, email: bool = True, **extra) -> dict:
    text = (
        f"Wir suchen Verstärkung im IT-Support. Aufgaben: Windows-Clients, Anwender-Support, Netzwerk.\n"
        f"Ansprechpartnerin: Frau Dr. Lena Muster\n"
        + (f"Bewerbung bitte an bewerbung@firma{i}.de oder info@firma{i}.de\n" if email else "Bewerbung über unser Portal.\n")
    )
    zeile = {
        "referenznummer": f"10000-TEST{i:04d}-S",
        "stellenangebotsTitel": f"IT-Support Mitarbeiter {i} (m/w/d)",
        "firma": f"Firma {i} GmbH",
        "hauptberuf": "Fachinformatiker/in - Systemintegration",
        "stellenlokationen": [{"adresse": {"plz": "12345", "ort": "Musterstadt"}}],
        "arbeitszeitVollzeit": True,
        "datumErsteVeroeffentlichung": "2026-09-20",
    }
    details = {**zeile, "stellenangebotsBeschreibung": text, "allianzpartnerUrl": f"www.firma{i}.de",
               "istArbeitnehmerUeberlassung": False, "istGeringfuegigeBeschaeftigung": False}
    details.update(extra)
    return {"zeile": zeile, "details": details}


class FalscheQuelle:

    def __init__(self, anzeigen: list[dict]):
        self.anzeigen = anzeigen
        self.suchen = 0

    def suche(self, was, wo, umkreis_km=25, veroeffentlicht_seit_tage=14, ohne_zeitarbeit=True, max_treffer=50,
              angebotsart=1):
        self.suchen += 1
        for a in self.anzeigen[:max_treffer]:
            yield a["zeile"]

    def details(self, refnr):
        return next(a["details"] for a in self.anzeigen if a["zeile"]["referenznummer"] == refnr)


class FalschesModell:

    def __init__(self, maengel_erst: int = 0):
        self.aufrufe = 0
        self.maengel_erst = maengel_erst

    def bereit(self):
        return True, "falsch"

    def frage_json(self, system: str, nutzer: str) -> dict:
        self.aufrufe += 1
        if "bewertest" in system:
            return {"punkte": 80, "begruendung": "passt zum Support-Profil"}
        if self.maengel_erst > 0:
            self.maengel_erst -= 1
            return {"betreff": "Bewerbung", "absaetze": ["Sehr geehrte Damen und Herren, [Name] ..."]}
        satz = "Ich habe Windows-Clients eingerichtet und Anwender im Alltag unterstützt, geduldig und genau. "
        return {"betreff": "Bewerbung als IT-Support Mitarbeiter (m/w/d)",
                "absaetze": [satz * 4, satz * 4, satz * 3, "Ich kann sofort beginnen und freue mich auf ein Gespräch."]}


@pytest.fixture
def projekt(tmp_path: Path):
    (tmp_path / "profil" / "anlagen").mkdir(parents=True)
    (tmp_path / "profil" / "profil.md").write_text(PROFIL, encoding="utf-8")
    (tmp_path / "profil" / "anlagen" / "Lebenslauf.pdf").write_bytes(b"%PDF-1.4\n% Test\n")
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "00 - Index.md").write_text("# Index\n", encoding="utf-8")
    git = ["git", "-C", str(vault)]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A"], check=True)
    subprocess.run([*git, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "start"], check=True)
    subprocess.run([*git, "config", "user.name", "test"], check=True)
    subprocess.run([*git, "config", "user.email", "test@example.org"], check=True)
    return tmp_path


def baue_config(projekt: Path, smtp_port: int = 0, **suche) -> Config:
    return Config(
        wurzel=projekt,
        profil=projekt / "profil" / "profil.md",
        anlagen=[projekt / "profil" / "anlagen" / "Lebenslauf.pdf"],
        daten=projekt / "daten",
        suche=Suche(**{"anzahl": 8, **suche}),
        llm=LLM(backend="lmstudio"),
        mail=Mail(sachbearbeitung="sb@amt.example", kopie_an_mich=True),
        vault=Vault(pfad=str(projekt / "vault"), ordner="Bewerbungen", git_commit=True),
        app=App(port=freier_port()),
        smtp=Smtp(host="127.0.0.1", port=smtp_port, user="erika@example.org", password="test"),
    )


def lies_json(pfad: Path):
    return json.loads(pfad.read_text(encoding="utf-8"))
