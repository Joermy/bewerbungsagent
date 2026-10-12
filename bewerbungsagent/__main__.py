"""Kommandozeile.

  python -m bewerbungsagent app        Oberflaeche im Browser (Standard)
  python -m bewerbungsagent lauf       neuer Lauf im Terminal
  python -m bewerbungsagent status     Einrichtung pruefen
  python -m bewerbungsagent senden ID  Versand mit Rueckfrage im Terminal
  python -m bewerbungsagent mcp        MCP-Server (stdio) fuer Claude Code, Hermes & Co.

  python -m bewerbungsagent lebenslauf [ZIEL.pdf]      Lebenslauf als PDF (aus profil/lebenslauf.yaml)
  python -m bewerbungsagent portfolio QUELLE           Projekte aus der eigenen Website holen
  python -m bewerbungsagent ats DATEI [--titel ...]    ATS-Check einer Anzeige (Textdatei, - = stdin)
  python -m bewerbungsagent stelle URL                 Anzeige von einer Webseite als Entwurf anlegen
  python -m bewerbungsagent hermes-skill               Skill fuer Hermes Agent installieren
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import config


def _utf8_konsole():
    for strom in (sys.stdout, sys.stderr):
        try:
            strom.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bewerbungsagent", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--wurzel", default=None, help="Projektordner mit config.yaml (Standard: automatisch)")
    unter = parser.add_subparsers(dest="befehl")
    app = unter.add_parser("app", help="Oberflaeche starten")
    app.add_argument("--ohne-browser", action="store_true")
    unter.add_parser("lauf", help="neuen Lauf im Terminal")
    unter.add_parser("suchen", help="Trockenlauf: nur suchen und filtern, nichts speichern")
    unter.add_parser("status", help="Einrichtung pruefen")
    senden = unter.add_parser("senden", help="Lauf nach Rueckfrage verschicken")
    senden.add_argument("batch_id")
    unter.add_parser("mcp", help="MCP-Server ueber stdio")
    lebenslauf = unter.add_parser("lebenslauf", help="Lebenslauf als PDF erzeugen")
    lebenslauf.add_argument("ziel", nargs="?", default="")
    lebenslauf.add_argument("--projekte", action="store_true", help="zusaetzlich die Projektseite")
    port = unter.add_parser("portfolio", help="Projekte aus der Portfolio-Website importieren")
    port.add_argument("quelle", help="URL (https://name.github.io) oder Ordner der Website")
    port.add_argument("--max", type=int, default=6)
    port.add_argument("--ersetzen", action="store_true")
    ats = unter.add_parser("ats", help="ATS-Check einer Anzeige gegen den Lebenslauf")
    ats.add_argument("datei", help="Textdatei mit der Anzeige, - fuer stdin")
    ats.add_argument("--titel", default="")
    ats.add_argument("--modell", action="store_true", help="Begriffe zusaetzlich vom Modell ziehen lassen")
    stelle = unter.add_parser("stelle", help="Anzeige per Link uebernehmen")
    stelle.add_argument("url")
    unter.add_parser("hermes-skill", help="Skill nach ~/.hermes/skills/ schreiben")
    args = parser.parse_args(argv)

    if args.befehl == "mcp":
        from .mcp_server import main as mcp_main
        mcp_main()
        return 0

    _utf8_konsole()
    cfg = config.lade(args.wurzel or config.projektwurzel())

    if args.befehl in (None, "app"):
        from .app import starte
        starte(cfg, oeffnen=not getattr(args, "ohne_browser", False))
        return 0

    from .dienst import Abbruch, Dienst
    dienst = Dienst(cfg)

    if args.befehl == "status":
        def zeile(ok: bool, name: str, info: str):
            print(f"  {'ok   ' if ok else 'FEHLT'}  {name:<16} {info}")

        profil_ok = True
        try:
            p = dienst.profil
            zeile(True, "Profil", f"{p.name}, {p.wohnort}, Suchbegriffe: {', '.join(p.suchbegriffe)}")
        except Exception as fehler:
            profil_ok = False
            zeile(False, "Profil", str(fehler))
        anhaenge = dienst.anhang_uebersicht() if profil_ok else []
        zeile(bool(anhaenge), "Anhaenge", ", ".join(anhaenge) or "kein Lebenslauf - in der App anlegen oder anlagen setzen")
        from . import drucker
        from . import lebenslauf as lv
        browser = drucker.finde_browser(cfg.dokumente.browser) if cfg.dokumente.engine != "fpdf" else None
        zeile(lv.pfad(cfg.wurzel).exists(), "Lebenslauf", "profil/lebenslauf.yaml" if lv.pfad(cfg.wurzel).exists()
              else "noch nicht angelegt (App: Lebenslauf und Design)")
        zeile(bool(browser), "PDF-Druck", browser or "einfaches Layout - Edge/Chrome nicht gefunden (dokumente.browser)")
        modell_ok, modell_info = dienst.llm.bereit()
        zeile(modell_ok, f"Modell ({cfg.llm.backend})", modell_info)
        smtp = dienst.smtp_probleme()
        zeile(not smtp, "SMTP", "; ".join(smtp) or f"{cfg.smtp.user} ueber {cfg.smtp.host}:{cfg.smtp.port}")
        zeile(bool(cfg.mail.sachbearbeitung), "Sachbearbeitung", cfg.mail.sachbearbeitung or "mail.sachbearbeitung in config.yaml")
        zeile(dienst.vault.aktiv, "Vault", str(dienst.vault.ordner) if dienst.vault.aktiv else "aus")
        return 0 if profil_ok else 1

    if args.befehl == "suchen":
        cfg.llm.backend = "keins"
        stellen, _ = dienst.suche()
        mit = [s for s in stellen if s.per_mail]
        print(f"\n{len(mit)} per E-Mail bewerbbar (@), {len(stellen) - len(mit)} selbst bewerben "
              f"(P = Anzeige verlangt Portal)\n")
        for s in stellen[:40]:
            km = f"{s.entfernung_km} km" if s.entfernung_km is not None else ""
            print(f"  {s.punkte:3d}  {'@' if s.per_mail else ('P' if s.weg == 'portal' else ' ')}  {s.titel[:52]:<52} {s.firma[:28]:<28} {s.ort[:16]:<16} {km}")
        return 0

    if args.befehl == "lebenslauf":
        u = dienst.unterlagen
        if not u.html_aktiv:
            print("Kein Edge, Chrome oder Chromium gefunden - Pfad unter dokumente.browser in config.yaml eintragen.")
            return 1
        ziel = Path(args.ziel or f"Lebenslauf_{dienst.profil.name.replace(' ', '_')}.pdf").resolve()
        erg = u.lebenslauf(ziel)
        print(f"{erg.pfad}  ({erg.seiten} Seiten)" + ("".join(f"\n  Hinweis: {h}" for h in erg.hinweise)))
        if args.projekte:
            p2 = u.projektseite(ziel.with_name(ziel.stem + "_Projekte.pdf"))
            print(p2.pfad)
        return 0

    if args.befehl == "portfolio":
        from . import lebenslauf as lv
        from . import portfolio
        d = dienst.unterlagen.daten()
        neu = portfolio.importiere(args.quelle, cfg.wurzel, args.max)
        d["projekte"] = portfolio.zusammenfuehren(d["projekte"], neu, args.ersetzen)
        lv.speichere(cfg.wurzel, d)
        for p in neu:
            print(f"  {p['titel']:<32} {p['url'] or '-':<48} {'Bild' if p['bild'] else ''}")
        print(f"{len(neu)} Projekte in profil/lebenslauf.yaml")
        return 0

    if args.befehl == "ats":
        text = sys.stdin.read() if args.datei == "-" else Path(args.datei).read_text(encoding="utf-8")
        titel = args.titel or text.strip().splitlines()[0][:120]
        b = dienst.ats(titel=titel, text=text, mit_modell=args.modell)
        print(f"\nTrefferquote {b['punkte']} %  ({len(b['gefunden'])} gefunden, {len(b['fehlend'])} fehlen)")
        print("  gefunden: " + ", ".join(x["wort"] for x in b["gefunden"]))
        print("  fehlt:    " + ", ".join(x["wort"] for x in b["fehlend"]))
        for h in b["hinweise"]:
            print(f"  - {h}")
        return 0

    if args.befehl == "stelle":
        batch = dienst.stelle_aus_link(args.url)
        e = batch["eintraege"][-1]
        print(f"Lauf {batch['id']}: {e['stelle']['titel']} bei {e['stelle']['firma']} - pruefen in der App")
        return 0

    if args.befehl == "hermes-skill":
        from . import integrationen
        print(integrationen.hermes_skill_installieren(cfg.wurzel))
        print("\nIn ~/.hermes/config.yaml eintragen:\n")
        print(integrationen.hermes_config(cfg.wurzel))
        return 0

    if args.befehl == "lauf":
        batch = dienst.lauf()
        print(f"\nLauf {batch['id']}: {len(batch['eintraege'])} Entwuerfe. Pruefen und senden: python -m bewerbungsagent app")
        return 0

    if args.befehl == "senden":
        batch = dienst.speicher.lade(args.batch_id)
        offen = [e for e in batch["eintraege"] if e["status"] in ("entwurf", "fehler")]
        for e in offen:
            print(f"  {e['stelle']['firma']:<40} {e['stelle']['email']}")
        print(f"\n{len(offen)} Bewerbungen, danach Nachweis an: {cfg.mail.sachbearbeitung or '(keine Adresse)'}")
        if not sys.stdin.isatty():
            print("Senden nur interaktiv im Terminal oder in der App.")
            return 2
        eingabe = input("Zum Senden SENDEN eintippen: ").strip()
        try:
            dienst.senden(args.batch_id, eingabe)
        except Abbruch as fehler:
            print(f"Abgebrochen: {fehler}")
            return 1
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
