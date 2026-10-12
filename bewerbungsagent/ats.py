"""ATS-Check: Wie gut findet ein Bewerbungssystem die Anforderungen einer Anzeige im Lebenslauf?

Bewerbungsportale (ATS) lesen den Lebenslauf als Text und suchen nach den Begriffen
der Anzeige. Dieser Check zieht die Begriffe aus der Anzeige - per Heuristik und,
wenn vorhanden, mit dem Sprachmodell - und gleicht sie mit Lebenslauf und Profil ab.

Grundsatz: fehlende Begriffe sind ein Hinweis, keine Aufforderung. Eingetragen wird
nur, was stimmt. Das Kurzprofil schreibt das Modell nur aus belegten Fakten neu.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import asdict, dataclass, field

from . import lebenslauf as lv

# Woerter, die in fast jeder Anzeige stehen und nichts ueber die Stelle sagen
FUELLWOERTER = set("""
aufgabe aufgaben anforderung anforderungen bewerbung bewerbungen bewerber bewerberin unternehmen firma team
teams mitarbeiter mitarbeiterin mitarbeitende kollegen kolleginnen stelle stellen arbeitsplatz arbeitgeber
profil ihr ihre wir sie du dein deine uns unser unsere bereich bereiche moeglichkeit moeglichkeiten angebot
angebote vorteil vorteile benefits standort standorte zukunft rahmen zeit jahr jahre jahren monat monate
wochen tag tage kunde art weise sinne interesse freude spass lust chance chancen ausschreibung anzeige
voraussetzung voraussetzungen kenntnis kenntnisse erfahrung erfahrungen bereitschaft verguetung gehalt
urlaub urlaubstage arbeitszeit arbeitszeiten beginn eintritt eintrittstermin kontakt ansprechpartner
ansprechpartnerin email mail telefon website homepage link portal online unterlagen lebenslauf anschreiben
zeugnisse zeugnis gmbh co kg ag mbh ug ev herr frau dr strasse str plz ort land deutschland umgebung
mwd wmd mfd dmw all genders mensch menschen person personen wert werte wertschaetzung atmosphaere
umfeld klima familie familienunternehmen mittelstand konzern branche markt leistung leistungen
weiterbildung weiterbildungen entwicklung entwicklungsmoeglichkeiten karriere einarbeitung
""".split())

STOPP = set("""
der die das den dem des ein eine einer eines einem einen und oder aber sowie mit ohne fuer von vom zu zum zur
im in an am auf aus bei nach ueber unter vor hinter neben zwischen durch gegen um als wie wenn dass ob auch
noch nur sehr mehr gerne gern bitte ist sind war waren wird werden wurde wurden hat haben hatte hatten kann
koennen soll sollen muss muessen darf duerfen will wollen sich ihr ihre ihren ihrem ihrer wir uns unser
sie du dich dir dein deine es er man jede jeder jedes alle allem allen alles viele vielen einige ab bis
sowohl weder noch nicht kein keine keinen etc z b bzw ggf idr usw u a eu
""".split())

# Schreibweisen, die als gleich gelten (alles klein, ohne Umlaute)
SYNONYME = [
    {"ms office", "microsoft office", "office", "office 365", "microsoft 365", "word excel", "ms-office"},
    {"excel", "ms excel", "microsoft excel"},
    {"fuehrerschein klasse b", "fuehrerschein b", "klasse b", "pkw-fuehrerschein", "fuehrerschein"},
    {"teamfaehigkeit", "teamarbeit", "teamfaehig", "im team"},
    {"kundenservice", "kundenbetreuung", "kundensupport", "kundenkontakt", "kundenberatung", "kundenorientierung"},
    {"zuverlaessigkeit", "zuverlaessig"},
    {"belastbarkeit", "belastbar", "stressresistenz"},
    {"kommunikationsfaehigkeit", "kommunikationsstaerke", "kommunikativ", "kommunikation"},
    {"selbststaendigkeit", "selbststaendig", "eigenstaendig", "selbststaendige arbeitsweise"},
    {"deutschkenntnisse", "deutsch", "muttersprache deutsch"},
    {"englischkenntnisse", "englisch"},
    {"javascript", "js"},
    {"typescript", "ts"},
    {"html", "html5"},
    {"css", "css3"},
    {"it-support", "support", "anwendersupport", "first-level-support", "helpdesk", "service desk"},
    {"schichtbereitschaft", "schichtarbeit", "schichtdienst", "wechselschicht"},
    {"gabelstapler", "staplerschein", "flurfoerderzeuge", "stapler"},
    {"lagerlogistik", "lager", "logistik", "kommissionierung"},
    {"sap", "sap erp", "sap s/4hana"},
    {"windows", "windows 10", "windows 11", "windows-clients"},
    {"netzwerk", "netzwerktechnik", "netzwerke"},
]

ABSCHLUESSE = [
    {"realschulabschluss", "mittlere reife", "mittlerer schulabschluss", "msa"},
    {"hauptschulabschluss", "berufsreife", "erster schulabschluss", "berufsbildungsreife"},
    {"abitur", "allgemeine hochschulreife", "fachabitur", "fachhochschulreife"},
]
SYNONYME += ABSCHLUESSE

# Fachbegriffe, die oft klein oder als Abkuerzung stehen und sonst durchrutschen
BEKANNTE = """
python java javascript typescript c# c++ php sql html css react vue angular node.js .net git linux windows
macos docker kubernetes aws azure sap excel word powerpoint outlook office sps cnc cad autocad solidworks
erp crm datev lexware photoshop illustrator figma blender unity unreal three.js webgl wordpress shopify
seo sem jira confluence scrum kanban itil gabelstapler staplerschein fuehrerschein schichtbereitschaft
""".split()


def falte(text: str) -> str:
    """klein, Umlaute als ae/oe/ue, ss statt ß, Akzente weg."""
    t = (text or "").lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    t = unicodedata.normalize("NFKD", t)
    return "".join(c for c in t if not unicodedata.combining(c))


def stamm(wort: str) -> str:
    w = falte(wort)
    for endung in ("ungen", "heiten", "keiten", "innen", "ern", "en", "er", "es", "e", "n", "s"):
        if len(w) > len(endung) + 3 and w.endswith(endung):
            return w[: -len(endung)]
    return w


@dataclass
class Begriff:
    wort: str
    gewicht: float
    art: str = "fach"           # fach | werkzeuge | persoenlich | formal | titel
    gefunden: bool = False
    beleg: str = ""             # wo im Lebenslauf gefunden

    def als_dict(self) -> dict:
        return asdict(self)


@dataclass
class Bericht:
    punkte: int
    begriffe: list[Begriff]
    hinweise: list[str] = field(default_factory=list)
    titel_treffer: bool = False
    mit_modell: bool = False

    @property
    def gefunden(self) -> list[Begriff]:
        return [b for b in self.begriffe if b.gefunden]

    @property
    def fehlend(self) -> list[Begriff]:
        return [b for b in self.begriffe if not b.gefunden]

    def als_dict(self) -> dict:
        return {"punkte": self.punkte, "titel_treffer": self.titel_treffer, "mit_modell": self.mit_modell,
                "hinweise": self.hinweise, "gefunden": [b.als_dict() for b in self.gefunden],
                "fehlend": [b.als_dict() for b in self.fehlend]}


# ---------------------------------------------------------------- Begriffe aus der Anzeige

_ABSCHNITT_PROFIL = re.compile(r"(profil|das bringst du mit|das bringen sie mit|anforderung|voraussetzung|"
                               r"was du mitbringst|was sie mitbringen|qualifikation|wir erwarten)", re.I)
_ABSCHNITT_AUFGABEN = re.compile(r"(aufgaben|deine taetigkeit|ihre taetigkeit|das erwartet|was dich erwartet)", re.I)
_ABSCHNITT_ANGEBOT = re.compile(r"(wir bieten|das bieten wir|unser angebot|benefits|was wir bieten|deine vorteile)", re.I)


def _abschnitte(text: str) -> list[tuple[float, str]]:
    """Zerlegt die Anzeige grob; Anforderungen zaehlen doppelt, das Angebot der Firma gar nicht."""
    teile: list[tuple[float, str]] = []
    gewicht = 1.0
    for zeile in (text or "").splitlines():
        kurz = falte(zeile.strip())[:60]
        if len(kurz) < 60 and _ABSCHNITT_PROFIL.search(kurz):
            gewicht = 2.0
        elif len(kurz) < 60 and _ABSCHNITT_AUFGABEN.search(kurz):
            gewicht = 1.4
        elif len(kurz) < 60 and _ABSCHNITT_ANGEBOT.search(kurz):
            gewicht = 0.0
        teile.append((gewicht, zeile))
    return teile


# Mehrwortbegriffe, die zusammen bleiben muessen
PHRASEN = sorted({v for g in SYNONYME for v in g if " " in v} | {
    "mittlere reife", "erste hilfe", "sicherer umgang", "abgeschlossene ausbildung", "abgeschlossene berufsausbildung",
    "b2-niveau", "c1-niveau", "polizeiliches fuehrungszeugnis", "erweitertes fuehrungszeugnis",
}, key=len, reverse=True)

ADJEKTIVE = set("""
gute guter gutes guten sehr erste ersten erster hohe hoher hohes sichere sicherer sicheres sicheren
abgeschlossene abgeschlossener fundierte fundierten mehrjaehrige mehrjaehriger einschlaegige einschlaegiger
selbststaendige strukturierte strukturierter freundliche freundliches offene offener flexible flexibler
zuverlaessige verantwortungsvolle idealerweise wuenschenswert vorteilhaft ausgepraegte ausgepraegter
grundlegende grundlegender praktische praktischer technisches technische technischer kaufmaennische
kaufmaennischer handwerkliche handwerkliches sorgfaeltige sorgfaeltiger eigenverantwortliche teamorientierte
motivierte motivierter engagierte engagierter interessierte interessierter neue neuen moderne modernen
""".split())


def _kandidaten(zeile: str) -> list[str]:
    funde: list[str] = []
    gefaltet = falte(zeile)
    for phrase in PHRASEN:
        stelle = gefaltet.find(phrase)
        if stelle >= 0 and (stelle == 0 or not gefaltet[stelle - 1].isalnum()):
            funde.append(zeile[stelle:stelle + len(phrase)])
            # aus der Zeile nehmen, damit die Einzelwoerter nicht noch einmal zaehlen
            zeile = zeile[:stelle] + " " * len(phrase) + zeile[stelle + len(phrase):]
            gefaltet = falte(zeile)
    # Substantive (gross geschrieben), auch mit Bindestrich: "IT-Support", "Windows-Clients"
    for m in re.finditer(r"\b[A-ZÄÖÜ][\wäöüß]+(?:-[\wÄÖÜäöüß]+)*", zeile):
        if falte(m.group(0)) in ADJEKTIVE:
            continue
        funde.append(m.group(0))
    # Abkuerzungen und Technikbegriffe: SAP, SPS, C#, .NET, Node.js
    for m in re.finditer(r"(?<![\w.])(?:[A-Z]{2,6}\d?|[A-Za-z]+(?:\.js|#|\+\+)|\.NET)(?![\w])", zeile):
        funde.append(m.group(0))
    f = falte(zeile)
    for b in BEKANNTE:
        if re.search(rf"(?<![\w]){re.escape(b)}(?![\w])", f):
            funde.append(b)
    return funde


def art_von(wort: str) -> str:
    f = falte(wort)
    if (any(t in g for g in ABSCHLUESSE for t in f.split(" oder ")) or "fuehrerschein" in f or "schicht" in f
            or re.search(r"(deutsch|englisch|franzoesisch|spanisch|tuerkisch|russisch|polnisch)", f)
            or "zeugnis" in f):
        return "formal"
    if re.search(r"(faehigkeit|keit|bereitschaft|staerke|orientierung|denken|freude|sinn)$", f):
        return "persoenlich"
    if f in BEKANNTE or re.search(r"[A-Z]{2,}|\.js|#|\+\+", wort):
        return "werkzeuge"
    return "fach"


_TITEL_WEG = re.compile(r"\((?:m|w|d|f|x|gn|all|divers)[^)]*\)|/\s?-?\s?(?:frau|in|innen|mann|e)\b|\(in\)|\b(?:ausbildung|duales studium)\s+(?:zum|zur|als)\b|"
                        r"\b(?:zum|zur|als)\b|\b20\d\d\b|\bab sofort\b|\b(?:in )?(?:voll|teil)zeit\b", re.I)


def titel_kern(titel: str) -> str:
    """'Ausbildung zum Kaufmann für Büromanagement (m/w/d) 2027' -> 'Kaufmann für Büromanagement'."""
    kern = _TITEL_WEG.sub(" ", titel or "")
    kern = re.sub(r"^\s*(ausbildung|azubi|auszubildende[rn]?)\b[\s:–-]*", "", kern.strip(), flags=re.I)
    return re.sub(r"\s+", " ", kern).strip(" -–:,/")


def _titel_woerter(titel: str) -> list[str]:
    return [w for w in re.findall(r"[\wäöüÄÖÜß-]{4,}", titel_kern(titel)) if falte(w) not in FUELLWOERTER | STOPP]


def heuristik(titel: str, text: str, max_anzahl: int = 18) -> list[Begriff]:
    """Begriffe aus der Anzeige. Der Stellentitel zaehlt als ein Begriff (art "titel"), nicht Wort fuer Wort."""
    zaehler: Counter[str] = Counter()
    schreibweise: dict[str, str] = {}
    titelstaemme = {stamm(w) for w in _titel_woerter(titel)}
    for gewicht, zeile in _abschnitte(text):
        if gewicht == 0:
            continue
        kandidaten = _kandidaten(zeile)
        # "Mittlere Reife oder Abitur": Abschluesse in einer Zeile mit "oder" sind Alternativen
        abschluesse = [k for k in kandidaten if any(falte(k) in g for g in ABSCHLUESSE)]
        if len(abschluesse) > 1 and " oder " in falte(zeile):
            kandidaten = [k for k in kandidaten if k not in abschluesse] + [" oder ".join(abschluesse)]
        for k in kandidaten:
            schluessel = stamm(k)
            if schluessel in titelstaemme:
                continue
            if len(schluessel) < 2 or falte(k) in FUELLWOERTER or falte(k) in STOPP or schluessel in FUELLWOERTER:
                continue
            if re.fullmatch(r"\d+", k):
                continue
            zaehler[schluessel] += gewicht
            schreibweise.setdefault(schluessel, k)
    begriffe = []
    if titel_kern(titel):
        begriffe.append(Begriff(titel_kern(titel), 5.0, "titel"))
    for schluessel, wert in zaehler.most_common(max_anzahl * 2):
        wort = schreibweise[schluessel]
        if wert < 1.4 and not any(falte(wort) == b for b in BEKANNTE):
            continue  # einmal im Fliesstext erwaehnt: eher Rauschen
        begriffe.append(Begriff(wort, round(min(wert, 8.0), 1), art_von(wort)))
        if len(begriffe) >= max_anzahl:
            break
    return begriffe


# ---------------------------------------------------------------- Abgleich

def _varianten(wort: str) -> set[str]:
    f = falte(wort).strip()
    if " oder " in f:
        return set().union(*(_varianten(teil) for teil in f.split(" oder ")))
    aus = {f}
    for gruppe in SYNONYME:
        if f in gruppe:
            aus |= gruppe
    return aus


def finde_titel(titel: str, text: str) -> str:
    """Titel gilt als gefunden, wenn alle Kernwoerter vorkommen (Reihenfolge egal)."""
    woerter = _titel_woerter(titel) or [titel]
    belege = [finde(w, text) for w in woerter]
    return belege[0] if all(belege) else ""


def finde(wort: str, text: str) -> str:
    """Sucht ein Wort im Text - mit Synonymen, Wortstamm und als Teil zusammengesetzter Woerter.
    Gibt die Fundstelle (kurzer Ausschnitt) zurueck oder ''."""
    gefaltet = falte(text)
    for v in sorted(_varianten(wort), key=len, reverse=True):
        if not v:
            continue
        muster = re.escape(v) if len(v) < 5 else re.escape(stamm(v) if " " not in v else v)
        grenze_vorn = r"(?<![\w])" if len(v) < 5 else ""
        treffer = re.search(grenze_vorn + muster + (r"(?![\w])" if len(v) < 4 else ""), gefaltet)
        if treffer:
            a, b = max(0, treffer.start() - 30), min(len(gefaltet), treffer.end() + 30)
            return text[a:b].replace("\n", " ").strip()
    return ""


def pruefe(titel: str, anzeige: str, lebenslauf: dict, profil_text: str = "", llm=None,
           melde=lambda _: None) -> Bericht:
    begriffe = heuristik(titel, anzeige)
    mit_modell = False
    if llm is not None:
        try:
            antwort = llm.frage_json(llm.prompt("ats_schluesselwoerter"),
                                     f"STELLE: {titel}\n\nANZEIGE:\n{anzeige[:6000]}",
                                     aufgabe="ats_schluesselwoerter")
            vorhanden = {stamm(b.wort) for b in begriffe}
            for art in ("formal", "werkzeuge", "fach", "persoenlich"):
                for wort in antwort.get(art) or []:
                    wort = str(wort).strip()
                    if not wort or len(wort) > 60 or stamm(wort) in vorhanden:
                        continue
                    if not finde(wort, titel + "\n" + anzeige) and len(wort.split()) == 1:
                        continue  # Modell hat etwas eingebracht, das nicht in der Anzeige steht
                    begriffe.append(Begriff(wort, 2.5 if art in ("formal", "werkzeuge") else 2.0, art))
                    vorhanden.add(stamm(wort))
            mit_modell = True
        except Exception as fehler:  # Modell optional
            melde(f"Modell fuer Schluesselwoerter nicht nutzbar: {fehler}")

    lv_text = lv.als_text(lebenslauf)
    gesamt = lv_text + "\n" + (profil_text or "")
    for b in begriffe:
        beleg = finde_titel(b.wort, gesamt) if b.art == "titel" else finde(b.wort, gesamt)
        b.gefunden, b.beleg = bool(beleg), beleg
    summe = sum(b.gewicht for b in begriffe) or 1
    punkte = round(100 * sum(b.gewicht for b in begriffe if b.gefunden) / summe)

    kopf = " ".join([lebenslauf["person"].get("titel", ""), lebenslauf.get("kurzprofil", "")])
    kern = titel_kern(titel)
    titel_treffer = bool(kern) and bool(finde_titel(kern, kopf))

    hinweise = []
    if kern and not titel_treffer:
        hinweise.append(f"„{kern}“ steht nicht in Wunschposition oder Kurzprofil – Portale gewichten den "
                        "Stellentitel stark. Wenn es passt: als Wunschposition eintragen.")
    fehlend_wichtig = [b.wort for b in sorted(begriffe, key=lambda x: -x.gewicht) if not b.gefunden and b.art != "titel"][:5]
    if fehlend_wichtig:
        hinweise.append("Nicht gefunden: " + ", ".join(fehlend_wichtig) +
                        ". Nur ergänzen, wenn es stimmt - etwa als Stichpunkt bei einer Station oder unter Kenntnisse.")
    d = lebenslauf
    if d["design"].get("vorlage") != "klar":
        hinweise.append("Für Online-Portale die Vorlage „klar“ nehmen: eine Spalte liest jedes System sicher.")
    if not d["person"].get("email") or not d["person"].get("telefon"):
        hinweise.append("E-Mail und Telefon gehören in den Kopf des Lebenslaufs.")
    if not d.get("kurzprofil"):
        hinweise.append("Ein Kurzprofil mit zwei, drei Sätzen hilft Mensch und Maschine beim ersten Blick.")
    ohne_zeit = [e.get("titel") or e.get("abschluss") for e in d["erfahrung"] + d["bildung"] if not e.get("von")]
    if ohne_zeit:
        hinweise.append("Ohne Zeitangabe: " + ", ".join(x for x in ohne_zeit if x) + ".")
    return Bericht(punkte, begriffe, hinweise, titel_treffer, mit_modell)


def kurzprofil_vorschlag(bericht: Bericht, titel: str, lebenslauf: dict, profil_text: str, llm) -> dict:
    """Neues Kurzprofil aus belegten Fakten. Begriffe, die das Modell nutzt, aber nicht belegt sind,
    werden gemeldet - der Vorschlag wird dann nicht empfohlen."""
    eingabe = (f"STELLE: {titel}\n\nTREFFER: {', '.join(b.wort for b in bericht.gefunden)}\n"
               f"FEHLT: {', '.join(b.wort for b in bericht.fehlend)}\n\n"
               f"BISHERIGES KURZPROFIL:\n{lebenslauf.get('kurzprofil', '')}\n\n"
               f"LEBENSLAUF:\n{lv.als_text(lebenslauf)[:4000]}\n\nPROFIL:\n{(profil_text or '')[:2500]}")
    antwort = llm.frage_json(llm.prompt("ats_kurzprofil"), eingabe, aufgabe="ats_kurzprofil")
    text = str(antwort.get("kurzprofil") or "").strip()
    belegbar = lv.als_text(lebenslauf) + "\n" + (profil_text or "")
    unbelegt = [w for w in antwort.get("genutzt") or [] if not finde(str(w), belegbar)]
    for b in bericht.fehlend:
        if finde(b.wort, text) and not finde(b.wort, belegbar) and b.wort not in unbelegt:
            unbelegt.append(b.wort)
    return {"kurzprofil": text, "unbelegt": unbelegt, "empfohlen": bool(text) and not unbelegt}
