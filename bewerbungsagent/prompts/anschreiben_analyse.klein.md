<!-- Schritt 1 fuer kleine Modelle (7-14B). Kurz, nummeriert, ein Beispiel. -->
Du liest eine Stellenanzeige und ein Bewerberprofil. Du schreibst KEINEN Brief.
Antworte auf Deutsch und NUR mit JSON.

Felder:
1. "firma": ein Satz, was die Firma macht. Nur aus der Anzeige. Unbekannt = "".
2. "anforderungen": genau 3 Anforderungen der Stelle, kurz (höchstens 8 Wörter).
3. "belege": genau 3 Einträge. Zu jeder Anforderung ein Satz aus dem PROFIL, der dazu passt.
   Kein passender Satz im Profil = "". NIE etwas erfinden.
4. "motivation": ein Grund aus dem Profil, warum die Stelle passt. Unbekannt = "".
5. "arbeitsprobe": true bei Web, IT, Software, Gestaltung oder Medien, sonst false.

Beispiel:
{"firma": "Ein Softwarehaus für Praxissoftware in Hannover.",
 "anforderungen": ["Kundensupport am Telefon", "Windows-Kenntnisse", "Teamarbeit"],
 "belege": ["Am Empfang einer Arztpraxis Telefon und Termine betreut", "Windows-Rechner für Familie und Bekannte eingerichtet", ""],
 "motivation": "Möchte beruflich in die IT.",
 "arbeitsprobe": true}
