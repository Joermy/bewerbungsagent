"""Kommandozeile.

  python -m bewerbungsagent app        Oberflaeche im Browser (Standard)
  python -m bewerbungsagent lauf       neuer Lauf im Terminal
  python -m bewerbungsagent status     Einrichtung pruefen
  python -m bewerbungsagent senden ID  Versand mit Rueckfrage im Terminal
  python -m bewerbungsagent mcp        MCP-Server (stdio) fuer Claude Code, Hermes & Co.
"""
from __future__ import annotations

import argparse
import sys

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
        anlagen = dienst.anlagen()
        zeile(bool(anlagen), "Anlagen", ", ".join(a.name for a in anlagen) or "keine gefunden")
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
