from __future__ import annotations

from datetime import date

import httpx
import pytest

from bewerbungsagent import anschreiben as ans
from bewerbungsagent import bewertung, kontakt, llm, pdf, profil
from bewerbungsagent.config import Config, LLM as LLMConf, lese_env
from bewerbungsagent.quellen.arbeitsagentur import Arbeitsagentur, zu_stelle
from bewerbungsagent.stelle import Stelle
from bewerbungsagent.vault import notizname

from conftest import PROFIL, FalschesModell, anzeige


def test_email_verschleiert_und_unbrauchbare_raus():
    text = "Kontakt: jobs (at) firma [dot] de, noreply@firma.de, datenschutz@firma.de"
    assert kontakt.emails(text) == ["jobs@firma.de"]


def test_beste_email_bevorzugt_bewerbungsadresse_der_firmendomain():
    text = "info@agentur.de, kontakt@firma.de, bewerbung@firma.de"
    assert kontakt.beste_email(text, "www.firma.de") == "bewerbung@firma.de"
    assert kontakt.beste_email("keine adresse hier") == ""


def test_anrede_nach_din_nur_nachname():
    assert kontakt.anrede("Frau Anna Schneider") == "Sehr geehrte Frau Schneider,"
    assert kontakt.anrede("Herr Dr. Max Weber") == "Sehr geehrter Herr Dr. Weber,"
    assert kontakt.anrede("") == "Sehr geehrte Damen und Herren,"


def test_ansprechpartner_aus_text():
    assert kontakt.ansprechpartner("Ihre Ansprechpartnerin: Frau Dr. Lena Muster") == "Frau Dr. Lena Muster"


def test_profil_parse_und_pflichtfelder():
    p = profil.parse(PROFIL)
    assert p.name == "Erika Beispiel" and p.suchbegriffe == ["Fachinformatiker", "IT-Support"]
    assert "Windows-Clients" in p.text
    with pytest.raises(ValueError, match="Pflichtfelder"):
        profil.parse("---\nname: X\n---\ntext")


def test_env_leser(tmp_path):
    (tmp_path / ".env").write_text("# kommentar\nSMTP_USER=a@b.de\nSMTP_PASSWORD='geheim = ja'\n", encoding="utf-8")
    assert lese_env(tmp_path / ".env") == {"SMTP_USER": "a@b.de", "SMTP_PASSWORD": "geheim = ja"}


def test_arbeitsagentur_blaettert_und_baut_stelle():
    seiten = {1: [anzeige(i)["zeile"] for i in range(50)], 2: [anzeige(i)["zeile"] for i in range(50, 60)]}
    aufrufe = []

    def antwort(request: httpx.Request):
        aufrufe.append(request)
        assert request.headers["X-API-Key"] == "jobboerse-jobsuche"
        if "/jobdetails/" in request.url.path:
            return httpx.Response(200, json=anzeige(3)["details"])
        seite = int(request.url.params["page"])
        return httpx.Response(200, json={"ergebnisliste": seiten.get(seite, []), "maxErgebnisse": 60})

    ba = Arbeitsagentur(httpx.Client(transport=httpx.MockTransport(antwort)), pause_s=0)
    zeilen = list(ba.suche("IT", "Musterstadt", max_treffer=100))
    assert len(zeilen) == 60 and aufrufe[0].url.params["zeitarbeit"] == "false"
    s = zu_stelle(zeilen[3], ba.details(zeilen[3]["referenznummer"]))
    assert s.email == "bewerbung@firma3.de"
    assert s.ansprechpartner == "Frau Dr. Lena Muster"
    assert s.url.endswith("10000-TEST0003-S") and s.plz == "12345"


def _stelle(i, **felder) -> Stelle:
    a = anzeige(i)
    return zu_stelle(a["zeile"], {**a["details"], **felder})


def test_regeln_sortieren_aus():
    p = profil.parse(PROFIL)
    stellen = [
        _stelle(1),
        _stelle(2, istArbeitnehmerUeberlassung=True),
        _stelle(3, stellenangebotsTitel="Praktikum IT"),
        _stelle(4, stellenangebotsTitel="Minijob Aushilfe IT"),
        _stelle(5, arbeitszeitVollzeit=False),
        _stelle(6, firma="Firma 1 GmbH"),
        _stelle(7, firma="Gesperrt AG"),
    ]
    behalten, raus = bewertung.regeln(stellen, p, True, True, {"gesperrt ag"})
    assert [s.refnr for s in behalten] == [stellen[0].refnr]
    assert [r.grund for r in raus] == ["Zeitarbeit", "Ausschlusswort im Titel", "Minijob", "keine Vollzeit",
                                      "Firma schon in diesem Lauf", "Firma innerhalb der Sperrfrist schon angeschrieben"]


def test_heuristik_belohnt_passung():
    p = profil.parse(PROFIL)
    gut = _stelle(1)
    schlecht = Stelle(quelle="ba", refnr="x", titel="Koch (m/w/d)", firma="Kantine", beschreibung="Kochen, Spülen")
    assert bewertung.heuristik(gut, p) > bewertung.heuristik(schlecht, p)


def test_llm_bewertung_sortiert_um():
    p = profil.parse(PROFIL)
    stellen = [_stelle(i) for i in range(3)]
    bewertung.sortiere(stellen, p, FalschesModell(), melde=lambda _: None)
    assert all(s.punkte == 80 and "Support" in s.begruendung for s in stellen)


def test_bereinige_denkbloecke_und_zaeune():
    assert llm.bereinige("<think>hmm</think>\n```json\n{\"a\": 1}\n```") == '{"a": 1}'
    assert llm.bereinige("viel denken</think>{\"a\": 2}") == '{"a": 2}'
    assert llm.json_aus('Klar! Hier: {"a": 3} Viel Erfolg') == {"a": 3}
    with pytest.raises(llm.LLMFehler):
        llm.json_aus("kein json")


def test_openai_backend_waehlt_geladenes_modell(tmp_path):
    gesehen = {}

    def antwort(request: httpx.Request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "qwen-test"}]})
        gesehen.update(__import__("json").loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": "<think>x</think>{\"ok\": true}"}}]})

    cfg = Config(wurzel=tmp_path, profil=tmp_path, anlagen=[], daten=tmp_path, llm=LLMConf(backend="lmstudio"))
    modell = llm.LLM(cfg, httpx.Client(transport=httpx.MockTransport(antwort)))
    assert modell.frage_json("sys", "nutzer") == {"ok": True}
    assert gesehen["model"] == "qwen-test" and gesehen["messages"][0]["content"] == "sys"


def test_backend_keins_wirft_kein_modell(tmp_path):
    cfg = Config(wurzel=tmp_path, profil=tmp_path, anlagen=[], daten=tmp_path, llm=LLMConf(backend="keins"))
    with pytest.raises(llm.KeinModell):
        llm.LLM(cfg).frage("a", "b")


def test_pruefung_findet_platzhalter_anrede_und_laenge():
    p = profil.parse(PROFIL)
    a = ans.Anschreiben(betreff="B", anrede="x", absaetze=["Sehr geehrte Damen [Firma]", "Mit freundlichen Grüßen"])
    m = ans.pruefe(a, p)
    assert any("Platzhalter" in x for x in m) and "Anrede im Text" in m and "Grussformel im Text" in m
    assert any("Woerter" in x for x in m)


def test_erzeuge_wiederholt_bei_maengeln_und_setzt_rahmen():
    p = profil.parse(PROFIL)
    s = _stelle(1)
    modell = FalschesModell(maengel_erst=1)
    a = ans.erzeuge(s, p, modell)
    assert modell.aufrufe == 2 and a.maengel == []
    assert a.anrede == "Sehr geehrte Frau Dr. Muster,"
    assert a.betreff == f"Bewerbung als IT-Support Mitarbeiter - Ref. {s.refnr}"


def test_pdf_passt_oder_meldet_ueberlauf(tmp_path):
    p = profil.parse(PROFIL)
    s = _stelle(1)
    normal = ans.Anschreiben(betreff="Bewerbung als Test", anrede="Sehr geehrte Damen und Herren,",
                             absaetze=["Wort " * 80] * 4)
    assert pdf.anschreiben_pdf(tmp_path / "a.pdf", p, s, normal, ["Lebenslauf"], date(2026, 9, 26))
    assert (tmp_path / "a.pdf").read_bytes().startswith(b"%PDF")
    riesig = ans.Anschreiben(betreff="B", anrede="Hallo,", absaetze=["Wort " * 200] * 4)
    assert not pdf.anschreiben_pdf(tmp_path / "b.pdf", p, s, riesig, [], date(2026, 9, 26))


def test_nachweis_pdf(tmp_path):
    p = profil.parse(PROFIL)
    e = [{"datum": "2026-09-26", "firma": f"Firma {i}", "ort": "Musterstadt", "titel": "IT (m/w/d)", "refnr": "R", "email": "a@b.de"}
         for i in range(30)]
    assert pdf.nachweis_pdf(tmp_path / "n.pdf", p, e).stat().st_size > 1000


def test_notizname_ohne_verbotene_zeichen():
    assert notizname("A/B: GmbH", "IT-Support (m/w/d) [Remote]") == "A B GmbH - IT-Support Remote"


def test_name_mit_akzent_wird_nicht_abgeschnitten():
    assert kontakt.ansprechpartner("steht Ihnen Herr Gerrit Graën zur Verfügung") == "Herr Gerrit Graën"
    assert kontakt.anrede("Frau Dr. Anna-Lena Müller-Schmidt") == "Sehr geehrte Frau Dr. Müller-Schmidt,"
    assert kontakt.ansprechpartner("Frau gerne") == ""


def test_ort_kommt_aus_dem_suchtreffer_nicht_vom_firmensitz():
    a = anzeige(1)
    zeile = {**a["zeile"], "stellenlokationen": [{"adresse": {"ort": "Braunschweig"}}], "entfernung": 19}
    details = {**a["details"], "stellenlokationen": [{"adresse": {"ort": "Frankfurt am Main"}},
                                                     {"adresse": {"ort": "Braunschweig"}}]}
    s = zu_stelle(zeile, details)
    assert s.ort == "Braunschweig" and s.entfernung_km == 19


def test_titel_ohne_geschuetzte_leerzeichen():
    a = anzeige(1)
    s = zu_stelle({**a["zeile"], "stellenangebotsTitel": "IT-Support (m/w/d)\xa0 "}, None)
    assert s.titel == "IT-Support (m/w/d)"


def test_geschlechtsangabe_ohne_klammern_und_html_entitaeten():
    assert notizname("job meets life GmbH", "Teamleiter m/w/d IT") == "job meets life GmbH - Teamleiter IT"
    a = anzeige(1)
    s = zu_stelle(a["zeile"], {**a["details"], "stellenangebotsBeschreibung": "IT-Support&#160;Mitarbeiter &amp; mehr"})
    assert s.beschreibung == "IT-Support Mitarbeiter & mehr"


def test_openai_backend_ueberspringt_embedding_und_meldet_offline(tmp_path):
    def antwort(request: httpx.Request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "text-embedding-nomic-embed-text-v1.5"}, {"id": "qwen"}]})
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    cfg = Config(wurzel=tmp_path, profil=tmp_path, anlagen=[], daten=tmp_path, llm=LLMConf(backend="lmstudio"))
    modell = llm.LLM(cfg, httpx.Client(transport=httpx.MockTransport(antwort)))
    modell.frage("a", "b")
    assert modell._modell == "qwen"

    def aus(request):
        raise httpx.ConnectError("Verbindung verweigert")

    offline = llm.LLM(cfg, httpx.Client(transport=httpx.MockTransport(aus)))
    with pytest.raises(llm.LLMFehler, match="nicht erreichbar"):
        offline.frage("a", "b")


def test_profil_mit_strichen_im_kommentar_und_bom():
    text = "﻿---\n# Kommentar mit '---' drin\n" + PROFIL.split("---\n", 1)[1]
    p = profil.parse(text.replace("\n", "\r\n"))
    assert p.name == "Erika Beispiel" and "Windows-Clients" in p.text


def test_batch_ids_eindeutig_auch_in_derselben_sekunde(tmp_path):
    from bewerbungsagent.speicher import Speicher
    s = Speicher(tmp_path)
    ids = {s.neuer_batch()["id"] for _ in range(5)}
    assert len(ids) == 5 and len(s.alle()) == 5


def test_stammtreffer_im_titel():
    assert bewertung._stamm_treffer("lagermitarbeiter gesucht (m/w/d)", ["Lagerhelfer"])
    assert bewertung._stamm_treffer("medientechnologe digitaldruck", ["Mediengestalter"])
    assert not bewertung._stamm_treffer("elektroinstallateur", ["IT-Support", "Lagerhelfer"])


def test_ausbildungsanzeige_art_beginn_und_prompt():
    a = anzeige(1)
    s = zu_stelle(a["zeile"], {**a["details"], "stellenangebotsart": "AUSBILDUNG",
                               "eintrittszeitraum": {"von": "2027-08-01"}})
    assert s.art == "ausbildung" and s.beginn == "2027-08-01"
    prompt = ans.nutzer_prompt(s, profil.parse(PROFIL))
    assert "(Ausbildungsplatz)" in prompt and "Beginn: 2027-08-01" in prompt


def test_mailtext_mit_ausbildungsbetreff():
    from bewerbungsagent import mail
    p = profil.parse(PROFIL)
    e = {"stelle": {"refnr": "R1", "titel": "Ausbildung Fachlagerist", "email": "a@b.de", "firma": "F"},
         "anschreiben": {"betreff": "Bewerbung um einen Ausbildungsplatz als Fachlagerist - Ref. R1",
                         "anrede": "Sehr geehrte Damen und Herren,"}, "pdf": __file__}
    text = mail.bewerbungsmail(p, e, []).get_body(("plain",)).get_content()
    assert "meine Bewerbung um einen Ausbildungsplatz als Fachlagerist (Referenznummer R1" in text


def test_geforderter_abschluss_filtert_und_senkt():
    p = profil.parse(PROFIL.replace("arbeitszeit: vollzeit", "arbeitszeit: egal\nschulabschluss: hauptschule"))
    abi = _stelle(1, geforderterBildungsabschluss="ABITUR_HOCHSCHULREIFE")
    mr = _stelle(2, geforderterBildungsabschluss="MITTLERE_REIFE_MITTLERER_BILDUNGSABSCHLUSS")
    hs = _stelle(3, geforderterBildungsabschluss="HAUPTSCHULABSCHLUSS")
    behalten, raus = bewertung.regeln([abi, mr, hs], p, True, True, set())
    assert [r.grund for r in raus] == ["verlangt Abitur"]
    assert bewertung.heuristik(mr, p) == bewertung.heuristik(hs, p) - 15


def test_ausbildung_ohne_titel_nimmt_beruf():
    a = anzeige(1)
    zeile = {**a["zeile"], "stellenangebotsTitel": None, "hauptberuf": "Kaufmann/-frau - Büromanagement"}
    assert zu_stelle(zeile, None).titel == "Ausbildung: Kaufmann/-frau - Büromanagement"


@pytest.mark.parametrize("text, weg", [
    ("Wir freuen uns auf deine Bewerbung. Senden Sie Ihre Bewerbungsunterlagen an: bewerbung@x.de", "email"),
    ("Sollten Sie vorab weitere Auskünfte wünschen, steht Ihnen Herr Muster zur Verfügung. "
     "Sie erreichen ihn unter Tel. 0511 123 oder per E-Mail unter karriere@x.de", "portal"),
    ("Bitte nutze den Button ONLINE BEWERBEN. Eine Bewerbung per E-Mail können wir leider nicht "
     "berücksichtigen. Fragen? ausbildung@x.de", "portal"),
    ("Bewerben Sie sich auf karriere.x.de. Bei weiteren Fragen erreichen Sie uns unter: jobs@x.de", "portal"),
    ("Sie können uns gerne Informationen zu Ihren Dienstleistungen per Mail unter pb@x.de senden.", "portal"),
    ("Klicke auf Jetzt bewerben oder nimm Kontakt auf. Telefonisch oder per Mail (jobs@x.de)", "email"),
    ("Jetzt bewerben! Giuseppe Muster | Recruiting | recruiting@x.de", "portal"),
    ("Auf diese Stelle bewerben: https://x.jobs.personio.de/job/1 ... job@x.de", "portal"),
])
def test_bewerbungsweg(text, weg):
    email = kontakt.emails(text)[-1]
    assert kontakt.bewerbungsweg(text, email)[0] == weg


def test_ansprechpartner_herrn_mit_namenszusatz():
    assert kontakt.ansprechpartner("Unterlagen an: Firma z.H. Herrn La Mela Dieselstraße 1") == "Herr La Mela"
    assert kontakt.anrede("Herr La Mela") == "Sehr geehrter Herr La Mela,"
    assert kontakt.anrede("Frau Anna van Dijk") == "Sehr geehrte Frau van Dijk,"


def test_anschrift_herrn_anrede_herr(tmp_path):
    p = profil.parse(PROFIL)
    s = _stelle(1)
    s.ansprechpartner = "Herr La Mela"
    a = ans.Anschreiben(betreff="B", anrede=kontakt.anrede(s.ansprechpartner), absaetze=["Wort " * 60] * 3)
    assert pdf.anschreiben_pdf(tmp_path / "x.pdf", p, s, a, [])
    assert a.anrede == "Sehr geehrter Herr La Mela,"


def test_portfolio_lockert_abschlussfilter_und_landet_im_prompt():
    basis = PROFIL.replace("arbeitszeit: vollzeit", "arbeitszeit: egal\nschulabschluss: hauptschule")
    ohne = profil.parse(basis)
    mit = profil.parse(basis.replace("schulabschluss: hauptschule",
                                     "schulabschluss: hauptschule\nportfolio: https://max.example/\n"
                                     "arbeitsproben:\n  - https://probe.example/"))
    abi = _stelle(1, geforderterBildungsabschluss="ABITUR_HOCHSCHULREIFE")
    assert bewertung.regeln([abi], ohne, True, True, set())[1]
    assert bewertung.regeln([abi], mit, True, True, set())[0]
    prompt = ans.nutzer_prompt(abi, mit)
    assert "Portfolio: https://max.example/" in prompt and "Arbeitsprobe: https://probe.example/" in prompt
    assert "Verlangter Schulabschluss: ABITUR_HOCHSCHULREIFE" in prompt


def test_pdf_pfade_ueberleben_verschieben_des_projektordners(tmp_path):
    import json as _json
    from bewerbungsagent.speicher import Speicher
    alt = Speicher(tmp_path / "alt")
    b = alt.neuer_batch()
    pdf_ordner = alt.ordner(b["id"]) / "pdf"
    pdf_ordner.mkdir()
    (pdf_ordner / "01_Firma.pdf").write_bytes(b"%PDF")
    b["eintraege"].append({"pdf": str(pdf_ordner / "01_Firma.pdf"), "stelle": {}, "status": "entwurf"})
    alt.speichere(b)
    (tmp_path / "alt").rename(tmp_path / "neu")
    geladen = Speicher(tmp_path / "neu").lade(b["id"])
    assert geladen["eintraege"][0]["pdf"] == str(tmp_path / "neu" / "batches" / b["id"] / "pdf" / "01_Firma.pdf")
