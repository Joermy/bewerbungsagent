from __future__ import annotations

import re
import subprocess
from datetime import date, datetime
from pathlib import Path

from .config import Config
from .speicher import ENTFERNT, GESENDET

UEBERSICHT = "00 - Bewerbungen Uebersicht"
EIGENE = "## Eigene Notizen"
_VERBOTEN = re.compile(r'[<>:"/\\|?*\[\]#^]')
_GESCHLECHT = r"(?:m/w/d|w/m/d|m/f/d|d/m/w|m/w/x|w/d/m|m-w-d|gn\*?)"
_MWD = re.compile(rf"\s*(?:\({_GESCHLECHT}\)|\b{_GESCHLECHT}(?=\s|$))", re.I)

STATUS_TEXT = {
    None: "vorgeschlagen",
    "entwurf": "vorgeschlagen",
    GESENDET: "gesendet",
    ENTFERNT: "verworfen",
    "fehler": "fehler",
}


def _yaml_str(wert) -> str:
    text = str(wert if wert is not None else "").replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def notizname(firma: str, titel: str) -> str:
    titel = _MWD.sub("", titel)
    name = f"{firma.strip()} - {titel.strip()}"
    name = _VERBOTEN.sub(" ", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:90].rstrip(" .-")


def bewerbungsstand(eintrag: dict) -> str:
    return eintrag.get("rueckmeldung") or STATUS_TEXT.get(eintrag.get("status"), eintrag.get("status") or "")


def _deutsch(zeit: str | None) -> str:
    if not zeit:
        return ""
    try:
        d = datetime.fromisoformat(zeit)
    except ValueError:
        return zeit
    return d.strftime("%d.%m.%Y %H:%M") if "T" in zeit else d.strftime("%d.%m.%Y")


class Vault:
    def __init__(self, cfg: Config):
        self.aktiv = bool(cfg.vault.pfad)
        self.wurzel = Path(cfg.vault.pfad) if self.aktiv else Path()
        self.ordner = self.wurzel / cfg.vault.ordner
        self.stellen = self.ordner / "Stellen"
        self.git_commit = cfg.vault.git_commit


    def pfad_fuer(self, eintrag: dict) -> Path:
        if eintrag.get("vault_notiz"):
            return self.wurzel / eintrag["vault_notiz"]
        s = eintrag["stelle"]
        name = notizname(s["firma"], s["titel"])
        pfad = self.stellen / f"{name}.md"
        if pfad.exists() and f'refnr: "{s["refnr"]}"' not in pfad.read_text(encoding="utf-8"):
            pfad = self.stellen / f"{name} ({s['refnr'][-6:]}).md"
        return pfad

    def schreibe_stelle(self, eintrag: dict, batch: dict) -> str | None:
        if not self.aktiv:
            return None
        pfad = self.pfad_fuer(eintrag)
        eigene = ""
        if pfad.exists():
            alt = pfad.read_text(encoding="utf-8")
            if "\nbewerbung: gesendet" in alt and not eintrag.get("gesendet_am") \
                    and f'batch: "{batch["id"]}"' not in alt:
                return pfad.relative_to(self.wurzel).as_posix()
            if EIGENE in alt:
                eigene = alt.split(EIGENE, 1)[1].split("\n## Verwandt", 1)[0].strip("\n")
        pfad.parent.mkdir(parents=True, exist_ok=True)
        pfad.write_text(self._stellen_text(eintrag, batch, pfad.stem, eigene), encoding="utf-8")
        return pfad.relative_to(self.wurzel).as_posix()

    def _stellen_text(self, e: dict, batch: dict, titel: str, eigene: str) -> str:
        s = e["stelle"]
        a = e.get("anschreiben") or {}
        stand = bewerbungsstand(e)
        erfasst = (batch.get("erstellt") or date.today().isoformat())[:10]
        fm = [
            "---",
            f"title: {_yaml_str(titel)}",
            f"erfasst: {erfasst}",
            "tags:",
            "  - bewerbung",
            "  - stelle",
            *(["  - ausbildung"] if s.get("art") == "ausbildung" else []),
            f"status: {'umgesetzt' if stand in ('gesendet', 'eingeladen', 'absage', 'zusage') else 'entwurf'}",
            f"source: {_yaml_str(s.get('url'))}",
            "generiert_von: bewerbungsagent",
            f"firma: {_yaml_str(s.get('firma'))}",
            f"ort: {_yaml_str(' '.join(x for x in (s.get('plz'), s.get('ort')) if x))}",
            f"refnr: {_yaml_str(s.get('refnr'))}",
            f"kontakt: {_yaml_str(s.get('email'))}",
            f"veroeffentlicht: {_yaml_str(s.get('veroeffentlicht'))}",
            f"art: {s.get('art') or 'arbeit'}",
            f"beginn: {_yaml_str(s.get('beginn') or '')}",
            f"bewerbung: {stand}",
            f"gesendet_am: {_yaml_str(e.get('gesendet_am') or '')}",
            f"passung: {int(s.get('punkte') or 0)}",
            f"batch: {_yaml_str(batch['id'])}",
            "---",
        ]
        zustand = {
            "gesendet": f"gesendet am {_deutsch(e.get('gesendet_am'))} an `{s.get('email')}`",
            "vorgeschlagen": "vorgeschlagen, wartet auf Freigabe",
            "verworfen": "aus dem Lauf genommen, nicht gesendet",
            "fehler": f"Versand fehlgeschlagen: `{e.get('fehler')}`",
        }.get(stand, stand)
        zeilen = [
            *fm, "", f"# {titel}", "",
            "> [!abstract] Stand",
            f"> {zustand}. Passung {int(s.get('punkte') or 0)}/100 - {s.get('begruendung') or ''}".rstrip(" -"),
            "",
            "| | |", "|---|---|",
            f"| Firma | {s.get('firma')} |",
            f"| Stelle | {s.get('titel')} |",
            f"| Art | {'Ausbildung' if s.get('art') == 'ausbildung' else 'Arbeit'}{' ab ' + _deutsch(s['beginn']) if s.get('beginn') else ''} |",
            f"| Ort | {' '.join(x for x in (s.get('plz'), s.get('ort')) if x)} |",
            f"| Beruf | {s.get('beruf') or ''} |",
            f"| Referenz | [{s.get('refnr')}]({s.get('url')}) |",
            f"| Veröffentlicht | {_deutsch(s.get('veroeffentlicht'))} |",
            f"| Kontakt | {s.get('email') or 'keine Adresse in der Anzeige'}{' · ' + s['ansprechpartner'] if s.get('ansprechpartner') else ''} |",
            f"| Arbeitszeit | {'Vollzeit' if s.get('vollzeit') else 'Teilzeit' if s.get('vollzeit') is False else 'k. A.'} |",
            f"| Zeitarbeit | {'ja' if s.get('zeitarbeit') else 'nein'} |",
            f"| Abschluss verlangt | {(s.get('abschluss_gefordert') or 'k. A.').replace('_', ' ').lower()} |",
            f"| Bewerbungsweg | {'E-Mail' if (s.get('weg') or 'email') == 'email' and s.get('email') else s.get('weg_grund') or 'keine Adresse'} |",
            "",
        ]
        if s.get("zeugnis_verlangt"):
            zeilen += ["> [!warning] Zeugnis", "> Die Anzeige verlangt ein Schulzeugnis. Angehängt ist nur der Lebenslauf.", ""]
        if a:
            zeilen += ["## Anschreiben", "", f"**{a.get('betreff', '')}**", "", a.get("anrede", ""), ""]
            for p in a.get("absaetze", []):
                zeilen += [p, ""]
            zeilen += [a.get("gruss", ""), ""]
            if a.get("maengel"):
                zeilen += ["> [!warning] Automatische Prüfung", f"> {', '.join(a['maengel'])}", ""]
        zeilen += ["## Verlauf", ""]
        zeilen.append(f"- {_deutsch(batch.get('erstellt'))} vorgeschlagen (Lauf `{batch['id']}`)")
        if e.get("gesendet_am"):
            zeilen.append(f"- {_deutsch(e['gesendet_am'])} gesendet an `{s.get('email')}`")
        if e.get("rueckmeldung"):
            zeilen.append(f"- {_deutsch(e.get('rueckmeldung_am'))} Rückmeldung: {e['rueckmeldung']}")
        zeilen += ["", EIGENE, "", eigene or "_Gesprächstermine, Rückmeldungen, Eindrücke._", "",
                   "## Stellenausschreibung", "", "```text", (s.get("beschreibung") or "")[:8000].replace("```", "'''"), "```", "",
                   "## Verwandt", "", f"- [[{UEBERSICHT}]]", "- [[00 - Index]]", ""]
        return "\n".join(zeilen)


    def schreibe_uebersicht(self, batches: list[dict]) -> None:
        if not self.aktiv:
            return
        je_stelle: dict[str, tuple[dict, dict]] = {}
        for b in batches:
            for e in b["eintraege"]:
                if not e.get("vault_notiz"):
                    continue
                ref = e["stelle"]["refnr"]
                if ref not in je_stelle or (e.get("gesendet_am") and not je_stelle[ref][1].get("gesendet_am")):
                    je_stelle[ref] = (b, e)
        eintraege = sorted(je_stelle.values(), key=lambda be: be[1].get("gesendet_am") or be[0]["erstellt"],
                           reverse=True)
        gesendet = [(b, e) for b, e in eintraege if e.get("gesendet_am")]
        monat = date.today().strftime("%Y-%m")
        im_monat = sum(1 for _, e in gesendet if e["gesendet_am"].startswith(monat))
        einladungen = sum(1 for _, e in eintraege if e.get("rueckmeldung") == "eingeladen")
        absagen = sum(1 for _, e in eintraege if e.get("rueckmeldung") == "absage")

        zeilen = [
            "---", f"title: {_yaml_str(UEBERSICHT)}", f"erfasst: {date.today().isoformat()}",
            "tags:", "  - moc", "  - bewerbung", "status: umgesetzt", "generiert_von: bewerbungsagent", "---", "",
            "# 00 – Bewerbungen Übersicht", "",
            "> [!abstract] Generiert",
            "> Diese Datei und alle Notizen unter `Stellen/` schreibt der Bewerbungsagent neu. "
            "Von Hand nur unter `## Eigene Notizen` in einer Stellen-Notiz schreiben.", "",
            "| Kennzahl | Wert |", "|---|---:|",
            f"| gesendet gesamt | {len(gesendet)} |",
            f"| gesendet im {date.today().strftime('%m/%Y')} | {im_monat} |",
            f"| Einladungen | {einladungen} |",
            f"| Absagen | {absagen} |", "",
            "## Alle Stellen", "",
            "| Datum | Stelle | Stand | Passung |", "|---|---|---|---:|",
        ]
        for b, e in eintraege:
            name = Path(e["vault_notiz"]).stem
            datum = _deutsch((e.get("gesendet_am") or b["erstellt"])[:10])
            zeilen.append(f"| {datum} | [[{name}]] | {bewerbungsstand(e)} | {int(e['stelle'].get('punkte') or 0)} |")
        offen = batches[0].get("ohne_email") if batches else []
        if offen:
            zeilen += ["", "## Von Hand bewerben", "",
                       "Passende Stellen aus dem letzten Lauf ohne E-Mail-Adresse in der Anzeige. "
                       "Meist Bewerbungsportal oder Kontakt hinter dem Captcha der Jobbörse.", "",
                       "| Stelle | Firma | Ort | Warum | Passung |", "|---|---|---|---|---:|"]
            for s in offen[:25]:
                warum = s.get("weg_grund") or "keine Adresse im Anzeigentext"
                zeilen.append(f"| [{s['titel']}]({s['url']}) | {s['firma']} | {s['ort']} | {warum} | {s.get('punkte', 0)} |")
        zeilen += ["", "## Verwandt", "", "- [[Projekt - bewerbungsagent]]", "- [[00 - Index]]", ""]
        self.ordner.mkdir(parents=True, exist_ok=True)
        (self.ordner / f"{UEBERSICHT}.md").write_text("\n".join(zeilen), encoding="utf-8")


    def commit(self, nachricht: str) -> str:
        if not (self.aktiv and self.git_commit and (self.wurzel / ".git").exists()):
            return "kein Commit (aus oder kein Git-Repo)"
        rel = self.ordner.relative_to(self.wurzel).as_posix()

        def git(*args):
            return subprocess.run(["git", "-C", str(self.wurzel), *args], capture_output=True, text=True,
                                  encoding="utf-8")

        git("add", "--", rel)
        if not git("diff", "--cached", "--quiet", "--", rel).returncode:
            return "nichts zu committen"
        lauf = git("commit", "-m", nachricht, "--only", "--", rel)
        return lauf.stdout.strip().splitlines()[0] if lauf.returncode == 0 else f"git-Fehler: {lauf.stderr.strip()[:200]}"
