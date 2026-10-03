from __future__ import annotations

import json
import mimetypes
import secrets
import threading
import traceback
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from .config import Config
from .dienst import Abbruch, Dienst
from .speicher import jetzt

STATISCH = Path(__file__).parent / "statisch"


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
                    [] if dienst.anlagen() else ["kein Lebenslauf unter 'anlagen' gefunden"])
                batch["ungemeldet"] = len(dienst.ungemeldet(batch))
                batch["anlagen"] = [a.name for a in dienst.anlagen()]
                return self._json(batch)
            if teile == ["api", "auftrag"]:
                return self._json(auftrag.zustand())
            if teile == ["api", "historie"]:
                return self._json(self._historie())
            return self._json({"fehler": "unbekannt"}, HTTPStatus.NOT_FOUND)

        def _status(self) -> dict:
            profil_ok, profil_info = True, ""
            try:
                p = dienst.profil
                profil_info = f"{p.name} · {p.wohnort} · {', '.join(p.suchbegriffe)}"
            except Exception as fehler:
                profil_ok, profil_info = False, str(fehler)
            llm_ok, llm_info = dienst.llm.bereit()
            anlagen = dienst.anlagen()
            smtp = dienst.smtp_probleme()
            return {
                "pruefungen": [
                    {"name": "Profil", "ok": profil_ok, "info": profil_info},
                    {"name": "Anlagen", "ok": bool(anlagen),
                     "info": ", ".join(a.name for a in anlagen) or "Lebenslauf fehlt (config.yaml: anlagen)"},
                    {"name": f"Modell ({cfg.llm.backend})", "ok": llm_ok, "info": llm_info},
                    {"name": "E-Mail-Versand", "ok": not smtp,
                     "info": "; ".join(smtp) or f"{cfg.smtp.user} über {cfg.smtp.host}:{cfg.smtp.port}"},
                    {"name": "Sachbearbeitung", "ok": bool(cfg.mail.sachbearbeitung),
                     "info": cfg.mail.sachbearbeitung or "mail.sachbearbeitung in config.yaml"},
                    {"name": "Vault", "ok": dienst.vault.aktiv,
                     "info": str(dienst.vault.ordner) if dienst.vault.aktiv else "aus (vault.pfad leer)"},
                ],
                "anzahl": cfg.suche.anzahl,
            }

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
            roh = self.rfile.read(min(laenge, 1_000_000)) if laenge else b""
            if not self._berechtigt():
                return self._json({"fehler": "Token fehlt"}, HTTPStatus.FORBIDDEN)
            teile = [t for t in unquote(urlparse(self.path).path).split("/") if t]
            try:
                daten = json.loads(roh.decode("utf-8")) if roh else {}
                return self._post_api(teile, daten)
            except Abbruch as fehler:
                return self._json({"fehler": str(fehler)}, HTTPStatus.CONFLICT)
            except (FileNotFoundError, IndexError, ValueError, KeyError) as fehler:
                return self._json({"fehler": str(fehler)}, HTTPStatus.BAD_REQUEST)

        def _hintergrund(self, name: str, funktion):
            if not auftrag.starte(name, funktion):
                return self._json({"fehler": f"Es läuft schon: {auftrag.name}"}, HTTPStatus.CONFLICT)
            return self._json({"gestartet": name})

        def _post_api(self, teile: list[str], d: dict):
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
