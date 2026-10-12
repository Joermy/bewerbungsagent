"""Anbindung an Agenten: Hermes Agent, Claude Desktop und Claude Code ueber MCP.

Erzeugt die Konfigurationsschnipsel mit den echten Pfaden dieses Rechners und
schreibt auf Wunsch den Hermes-Skill nach ~/.hermes/skills/bewerbungsagent/SKILL.md.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

from . import modellcfg as mc

SKILL_KOPF = """---
name: bewerbungsagent
description: Stellen suchen, Lebenslauf pflegen und Anschreiben schreiben mit dem lokalen Bewerbungsagenten (MCP). Nutzen, wenn die Person Bewerbungen, Stellen, Anschreiben, Lebenslauf oder ATS erwähnt.
version: 1.0.0
metadata:
  hermes:
    tags: [bewerbung, jobs, lebenslauf, deutsch]
    requires_toolsets: [mcp]
---
"""

SKILL_ENDE = """

## Werkzeuge (MCP-Server "bewerbungsagent")

| Werkzeug | Wozu |
| --- | --- |
| profil_zeigen, lebenslauf_zeigen | Fakten über die Person lesen |
| lauf_starten, lauf_zeigen, laeufe_auflisten | Stellen suchen und ansehen |
| anschreiben_regeln, anschreiben_setzen | Regeln lesen, Text für eine Stelle eintragen |
| ats_pruefen, kurzprofil_fuer_stelle | Abgleich Anzeige ↔ Lebenslauf, Kurzprofil je Stelle |
| stelle_aus_link, stelle_hinzufuegen | Anzeige von einer Webseite oder von Hand aufnehmen |
| lebenslauf_aendern, portfolio_importieren | Lebenslauf pflegen (nur mit Zustimmung der Person) |
| versand_pruefen | Prüfen, ob alles für den Versand bereit ist |

Senden gibt es als Werkzeug nicht – das macht die Person in der App.

## Modell

Hermes Agent braucht ein Modell mit mindestens 64k Kontext. Lokal z. B. Hermes 3 (Llama 3.1 8B)
oder Qwen 2.5 7B über Ollama oder LM Studio; den Kontext im Server entsprechend hochsetzen.
"""


def python_pfad() -> str:
    return sys.executable.replace("\\", "/")


def _server(wurzel: Path) -> dict:
    return {"command": python_pfad(), "args": ["-m", "bewerbungsagent", "mcp"],
            "env": {"BEWERBUNGSAGENT_WURZEL": str(Path(wurzel).resolve()).replace("\\", "/")}}


def hermes_config(wurzel: Path) -> str:
    return "# in ~/.hermes/config.yaml ergänzen\n" + yaml.safe_dump(
        {"mcp_servers": {"bewerbungsagent": _server(wurzel)}}, allow_unicode=True, sort_keys=False)


def claude_desktop(wurzel: Path) -> str:
    return json.dumps({"mcpServers": {"bewerbungsagent": _server(wurzel)}}, indent=2, ensure_ascii=False)


def claude_code(wurzel: Path) -> str:
    s = _server(wurzel)
    return (f'claude mcp add bewerbungsagent -s user -e BEWERBUNGSAGENT_WURZEL="{s["env"]["BEWERBUNGSAGENT_WURZEL"]}"'
            f' -- "{s["command"]}" -m bewerbungsagent mcp')


def agent_prompt(wurzel: Path) -> str:
    try:
        return mc.lade(wurzel).prompt("agent")
    except FileNotFoundError:
        return ""


def skill_text(wurzel: Path) -> str:
    return SKILL_KOPF + "\n# Bewerbungsagent\n\n" + agent_prompt(wurzel) + SKILL_ENDE


def hermes_skill_installieren(wurzel: Path, heim: Path | None = None) -> Path:
    ziel = (heim or Path.home()) / ".hermes" / "skills" / "bewerbungsagent" / "SKILL.md"
    ziel.parent.mkdir(parents=True, exist_ok=True)
    ziel.write_text(skill_text(wurzel), encoding="utf-8")
    return ziel


def alles(wurzel: Path) -> dict:
    hermes_skill = Path.home() / ".hermes" / "skills" / "bewerbungsagent" / "SKILL.md"
    return {
        "hermes_config": hermes_config(wurzel),
        "hermes_skill": skill_text(wurzel),
        "hermes_skill_pfad": str(hermes_skill),
        "hermes_skill_da": hermes_skill.exists(),
        "hermes_da": (Path.home() / ".hermes").exists(),
        "claude_desktop": claude_desktop(wurzel),
        "claude_code": claude_code(wurzel),
        "agent_prompt": agent_prompt(wurzel),
    }
