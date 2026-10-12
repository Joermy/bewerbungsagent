"use strict";
// Lebenslauf-Editor mit Live-Vorschau. Daten: profil/lebenslauf.yaml

const LV = {
  daten: null,
  meta: null,
  geaendert: false,
  art: "lebenslauf",
  timer: null,
  laeuft: 0,
};

const PERSON_FELDER = [
  ["name", "Name"], ["titel", "Wunschposition oder Berufsbezeichnung"], ["email", "E-Mail"], ["telefon", "Telefon"],
  ["strasse", "Straße und Hausnummer"], ["plz_ort", "PLZ und Ort"], ["web", "Website oder Portfolio"],
  ["github", "GitHub"], ["linkedin", "LinkedIn"], ["geburtsdatum", "Geburtsdatum (freiwillig)"],
  ["geburtsort", "Geburtsort (freiwillig)"], ["fuehrerschein", "Führerschein"], ["verfuegbar", "Verfügbar ab"],
];

const LISTEN = {
  erfahrung: {
    titel: "Erfahrung", neu: { titel: "", firma: "", ort: "", von: "", bis: "", punkte: [] },
    felder: [["titel", "Tätigkeit"], ["firma", "Firma"], ["ort", "Ort"], ["von", "von (z. B. 2025-04)"], ["bis", "bis (2026-03 oder heute)"]],
    punkte: true, kopf: (x) => [x.titel, x.firma].filter(Boolean).join(" · "),
  },
  bildung: {
    titel: "Bildung", neu: { abschluss: "", schule: "", ort: "", von: "", bis: "", note: "", punkte: [] },
    felder: [["abschluss", "Abschluss"], ["schule", "Schule"], ["ort", "Ort"], ["von", "von (z. B. 2014)"], ["bis", "bis"], ["note", "Note (freiwillig)"]],
    punkte: true, kopf: (x) => [x.abschluss, x.schule].filter(Boolean).join(" · "),
  },
  projekte: {
    titel: "Projekte", neu: { titel: "", untertitel: "", beschreibung: "", technik: [], url: "", github: "", bild: "" },
    felder: [["titel", "Titel"], ["untertitel", "Untertitel"], ["url", "Link (für QR-Code)"], ["github", "GitHub"], ["technik", "Technik, mit Komma getrennt"]],
    text: "beschreibung", bild: true, kopf: (x) => x.titel,
  },
  sprachen: {
    titel: "Sprachen", neu: { name: "", stufe: "", wert: 3 },
    felder: [["name", "Sprache"], ["stufe", "Niveau, z. B. Muttersprache oder B2"], ["wert", "Skala 0–5"]],
    kopf: (x) => [x.name, x.stufe].filter(Boolean).join(" · "),
  },
  zertifikate: {
    titel: "Weiterbildung und Zertifikate", neu: { name: "", aussteller: "", jahr: "" },
    felder: [["name", "Bezeichnung"], ["aussteller", "Aussteller"], ["jahr", "Jahr"]],
    kopf: (x) => [x.name, x.jahr].filter(Boolean).join(" · "),
  },
};

ansichten.lebenslauf = async function ladeLebenslauf(neu = false) {
  if (LV.daten && !neu) { zeichneVorschau(); return; }
  const antwort = await api("/api/lebenslauf");
  LV.meta = antwort;
  LV.daten = antwort.daten;
  LV.geaendert = false;
  const banner = $("#lvHinweis");
  const meldungen = [];
  if (!antwort.vorhanden) meldungen.push("Noch kein Lebenslauf gespeichert – das hier ist ein Entwurf aus deinem Profil. Ergänzen und speichern.");
  if (!antwort.druck) meldungen.push("Kein Edge, Chrome oder Chromium gefunden: Die Vorschau geht, für PDFs den Browserpfad unter dokumente.browser in config.yaml eintragen.");
  banner.textContent = meldungen.join(" ");
  banner.classList.toggle("versteckt", !meldungen.length);
  $("#lvPdf").href = `/unterlagen/${TOKEN}/lebenslauf.pdf`;
  $("#lvPdf").classList.toggle("versteckt", !antwort.druck);
  $("#lvYaml").value = antwort.yaml;
  zeichneInhalt();
  zeichneDesign();
  stand();
  zeichneVorschau();
};

function stand(text) {
  $("#lvStand").textContent = text || (LV.geaendert ? "Nicht gespeichert" : "Gespeichert");
  $("#lvStand").classList.toggle("offen", LV.geaendert);
}

function geaendert() {
  LV.geaendert = true;
  stand();
  clearTimeout(LV.timer);
  LV.timer = setTimeout(zeichneVorschau, 550);
}

// ---------------------------------------------------------------- Vorschau

async function zeichneVorschau() {
  if (!LV.daten) return;
  const nr = ++LV.laeuft;
  $("#vorschauStand").textContent = "aktualisiert …";
  try {
    const { id } = await api("/api/vorschau", { art: LV.art, daten: LV.daten });
    if (nr !== LV.laeuft) return;
    const rahmen = $("#lvVorschau");
    let y = 0;
    try { y = rahmen.contentWindow.scrollY; } catch (e) { /* egal */ }
    rahmen.onload = () => {
      try { rahmen.contentWindow.scrollTo(0, y); } catch (e) { /* egal */ }
      $("#vorschauStand").textContent = "";
    };
    rahmen.src = `/vorschau/${TOKEN}/${id}`;
  } catch (err) {
    $("#vorschauStand").textContent = err.message;
  }
}

$$("#vorschauArt button").forEach((b) => b.addEventListener("click", () => {
  $$("#vorschauArt button").forEach((x) => x.classList.toggle("aktiv", x === b));
  LV.art = b.dataset.art;
  zeichneVorschau();
}));

$$("#lvReiter button").forEach((b) => b.addEventListener("click", () => {
  $$("#lvReiter button").forEach((x) => x.classList.toggle("aktiv", x === b));
  $$("[data-lvbereich]").forEach((x) => x.classList.toggle("versteckt", x.dataset.lvbereich !== b.dataset.lv));
  if (b.dataset.lv === "yaml") $("#lvYaml").value = jsyaml(LV.daten);
}));

// sehr einfache YAML-Ausgabe fuer den Reiter (der Server liefert beim Laden die echte)
function jsyaml(d) {
  return LV.geaendert ? "# Ungespeicherte Änderungen – erst speichern, dann hier bearbeiten.\n" + LV.meta.yaml : LV.meta.yaml;
}

// ---------------------------------------------------------------- Inhalt

function feld(beschriftung, wert, beiAenderung, art = "input", extra = {}) {
  const eingabe = art === "textarea" ? el("textarea", { rows: extra.zeilen || "3" }) : el("input", { type: extra.typ || "text" });
  if (extra.platzhalter) eingabe.placeholder = extra.platzhalter;
  eingabe.value = wert ?? "";
  eingabe.addEventListener("input", () => { beiAenderung(eingabe.value); geaendert(); });
  return el("label", { class: "feld" + (extra.breit ? " breit" : "") }, el("span", { text: beschriftung }), eingabe);
}

function gruppe(titel, inhalt, offen = false, zusatz = null) {
  const d = el("details", { class: "lv-gruppe" }, el("summary", {}, el("span", { text: titel }), zusatz), ...inhalt);
  if (offen) d.open = true;
  return d;
}

function zeichneInhalt() {
  const d = LV.daten;
  const ziel = $("#lvInhalt");
  const p = d.person;

  // Person mit Foto
  const fotoBild = el("div", { class: "foto-wahl" });
  const fotoKnopf = el("input", { type: "file", accept: "image/png,image/jpeg,image/webp" });
  const zeigeFoto = () => {
    fotoBild.replaceChildren(el("span", { class: "gedaempft klein", text: p.foto ? p.foto : "kein Foto" }));
  };
  zeigeFoto();
  fotoKnopf.addEventListener("change", async () => {
    const datei = fotoKnopf.files[0];
    if (!datei) return;
    try {
      const daten = await verkleinere(datei, 900);
      const { pfad } = await api("/api/bild", { art: "foto", name: "foto", daten });
      p.foto = pfad;
      zeigeFoto();
      geaendert();
    } catch (err) { hinweis(err.message); }
  });
  const personFelder = el("div", { class: "zwei" }, ...PERSON_FELDER.map(([k, name]) => feld(name, p[k], (v) => { p[k] = v; })));
  const fotoZeile = el("div", { class: "foto-zeile" }, el("label", { class: "knopf klein" }, "Foto wählen", fotoKnopf), fotoBild,
    el("button", { class: "knopf klein leise", text: "Foto entfernen", onclick: () => { p.foto = ""; zeigeFoto(); geaendert(); } }));

  // Kurzprofil mit Wortzahl
  const zaehler = el("span", { class: "gedaempft klein" });
  const zaehle = () => { const n = (d.kurzprofil || "").split(/\s+/).filter(Boolean).length; zaehler.textContent = `${n} Wörter – gut sind 35 bis 70`; };
  zaehle();
  const kurz = feld("Zwei bis drei Sätze: wer du bist, was du kannst, was du suchst", d.kurzprofil, (v) => { d.kurzprofil = v; zaehle(); }, "textarea", { zeilen: "6" });

  const teile = [
    gruppe("Person und Kontakt", [fotoZeile, personFelder], !LV.meta.vorhanden),
    gruppe("Kurzprofil", [kurz, zaehler], true),
    liste("erfahrung"),
    liste("bildung"),
    projektGruppe(),
    kenntnisGruppe(),
    liste("sprachen"),
    liste("zertifikate"),
    gruppe("Interessen", [feld("Mit Komma getrennt", (d.interessen || []).join(", "), (v) => {
      d.interessen = v.split(",").map((x) => x.trim()).filter(Boolean);
    })]),
  ];
  if (!LV.meta.vorhanden) {
    teile.unshift(el("div", { class: "karte-flach leise-karte" },
      el("p", { text: "Tipp: Mit „Aus Profil übernehmen“ holst du Name, Kontakt und die Stichpunkte aus profil.md. Projekte kommen am schnellsten über den Portfolio-Import." }),
      el("button", { class: "knopf klein", text: "Aus Profil übernehmen", onclick: async () => {
        const { daten } = await api("/api/lebenslauf/aus-profil", {});
        LV.daten = daten; zeichneInhalt(); geaendert();
      } })));
  }
  ziel.replaceChildren(...teile);
}

function eintragKnoepfe(arr, i, neuZeichnen) {
  const k = (text, titel, fn) => el("button", { class: "knopf klein leise", title: titel, text, onclick: (ev) => { ev.preventDefault(); fn(); neuZeichnen(); geaendert(); } });
  return el("div", { class: "eintrag-knoepfe" },
    k("↑", "nach oben", () => { if (i > 0) [arr[i - 1], arr[i]] = [arr[i], arr[i - 1]]; }),
    k("↓", "nach unten", () => { if (i < arr.length - 1) [arr[i + 1], arr[i]] = [arr[i], arr[i + 1]]; }),
    k("Entfernen", "Eintrag löschen", () => arr.splice(i, 1)));
}

function liste(name) {
  const def = LISTEN[name];
  const arr = LV.daten[name];
  const behaelter = el("div", { class: "eintraege" });
  const zeichne = () => {
    behaelter.replaceChildren(...arr.map((x, i) => {
      const kopf = el("span", { class: "eintrag-titel", text: def.kopf(x) || "Neuer Eintrag" });
      const felder = def.felder.map(([k, b]) => {
        const wert = Array.isArray(x[k]) ? x[k].join(", ") : x[k];
        return feld(b, wert, (v) => {
          x[k] = k === "technik" ? v.split(",").map((t) => t.trim()).filter(Boolean) : k === "wert" ? Number(v) || 0 : v;
          kopf.textContent = def.kopf(x) || "Neuer Eintrag";
        }, "input", k === "wert" ? { typ: "number" } : {});
      });
      const extra = [];
      if (def.text) extra.push(feld("Beschreibung, ein bis zwei Sätze", x[def.text], (v) => { x[def.text] = v; }, "textarea", { zeilen: "2", breit: true }));
      if (def.punkte) extra.push(feld("Stichpunkte, einer pro Zeile – mit einem Verb anfangen", (x.punkte || []).join("\n"),
        (v) => { x.punkte = v.split("\n").map((t) => t.trim()).filter(Boolean); }, "textarea", { zeilen: "3", breit: true }));
      if (def.bild) extra.push(bildFeld(x));
      const d = el("details", { class: "eintrag" }, el("summary", {}, kopf, eintragKnoepfe(arr, i, zeichne)),
        el("div", { class: "zwei" }, ...felder, ...extra));
      if (!def.kopf(x)) d.open = true;
      return d;
    }));
  };
  zeichne();
  const plus = el("button", { class: "knopf klein", text: "+ Eintrag", onclick: () => { arr.push(structuredClone(def.neu)); zeichne(); geaendert(); } });
  return gruppe(`${def.titel} (${arr.length})`, [behaelter, plus]);
}

function bildFeld(x) {
  const status = el("span", { class: "gedaempft klein", text: x.bild || "kein Bild" });
  const wahl = el("input", { type: "file", accept: "image/png,image/jpeg,image/webp" });
  wahl.addEventListener("change", async () => {
    const datei = wahl.files[0];
    if (!datei) return;
    try {
      const daten = await verkleinere(datei, 1200);
      const { pfad } = await api("/api/bild", { art: "projekt", name: x.titel || "projekt", daten });
      x.bild = pfad; status.textContent = pfad; geaendert();
    } catch (err) { hinweis(err.message); }
  });
  return el("div", { class: "feld breit" }, el("span", { text: "Vorschaubild (16:10 wirkt am besten)" }),
    el("div", { class: "foto-zeile" }, el("label", { class: "knopf klein" }, "Bild wählen", wahl), status));
}

function projektGruppe() {
  const g = liste("projekte");
  const quelle = el("input", { placeholder: "https://name.github.io oder Ordner der Website", value: (LV.daten.person.web || "") });
  const anzahl = el("input", { type: "number", value: "6", min: "1", max: "20", class: "schmal-zahl" });
  const ersetzen = el("input", { type: "checkbox" });
  const los = el("button", { class: "knopf klein primaer", text: "Projekte importieren", onclick: async (ev) => {
    ev.preventDefault();
    if (LV.geaendert && !confirm("Ungespeicherte Änderungen gehen beim Import verloren. Trotzdem importieren?")) return;
    try {
      await auftragErgebnis("/api/portfolio", { quelle: quelle.value, max: Number(anzahl.value), ersetzen: ersetzen.checked });
      await ansichten.lebenslauf(true);
    } catch (err) { hinweis(err.message); }
  } });
  const box = el("div", { class: "import-box" },
    el("strong", { text: "Aus deiner Portfolio-Website holen" }),
    el("p", { class: "gedaempft klein", text: "Liest daten/projekte.js oder projekte.json deiner Website, übernimmt Titel, Beschreibung, Technik, Link und lädt die Vorschaubilder herunter." }),
    el("div", { class: "import-zeile" }, quelle, anzahl, el("label", { class: "haken" }, ersetzen, " ersetzen"), los));
  g.querySelector("summary").after(box);
  return g;
}

function kenntnisGruppe() {
  const arr = LV.daten.kenntnisse;
  const behaelter = el("div", { class: "eintraege" });
  const zeichne = () => {
    behaelter.replaceChildren(...arr.map((g, i) => {
      const kopf = el("span", { class: "eintrag-titel", text: g.gruppe || "Neue Gruppe" });
      const zeilen = el("div", { class: "kenntnis-zeilen" });
      const zeichneZeilen = () => {
        zeilen.replaceChildren(...g.eintraege.map((k, j) => {
          const name = el("input", { value: k.name, placeholder: "z. B. Python" });
          name.addEventListener("input", () => { k.name = name.value; geaendert(); });
          const stufe = el("select", {}, ...["keine Skala", "1", "2", "3", "4", "5"].map((t, n) => el("option", { value: String(n), text: t })));
          stufe.value = String(k.stufe || 0);
          stufe.addEventListener("change", () => { k.stufe = Number(stufe.value); geaendert(); });
          const weg = el("button", { class: "knopf klein leise", text: "×", title: "entfernen", onclick: (ev) => { ev.preventDefault(); g.eintraege.splice(j, 1); zeichneZeilen(); geaendert(); } });
          return el("div", { class: "kenntnis-zeile" }, name, stufe, weg);
        }));
      };
      zeichneZeilen();
      const plus = el("button", { class: "knopf klein leise", text: "+ Kenntnis", onclick: (ev) => { ev.preventDefault(); g.eintraege.push({ name: "", stufe: 0 }); zeichneZeilen(); } });
      const d = el("details", { class: "eintrag" }, el("summary", {}, kopf, eintragKnoepfe(arr, i, zeichne)),
        feld("Gruppe, z. B. Programmierung", g.gruppe, (v) => { g.gruppe = v; kopf.textContent = v || "Neue Gruppe"; }),
        zeilen, plus);
      return d;
    }));
  };
  zeichne();
  const plus = el("button", { class: "knopf klein", text: "+ Gruppe", onclick: () => { arr.push({ gruppe: "", eintraege: [{ name: "", stufe: 0 }] }); zeichne(); geaendert(); } });
  return gruppe(`Kenntnisse (${arr.length} Gruppen)`, [el("p", { class: "gedaempft klein", text: "Skala 1–5 zeigt Punkte oder Balken. Ohne Skala erscheinen die Einträge als Schlagworte." }), behaelter, plus]);
}

// Bilder vor dem Hochladen verkleinern (spart Platz in PDF und Mail)
function verkleinere(datei, maxKante) {
  return new Promise((ok, fehler) => {
    const leser = new FileReader();
    leser.onerror = () => fehler(new Error("Bild nicht lesbar"));
    leser.onload = () => {
      const bild = new Image();
      bild.onerror = () => fehler(new Error("Bild nicht lesbar"));
      bild.onload = () => {
        const f = Math.min(1, maxKante / Math.max(bild.width, bild.height));
        const c = document.createElement("canvas");
        c.width = Math.round(bild.width * f);
        c.height = Math.round(bild.height * f);
        c.getContext("2d").drawImage(bild, 0, 0, c.width, c.height);
        ok(c.toDataURL("image/jpeg", 0.88));
      };
      bild.src = leser.result;
    };
    leser.readAsDataURL(datei);
  });
}

// ---------------------------------------------------------------- Design

function zeichneDesign() {
  const d = LV.daten.design;
  const m = LV.meta;
  const ziel = $("#lvDesign");
  const neu = () => { geaendert(); zeichneDesign(); };

  const vorlagen = el("div", { class: "vorlagen" }, ...Object.entries(m.vorlagen).map(([k, text]) => el("button", {
    class: "vorlage" + (d.vorlage === k ? " aktiv" : ""), onclick: () => { d.vorlage = k; neu(); },
  }, el("span", { class: `vorlage-bild v-${k}` }, el("i"), el("i"), el("i")), el("strong", { text: k[0].toUpperCase() + k.slice(1) }), el("small", { text }))));

  const farben = el("div", { class: "farben" }, ...Object.entries(m.akzente).map(([k, farbe]) => el("button", {
    class: "farbe" + (!d.eigene_farbe && d.akzent === k ? " aktiv" : "") + (k === "spektrum" ? " spektrum" : ""),
    style: `--f:${farbe}`, title: k, onclick: () => { d.akzent = k; d.eigene_farbe = ""; neu(); },
  })));
  const eigene = el("input", { type: "color", value: d.eigene_farbe || "#9b5cff", title: "eigene Farbe" });
  eigene.addEventListener("change", () => { d.eigene_farbe = eigene.value; neu(); });
  farben.append(el("label", { class: "farbe eigen" + (d.eigene_farbe ? " aktiv" : ""), title: "eigene Farbe" }, eigene));

  const auswahl = (name, wert, optionen, fn) => {
    const s = el("select", {}, ...Object.entries(optionen).map(([k, t]) => el("option", { value: k, text: t })));
    s.value = wert;
    s.addEventListener("change", () => fn(s.value));
    return el("label", { class: "feld" }, el("span", { text: name }), s);
  };
  const schalter = (name, schluessel) => {
    const c = el("input", { type: "checkbox" });
    c.checked = !!d[schluessel];
    c.addEventListener("change", () => { d[schluessel] = c.checked; geaendert(); });
    return el("label", { class: "haken" }, c, " " + name);
  };

  const reihenfolge = el("ol", { class: "reihenfolge" }, ...d.abschnitte.map((a, i) => {
    const aus = (d.ausblenden || []).includes(a);
    const c = el("input", { type: "checkbox" });
    c.checked = !aus;
    c.addEventListener("change", () => {
      d.ausblenden = (d.ausblenden || []).filter((x) => x !== a);
      if (!c.checked) d.ausblenden.push(a);
      geaendert();
    });
    const schieb = (r) => el("button", { class: "knopf klein leise", text: r < 0 ? "↑" : "↓", onclick: () => {
      const j = i + r;
      if (j < 0 || j >= d.abschnitte.length) return;
      [d.abschnitte[i], d.abschnitte[j]] = [d.abschnitte[j], d.abschnitte[i]];
      neu();
    } });
    return el("li", { class: aus ? "aus" : "" }, el("label", { class: "haken" }, c, " " + m.abschnitte[a]), schieb(-1), schieb(1));
  }));

  const dok = m.dokumente;
  const dokSchalter = (name, schluessel) => {
    const c = el("input", { type: "checkbox" });
    c.checked = !!dok[schluessel];
    c.addEventListener("change", async () => {
      try { LV.meta.dokumente = await api("/api/dokumente", { [schluessel]: c.checked }); } catch (err) { hinweis(err.message); }
    });
    return el("label", { class: "haken" }, c, " " + name);
  };
  const anhang = el("select", {}, el("option", { value: "einzeln", text: "einzelne PDFs (Anschreiben, Lebenslauf, Anlagen)" }),
    el("option", { value: "mappe", text: "eine Bewerbungsmappe (alles in einer PDF)" }));
  anhang.value = dok.anhang;
  anhang.addEventListener("change", async () => {
    try { LV.meta.dokumente = await api("/api/dokumente", { anhang: anhang.value }); } catch (err) { hinweis(err.message); }
  });

  const maxProjekte = el("input", { type: "number", min: "0", max: "8", value: String(d.max_projekte), class: "schmal-zahl" });
  maxProjekte.addEventListener("input", () => { d.max_projekte = Number(maxProjekte.value) || 0; geaendert(); });

  ziel.replaceChildren(
    el("div", { class: "karte-flach" }, el("h3", { text: "Vorlage" }), vorlagen),
    el("div", { class: "karte-flach" }, el("h3", { text: "Farbe und Schrift" }), farben,
      el("div", { class: "zwei" },
        auswahl("Schrift", d.schrift, { bricolage: "Bricolage Grotesque + Inter (modern)", inter: "Inter (neutral)", serif: "Source Serif + Inter (klassisch)" }, (v) => { d.schrift = v; geaendert(); }),
        auswahl("Skalen bei Kenntnissen", d.skalen, { punkte: "Punkte", balken: "Balken", aus: "keine" }, (v) => { d.skalen = v; geaendert(); }),
        auswahl("Fotoform", d.foto_form, { rund: "rund", eckig: "abgerundetes Rechteck" }, (v) => { d.foto_form = v; geaendert(); }),
        el("label", { class: "feld" }, el("span", { text: "Projekte im Lebenslauf (höchstens)" }), maxProjekte)),
      el("div", { class: "haken-liste" }, schalter("Foto zeigen", "foto"), schalter("QR-Codes zu Projekten", "qr"),
        schalter("Projektbilder zeigen", "projekt_bilder"), schalter("Ort und Datum am Ende", "ort_datum"),
        schalter("Unterschriftslinie", "unterschrift_im_lebenslauf"))),
    el("div", { class: "karte-flach" }, el("h3", { text: "Abschnitte und Reihenfolge" }), reihenfolge),
    el("div", { class: "karte-flach" }, el("h3", { text: "Beim Versand anhängen" }),
      el("label", { class: "feld" }, el("span", { text: "Form" }), anhang),
      el("div", { class: "haken-liste" }, dokSchalter("Lebenslauf aus diesen Daten erzeugen", "lebenslauf"),
        dokSchalter("Projektseite anhängen", "projektseite"), dokSchalter("Deckblatt vor der Mappe", "deckblatt")),
      el("p", { class: "gedaempft klein", text: "Wird der Lebenslauf erzeugt, fällt eine alte Lebenslauf-PDF aus den Anlagen weg. Zeugnisse und andere Anlagen bleiben." })),
  );
}

// ---------------------------------------------------------------- Speichern, YAML, ATS

$("#lvSpeichern").addEventListener("click", async () => {
  try {
    const antwort = await api("/api/lebenslauf", { daten: LV.daten });
    LV.meta = antwort;
    LV.daten = antwort.daten;
    LV.geaendert = false;
    $("#lvHinweis").classList.add("versteckt");
    stand("Gespeichert");
    zeichneInhalt();
  } catch (err) { hinweis(err.message); }
});

$("#lvYamlLos").addEventListener("click", async () => {
  try {
    await api("/api/lebenslauf", { yaml: $("#lvYaml").value });
    await ansichten.lebenslauf(true);
    stand("YAML übernommen");
  } catch (err) { hinweis(err.message); }
});

async function atsLauf(mitModell) {
  const daten = { titel: $("#atsTitel").value, text: $("#atsText").value };
  try {
    const b = mitModell ? await auftragErgebnis("/api/ats", { ...daten, modell: true }) : await api("/api/ats", daten);
    zeigeAts($("#atsErgebnis"), b);
  } catch (err) { hinweis(err.message); }
}
$("#atsLos").addEventListener("click", () => atsLauf(false));
$("#atsModell").addEventListener("click", () => atsLauf(true));
$("#atsKurz").addEventListener("click", async () => {
  try {
    const v = await auftragErgebnis("/api/ats/kurzprofil", { titel: $("#atsTitel").value, text: $("#atsText").value });
    const ziel = $("#atsErgebnis");
    const uebernehmen = el("button", { class: "knopf klein primaer", text: "Ins Kurzprofil übernehmen", onclick: () => {
      LV.daten.kurzprofil = v.kurzprofil; zeichneInhalt(); geaendert();
    } });
    zeigeAts(ziel, v.bericht);
    ziel.prepend(el("div", { class: "vorschlag" }, el("h4", { text: "Vorschlag für das Kurzprofil" }), el("p", { text: v.kurzprofil }),
      el("p", { class: v.unbelegt.length ? "warnung" : "gedaempft klein",
        text: v.unbelegt.length ? `Nicht im Lebenslauf belegt: ${v.unbelegt.join(", ")} – so nicht übernehmen.` : "Nur belegte Begriffe verwendet." }),
      uebernehmen));
  } catch (err) { hinweis(err.message); }
});

window.addEventListener("beforeunload", (ev) => {
  if (LV.geaendert) { ev.preventDefault(); ev.returnValue = ""; }
});
