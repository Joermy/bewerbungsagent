"use strict";
// Jobquellen, Lesezeichen und Portal-Zentrale

ansichten.quellen = async function ladeQuellen() {
  const q = await api("/api/quellen");
  zeichneQuellen(q);
  zeichneLesezeichen(q);
  zeichnePortale(q);
};

function zeichneQuellen(q) {
  const c = q.quellen;
  const s = q.schluessel;
  const speichere = async (werte) => {
    try { const neu = await api("/api/quellen", werte); zeichneQuellen(neu); zeichnePortale(neu); } catch (err) { hinweis(err.message); }
  };
  const zeile = (schluessel, titel, text, status) => {
    const c2 = el("input", { type: "checkbox" });
    c2.checked = !!c[schluessel];
    c2.addEventListener("change", () => speichere({ [schluessel]: c2.checked }));
    return el("li", { class: "quelle" }, el("label", { class: "schalter" }, c2, el("span")),
      el("div", {}, el("strong", { text: titel }), el("p", { class: "gedaempft klein", text })),
      status ? el("span", { class: "pille " + (status.ok ? "gesendet" : "fehler"), text: status.text }) : null);
  };
  const zahl = (schluessel, name, min, max) => {
    const i = el("input", { type: "number", min: String(min), max: String(max), value: String(c[schluessel]), class: "schmal-zahl" });
    i.addEventListener("change", () => speichere({ [schluessel]: Number(i.value) }));
    return el("label", { class: "feld inline" }, el("span", { text: name }), i);
  };
  $("#quellenKarte").replaceChildren(
    el("h3", { text: "Automatische Suche" }),
    el("ul", { class: "quellen" },
      zeile("arbeitsagentur", "Jobbörse der Arbeitsagentur", "Offizielle Schnittstelle, mit vollem Anzeigentext und oft einer Bewerbungsadresse."),
      zeile("adzuna", "Adzuna", "Sammelt Anzeigen vieler Jobbörsen und Firmenseiten. Kostenloser Schlüssel auf developer.adzuna.com, in .env: ADZUNA_APP_ID und ADZUNA_APP_KEY.",
        c.adzuna ? { ok: s.adzuna, text: s.adzuna ? "Schlüssel da" : "Schlüssel fehlt" } : null),
      zeile("jooble", "Jooble", "Weitere Suchmaschine für Stellen. Schlüssel über jooble.org/api/about, in .env: JOOBLE_KEY.",
        c.jooble ? { ok: s.jooble, text: s.jooble ? "Schlüssel da" : "Schlüssel fehlt" } : null),
      zeile("mail_alarme", "Jobalarme aus dem Postfach", "Liest die Mails von Indeed, StepStone, LinkedIn, XING und Co. – nur lesen, nichts löschen. In .env: IMAP_HOST, IMAP_USER, IMAP_PASSWORD.",
        c.mail_alarme ? { ok: s.imap, text: s.imap ? "Postfach da" : "Zugang fehlt" } : null)),
    el("div", { class: "zahlen-zeile" }, zahl("max_treffer", "Treffer je Suchbegriff", 5, 200), zahl("mail_tage", "Alarme der letzten Tage", 1, 60)),
    el("p", { class: "gedaempft klein", text: "Anzeigen ohne Bewerbungsadresse landen unter „Selbst bewerben“ – mit Link zur Originalanzeige. Doppelte Anzeigen von mehreren Portalen fallen zusammen." }));
}

function zeichneLesezeichen(q) {
  const lz = q.lesezeichen;
  const link = (href, text, klasse) => {
    const a = el("a", { class: "lesezeichen " + klasse, text, title: "In die Lesezeichenleiste ziehen" });
    a.setAttribute("href", href);
    a.addEventListener("click", (ev) => { ev.preventDefault(); alert("Dieses Lesezeichen in die Lesezeichenleiste ziehen und dann auf einer Stellenanzeige anklicken."); });
    return a;
  };
  $("#lesezeichenKarte").replaceChildren(
    el("h3", { text: "Lesezeichen für den Browser" }),
    el("p", { class: "gedaempft", text: "Ziehe die beiden Knöpfe in deine Lesezeichenleiste. Sie arbeiten in deinem eigenen Browser – also auch auf Seiten, für die man angemeldet sein oder ein Captcha lösen muss." }),
    el("div", { class: "lesezeichen-zeile" }, link(lz.uebernehmen, "↓ Übernehmen", "primaer"),
      el("p", { class: "klein", text: "Auf einer Stellenanzeige anklicken: die Anzeige kommt hierher, du bestätigst, der Agent schreibt das Anschreiben. Markierter Text hat Vorrang." })),
    lz.ausfuellen ? el("div", { class: "lesezeichen-zeile" }, link(lz.ausfuellen, "✎ Ausfüllen", ""),
      el("p", { class: "klein", text: "Im Bewerbungsformular eines Portals anklicken: Name, E-Mail, Telefon, Adresse und Links werden eingetragen. Abgeschickt wird nichts, Passwörter und Uploads bleiben bei dir. Nach Profiländerungen neu ziehen." }))
      : el("p", { class: "gedaempft klein", text: "„Ausfüllen“ erscheint, sobald ein Profil angelegt ist." }));
}

function zeichnePortale(q) {
  const wegeText = (wege) => wege.map((w) => ({ api: "API", mail: "Jobalarm", lesezeichen: "Lesezeichen" })[w]).join(" · ");
  const zeilen = q.portale.map((p) => {
    const haken = (schluessel) => {
      const c = el("input", { type: "checkbox" });
      c.checked = !!p[schluessel];
      c.addEventListener("change", async () => {
        try { await api("/api/portal", { id: p.id, [schluessel]: c.checked }); } catch (err) { hinweis(err.message); }
      });
      return c;
    };
    const notiz = el("input", { class: "notiz", value: p.notiz || "", placeholder: "Notiz, z. B. Benutzername" });
    notiz.addEventListener("change", async () => {
      try { await api("/api/portal", { id: p.id, notiz: notiz.value }); } catch (err) { hinweis(err.message); }
    });
    return [
      el("div", {}, link(p.name, p.url), el("small", { class: "gedaempft block", text: p.art })),
      el("div", {}, el("span", { class: "klein", text: wegeText(p.wege) }), p.tipp ? el("small", { class: "gedaempft block", text: p.tipp }) : null),
      el("span", { class: "pille " + (/sucht|gelesen/.test(p.aktiv) ? "gesendet" : /fehlt/.test(p.aktiv) ? "fehler" : ""), text: p.aktiv }),
      haken("konto"), haken("alarm"), notiz,
    ];
  });
  tabelle($("#portalTabelle"), ["Portal", "So nutzt der Agent es", "Stand", "Konto", "Jobalarm", "Notiz"], zeilen, "");
}
