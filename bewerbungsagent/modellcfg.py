"""Einstellungen und Systemprompts fuer das Sprachmodell.

modell.yaml im Projektordner (optional, Vorlage: modell.example.yaml):

    voreinstellung: klein          # klein | mittel | gross
    voreinstellungen:              # einzelne Werte ueberschreiben
      klein: {kontext: 8192, temperatur: 0.4}
    aufgaben:                      # je Aufgabe Werte ueberschreiben
      anschreiben_schreiben: {temperatur: 0.65, max_tokens: 1100}

Systemprompts liegen als Markdown in bewerbungsagent/prompts/. Eigene Fassungen
gehoeren nach profil/prompts/<aufgabe>.md (oder <aufgabe>.klein.md) und haben
Vorrang. Die App schreibt dort hinein; "Standard wiederherstellen" loescht die Datei.
"""
from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

import yaml

PAKET_PROMPTS = Path(__file__).parent / "prompts"


@dataclass
class Einstellung:
    kontext: int = 8192          # num_ctx (Ollama) bzw. Hinweis fuer LM Studio
    temperatur: float = 0.5
    top_p: float = 0.9
    top_k: int = 40
    wiederholung: float = 1.1    # repeat_penalty
    max_tokens: int = 900
    seed: int | None = None
    strukturiert: bool = True    # JSON-Schema erzwingen (Grammatik)
    mehrstufig: bool = False     # Anschreiben in Schritten
    beispiele: bool = True       # Beispiel-Absaetze mitschicken
    anzeige_zeichen: int = 6000  # so viel Anzeigentext geht ans Modell
    profil_zeichen: int = 6000

    def als_dict(self) -> dict:
        return asdict(self)


VOREINSTELLUNGEN: dict[str, Einstellung] = {
    # 7-9B, z. B. Llama 3.1 8B Instruct, Qwen 2.5 7B, Hermes 3 8B, Mistral 7B
    "klein": Einstellung(kontext=8192, temperatur=0.4, top_p=0.9, top_k=40, wiederholung=1.12, max_tokens=900,
                         strukturiert=True, mehrstufig=True, beispiele=True, anzeige_zeichen=2600,
                         profil_zeichen=2600),
    # 12-14B, z. B. Qwen 2.5 14B, Mistral Nemo 12B, Gemma 3 12B
    "mittel": Einstellung(kontext=12288, temperatur=0.5, top_p=0.92, top_k=50, wiederholung=1.08, max_tokens=1100,
                          strukturiert=True, mehrstufig=True, beispiele=True, anzeige_zeichen=4500,
                          profil_zeichen=4500),
    # 27B+ oder Claude/grosse API-Modelle
    "gross": Einstellung(kontext=32768, temperatur=0.6, top_p=0.95, top_k=60, wiederholung=1.0, max_tokens=1400,
                         strukturiert=True, mehrstufig=False, beispiele=False, anzeige_zeichen=7000,
                         profil_zeichen=7000),
}

AUFGABEN: dict[str, str] = {
    "bewertung": "Passung einer Stelle bewerten",
    "anschreiben": "Anschreiben in einem Schritt (grosse Modelle)",
    "anschreiben_analyse": "Anschreiben, Schritt 1: Anzeige auswerten und Belege aus dem Profil zuordnen",
    "anschreiben_schreiben": "Anschreiben, Schritt 2: Absaetze schreiben",
    "ats_schluesselwoerter": "Schluesselwoerter aus der Anzeige ziehen",
    "ats_kurzprofil": "Kurzprofil im Lebenslauf auf die Stelle zuschneiden",
    "stichpunkte": "Stichpunkte im Lebenslauf verbessern",
    "agent": "Systemprompt fuer Agenten ueber MCP (Hermes Agent, Claude Code, Claude Desktop)",
}

# Abweichungen je Aufgabe, gelten fuer alle Voreinstellungen
AUFGABEN_STANDARD: dict[str, dict] = {
    "bewertung": {"temperatur": 0.1, "max_tokens": 200},
    "anschreiben_analyse": {"temperatur": 0.15, "max_tokens": 700},
    "ats_schluesselwoerter": {"temperatur": 0.1, "max_tokens": 700},
    "ats_kurzprofil": {"temperatur": 0.35, "max_tokens": 400},
    "stichpunkte": {"temperatur": 0.3, "max_tokens": 600},
}


@dataclass
class Modellcfg:
    wurzel: Path
    voreinstellung: str = "klein"
    voreinstellungen: dict[str, dict] = field(default_factory=dict)
    aufgaben: dict[str, dict] = field(default_factory=dict)
    verbindung: dict = field(default_factory=dict)   # backend, modell, basis_url - Vorrang vor config.yaml

    # ------------------------------------------------------------ Werte

    def basis(self, name: str | None = None) -> Einstellung:
        name = name or self.voreinstellung
        e = copy.deepcopy(VOREINSTELLUNGEN.get(name, VOREINSTELLUNGEN["klein"]))
        _anwenden(e, self.voreinstellungen.get(name))
        return e

    def fuer(self, aufgabe: str | None) -> Einstellung:
        e = self.basis()
        if aufgabe:
            _anwenden(e, AUFGABEN_STANDARD.get(aufgabe))
            _anwenden(e, self.aufgaben.get(aufgabe))
        return e

    # ------------------------------------------------------------ Prompts

    @property
    def eigene_prompts(self) -> Path:
        return self.wurzel / "profil" / "prompts"

    def _kandidaten(self, aufgabe: str) -> list[Path]:
        klein = self.voreinstellung in ("klein", "mittel")
        namen = ([f"{aufgabe}.klein.md"] if klein else []) + [f"{aufgabe}.md"]
        return [self.eigene_prompts / n for n in namen] + [PAKET_PROMPTS / n for n in namen]

    def prompt(self, aufgabe: str) -> str:
        for pfad in self._kandidaten(aufgabe):
            if pfad.exists():
                return _ohne_kommentar(pfad.read_text(encoding="utf-8"))
        raise FileNotFoundError(f"Kein Prompt fuer Aufgabe {aufgabe!r}")

    def prompt_quelle(self, aufgabe: str) -> tuple[str, bool]:
        """(Text, eigen?) fuer die App."""
        for pfad in self._kandidaten(aufgabe):
            if pfad.exists():
                return _ohne_kommentar(pfad.read_text(encoding="utf-8")), self.eigene_prompts in pfad.parents
        return "", False

    def standard_prompt(self, aufgabe: str) -> str:
        for pfad in self._kandidaten(aufgabe):
            if PAKET_PROMPTS in pfad.parents and pfad.exists():
                return _ohne_kommentar(pfad.read_text(encoding="utf-8"))
        return ""

    def setze_prompt(self, aufgabe: str, text: str) -> Path:
        if aufgabe not in AUFGABEN:
            raise ValueError(f"Unbekannte Aufgabe: {aufgabe}")
        klein = self.voreinstellung in ("klein", "mittel") and (PAKET_PROMPTS / f"{aufgabe}.klein.md").exists()
        ziel = self.eigene_prompts / (f"{aufgabe}.klein.md" if klein else f"{aufgabe}.md")
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_text(text.strip() + "\n", encoding="utf-8")
        return ziel

    def prompt_zuruecksetzen(self, aufgabe: str) -> None:
        for n in (f"{aufgabe}.klein.md", f"{aufgabe}.md"):
            (self.eigene_prompts / n).unlink(missing_ok=True)

    # ------------------------------------------------------------ Speichern

    def als_dict(self) -> dict:
        aus = {"voreinstellung": self.voreinstellung, "voreinstellungen": self.voreinstellungen,
               "aufgaben": self.aufgaben}
        if any(self.verbindung.values()):
            aus["verbindung"] = {k: v for k, v in self.verbindung.items() if v not in (None, "")}
        return aus

    def speichere(self) -> Path:
        ziel = self.wurzel / "modell.yaml"
        kopf = "# Einstellungen fuer das Sprachmodell. Vorlage und Erklaerung: modell.example.yaml\n"
        ziel.write_text(kopf + yaml.safe_dump(self.als_dict(), allow_unicode=True, sort_keys=False), encoding="utf-8")
        return ziel


def _anwenden(e: Einstellung, werte: dict | None) -> None:
    if not werte:
        return
    erlaubt = {f.name: f.type for f in fields(Einstellung)}
    for k, v in werte.items():
        if k in erlaubt and v is not None:
            setattr(e, k, v)


def _ohne_kommentar(text: str) -> str:
    # Zeilen, die mit "<!--" beginnen und enden, sind Notizen fuer Menschen
    zeilen = [z for z in text.splitlines() if not (z.strip().startswith("<!--") and z.strip().endswith("-->"))]
    return "\n".join(zeilen).strip()


def lade(wurzel: Path) -> Modellcfg:
    wurzel = Path(wurzel)
    pfad = wurzel / "modell.yaml"
    roh = yaml.safe_load(pfad.read_text(encoding="utf-8")) if pfad.exists() else {}
    roh = roh or {}
    return Modellcfg(
        wurzel=wurzel,
        voreinstellung=str(roh.get("voreinstellung") or "klein"),
        voreinstellungen={k: dict(v or {}) for k, v in (roh.get("voreinstellungen") or {}).items()},
        aufgaben={k: dict(v or {}) for k, v in (roh.get("aufgaben") or {}).items()},
        verbindung=dict(roh.get("verbindung") or {}),
    )
