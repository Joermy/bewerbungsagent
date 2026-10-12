from __future__ import annotations

import base64
import json
import mimetypes
import re
import secrets
import threading
import traceback
import webbrowser
from collections import OrderedDict
from dataclasses import asdict
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

import yaml

from . import config as config_mod
from . import drucker, integrationen, lesezeichen, render
from . import lebenslauf as lv
from . import modellcfg as mc
from .config import Config
from .dienst import Abbruch, Dienst
from .llm import BACKENDS, LLM, LLMFehler
from .portale import WEGE, Portale
from .quellen.gemeinsam import QuellenFehler
from .speicher import jetzt
from .stelle import Stelle

STATISCH = Path(__file__).parent / "statisch"
MAX_KOERPER = 16_000_000
VORSCHAU_CSP = ("default-src 'none'; img-src data: 'self'; font-src 'self' data:; style-src 'unsafe-inline'; "
                "script-src 'unsafe-inline'; base-uri 'none'; form-action 'none'")
BEISPIEL_ANZEIGE = """Ausbildung zum Fachinformatiker für Anwendungsentwicklung (m/w/d) 2027

Wir sind ein Softwarehaus mit 40 Mitarbeitenden und entwickeln Programme für Handwerksbetriebe.

Deine Aufgaben:
- Du entwickelst mit uns Webanwendungen in JavaScript und TypeScript
- Du lernst Datenbanken und SQL kennen
- Du testest neue Funktionen und hilfst Kunden am Telefon

Das bringst du mit:
- Mittlere Reife oder Abitur
- Interesse an Programmierung, erste eigene Projekte sind ein Plus
- Teamfähigkeit und Zuverlässigkeit

Bewerbung bitte per E-Mail an ausbildung@muster-software.example, Ansprechpartnerin Frau Petra Klein."""

BEISPIEL_BRIEF = {
    "betreff": "Bewerbung als Fachinformatiker für Anwendungsentwicklung",
    "anrede": "Sehr geehrte Frau Muster,",
    "absaetze": [
        "Ihre Anzeige hat mich sofort angesprochen. Dieser Brief ist eine Vorschau: So sieht ein Anschreiben "
        "mit dem gewählten Design aus. Den echten Text schreibt der Agent für jede Stelle neu.",
        "Kopf, Farben und Schriften kommen aus dem Lebenslauf – Anschreiben, Lebenslauf, Deckblatt und "
        "Projektseite wirken dadurch wie aus einem Guss. Das Anschriftfeld sitzt nach DIN 5008 und passt "
        "in einen Fensterumschlag.",
        "Ist ein Text zu lang, verkleinert die Vorlage die Schrift in kleinen Stufen. Reicht das nicht, "
        "meldet die Prüfung, dass gekürzt werden muss.",
    ],
    "gruss": "Mit freundlichen Grüßen",
}


class Auftrag:

    def __init__(self):
        self.sperre = threading.Lock()
        self.name: str | None = None
        self.log: list[str] = []
        self.fehler: str | None = None
        self.fertig = True
        self.ergebnis: dict | None = None

    def zustand(self) -> dict:
        return {"name": self.name, "log": self.log[-200:], "fehler": self.fehler, "fertig": self.fertig,
                "ergebnis": self.ergebnis}

    def starte(self, name: str, funktion) -> bool:
        with self.sperre:
            if not self.fertig:
                return False
            self.name, self.log, self.fehler, self.fertig, self.ergebnis = name, [], None, False, None

        def melde(text: str):
            self.log.append(f"{jetzt()[11:]}  {text}")

        def lauf():
            try:
                self.ergebnis = funktion(melde)
            except Abbruch as fehler:
                self.fehler = str(fehler)
                melde(f"Abgebrochen: {fehler}")
            except Exception as fehler:
                self.fehler = f"{type(fehler).__name__}: {fehler}"
                melde(self.fehler)
                traceback.print_exc()
            finally:
                self.fertig = True

        threading.Thread(target=lauf, daemon=True).start()
        return True


def _kurz(batch: dict) -> dict:
    e = batch["eintraege"]
    return {
        "id": batch["id"], "erstellt": batch["erstellt"], "status": batch["status"],
        "anzahl": sum(x["status"] != "entfernt" for x in e),
        "gesendet": sum(x["status"] == "gesendet" for x in e),
        "sachbearbeitung": bool(batch.get("sachbearbeitung")),
    }


def baue_handler(cfg: Config, dienst: Dienst, token: str):
    auftrag = Auftrag()
    erlaubte_hosts = {f"127.0.0.1:{cfg.app.port}", f"localhost:{cfg.app.port}"}
    vorschauen: OrderedDict[str, str] = OrderedDict()
    portale = Portale(cfg.daten)

    def merke_vorschau(html: str) -> str:
        kennung = secrets.token_urlsafe(9)
        vorschauen[kennung] = html
        while len(vorschauen) > 12:
            vorschauen.popitem(last=False)
        return kennung

    def vorschau_html(d: dict) -> str:
        art = str(d.get("art") or "lebenslauf")
        daten = lv.normalisiere(d["daten"]) if isinstance(d.get("daten"), dict) else dienst.unterlagen.daten()
        if art == "lebenslauf":
            return render.lebenslauf(daten, cfg.wurzel, "vorschau")
        if art == "projekte":
            return render.portfolio(daten, cfg.wurzel, "vorschau")
        u = dienst.unterlagen
        if d.get("batch") and d.get("i") is not None:
            e = dienst.speicher.lade(str(d["batch"]))["eintraege"][int(d["i"])]
            stelle = Stelle.aus_dict(e["stelle"])
            if e.get("kurzprofil"):
                daten["kurzprofil"] = e["kurzprofil"]
            from .anschreiben import Anschreiben
            a = Anschreiben.aus_dict(e["anschreiben"]) if e.get("anschreiben") else None
        else:
            stelle = Stelle(quelle="beispiel", refnr="", titel="Fachinformatiker für Anwendungsentwicklung (m/w/d)",
                            firma="Muster GmbH", ansprechpartner="Frau Petra Muster",
                            firmen_adresse=["Hafenstraße 4", "12345 Musterstadt"], art="ausbildung")
            from .anschreiben import Anschreiben
            a = Anschreiben(**BEISPIEL_BRIEF)
        if art == "deckblatt":
            angaben = {"position": re.sub(r"\s*\(.*?\)", "", stelle.titel), "firma": stelle.firma,
                       "art": "Ausbildung" if stelle.art == "ausbildung" else "",
                       "inhalt": [("Anschreiben", 2), ("Lebenslauf", 3), ("Projekte", 5)]}
            return render.deckblatt(daten, cfg.wurzel, angaben, "vorschau")
        if a is None:
            raise ValueError("Für diese Stelle gibt es noch kein Anschreiben")
        brief = u.brief(stelle, a, u.anlagen_namen(dienst.anlagen()))
        return render.anschreiben(daten, cfg.wurzel, brief, "vorschau")

    class Handler(BaseHTTPRequestHandler):
        server_version = "bewerbungsagent"

        def log_message(self, *_):
            pass


        def _json(self, daten, status=HTTPStatus.OK):
            roh = json.dumps(daten, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(roh)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(roh)

        def _datei(self, pfad: Path, typ: str | None = None):
            if not pfad.is_file():
                return self._json({"fehler": "nicht gefunden"}, HTTPStatus.NOT_FOUND)
            roh = pfad.read_bytes()
            if pfad.name == "index.html":
                roh = roh.replace(b"__TOKEN__", token.encode())
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", typ or mimetypes.guess_type(pfad.name)[0] or "application/octet-stream")
            self.send_header("Content-Length", str(len(roh)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; style-src 'self' 'unsafe-inline'; frame-src 'self'; object-src 'self'")
            self.end_headers()
            self.wfile.write(roh)

        def _html(self, html: str):
            roh = html.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(roh)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", VORSCHAU_CSP)
            self.end_headers()
            self.wfile.write(roh)

        def _unterlage(self, art: str):
            u = dienst.unterlagen
            if not u.html_aktiv:
                return self._json({"fehler": "Kein Edge/Chrome/Chromium für den PDF-Druck gefunden"},
                                  HTTPStatus.SERVICE_UNAVAILABLE)
            try:
                if art == "lebenslauf.pdf":
                    erg = u.lebenslauf()
                elif art == "projekte.pdf":
                    erg = u.projektseite()
                else:
                    return self._json({"fehler": "unbekannt"}, HTTPStatus.NOT_FOUND)
            except drucker.DruckFehler as fehler:
                return self._json({"fehler": str(fehler)}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return self._datei(erg.pfad, "application/pdf")

        def _lokal(self) -> bool:
            return self.headers.get("Host", "") in erlaubte_hosts

        def _berechtigt(self) -> bool:
            return self._lokal() and secrets.compare_digest(self.headers.get("X-Token", ""), token)


        def do_GET(self):
            if not self._lokal():
                return self._json({"fehler": "Host nicht erlaubt"}, HTTPStatus.FORBIDDEN)
            pfad = unquote(urlparse(self.path).path)
            if pfad in ("/", "/index.html"):
                return self._datei(STATISCH / "index.html", "text/html; charset=utf-8")
            if pfad.startswith("/statisch/"):
                ziel = (STATISCH / pfad.removeprefix("/statisch/")).resolve()
                if STATISCH.resolve() not in ziel.parents:
                    return self._json({"fehler": "nein"}, HTTPStatus.FORBIDDEN)
                return self._datei(ziel)
            teile = [t for t in pfad.split("/") if t]
            if len(teile) == 3 and teile[0] == "vorschau":
                if not secrets.compare_digest(teile[1], token) or teile[2] not in vorschauen:
                    return self._json({"fehler": "Vorschau abgelaufen"}, HTTPStatus.NOT_FOUND)
                return self._html(vorschauen[teile[2]])
            if len(teile) == 3 and teile[:1] == ["unterlagen"] and secrets.compare_digest(teile[1], token):
                return self._unterlage(teile[2])
            if len(teile) == 5 and teile[:2] == ["api", "mappe"]:
                _, _, tok, batch_id, i = teile
                if not secrets.compare_digest(tok, token):
                    return self._json({"fehler": "Token"}, HTTPStatus.FORBIDDEN)
                e = dienst.speicher.lade(batch_id)["eintraege"][int(i)]
                return self._datei(Path(e.get("mappe") or e.get("lebenslauf") or ""), "application/pdf")
            if len(teile) == 5 and teile[:2] == ["api", "pdf"]:
                _, _, tok, batch_id, i = teile
                if not secrets.compare_digest(tok, token):
                    return self._json({"fehler": "Token"}, HTTPStatus.FORBIDDEN)
                try:
                    e = dienst.speicher.lade(batch_id)["eintraege"][int(i)]
                except (FileNotFoundError, IndexError, ValueError) as fehler:
                    return self._json({"fehler": str(fehler)}, HTTPStatus.NOT_FOUND)
                return self._datei(Path(e.get("pdf") or ""), "application/pdf")
            if len(teile) == 4 and teile[:2] == ["api", "anlage"]:
                _, _, tok, n = teile
                anlagen = dienst.anlagen()
                if not secrets.compare_digest(tok, token) or not n.isdigit() or int(n) >= len(anlagen):
                    return self._json({"fehler": "nicht gefunden"}, HTTPStatus.NOT_FOUND)
                return self._datei(anlagen[int(n)])
            if not self._berechtigt():
                return self._json({"fehler": "Token fehlt"}, HTTPStatus.FORBIDDEN)
            try:
                return self._get_api(teile)
            except FileNotFoundError as fehler:
                return self._json({"fehler": str(fehler)}, HTTPStatus.NOT_FOUND)

        def _get_api(self, teile: list[str]):
            if teile == ["api", "status"]:
                return self._json(self._status())
            if teile == ["api", "batches"]:
                return self._json([_kurz(b) for b in dienst.speicher.alle()])
            if len(teile) == 3 and teile[:2] == ["api", "batch"]:
                batch = dienst.speicher.lade(teile[2])
                batch["versand_probleme"] = dienst.pruefe_versand(batch)
                batch["einzel_probleme"] = dienst.smtp_probleme() + (
                    [] if dienst.anlagen() or dienst.erzeugt_lebenslauf() else ["kein Lebenslauf angelegt"])
                batch["ungemeldet"] = len(dienst.ungemeldet(batch))
                batch["anlagen"] = [a.name for a in dienst.anlagen()]
                batch["anhaenge"] = dienst.anhang_uebersicht()
                batch["druck"] = dienst.unterlagen.html_aktiv
                return self._json(batch)
            if teile == ["api", "auftrag"]:
                return self._json(auftrag.zustand())
            if teile == ["api", "historie"]:
                return self._json(self._historie())
            if teile == ["api", "lebenslauf"]:
                return self._json(self._lebenslauf())
            if teile == ["api", "modell"]:
                return self._json(self._modell())
            if teile == ["api", "quellen"]:
                return self._json(self._quellen())
            if teile == ["api", "agenten"]:
                return self._json(integrationen.alles(cfg.wurzel))
            return self._json({"fehler": "unbekannt"}, HTTPStatus.NOT_FOUND)

        def _lebenslauf(self) -> dict:
            vorhanden = lv.pfad(cfg.wurzel).exists()
            try:
                u = dienst.unterlagen
                daten = u.daten()
            except Exception:
                u, daten = None, lv.lade(cfg.wurzel)
            return {
                "daten": daten, "vorhanden": vorhanden,
                "yaml": yaml.safe_dump(daten, allow_unicode=True, sort_keys=False, width=110),
                "vorlagen": lv.VORLAGEN, "akzente": {k: v[0] for k, v in lv.AKZENTE.items()},
                "schriften": {k: v[0] for k, v in lv.SCHRIFTEN.items()}, "abschnitte": lv.ABSCHNITT_TITEL,
                "dokumente": asdict(cfg.dokumente), "druck": bool(u and u.html_aktiv),
                "browser": (u.browser if u else None) or "",
            }

        def _modell(self) -> dict:
            m = mc.lade(cfg.wurzel)
            prompts = []
            for aufgabe, beschreibung in mc.AUFGABEN.items():
                text, eigen = m.prompt_quelle(aufgabe)
                prompts.append({"aufgabe": aufgabe, "beschreibung": beschreibung, "text": text, "eigen": eigen,
                                "standard": m.standard_prompt(aufgabe)})
            llm = LLM(cfg)
            try:
                modelle = llm.modelle()
                erreichbar = True
            except LLMFehler:
                modelle, erreichbar = [], False
            bereit, info = llm.bereit() if erreichbar or llm.backend in ("claude-cli", "anthropic", "keins") \
                else (False, "Modellserver nicht erreichbar")
            return {
                "verbindung": {"backend": cfg.llm.backend, "modell": cfg.llm.modell, "basis_url": cfg.llm.basis_url,
                               "standard_url": llm._basis(), "timeout_s": cfg.llm.timeout_s},
                "backends": BACKENDS, "modelle": modelle, "bereit": bereit, "info": info,
                "voreinstellung": m.voreinstellung,
                "voreinstellungen": {k: m.basis(k).als_dict() for k in mc.VOREINSTELLUNGEN},
                "standard_werte": {k: v.als_dict() for k, v in mc.VOREINSTELLUNGEN.items()},
                "eigene_werte": m.voreinstellungen, "aufgaben_werte": m.aufgaben,
                "aufgaben_standard": mc.AUFGABEN_STANDARD, "aufgaben": mc.AUFGABEN, "prompts": prompts,
                "felder": list(mc.Einstellung().als_dict().keys()),
            }

        def _quellen(self) -> dict:
            k = cfg.schluessel
            try:
                formular = lesezeichen.formulardaten(dienst.profil, dienst.unterlagen.daten())
            except Exception:
                formular = {}
            return {
                "quellen": asdict(cfg.quellen),
                "schluessel": {"adzuna": bool(k.adzuna_id and k.adzuna_key), "jooble": bool(k.jooble),
                               "imap": bool(k.imap_host and k.imap_user and k.imap_password)},
                "portale": portale.liste(cfg), "wege": WEGE,
                "lesezeichen": {"uebernehmen": lesezeichen.uebernehmen(cfg.app.port),
                                "ausfuellen": lesezeichen.ausfuellen(formular) if formular else ""},
            }

        def _status(self) -> dict:
            profil_ok, profil_info = True, ""
            try:
                p = dienst.profil
                profil_info = f"{p.name} · {p.wohnort} · {', '.join(p.suchbegriffe)}"
            except Exception as fehler:
                profil_ok, profil_info = False, str(fehler)
            llm_ok, llm_info = dienst.llm.bereit()
            smtp = dienst.smtp_probleme()
            return {
                "pruefungen": [
                    {"name": "Profil", "ok": profil_ok, "info": profil_info},
                    {"name": "Anhänge", "ok": bool(dienst.anhang_uebersicht()),
                     "info": ", ".join(dienst.anhang_uebersicht()) or "kein Lebenslauf – Reiter Lebenslauf oder config.yaml: anlagen"},
                    {"name": f"Modell ({cfg.llm.backend})", "ok": llm_ok, "info": llm_info},
                    {"name": "E-Mail-Versand", "ok": not smtp,
                     "info": "; ".join(smtp) or f"{cfg.smtp.user} über {cfg.smtp.host}:{cfg.smtp.port}"},
                    {"name": "Sachbearbeitung", "ok": bool(cfg.mail.sachbearbeitung),
                     "info": cfg.mail.sachbearbeitung or "mail.sachbearbeitung in config.yaml"},
                    {"name": "Vault", "ok": dienst.vault.aktiv,
                     "info": str(dienst.vault.ordner) if dienst.vault.aktiv else "aus (vault.pfad leer)"},
                    {"name": "Lebenslauf", "ok": lv.pfad(cfg.wurzel).exists(),
                     "info": "profil/lebenslauf.yaml – im Reiter Lebenslauf bearbeiten"
                     if lv.pfad(cfg.wurzel).exists() else "noch nicht angelegt – Reiter Lebenslauf"},
                    {"name": "PDF-Druck", "ok": self._browser_ok(),
                     "info": self._browser_info()},
                ],
                "anzahl": cfg.suche.anzahl,
            }

        def _browser_ok(self) -> bool:
            return cfg.dokumente.engine.lower() != "fpdf" and bool(drucker.finde_browser(cfg.dokumente.browser))

        def _browser_info(self) -> str:
            if cfg.dokumente.engine.lower() == "fpdf":
                return "einfaches Layout (dokumente.engine: fpdf)"
            b = drucker.finde_browser(cfg.dokumente.browser)
            return b or "Edge, Chrome oder Chromium nicht gefunden – Pfad unter dokumente.browser eintragen"

        def _historie(self) -> list[dict]:
            zeilen = []
            for b in dienst.speicher.alle():
                for i, e in enumerate(b["eintraege"]):
                    if e["status"] == "gesendet":
                        s = e["stelle"]
                        zeilen.append({"batch": b["id"], "i": i, "datum": e["gesendet_am"], "firma": s["firma"],
                                       "titel": s["titel"], "ort": s["ort"], "email": s["email"], "url": s["url"],
                                       "rueckmeldung": e.get("rueckmeldung")})
            return sorted(zeilen, key=lambda z: z["datum"] or "", reverse=True)


        def do_POST(self):
            laenge = int(self.headers.get("Content-Length") or 0)
            if laenge > MAX_KOERPER:
                return self._json({"fehler": "Anfrage zu groß"}, HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
            roh = self.rfile.read(laenge) if laenge else b""
            if not self._berechtigt():
                return self._json({"fehler": "Token fehlt"}, HTTPStatus.FORBIDDEN)
            teile = [t for t in unquote(urlparse(self.path).path).split("/") if t]
            try:
                daten = json.loads(roh.decode("utf-8")) if roh else {}
                return self._post_api(teile, daten)
            except Abbruch as fehler:
                return self._json({"fehler": str(fehler)}, HTTPStatus.CONFLICT)
            except (FileNotFoundError, IndexError, ValueError, KeyError, QuellenFehler, yaml.YAMLError,
                    drucker.DruckFehler) as fehler:
                return self._json({"fehler": str(fehler)}, HTTPStatus.BAD_REQUEST)

        def _hintergrund(self, name: str, funktion):
            if not auftrag.starte(name, funktion):
                return self._json({"fehler": f"Es läuft schon: {auftrag.name}"}, HTTPStatus.CONFLICT)
            return self._json({"gestartet": name})

        def _post_api(self, teile: list[str], d: dict):
            neu = self._post_neu(teile, d)
            if neu is not None:
                return neu
            if teile == ["api", "lauf"]:
                return self._hintergrund("Neuer Lauf", lambda melde: {"batch": dienst.lauf(melde)["id"]})
            if len(teile) == 4 and teile[:2] == ["api", "batch"] and teile[3] == "verwerfen":
                return self._json(_kurz(dienst.verwerfen(teile[2])))
            if teile == ["api", "hinzufuegen"]:
                batch_id = str(d.get("batch") or "") or dienst.speicher.neuer_batch()["id"]
                felder = {k: str(d.get(k, "")) for k in ("firma", "titel", "beschreibung", "email", "ort", "url",
                                                         "art", "ansprechpartner")}
                if not felder["firma"].strip() or not felder["titel"].strip():
                    raise ValueError("Firma und Stellentitel sind Pflicht")
                return self._hintergrund("Stelle von Hand",
                                         lambda melde: {"batch": dienst.hinzufuegen(batch_id, melde=melde, **felder)["id"]})
            if len(teile) == 4 and teile[:2] == ["api", "batch"] and teile[3] == "senden":
                batch_id = teile[2]
                bestaetigung = str(d.get("bestaetigung", ""))
                nur = [int(x) for x in d["nur"]] if d.get("nur") is not None else None
                return self._hintergrund("Senden", lambda melde: {
                    "batch": dienst.senden(batch_id, bestaetigung, melde, nur=nur)["id"]})
            if len(teile) == 4 and teile[:2] == ["api", "batch"] and teile[3] == "nachweis":
                batch_id = teile[2]
                bestaetigung = str(d.get("bestaetigung", ""))
                return self._hintergrund("Nachweis senden", lambda melde: {
                    "batch": dienst.nachweis_senden(batch_id, bestaetigung, melde)["id"]})
            if len(teile) == 4 and teile[:2] == ["api", "batch"] and teile[3] == "uebernehmen":
                batch_id, refnr = teile[2], str(d.get("refnr", ""))
                return self._hintergrund("Anschreiben erstellen", lambda melde: {
                    "batch": dienst.uebernehmen(batch_id, refnr, melde)["id"]})
            if len(teile) == 5 and teile[:2] == ["api", "batch"]:
                _, _, batch_id, i, aktion = teile
                i = int(i)
                if aktion == "text":
                    absaetze = [str(p) for p in d.get("absaetze", [])]
                    return self._json(dienst.setze_text(batch_id, i, str(d.get("betreff", "")), absaetze))
                if aktion == "neu":
                    return self._hintergrund("Neu schreiben", lambda melde: dienst.neu_schreiben(batch_id, i, melde))
                if aktion == "entfernen":
                    return self._hintergrund("Entfernen und nachrücken",
                                             lambda melde: {"batch": dienst.entferne(batch_id, i, True, melde)["id"]})
                if aktion == "rueckmeldung":
                    return self._json(dienst.rueckmeldung(batch_id, i, str(d.get("art", ""))))
                if aktion == "adresse":
                    return self._json(dienst.setze_adresse(batch_id, i, str(d.get("email", ""))))
                if aktion == "beworben":
                    return self._json(dienst.als_beworben(batch_id, i, str(d.get("weg", "portal"))))
            return self._json({"fehler": "unbekannt"}, HTTPStatus.NOT_FOUND)

        # ------------------------------------------------------------ Lebenslauf, Modell, Quellen

        def _post_neu(self, teile: list[str], d: dict):
            if teile == ["api", "vorschau"]:
                return self._json({"id": merke_vorschau(vorschau_html(d)), "token": token})
            if teile == ["api", "lebenslauf"]:
                if "yaml" in d:
                    daten = yaml.safe_load(str(d["yaml"])) or {}
                    if not isinstance(daten, dict):
                        raise ValueError("Der YAML-Text muss Abschnitte wie person:, erfahrung: enthalten")
                else:
                    daten = d.get("daten") or {}
                lv.speichere(cfg.wurzel, daten)
                dienst.profil_neu_laden()
                return self._json(self._lebenslauf())
            if teile == ["api", "lebenslauf", "aus-profil"]:
                return self._json({"daten": lv.aus_profil(dienst.profil)})
            if teile == ["api", "bild"]:
                return self._json({"pfad": self._bild_speichern(d)})
            if teile == ["api", "dokumente"]:
                werte = {**asdict(cfg.dokumente), **{k: v for k, v in d.items() if k in asdict(cfg.dokumente)}}
                config_mod.setze_abschnitt(cfg.wurzel, "dokumente", werte)
                for k, v in werte.items():
                    setattr(cfg.dokumente, k, v)
                return self._json(werte)
            if teile == ["api", "portfolio"]:
                quelle, anzahl, ersetzen = str(d.get("quelle") or ""), int(d.get("max") or 6), bool(d.get("ersetzen"))
                if not quelle.strip():
                    raise ValueError("Adresse oder Ordner der Portfolio-Website angeben")

                def importieren(melde):
                    from . import portfolio
                    melde(f"Lese Projekte aus {quelle} ...")
                    daten = dienst.unterlagen.daten()
                    neu = portfolio.importiere(quelle, cfg.wurzel, anzahl)
                    melde(f"{len(neu)} Projekte gefunden, {sum(1 for p in neu if p['bild'])} mit Vorschaubild")
                    daten["projekte"] = portfolio.zusammenfuehren(daten["projekte"], neu, ersetzen)
                    lv.speichere(cfg.wurzel, daten)
                    dienst.profil_neu_laden()
                    return {"projekte": [p["titel"] for p in daten["projekte"]]}
                return self._hintergrund("Portfolio importieren", importieren)
            if teile == ["api", "ats"]:
                batch_id = str(d.get("batch") or "")
                i = int(d["i"]) if d.get("i") is not None else None
                titel, text = str(d.get("titel") or ""), str(d.get("text") or "")
                if not batch_id and not text.strip():
                    raise ValueError("Anzeigentext einfügen")
                if d.get("modell"):
                    return self._hintergrund("ATS-Check mit Modell", lambda melde: dienst.ats(
                        batch_id, i, titel, text, True, melde))
                return self._json(dienst.ats(batch_id, i, titel, text, False))
            if teile == ["api", "ats", "kurzprofil"]:
                batch_id = str(d.get("batch") or "")
                i = int(d["i"]) if d.get("i") is not None else None
                titel, text = str(d.get("titel") or ""), str(d.get("text") or "")
                return self._hintergrund("Kurzprofil vorschlagen", lambda melde: dienst.ats_kurzprofil(
                    batch_id, i, titel, text, melde))
            if len(teile) == 5 and teile[:2] == ["api", "batch"] and teile[4] == "kurzprofil":
                return self._json(dienst.setze_kurzprofil(teile[2], int(teile[3]), str(d.get("kurzprofil") or "")))
            if teile == ["api", "modell"]:
                return self._json(self._modell_speichern(d))
            if teile == ["api", "modell", "prompt"]:
                m = mc.lade(cfg.wurzel)
                aufgabe = str(d.get("aufgabe") or "")
                if d.get("zuruecksetzen"):
                    m.prompt_zuruecksetzen(aufgabe)
                else:
                    if not str(d.get("text") or "").strip():
                        raise ValueError("Leerer Prompt - zum Zurücksetzen 'Standard' wählen")
                    m.setze_prompt(aufgabe, str(d["text"]))
                dienst._llm = None
                return self._json(self._modell())
            if teile == ["api", "modell", "beispiel"]:
                return self._json({"nutzer": self._beispiel_eingabe(d)})
            if teile == ["api", "modell", "test"]:
                return self._hintergrund("Prompt-Labor", lambda melde: self._prompt_test(d, melde))
            if teile == ["api", "agenten", "hermes-skill"]:
                return self._json({"pfad": str(integrationen.hermes_skill_installieren(cfg.wurzel))})
            if teile == ["api", "quellen"]:
                werte = {**asdict(cfg.quellen), **{k: v for k, v in d.items() if k in asdict(cfg.quellen)}}
                werte["max_treffer"] = max(5, min(200, int(werte["max_treffer"])))
                werte["mail_tage"] = max(1, min(60, int(werte["mail_tage"])))
                config_mod.setze_abschnitt(cfg.wurzel, "quellen", werte)
                for k, v in werte.items():
                    setattr(cfg.quellen, k, v)
                return self._json(self._quellen())
            if teile == ["api", "portal"]:
                portale.setze(str(d.get("id") or ""), d.get("konto"), d.get("alarm"), d.get("notiz"))
                return self._json(self._quellen())
            if teile == ["api", "stelle", "link"]:
                url = str(d.get("url") or "")
                daten = d.get("daten") if isinstance(d.get("daten"), dict) else None
                text, titel, batch_id = str(d.get("text") or ""), str(d.get("titel") or ""), str(d.get("batch") or "")
                if not (url or daten or text):
                    raise ValueError("Link zur Anzeige angeben")
                return self._hintergrund("Anzeige übernehmen", lambda melde: {"batch": dienst.stelle_aus_link(
                    url, daten, text, titel, "", batch_id, melde)["id"]})
            if teile == ["api", "stelle", "pruefen"]:
                from .quellen import jsonld
                daten = d.get("daten") if isinstance(d.get("daten"), dict) else None
                s = jsonld.aus_daten(daten, str(d.get("url") or "")) if daten else \
                    jsonld.aus_text(str(d.get("titel") or ""), "", str(d.get("text") or ""), str(d.get("url") or ""))
                return self._json(s.als_dict())
            return None

        def _bild_speichern(self, d: dict) -> str:
            art = str(d.get("art") or "foto")
            treffer = re.match(r"^data:image/(png|jpe?g|webp);base64,(.+)$", str(d.get("daten") or ""), re.S)
            if art not in ("foto", "projekt", "unterschrift") or not treffer:
                raise ValueError("Bitte ein Bild als PNG, JPG oder WebP wählen")
            endung = {"jpeg": "jpg"}.get(treffer.group(1), treffer.group(1))
            name = re.sub(r"[^\w-]+", "-", str(d.get("name") or art)).strip("-").lower()[:40] or art
            ordner = cfg.wurzel / "profil" / "bilder" / ("projekte" if art == "projekt" else "")
            ordner.mkdir(parents=True, exist_ok=True)
            ziel = ordner / f"{name}.{endung}"
            ziel.write_bytes(base64.b64decode(treffer.group(2)))
            return str(ziel.relative_to(cfg.wurzel)).replace("\\", "/")

        def _modell_speichern(self, d: dict) -> dict:
            m = mc.lade(cfg.wurzel)
            if d.get("voreinstellung") in mc.VOREINSTELLUNGEN:
                m.voreinstellung = d["voreinstellung"]
            felder = set(mc.Einstellung().als_dict())

            def sauber(werte) -> dict:
                aus = {}
                for k, v in (werte or {}).items():
                    if k in felder and v not in ("", None):
                        aus[k] = v
                return aus
            if isinstance(d.get("voreinstellungen"), dict):
                m.voreinstellungen = {k: sauber(v) for k, v in d["voreinstellungen"].items()
                                      if k in mc.VOREINSTELLUNGEN and sauber(v)}
            if isinstance(d.get("aufgaben"), dict):
                m.aufgaben = {k: sauber(v) for k, v in d["aufgaben"].items() if k in mc.AUFGABEN and sauber(v)}
            if isinstance(d.get("verbindung"), dict):
                v = d["verbindung"]
                if v.get("backend") and v["backend"] not in BACKENDS:
                    raise ValueError(f"Unbekanntes Backend: {v['backend']}")
                m.verbindung = {k: str(v.get(k) or "") for k in ("backend", "modell", "basis_url")}
                for k, wert in m.verbindung.items():
                    if wert or k != "backend":
                        setattr(cfg.llm, k, wert)
            m.speichere()
            dienst._llm = None
            return self._modell()

        def _beispiel_stelle(self, d: dict) -> Stelle:
            if d.get("batch") and d.get("i") is not None:
                return Stelle.aus_dict(dienst.speicher.lade(str(d["batch"]))["eintraege"][int(d["i"])]["stelle"])
            for b in dienst.speicher.alle():
                for e in b["eintraege"]:
                    if e["stelle"].get("beschreibung"):
                        return Stelle.aus_dict(e["stelle"])
            from .quellen.gemeinsam import baue
            return baue("beispiel", "1", "Ausbildung Fachinformatiker für Anwendungsentwicklung (m/w/d)",
                        "Muster Software GmbH", BEISPIEL_ANZEIGE, ort="Musterstadt")

        def _beispiel_eingabe(self, d: dict) -> str:
            from . import anschreiben as ans
            from . import ats as ats_mod
            aufgabe = str(d.get("aufgabe") or "")
            s = self._beispiel_stelle(d)
            p = dienst.profil
            e = LLM(cfg).einstellung(aufgabe or None)
            if aufgabe == "bewertung":
                return (f"# PROFIL\n{p.text[: e.profil_zeichen]}\n\n# STELLE\n{s.titel} bei {s.firma}, "
                        f"{s.ort}\n\n{s.beschreibung[: e.anzeige_zeichen]}")
            if aufgabe == "ats_schluesselwoerter":
                return f"STELLE: {s.titel}\n\nANZEIGE:\n{s.beschreibung[:6000]}"
            if aufgabe == "ats_kurzprofil":
                d_lv = dienst.unterlagen.daten()
                bericht = ats_mod.pruefe(s.titel, s.beschreibung, d_lv, p.text)
                return (f"STELLE: {s.titel}\n\nTREFFER: {', '.join(b.wort for b in bericht.gefunden)}\n"
                        f"FEHLT: {', '.join(b.wort for b in bericht.fehlend)}\n\nBISHERIGES KURZPROFIL:\n"
                        f"{d_lv.get('kurzprofil', '')}\n\nLEBENSLAUF:\n{lv.als_text(d_lv)[:4000]}\n\nPROFIL:\n{p.text[:2500]}")
            if aufgabe == "stichpunkte":
                d_lv = dienst.unterlagen.daten()
                punkte = next((x["punkte"] for x in d_lv["erfahrung"] if x.get("punkte")), ["Kunden beraten", "Kasse"])
                return "STICHPUNKTE:\n" + "\n".join(f"- {x}" for x in punkte)
            if aufgabe == "agent":
                return "Such mir neue Ausbildungsplätze und schreib die Anschreiben."
            return ans.nutzer_prompt(s, p, e.anzeige_zeichen, e.profil_zeichen)

        def _prompt_test(self, d: dict, melde) -> dict:
            aufgabe = str(d.get("aufgabe") or "anschreiben_schreiben")
            if aufgabe == "kette":
                return self._kette(d, melde)
            llm = LLM(cfg)
            system = str(d.get("system") or "") or llm.prompt(aufgabe)
            nutzer = str(d.get("nutzer") or "")
            if not nutzer.strip():
                raise Abbruch("Eingabe für das Modell fehlt")
            if isinstance(d.get("einstellung"), dict):
                # nur fuer diesen Test, nichts wird gespeichert
                llm.mcfg.aufgaben[aufgabe] = {**llm.mcfg.aufgaben.get(aufgabe, {}),
                                              **{k: v for k, v in d["einstellung"].items() if v not in ("", None)}}
            e = llm.einstellung(aufgabe)
            melde(f"{llm.backend} · {cfg.llm.modell or 'erstes geladenes Modell'} · Temperatur {e.temperatur}, "
                  f"Kontext {e.kontext}, max. {e.max_tokens} Tokens, Schema {'an' if e.strukturiert else 'aus'}")
            from .schemata import JE_AUFGABE
            schema = JE_AUFGABE.get(aufgabe) if d.get("schema", True) else None
            antwort = llm.frage(system, nutzer, aufgabe, schema)
            m = llm.letzte.als_dict() if llm.letzte else {}
            melde(f"fertig in {m.get('sekunden')} s" + (f", {m['tokens_pro_s']} Tokens/s" if m.get("tokens_pro_s") else ""))
            pruefung = None
            if aufgabe in ("anschreiben", "anschreiben_schreiben"):
                from . import anschreiben as ans
                from .llm import json_aus
                try:
                    j = json_aus(antwort)
                    probe = ans.Anschreiben(str(j.get("betreff") or ""), "Sehr geehrte Damen und Herren,",
                                            [str(x) for x in j.get("absaetze") or []])
                    pruefung = ans.pruefe(probe, dienst.profil, nutzer)
                except Exception as fehler:
                    pruefung = [f"keine gültige Antwort: {fehler}"]
            return {"antwort": antwort, "messung": m, "system": system, "maengel": pruefung}

        def _kette(self, d: dict, melde) -> dict:
            """Ganzes Anschreiben wie im echten Lauf - mit allen Schritten und Zeiten."""
            from . import anschreiben as ans
            llm = LLM(cfg)
            schritte = []
            frage = llm.frage

            def mit_messung(*args, **kw):
                text = frage(*args, **kw)
                if llm.letzte:
                    schritte.append(llm.letzte.als_dict())
                    melde(f"{llm.letzte.aufgabe or 'Schritt'}: {llm.letzte.sekunden:.1f} s")
                return text
            llm.frage = mit_messung
            s = self._beispiel_stelle(d)
            melde(f"Anschreiben für {s.firma} ({'zweistufig' if llm.mehrstufig else 'einstufig'}) ...")
            a = ans.erzeuge(s, dienst.profil, llm, versuche=1)
            text = f"Betreff: {a.betreff}\n\n{a.anrede}\n\n" + "\n\n".join(a.absaetze) + f"\n\n{a.gruss}"
            gesamt = round(sum(x["sekunden"] for x in schritte), 2)
            return {"antwort": text, "messung": {"sekunden": gesamt, "schritte": schritte,
                                                  "tokens_aus": sum(x.get("tokens_aus") or 0 for x in schritte) or None},
                    "maengel": a.maengel, "system": ""}

    return Handler


def starte(cfg: Config, oeffnen: bool = True) -> None:
    dienst = Dienst(cfg)
    token = secrets.token_urlsafe(24)
    server = ThreadingHTTPServer(("127.0.0.1", cfg.app.port), baue_handler(cfg, dienst, token))
    url = f"http://127.0.0.1:{cfg.app.port}/"
    print(f"Bewerbungsagent läuft: {url}  (Strg+C beendet)")
    if oeffnen:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
