from __future__ import annotations

import asyncio
import email
import json
import subprocess
import threading
import urllib.error
import urllib.request
from pathlib import Path
from email import policy

import pytest
from aiosmtpd.controller import Controller
from aiosmtpd.smtp import AuthResult

from bewerbungsagent.dienst import Abbruch, Dienst
from bewerbungsagent.speicher import ENTFERNT, GESENDET

from conftest import FalscheQuelle, FalschesModell, anzeige, baue_config, freier_port


class Sammler:
    def __init__(self):
        self.mails = []

    async def handle_DATA(self, server, session, envelope):
        self.mails.append((envelope.rcpt_tos, email.message_from_bytes(envelope.content, policy=policy.default)))
        return "250 OK"


@pytest.fixture
def smtp():
    sammler = Sammler()
    port = freier_port()
    controller = Controller(sammler, hostname="127.0.0.1", port=port, auth_require_tls=False,
                            authenticator=lambda *a: AuthResult(success=True))
    controller.start()
    yield port, sammler
    controller.stop()


def _dienst(projekt, smtp_port=0, anzeigen=None, modell=None, **suche):
    cfg = baue_config(projekt, smtp_port, **suche)
    anzeigen = anzeigen if anzeigen is not None else [anzeige(i) for i in range(14)] + [anzeige(90 + i, email=False) for i in range(3)]
    return Dienst(cfg, quelle=FalscheQuelle(anzeigen), llm=modell or FalschesModell())


def _git_log(projekt):
    return subprocess.run(["git", "-C", str(projekt / "vault"), "log", "--oneline"], capture_output=True, text=True).stdout


def test_lauf_legt_entwuerfe_pdfs_und_vault_notizen_an(projekt):
    d = _dienst(projekt)
    batch = d.lauf(melde=lambda _: None)
    assert len(batch["eintraege"]) == 8
    assert len(batch["reserve"]) == 6 and len(batch["ohne_email"]) == 3
    for e in batch["eintraege"]:
        assert e["anschreiben"]["maengel"] == []
        assert (projekt / "vault" / e["vault_notiz"]).exists()
        assert e["pdf"].endswith(".pdf")
    notiz = (projekt / "vault" / batch["eintraege"][0]["vault_notiz"]).read_text(encoding="utf-8")
    assert "bewerbung: vorgeschlagen" in notiz and "## Stellenausschreibung" in notiz and "[[00 - Index]]" in notiz
    uebersicht = (projekt / "vault" / "Bewerbungen" / "00 - Bewerbungen Uebersicht.md").read_text(encoding="utf-8")
    assert "## Von Hand bewerben" in uebersicht
    assert "Lauf" in _git_log(projekt)


def test_eigene_notizen_ueberleben_neuschreiben(projekt):
    d = _dienst(projekt)
    batch = d.lauf(melde=lambda _: None)
    pfad = projekt / "vault" / batch["eintraege"][0]["vault_notiz"]
    text = pfad.read_text(encoding="utf-8").replace("_Gesprächstermine, Rückmeldungen, Eindrücke._", "Telefonat am Montag")
    pfad.write_text(text, encoding="utf-8")
    d.setze_text(batch["id"], 0, "Bewerbung als X", ["Absatz " * 60, "Zweiter " * 60, "Dritter " * 40])
    assert "Telefonat am Montag" in pfad.read_text(encoding="utf-8")


def test_entfernen_laesst_reserve_nachruecken(projekt):
    d = _dienst(projekt)
    batch = d.lauf(melde=lambda _: None)
    batch = d.entferne(batch["id"], 2, melde=lambda _: None)
    assert batch["eintraege"][2]["status"] == ENTFERNT
    assert len(batch["eintraege"]) == 9 and batch["eintraege"][8]["anschreiben"]


def test_senden_braucht_woertliche_bestaetigung(projekt, smtp):
    port, sammler = smtp
    d = _dienst(projekt, port)
    batch = d.lauf(melde=lambda _: None)
    for falsch in ("", "senden", "ja", "SENDEN "):
        with pytest.raises(Abbruch):
            d.senden(batch["id"], falsch, melde=lambda _: None, pause_s=0)
    assert sammler.mails == []


def test_versand_an_firmen_und_sachbearbeitung(projekt, smtp):
    port, sammler = smtp
    d = _dienst(projekt, port)
    batch = d.lauf(melde=lambda _: None)
    d.entferne(batch["id"], 0, nachruecken=False, melde=lambda _: None)
    batch = d.senden(batch["id"], "SENDEN", melde=lambda _: None, pause_s=0)

    assert sum(e["status"] == GESENDET for e in batch["eintraege"]) == 7
    assert len(sammler.mails) == 8
    firmen = [m for r, m in sammler.mails if "sb@amt.example" not in r]
    empf, nachweis = next((r, m) for r, m in sammler.mails if "sb@amt.example" in r)
    for m in firmen:
        namen = [t.get_filename() for t in m.iter_attachments()]
        assert namen[0].startswith("Anschreiben_Erika_Beispiel_") and "Lebenslauf.pdf" in namen
        assert "Bcc" not in m
    assert "erika@example.org" in empf
    anhaenge = [t.get_filename() for t in nachweis.iter_attachments()]
    assert anhaenge[0].startswith("Bewerbungsnachweis") and len(anhaenge) == 8
    assert batch["sachbearbeitung"]["anzahl"] == 7

    zweiter = d.lauf(melde=lambda _: None)
    alte = {e["stelle"]["firma"] for e in batch["eintraege"] if e["status"] == GESENDET}
    assert not alte & {e["stelle"]["firma"] for e in zweiter["eintraege"]}

    notiz = (projekt / "vault" / batch["eintraege"][1]["vault_notiz"]).read_text(encoding="utf-8")
    assert "bewerbung: gesendet" in notiz and "status: umgesetzt" in notiz
    assert "gesendet" in _git_log(projekt)

    with pytest.raises(Abbruch, match="keine offenen"):
        d.senden(batch["id"], "SENDEN", melde=lambda _: None, pause_s=0)


def test_ohne_smtp_kein_versand(projekt):
    d = _dienst(projekt)
    d.cfg.smtp.password = ""
    batch = d.lauf(melde=lambda _: None)
    with pytest.raises(Abbruch, match="SMTP"):
        d.senden(batch["id"], "SENDEN", pause_s=0)


def _server(d):
    from http.server import ThreadingHTTPServer
    from bewerbungsagent.app import baue_handler
    server = ThreadingHTTPServer(("127.0.0.1", d.cfg.app.port), baue_handler(d.cfg, d, "tok"))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _anfrage(port, pfad, daten=None, token="tok", host=None):
    kopf = {"X-Token": token, "Content-Type": "application/json"}
    if host:
        kopf["Host"] = host
    req = urllib.request.Request(f"http://127.0.0.1:{port}{pfad}", headers=kopf,
                                 data=None if daten is None else json.dumps(daten).encode())
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as fehler:
        return fehler.code, fehler.read()


def test_app_schuetzt_api_und_liefert_daten(projekt):
    d = _dienst(projekt)
    batch = d.lauf(melde=lambda _: None)
    server = _server(d)
    port = d.cfg.app.port
    try:
        status, html = _anfrage(port, "/", token="")
        assert status == 200 and b'content="tok"' in html
        assert _anfrage(port, "/api/batches", token="falsch")[0] == 403
        assert _anfrage(port, "/api/batches", host="boese.example")[0] == 403
        assert _anfrage(port, f"/api/batch/{batch['id']}/senden", {"bestaetigung": "SENDEN"}, token="")[0] == 403

        status, roh = _anfrage(port, "/api/batches")
        assert status == 200 and json.loads(roh)[0]["anzahl"] == 8
        status, roh = _anfrage(port, f"/api/batch/{batch['id']}")
        assert "SMTP" not in " ".join(json.loads(roh)["versand_probleme"])
        status, roh = _anfrage(port, f"/api/pdf/tok/{batch['id']}/0")
        assert status == 200 and roh.startswith(b"%PDF")
        assert _anfrage(port, f"/api/pdf/falsch/{batch['id']}/0")[0] == 403
        assert _anfrage(port, "/statisch/../config.py")[0] in (403, 404)

        status, roh = _anfrage(port, f"/api/batch/{batch['id']}/1/text",
                               {"betreff": "Bewerbung als Test", "absaetze": ["Eins " * 60, "Zwei " * 60, "Drei " * 30]})
        assert status == 200 and json.loads(roh)["anschreiben"]["betreff"].startswith("Bewerbung als Test")
        status, roh = _anfrage(port, "/api/status")
        assert {p["name"] for p in json.loads(roh)["pruefungen"]} >= {"Profil", "Vault", "E-Mail-Versand"}
    finally:
        server.shutdown()


def test_mcp_bietet_kein_senden_an():
    from bewerbungsagent.mcp_server import server
    werkzeuge = asyncio.run(server.list_tools())
    namen = {w.name for w in werkzeuge}
    assert {"lauf_starten", "lauf_zeigen", "anschreiben_setzen", "profil_zeigen", "stelle_hinzufuegen",
            "stelle_uebernehmen"} <= namen
    assert not any("send" in n for n in namen)


def test_stelle_in_zwei_laeufen_nur_einmal_in_uebersicht(projekt, smtp):
    port, _ = smtp
    d = _dienst(projekt, port)
    alt = d.lauf(melde=lambda _: None)
    neu = d.lauf(melde=lambda _: None)
    d.senden(neu["id"], "SENDEN", melde=lambda _: None, pause_s=0)
    d.setze_text(alt["id"], 0, "Bewerbung als Alt", ["Alt " * 60, "Alt " * 60, "Alt " * 30])
    uebersicht = (projekt / "vault" / "Bewerbungen" / "00 - Bewerbungen Uebersicht.md").read_text(encoding="utf-8")
    notiz = Path(neu["eintraege"][0]["vault_notiz"]).stem
    assert uebersicht.count(f"[[{notiz}]]") == 1
    text = (projekt / "vault" / neu["eintraege"][0]["vault_notiz"]).read_text(encoding="utf-8")
    assert "bewerbung: gesendet" in text and "Bewerbung als Alt" not in text


def test_lauf_ohne_laufendes_modell_bricht_nicht_ab(projekt):
    import httpx
    from bewerbungsagent.llm import LLM

    def aus(request):
        raise httpx.ConnectError("Verbindung verweigert")

    cfg = baue_config(projekt)
    d = Dienst(cfg, quelle=FalscheQuelle([anzeige(i) for i in range(10)]),
               llm=LLM(cfg, httpx.Client(transport=httpx.MockTransport(aus))))
    batch = d.lauf(melde=lambda _: None)
    assert len(batch["eintraege"]) == 8
    assert all(e["anschreiben"] is None and "nicht erreichbar" in e["fehler"] for e in batch["eintraege"])
    assert d.pruefe_versand(batch)


def test_mindestpassung_verhindert_unpassende_anschreiben(projekt):
    d = _dienst(projekt)
    d.cfg.suche.mindest_passung_modell = 90
    batch = d.lauf(melde=lambda _: None)
    assert batch["eintraege"] == []


def test_smtp_pruefung_outlook_und_fremdes_absenderkonto(projekt):
    d = _dienst(projekt)
    assert d.smtp_probleme() == []
    d.cfg.smtp.host = "smtp-mail.outlook.com"
    assert any("Outlook" in p for p in d.smtp_probleme())
    d.cfg.smtp.host, d.cfg.smtp.user = "smtp.gmail.com", "jemand.anders@gmail.com"
    assert any("passt nicht" in p for p in d.smtp_probleme())


def test_lauf_verwerfen(projekt):
    d = _dienst(projekt)
    batch = d.lauf(melde=lambda _: None)
    batch = d.verwerfen(batch["id"])
    assert batch["status"] == "abgeschlossen" and all(e["status"] == ENTFERNT for e in batch["eintraege"])
    notiz = (projekt / "vault" / batch["eintraege"][0]["vault_notiz"]).read_text(encoding="utf-8")
    assert "bewerbung: verworfen" in notiz


def test_portal_anzeigen_landen_bei_selbst_bewerben(projekt):
    portal = anzeige(50, stellenangebotsBeschreibung="IT-Support. Bitte nur über unser Bewerbungsportal. "
                                                      "Bei Fragen: info@firma50.de")
    d = _dienst(projekt, anzeigen=[anzeige(i) for i in range(3)] + [portal])
    batch = d.lauf(melde=lambda _: None)
    assert "Firma 50 GmbH" not in {e["stelle"]["firma"] for e in batch["eintraege"]}
    selbst = {s["firma"]: s["weg_grund"] for s in batch["ohne_email"]}
    assert "Firma 50 GmbH" in selbst and selbst["Firma 50 GmbH"]


def _mit_portal(projekt, port=0):
    portal = anzeige(50, stellenangebotsBeschreibung="IT-Support. Bitte nur über unser Bewerbungsportal.")
    d = _dienst(projekt, port, anzeigen=[anzeige(i) for i in range(2)] + [portal])
    return d, d.lauf(melde=lambda _: None)


def test_einzeln_senden_und_nachweis_nur_fuer_neues(projekt, smtp):
    port, sammler = smtp
    d, batch = _mit_portal(projekt, port)
    batch = d.senden(batch["id"], "SENDEN", melde=lambda _: None, pause_s=0, nur=[0])
    assert [e["status"] for e in batch["eintraege"]] == [GESENDET, "entwurf"]
    assert len(sammler.mails) == 2
    batch = d.senden(batch["id"], "SENDEN", melde=lambda _: None, pause_s=0, nur=[1])
    assert len(sammler.mails) == 4
    letzter = sammler.mails[-1][1]
    assert "1 Bewerbung vom" in letzter["Subject"]
    with pytest.raises(Abbruch, match="nicht offen"):
        d.senden(batch["id"], "SENDEN", pause_s=0, nur=[0])


def test_portal_stelle_uebernehmen_als_beworben_und_nachweis(projekt, smtp):
    port, sammler = smtp
    d, batch = _mit_portal(projekt, port)
    ref = batch["ohne_email"][0]["refnr"]
    batch = d.uebernehmen(batch["id"], ref, melde=lambda _: None)
    i = len(batch["eintraege"]) - 1
    neu = batch["eintraege"][i]
    assert neu["anschreiben"] and neu["pdf"] and not batch["ohne_email"]
    batch = d.senden(batch["id"], "SENDEN", melde=lambda _: None, pause_s=0)
    assert batch["eintraege"][i]["status"] == "entwurf" and len(sammler.mails) == 3
    d.als_beworben(batch["id"], i, "portal")
    batch = d.nachweis_senden(batch["id"], "SENDEN", melde=lambda _: None)
    text = sammler.mails[-1][1].get_body(("plain",)).get_content()
    assert "online über das Bewerbungsportal" in text and len(sammler.mails) == 4
    assert batch["eintraege"][i]["gemeldet"]
    with pytest.raises(Abbruch, match="schon gemeldet"):
        d.nachweis_senden(batch["id"], "SENDEN")


def test_adresse_von_hand_und_stelle_von_hand(projekt, smtp):
    port, sammler = smtp
    d, batch = _mit_portal(projekt, port)
    batch = d.uebernehmen(batch["id"], batch["ohne_email"][0]["refnr"], melde=lambda _: None)
    i = len(batch["eintraege"]) - 1
    with pytest.raises(ValueError):
        d.setze_adresse(batch["id"], i, "keine adresse")
    d.setze_adresse(batch["id"], i, " Bewerbung@Firma50.de ")
    batch = d.hinzufuegen(batch["id"], "Zeitungs GmbH", "Mediengestalter (m/w/d)",
                          "Aus der Zeitung. Bewerbung an Frau Petra Klein.", "jobs@zeitung.example",
                          ort="Musterstadt", art="ausbildung", melde=lambda _: None)
    hand = batch["eintraege"][-1]
    assert hand["stelle"]["quelle"] == "manuell" and hand["stelle"]["ansprechpartner"] == "Frau Petra Klein"
    batch = d.senden(batch["id"], "SENDEN", melde=lambda _: None, pause_s=0, nur=[i, len(batch["eintraege"]) - 1])
    an = [r for r, _ in sammler.mails]
    assert any("bewerbung@firma50.de" in r for r in an) and any("jobs@zeitung.example" in r for r in an)
    with pytest.raises(ValueError):
        d.hinzufuegen(batch["id"], "", "Titel")


def test_app_von_hand_endpunkte(projekt, smtp):
    import time
    port_smtp, sammler = smtp
    d, batch = _mit_portal(projekt, port_smtp)
    server = _server(d)
    port = d.cfg.app.port

    def warte():
        for _ in range(100):
            if json.loads(_anfrage(port, "/api/auftrag")[1])["fertig"]:
                return json.loads(_anfrage(port, "/api/auftrag")[1])
            time.sleep(0.05)
        raise AssertionError("Auftrag haengt")

    try:
        bid = batch["id"]
        assert _anfrage(port, "/api/anlage/tok/0")[1].startswith(b"%PDF")
        assert _anfrage(port, "/api/anlage/falsch/0")[0] == 404
        assert _anfrage(port, f"/api/batch/{bid}/uebernehmen", {"refnr": batch["ohne_email"][0]["refnr"]})[0] == 200
        assert warte()["fehler"] is None
        b = json.loads(_anfrage(port, f"/api/batch/{bid}")[1])
        i = len(b["eintraege"]) - 1
        assert b["eintraege"][i]["anschreiben"] and b["anlagen"] == ["Lebenslauf.pdf"]
        assert _anfrage(port, f"/api/batch/{bid}/{i}/adresse", {"email": "quatsch"})[0] == 400
        assert _anfrage(port, f"/api/batch/{bid}/{i}/adresse", {"email": "hr@firma50.de"})[0] == 200
        _anfrage(port, f"/api/batch/{bid}/senden", {"bestaetigung": "ja", "nur": [i]})
        assert warte()["fehler"] and not sammler.mails
        _anfrage(port, f"/api/batch/{bid}/senden", {"bestaetigung": "SENDEN", "nur": [i]})
        assert warte()["fehler"] is None
        assert any("hr@firma50.de" in r for r, _ in sammler.mails)
        _anfrage(port, "/api/hinzufuegen", {"batch": bid, "firma": "Hand GmbH", "titel": "Mediengestalter",
                                            "art": "ausbildung", "beschreibung": "Aus der Zeitung."})
        assert warte()["fehler"] is None
        b = json.loads(_anfrage(port, f"/api/batch/{bid}")[1])
        j = len(b["eintraege"]) - 1
        assert b["eintraege"][j]["stelle"]["firma"] == "Hand GmbH"
        assert _anfrage(port, f"/api/batch/{bid}/{j}/beworben", {"weg": "post"})[0] == 200
        assert json.loads(_anfrage(port, f"/api/batch/{bid}")[1])["ungemeldet"] == 1
        _anfrage(port, f"/api/batch/{bid}/nachweis", {"bestaetigung": "SENDEN"})
        assert warte()["fehler"] is None
        assert "per Post" in sammler.mails[-1][1].get_body(("plain",)).get_content()
    finally:
        server.shutdown()


def test_nachweis_mit_portal_bewerbung_ohne_anschreiben(projekt, smtp):
    port, sammler = smtp
    d, batch = _mit_portal(projekt, port)
    d.cfg.llm.backend = "keins"
    batch = d.uebernehmen(batch["id"], batch["ohne_email"][0]["refnr"], melde=lambda _: None)
    i = len(batch["eintraege"]) - 1
    assert not batch["eintraege"][i]["pdf"]
    d.als_beworben(batch["id"], i, "portal")
    d.nachweis_senden(batch["id"], "SENDEN", melde=lambda _: None)
    assert "Bewerbungsportal" in sammler.mails[-1][1].get_body(("plain",)).get_content()


def test_manuelle_stelle_ohne_jobboersen_referenz(projekt, smtp):
    port, sammler = smtp
    d, batch = _mit_portal(projekt, port)
    batch = d.hinzufuegen(batch["id"], "Hand GmbH", "Mediengestalter", "Aus der Zeitung.", "jobs@hand.example",
                          melde=lambda _: None)
    i = len(batch["eintraege"]) - 1
    assert "Ref." not in batch["eintraege"][i]["anschreiben"]["betreff"]
    d.senden(batch["id"], "SENDEN", melde=lambda _: None, pause_s=0, nur=[i])
    firma, nachweis = sammler.mails[-2][1], sammler.mails[-1][1]
    text = firma.get_body(("plain",)).get_content()
    assert "Jobbörse" not in text and "manuell-" not in text
    assert nachweis["Subject"].endswith(f"1 Bewerbung vom {__import__('datetime').date.today():%d.%m.%Y}")
