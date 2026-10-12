"""Lebenslauf-Daten, ATS, Jobquellen, Lesezeichen, Portfolio-Import, Modell-Config und neue App-Endpunkte."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from urllib.parse import unquote

import httpx
import pytest
import yaml

from bewerbungsagent import ats, config, integrationen, lesezeichen, portale, portfolio
from bewerbungsagent import lebenslauf as lv
from bewerbungsagent import modellcfg as mc
from bewerbungsagent.anschreiben import Anschreiben, faktencheck, nutzer_prompt
from bewerbungsagent.dienst import Dienst
from bewerbungsagent.profil import parse
from bewerbungsagent.quellen import adzuna, gemeinsam, jooble, jsonld, mailalarm

from conftest import PROFIL, FalscheQuelle, FalschesModell, anzeige, baue_config
from test_ablauf import _anfrage, _server

WURZEL = Path(__file__).resolve().parent.parent
BEISPIEL = yaml.safe_load((WURZEL / "beispiel" / "lebenslauf.yaml").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- Lebenslauf-Daten

def test_normalisieren_ergaenzt_und_saeubert():
    d = lv.normalisiere({"person": {"name": "A"}, "kenntnisse": [{"gruppe": "X", "eintraege": ["Python", {"name": "Git", "stufe": 9}]}],
                         "design": {"vorlage": "gibtsnicht", "abschnitte": ["projekte", "quatsch"]}})
    assert d["design"]["vorlage"] == "profil"
    assert d["design"]["abschnitte"][0] == "projekte" and "quatsch" not in d["design"]["abschnitte"]
    assert d["kenntnisse"][0]["eintraege"] == [{"name": "Python", "stufe": 0}, {"name": "Git", "stufe": 5}]
    assert d["person"]["email"] == "" and d["erfahrung"] == []


def test_aus_profil_holt_kopf_und_stationen():
    p = parse(PROFIL)
    d = lv.aus_profil(p)
    assert d["person"]["name"] == "Erika Beispiel" and d["person"]["plz_ort"] == "12345 Musterstadt"
    assert d["bildung"][0]["abschluss"] == "Realschulabschluss"
    assert "Windows-Clients" in d["erfahrung"][0]["titel"]


def test_speichern_und_laden(tmp_path):
    lv.speichere(tmp_path, BEISPIEL)
    zurueck = lv.lade(tmp_path)
    assert zurueck["person"]["name"] == "Max Beispiel" and len(zurueck["projekte"]) == 4
    assert "Python" in lv.als_text(zurueck)


def test_zeitraum():
    assert lv.zeitraum("2025-04", "heute") == "04/2025 – heute"
    assert lv.zeitraum("2014", "") == "2014"


# ---------------------------------------------------------------- ATS

ANZEIGE = """Ausbildung zum Fachinformatiker für Anwendungsentwicklung (m/w/d)

Deine Aufgaben:
- Du entwickelst Webanwendungen mit JavaScript und TypeScript
- Du lernst Datenbanken mit SQL kennen

Das bringst du mit:
- Mittlere Reife oder Abitur
- Interesse an Programmierung, HTML, CSS oder Python
- Teamfähigkeit und Zuverlässigkeit

Wir bieten:
- 30 Tage Urlaub und ein Jobrad
"""


def test_ats_findet_und_vermisst_begriffe():
    d = lv.normalisiere(BEISPIEL)
    b = ats.pruefe("Ausbildung zum Fachinformatiker für Anwendungsentwicklung (m/w/d)", ANZEIGE, d)
    gefunden = {x.wort for x in b.gefunden}
    fehlend = {x.wort for x in b.fehlend}
    assert {"JavaScript", "Python", "HTML"} <= gefunden
    assert "Mittlere Reife oder Abitur" in gefunden          # Realschulabschluss zaehlt als mittlere Reife
    assert {"SQL", "TypeScript"} <= fehlend
    assert not {"Urlaub", "Jobrad"} & (gefunden | fehlend)     # Angebot der Firma zaehlt nicht
    assert b.titel_treffer and 40 <= b.punkte <= 95
    assert any(x.art == "titel" for x in b.begriffe)


def test_ats_modell_darf_nichts_einschleusen():
    class Modell:
        def prompt(self, aufgabe):
            return "x"

        def frage_json(self, system, nutzer, aufgabe=None):
            return {"fach": ["Datenbanken", "Raketenbau"], "werkzeuge": ["SQL"], "persoenlich": [], "formal": []}

    b = ats.pruefe("Fachinformatiker", ANZEIGE, lv.normalisiere(BEISPIEL), llm=Modell())
    assert b.mit_modell and "Raketenbau" not in {x.wort for x in b.begriffe}


def test_kurzprofil_vorschlag_meldet_unbelegtes():
    class Modell:
        def prompt(self, aufgabe):
            return "x"

        def frage_json(self, system, nutzer, aufgabe=None):
            return {"kurzprofil": "Entwickelt mit SQL und JavaScript.", "genutzt": ["SQL", "JavaScript"]}

    d = lv.normalisiere(BEISPIEL)
    b = ats.pruefe("Fachinformatiker", ANZEIGE, d)
    v = ats.kurzprofil_vorschlag(b, "Fachinformatiker", d, "", Modell())
    assert v["unbelegt"] == ["SQL"] and not v["empfohlen"]


def test_titel_kern():
    assert ats.titel_kern("Ausbildung zum Kaufmann/-frau für Büromanagement (m/w/d) 2027") == "Kaufmann für Büromanagement"


# ---------------------------------------------------------------- Faktencheck mit Lebenslauf

def test_faktencheck_kennt_lebenslauf():
    p = parse(PROFIL)
    text = ["Seit 2025 baue ich Websites."]
    assert faktencheck(text, p) == ["Jahr 2025"]
    p.zusatz = "Websites für kleine Betriebe 04/2025 heute 2025"
    assert faktencheck(text, p) == []
    assert "# Lebenslauf (Auszug)" in nutzer_prompt(gemeinsam.baue("x", "1", "T", "F"), p)


# ---------------------------------------------------------------- Jobquellen

def test_adzuna_wandelt_treffer_um():
    def antwort(request):
        assert request.url.params["what"] == "Fachinformatiker" and request.url.params["app_id"] == "id"
        return httpx.Response(200, json={"results": [{
            "id": "123", "title": "<strong>Fachinformatiker</strong> (m/w/d)", "description": "Wir suchen dich. Zeitarbeit bei Randstad.",
            "company": {"display_name": "Randstad Deutschland"}, "location": {"display_name": "Musterstadt, Niedersachsen"},
            "redirect_url": "https://www.adzuna.de/land/ad/123", "created": "2026-10-01T10:00:00Z", "contract_time": "full_time"}]})
    q = adzuna.Adzuna("id", "key", client=httpx.Client(transport=httpx.MockTransport(antwort)))
    s = list(q.suche("Fachinformatiker", "Musterstadt", max_treffer=5))[0]
    assert s.titel == "Fachinformatiker (m/w/d)" and s.ort == "Musterstadt" and s.refnr == "adzuna-123"
    assert s.zeitarbeit and s.vollzeit and s.weg == "portal" and s.veroeffentlicht == "2026-10-01"


def test_adzuna_ohne_schluessel():
    with pytest.raises(gemeinsam.QuellenFehler):
        adzuna.Adzuna("", "")


def test_jooble_wandelt_treffer_um():
    def antwort(request):
        koerper = json.loads(request.content)
        assert koerper["keywords"] == "Koch" and request.url.path == "/api/geheim"
        return httpx.Response(200, json={"totalCount": 1, "jobs": [{
            "title": "Koch (m/w/d)", "location": "Musterstadt", "snippet": "Bewerbung an <b>jobs@kantine.example</b>",
            "company": "Kantine GmbH", "link": "https://jooble.org/desc/1", "updated": "2026-10-02T00:00:00", "type": "Vollzeit"}]})
    q = jooble.Jooble("geheim", client=httpx.Client(transport=httpx.MockTransport(antwort)))
    s = list(q.suche("Koch", "Musterstadt", max_treffer=1))[0]
    assert s.email == "jobs@kantine.example" and s.per_mail and s.vollzeit


def test_schluessel_fasst_dubletten_zusammen():
    assert gemeinsam.schluessel("Firma GmbH", "Koch (m/w/d)") == gemeinsam.schluessel("Firma", "Koch")


JSONLD_SEITE = """<html><head><title>Job</title>
<script type="application/ld+json">{"@context":"https://schema.org","@graph":[{"@type":"WebSite"},
{"@type":"JobPosting","title":"Lagerist (m/w/d)","description":"<p>Kommissionierung.</p><ul><li>Staplerschein</li></ul>",
"hiringOrganization":{"@type":"Organization","name":"Lager AG","sameAs":"https://lager.example"},
"jobLocation":{"@type":"Place","address":{"streetAddress":"Weg 1","postalCode":"12345","addressLocality":"Musterstadt"}},
"datePosted":"2026-10-03","employmentType":["FULL_TIME"],"identifier":{"value":"L-7"},
"applicationContact":{"email":"jobs@lager.example"}}]}</script></head><body>x</body></html>"""


def test_jsonld_liest_jobposting():
    s = jsonld.aus_html(JSONLD_SEITE, "https://lager.example/job")
    assert s.titel == "Lagerist (m/w/d)" and s.firma == "Lager AG" and s.plz == "12345"
    assert s.firmen_adresse == ["Weg 1", "12345 Musterstadt"] and s.email == "jobs@lager.example"
    assert "- Staplerschein" in s.beschreibung and s.vollzeit and s.refnr == "link-L7"


def test_jsonld_meldet_captcha_statt_umgehen():
    with pytest.raises(gemeinsam.QuellenFehler, match="Lesezeichen"):
        jsonld.aus_html("<html><body>Please complete the captcha</body></html>", "https://x.example")


def test_jsonld_url_mit_sperre():
    c = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403, text="nein")))
    with pytest.raises(gemeinsam.QuellenFehler, match="automatischen Abrufe"):
        jsonld.aus_url("https://portal.example/job/1", c)


ALARM = """<html><body><table>
<tr><td><a href="https://de.indeed.com/rc/clk?jk=abc&from=ja">Fachinformatiker Systemintegration (m/w/d)</a></td></tr>
<tr><td>Netzwerk GmbH</td></tr><tr><td>Musterstadt</td></tr>
<tr><td><a href="https://de.indeed.com/rc/clk?jk=abc">Jetzt bewerben</a></td></tr>
<tr><td><a href="https://www.linkedin.com/comm/jobs/view/42">IT-Support Mitarbeiter</a></td></tr><tr><td>Support AG · Hannover</td></tr>
<tr><td><a href="https://de.indeed.com/settings">Einstellungen</a></td></tr>
</table></body></html>"""


def test_mailalarm_findet_anzeigen():
    funde = mailalarm.funde_aus_html(ALARM, "indeed")
    assert [f.titel for f in funde] == ["Fachinformatiker Systemintegration (m/w/d)", "IT-Support Mitarbeiter"]
    s = mailalarm.zu_stelle(funde[0])
    assert s.firma == "Netzwerk GmbH" and s.ort == "Musterstadt" and s.quelle == "mail-indeed"


def test_weitere_quellen_im_lauf(projekt):
    cfg = baue_config(projekt)
    cfg.quellen.adzuna = True
    cfg.schluessel.adzuna_id, cfg.schluessel.adzuna_key = "id", "key"
    d = Dienst(cfg, quelle=FalscheQuelle([anzeige(1)]), llm=FalschesModell())

    class Zusatz:
        name = "Test"

        def suche(self, *a, **k):
            yield gemeinsam.baue("adzuna", "9", "IT-Support Mitarbeiter 1 (m/w/d)", "Firma 1 GmbH")  # Dublette
            yield gemeinsam.baue("adzuna", "10", "Fachinformatiker Support", "Neue Firma GmbH", "Bewerbung an a@neu.example")
    d.weitere_quellen = lambda: [Zusatz]
    stellen, _ = d.suche(melde=lambda _: None)
    assert sorted(s.firma for s in stellen) == ["Firma 1 GmbH", "Neue Firma GmbH"]


def test_stelle_aus_link_legt_entwurf_an(projekt):
    d = Dienst(baue_config(projekt), quelle=FalscheQuelle([]), llm=FalschesModell())
    daten = json.loads(JSONLD_SEITE.split('json">')[1].split("</script>")[0])["@graph"][1]
    batch = d.stelle_aus_link(daten=daten, url="https://lager.example/job", melde=lambda _: None)
    e = batch["eintraege"][-1]
    assert e["stelle"]["firma"] == "Lager AG" and e["anschreiben"] and e["pdf"]


# ---------------------------------------------------------------- Lesezeichen und Portale

def test_lesezeichen_sind_gueltige_links():
    u = lesezeichen.uebernehmen(8765)
    assert u.startswith("javascript:") and "127.0.0.1:8765" in unquote(u) and " " not in u
    daten = lesezeichen.formulardaten(parse(PROFIL), None)
    assert daten["vorname"] == "Erika" and daten["plz"] == "12345" and daten["ort"] == "Musterstadt"
    a = unquote(lesezeichen.ausfuellen(daten))
    assert '"email": "erika@example.org"' in a and "password" in a


def test_portale_merken_status(tmp_path):
    p = portale.Portale(tmp_path)
    p.setze("indeed", konto=True, notiz="erika")
    eintrag = next(x for x in p.liste() if x["id"] == "indeed")
    assert eintrag["konto"] and eintrag["notiz"] == "erika" and not eintrag["alarm"]
    with pytest.raises(KeyError):
        p.setze("gibtsnicht", konto=True)


# ---------------------------------------------------------------- Portfolio-Import

def test_js_zu_json():
    roh = "window.P = [{slug: 'a', title: \"A \\\"x\\\"\", n: 2, ok: true, t: ['x',], /* k */ u: undefined, // z\n},];"
    assert portfolio.js_zu_json(roh) == [{"slug": "a", "title": 'A "x"', "n": 2, "ok": True, "t": ["x"], "u": None}]


def test_portfolio_aus_ordner(tmp_path):
    seite = tmp_path / "seite"
    (seite / "daten").mkdir(parents=True)
    (seite / "bilder" / "a").mkdir(parents=True)
    (seite / "bilder" / "a" / "hero-800.jpg").write_bytes(b"\xff\xd8bild")
    (seite / "daten" / "domain.txt").write_text("https://name.github.io\n")
    (seite / "daten" / "projekte.js").write_text(
        "window.PROJEKTE = [{slug: 'a', title: 'Alpha', subtitle: 'Eins', description: 'Text', "
        "technologies: ['Python'], github: 'https://github.com/x/a', heroImage: 'bilder/a/hero'}, {slug: 'b', title: 'Beta'}];")
    projekte = portfolio.importiere(str(seite), tmp_path / "projekt", 5)
    assert projekte[0]["url"] == "https://name.github.io/work/a/" and projekte[0]["bild"] == "profil/bilder/projekte/a.jpg"
    assert (tmp_path / "projekt" / projekte[0]["bild"]).read_bytes() == b"\xff\xd8bild"
    zusammen = portfolio.zusammenfuehren([{"titel": "Alpha", "beschreibung": "eigen"}, {"titel": "Eigenes"}], projekte)
    assert [p["titel"] for p in zusammen] == ["Alpha", "Beta", "Eigenes"] and zusammen[0]["beschreibung"] == "eigen"


# ---------------------------------------------------------------- Konfiguration und Modell

def test_config_abschnitt_schreiben(tmp_path):
    shutil.copy(WURZEL / "config.example.yaml", tmp_path / "config.example.yaml")
    config.setze_abschnitt(tmp_path, "quellen", {"adzuna": True})
    config.setze_abschnitt(tmp_path, "quellen", {"adzuna": False, "jooble": True})
    text = (tmp_path / "config.yaml").read_text()
    assert text.count("quellen:") == 1 and "suche:" in text
    c = config.lade(tmp_path)
    assert c.quellen.jooble and not c.quellen.adzuna and c.suche.anzahl == 8


def test_verbindung_aus_modell_yaml(tmp_path):
    shutil.copy(WURZEL / "config.example.yaml", tmp_path / "config.yaml")
    m = mc.lade(tmp_path)
    m.verbindung = {"backend": "ollama", "modell": "llama3.1:8b", "basis_url": ""}
    m.speichere()
    c = config.lade(tmp_path)
    assert c.llm.backend == "ollama" and c.llm.modell == "llama3.1:8b"


def test_agent_prompt_und_hermes_skill(tmp_path):
    assert "Erfinde nichts" in integrationen.agent_prompt(tmp_path)
    ziel = integrationen.hermes_skill_installieren(tmp_path, heim=tmp_path / "heim")
    text = ziel.read_text(encoding="utf-8")
    assert text.startswith("---\nname: bewerbungsagent") and "anschreiben_setzen" in text
    assert "BEWERBUNGSAGENT_WURZEL" in integrationen.hermes_config(tmp_path)
    assert json.loads(integrationen.claude_desktop(tmp_path))["mcpServers"]["bewerbungsagent"]["args"][-1] == "mcp"


def test_anthropic_backend_schickt_schema_im_system():
    from bewerbungsagent.config import LLM as LLMConf, Config
    from bewerbungsagent.llm import LLM
    gesehen = {}

    def antwort(request):
        gesehen.update(json.loads(request.content))
        assert request.headers["x-api-key"] == "k"
        return httpx.Response(200, json={"content": [{"type": "text", "text": '{"punkte": 70, "begruendung": "ok"}'}],
                                         "usage": {"input_tokens": 10, "output_tokens": 5}})
    cfg = Config(wurzel=WURZEL, profil=WURZEL, anlagen=[], daten=WURZEL, llm=LLMConf(backend="anthropic"), llm_api_key="k")
    llm = LLM(cfg, client=httpx.Client(transport=httpx.MockTransport(antwort)))
    assert llm.frage_json("Bewerte.", "Stelle", aufgabe="bewertung")["punkte"] == 70
    assert "Schema" in gesehen["system"] and gesehen["messages"][0]["role"] == "user"
    assert llm.letzte.tokens_aus == 5 and not llm.mehrstufig


# ---------------------------------------------------------------- App-Endpunkte

def test_app_lebenslauf_vorschau_quellen_modell(projekt):
    d = Dienst(baue_config(projekt), quelle=FalscheQuelle([anzeige(1)]), llm=FalschesModell())
    batch = d.lauf(melde=lambda _: None)
    server = _server(d)
    port = d.cfg.app.port
    try:
        status, roh = _anfrage(port, "/api/lebenslauf")
        daten = json.loads(roh)
        assert status == 200 and not daten["vorhanden"] and daten["daten"]["person"]["name"] == "Erika Beispiel"

        neu = lv.normalisiere(BEISPIEL)
        neu["person"]["foto"] = ""
        status, roh = _anfrage(port, "/api/lebenslauf", {"daten": neu})
        assert status == 200 and json.loads(roh)["vorhanden"] and lv.pfad(projekt).exists()
        assert "Max Beispiel" in d.profil.zusatz           # Profil kennt jetzt die Lebenslauf-Fakten

        assert _anfrage(port, "/api/lebenslauf", {"yaml": "- keine\n- abschnitte"})[0] == 400

        for art in ("lebenslauf", "anschreiben", "deckblatt", "projekte"):
            status, roh = _anfrage(port, "/api/vorschau", {"art": art})
            kennung = json.loads(roh)["id"]
            status, html = _anfrage(port, f"/vorschau/tok/{kennung}", token="")
            assert status == 200 and b"Max Beispiel" in html, art
        status, roh = _anfrage(port, "/api/vorschau", {"art": "anschreiben", "batch": batch["id"], "i": 0})
        assert status == 200
        assert _anfrage(port, "/vorschau/falsch/x", token="")[0] == 404

        status, roh = _anfrage(port, "/api/ats", {"batch": batch["id"], "i": 0})
        assert status == 200 and "punkte" in json.loads(roh)

        status, roh = _anfrage(port, "/api/quellen", {"jooble": True})
        q = json.loads(roh)
        assert q["quellen"]["jooble"] and not q["schluessel"]["jooble"]
        assert yaml.safe_load((projekt / "config.yaml").read_text())["quellen"]["jooble"] is True
        assert q["lesezeichen"]["uebernehmen"].startswith("javascript:")
        status, roh = _anfrage(port, "/api/portal", {"id": "stepstone", "alarm": True})
        assert next(p for p in json.loads(roh)["portale"] if p["id"] == "stepstone")["alarm"]

        status, roh = _anfrage(port, "/api/modell")
        m = json.loads(roh)
        assert status == 200 and m["voreinstellung"] == "klein" and any(p["aufgabe"] == "agent" for p in m["prompts"])
        status, roh = _anfrage(port, "/api/modell", {"voreinstellung": "mittel", "aufgaben": {"bewertung": {"temperatur": 0.05}}})
        assert json.loads(roh)["voreinstellung"] == "mittel"
        assert mc.lade(projekt).aufgaben["bewertung"]["temperatur"] == 0.05
        status, roh = _anfrage(port, "/api/modell/prompt", {"aufgabe": "bewertung", "text": "Eigener Prompt"})
        assert next(p for p in json.loads(roh)["prompts"] if p["aufgabe"] == "bewertung")["eigen"]
        status, roh = _anfrage(port, "/api/modell/prompt", {"aufgabe": "bewertung", "zuruecksetzen": True})
        assert not next(p for p in json.loads(roh)["prompts"] if p["aufgabe"] == "bewertung")["eigen"]
        status, roh = _anfrage(port, "/api/modell/beispiel", {"aufgabe": "anschreiben_analyse"})
        assert "# Stelle" in json.loads(roh)["nutzer"]

        status, roh = _anfrage(port, "/api/bild", {"art": "foto", "daten": "data:image/png;base64,iVBORw0KGgo="})
        assert json.loads(roh)["pfad"] == "profil/bilder/foto.png"
        assert _anfrage(port, "/api/bild", {"art": "foto", "daten": "data:text/html;base64,PGI+"})[0] == 400
    finally:
        server.shutdown()


def test_mcp_neue_werkzeuge():
    import asyncio
    from bewerbungsagent.mcp_server import server
    namen = {w.name for w in asyncio.run(server.list_tools())}
    assert {"lebenslauf_zeigen", "lebenslauf_aendern", "ats_pruefen", "kurzprofil_fuer_stelle", "stelle_aus_link",
            "portfolio_importieren", "prompt_zeigen"} <= namen
    assert not any("send" in n for n in namen)
