from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Suche:
    anzahl: int = 8
    angebotsart: str = "arbeit"
    umkreis_km: int = 25
    veroeffentlicht_seit_tage: int = 14
    ohne_zeitarbeit: bool = True
    ohne_minijob: bool = True
    max_treffer_je_begriff: int = 50
    sperrfrist_tage: int = 90
    mindest_passung: int = 30
    mindest_passung_modell: int = 50


@dataclass
class LLM:
    backend: str = "lmstudio"
    modell: str = ""
    basis_url: str = ""
    temperatur: float = 0.6
    timeout_s: int = 600


@dataclass
class Mail:
    absender_name: str = ""
    sachbearbeitung: str = ""
    kopie_an_mich: bool = True


@dataclass
class Vault:
    pfad: str = ""
    ordner: str = "Bewerbungen"
    git_commit: bool = True


@dataclass
class App:
    port: int = 8765


@dataclass
class Dokumente:
    engine: str = "auto"          # auto | chromium | fpdf
    browser: str = ""             # Pfad zu Edge/Chrome; leer = automatisch suchen
    anhang: str = "einzeln"       # einzeln | mappe
    lebenslauf: bool = True       # Lebenslauf aus profil/lebenslauf.yaml erzeugen und anhaengen
    projektseite: bool = False    # eigene Seite mit Projekten (Portfolio) anhaengen
    deckblatt: bool = True        # Deckblatt vor der Mappe


@dataclass
class Quellen:
    arbeitsagentur: bool = True
    adzuna: bool = False
    jooble: bool = False
    land: str = "de"
    max_treffer: int = 40
    mail_alarme: bool = False
    mail_ordner: str = "INBOX"
    mail_tage: int = 10


@dataclass
class Schluessel:
    adzuna_id: str = ""
    adzuna_key: str = ""
    jooble: str = ""
    imap_host: str = ""
    imap_port: int = 993
    imap_user: str = ""
    imap_password: str = ""


@dataclass
class Smtp:
    host: str = ""
    port: int = 465
    user: str = ""
    password: str = ""

    @property
    def vollstaendig(self) -> bool:
        return bool(self.host and self.user and self.password)


@dataclass
class Config:
    wurzel: Path
    profil: Path
    anlagen: list[Path]
    daten: Path
    suche: Suche = field(default_factory=Suche)
    llm: LLM = field(default_factory=LLM)
    mail: Mail = field(default_factory=Mail)
    vault: Vault = field(default_factory=Vault)
    app: App = field(default_factory=App)
    unterschrift: Path | None = None
    smtp: Smtp = field(default_factory=Smtp)
    llm_api_key: str = ""
    dokumente: Dokumente = field(default_factory=Dokumente)
    quellen: Quellen = field(default_factory=Quellen)
    schluessel: Schluessel = field(default_factory=Schluessel)


def lese_env(pfad: Path) -> dict[str, str]:
    werte: dict[str, str] = {}
    if not pfad.exists():
        return werte
    for zeile in pfad.read_text(encoding="utf-8").splitlines():
        zeile = zeile.strip()
        if not zeile or zeile.startswith("#") or "=" not in zeile:
            continue
        key, _, value = zeile.partition("=")
        werte[key.strip()] = value.strip().strip('"').strip("'")
    return werte


def _nur_bekannte(klasse, daten: dict | None):
    daten = daten or {}
    erlaubt = klasse.__dataclass_fields__.keys()
    return klasse(**{k: v for k, v in daten.items() if k in erlaubt})


def _vault(daten: dict | None, rel) -> Vault:
    v = _nur_bekannte(Vault, daten)
    if v.pfad:
        v.pfad = str(rel(v.pfad))
    return v


def projektwurzel() -> Path:
    if os.environ.get("BEWERBUNGSAGENT_WURZEL"):
        return Path(os.environ["BEWERBUNGSAGENT_WURZEL"])
    if (Path.cwd() / "config.yaml").exists():
        return Path.cwd()
    return Path(__file__).resolve().parent.parent


def _verbindung(wurzel: Path) -> dict:
    """Modellverbindung aus modell.yaml (von der App gesetzt) - hat Vorrang vor llm in config.yaml."""
    pfad = wurzel / "modell.yaml"
    if not pfad.exists():
        return {}
    try:
        roh = yaml.safe_load(pfad.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}
    return {k: v for k, v in (roh.get("verbindung") or {}).items() if v not in (None, "")}


def lade(wurzel: Path | str = ".") -> Config:
    wurzel = Path(wurzel).resolve()
    pfad = wurzel / "config.yaml"
    if not pfad.exists():
        pfad = wurzel / "config.example.yaml"
    roh = yaml.safe_load(pfad.read_text(encoding="utf-8")) or {}

    env = {**lese_env(wurzel / ".env"),
           **{k: v for k, v in os.environ.items()
              if k.startswith(("SMTP_", "LLM_", "ADZUNA_", "JOOBLE_", "IMAP_", "ANTHROPIC_"))}}

    def rel(p: str) -> Path:
        q = Path(p)
        return q if q.is_absolute() else wurzel / q

    return Config(
        wurzel=wurzel,
        profil=rel(roh.get("profil", "profil/profil.md")),
        anlagen=[rel(a) for a in roh.get("anlagen", [])],
        daten=rel(roh.get("daten", "daten")),
        suche=_nur_bekannte(Suche, roh.get("suche")),
        llm=_nur_bekannte(LLM, {**(roh.get("llm") or {}), **_verbindung(wurzel)}),
        mail=_nur_bekannte(Mail, roh.get("mail")),
        vault=_vault(roh.get("vault"), rel),
        app=_nur_bekannte(App, roh.get("app")),
        unterschrift=rel(roh["unterschrift"]) if roh.get("unterschrift") else None,
        smtp=Smtp(
            host=env.get("SMTP_HOST", ""),
            port=int(env.get("SMTP_PORT", "465") or 465),
            user=env.get("SMTP_USER", ""),
            password=env.get("SMTP_PASSWORD", ""),
        ),
        llm_api_key=env.get("LLM_API_KEY", "") or env.get("ANTHROPIC_API_KEY", ""),
        dokumente=_nur_bekannte(Dokumente, roh.get("dokumente")),
        quellen=_nur_bekannte(Quellen, roh.get("quellen")),
        schluessel=Schluessel(
            adzuna_id=env.get("ADZUNA_APP_ID", ""),
            adzuna_key=env.get("ADZUNA_APP_KEY", ""),
            jooble=env.get("JOOBLE_KEY", ""),
            imap_host=env.get("IMAP_HOST", ""),
            imap_port=int(env.get("IMAP_PORT", "993") or 993),
            imap_user=env.get("IMAP_USER", ""),
            imap_password=env.get("IMAP_PASSWORD", ""),
        ),
    )


def setze_abschnitt(wurzel: Path | str, name: str, werte: dict) -> Path:
    """Schreibt einen Abschnitt (z. B. quellen, dokumente) in config.yaml und laesst den Rest stehen.

    Kommentare in diesem einen Abschnitt gehen verloren, alle anderen bleiben erhalten.
    Gibt es noch keine config.yaml, wird config.example.yaml als Ausgangspunkt kopiert.
    """
    wurzel = Path(wurzel)
    ziel = wurzel / "config.yaml"
    if not ziel.exists():
        vorlage = wurzel / "config.example.yaml"
        ziel.write_text(vorlage.read_text(encoding="utf-8") if vorlage.exists() else "", encoding="utf-8")
    zeilen = ziel.read_text(encoding="utf-8").splitlines()
    block = [f"{name}:"] + ["  " + z for z in yaml.safe_dump(werte, allow_unicode=True, sort_keys=False).splitlines()]
    start = next((i for i, z in enumerate(zeilen) if z.startswith(f"{name}:")), None)
    if start is None:
        while zeilen and not zeilen[-1].strip():
            zeilen.pop()
        zeilen += [""] + block
    else:
        ende = start + 1
        while ende < len(zeilen) and (not zeilen[ende].strip() or zeilen[ende].startswith((" ", "\t", "#"))):
            ende += 1
        # Leerzeilen und Kommentare vor dem naechsten Abschnitt gehoeren zu diesem
        while ende > start + 1 and (not zeilen[ende - 1].strip() or zeilen[ende - 1].startswith("#")):
            ende -= 1
        zeilen[start:ende] = block
    ziel.write_text("\n".join(zeilen) + "\n", encoding="utf-8")
    return ziel
