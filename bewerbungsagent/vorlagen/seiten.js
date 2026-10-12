// Verteilt Inhaltsbloecke auf echte A4-Seiten. Laeuft in der Vorschau der App und
// beim Drucken (Chromium wartet ueber --virtual-time-budget, bis alles steht).
//
// Aufbau im Dokument:
//   <div id="quelle" hidden><div data-spalte="haupt">…Bloecke…</div><div data-spalte="seite">…</div></div>
//   <template id="folgeseite">…eine Seite mit [data-ziel="haupt"] und [data-ziel="seite"]…</template>
//   Die erste Seite steht schon im Dokument (.blatt mit Kopf) und hat dieselben Ziele.
// Bloecke mit .halten bleiben mit dem folgenden Block zusammen (Ueberschriften).
(function () {
  "use strict";

  function voll(ziel) {
    return ziel.scrollHeight > ziel.clientHeight + 1;
  }

  function neueSeite(vorlage, behaelter) {
    const knoten = vorlage.content.firstElementChild.cloneNode(true);
    behaelter.appendChild(knoten);
    return knoten;
  }

  function verteilen() {
    const quelle = document.getElementById("quelle");
    const vorlage = document.getElementById("folgeseite");
    const behaelter = document.getElementById("seiten");
    if (!quelle || !behaelter) return fertig();
    const spalten = Array.from(quelle.querySelectorAll("[data-spalte]"));
    const seiten = [behaelter.querySelector(".blatt")];

    for (const spalte of spalten) {
      const name = spalte.dataset.spalte;
      const bloecke = Array.from(spalte.children);
      let s = 0;
      let ziel = seiten[s].querySelector(`[data-ziel="${name}"]`);
      for (let i = 0; i < bloecke.length; i++) {
        const block = bloecke[i];
        ziel.appendChild(block);
        if (!voll(ziel)) continue;
        // passt nicht: Block (und eine haltende Ueberschrift davor) auf die naechste Seite
        const mitnehmen = [block];
        const davor = block.previousElementSibling;
        if (davor && davor.classList.contains("halten")) mitnehmen.unshift(davor);
        if (mitnehmen.length === ziel.children.length) {
          // Block ist fuer eine ganze Seite zu gross - stehen lassen, wird abgeschnitten
          document.documentElement.dataset.ueberlauf = "1";
          continue;
        }
        s += 1;
        if (!seiten[s]) {
          if (!vorlage) {
            document.documentElement.dataset.ueberlauf = "1";
            break;
          }
          seiten[s] = neueSeite(vorlage, behaelter);
        }
        ziel = seiten[s].querySelector(`[data-ziel="${name}"]`);
        if (!ziel) {
          document.documentElement.dataset.ueberlauf = "1";
          break;
        }
        mitnehmen.forEach((b) => ziel.appendChild(b));
      }
    }
    // leere Folgeseiten entfernen, Seitenzahlen setzen
    const alle = Array.from(behaelter.querySelectorAll(".blatt"));
    alle.forEach((b, i) => {
      const leer = i > 0 && Array.from(b.querySelectorAll("[data-ziel]")).every((z) => !z.children.length);
      if (leer) b.remove();
    });
    const rest = Array.from(behaelter.querySelectorAll(".blatt"));
    // Folgeseiten ohne Seitenspalte: Hauptspalte nimmt die volle Breite
    rest.forEach((b, i) => {
      const seite = b.querySelector('[data-ziel="seite"]');
      if (i > 0 && seite && !seite.children.length) b.classList.add("ohne-seite");
    });
    rest.forEach((b, i) => {
      b.querySelectorAll("[data-seitenzahl]").forEach((el) => {
        el.textContent = rest.length > 1 ? `${i + 1} / ${rest.length}` : "";
      });
    });
    document.documentElement.dataset.seiten = String(rest.length);
    fertig();
  }

  function anpassen() {
    // Einseitige Dokumente (Anschreiben): Schriftgrad stufenweise senken, bis alles passt
    const passen = document.querySelector("[data-einpassen]");
    if (!passen) return;
    const stufen = (passen.dataset.einpassen || "10.5,10.2,9.9,9.6,9.3").split(",").map(Number);
    for (const grad of stufen) {
      document.documentElement.style.setProperty("--grad", grad + "pt");
      if (!voll(passen)) {
        document.documentElement.dataset.schriftgrad = String(grad);
        return;
      }
    }
    document.documentElement.dataset.ueberlauf = "1";
  }

  function fertig() {
    const wurzel = document.documentElement;
    wurzel.dataset.fertig = "1";
    // Beim Drucken meldet der Titel dem Programm, wie es ausgegangen ist (PDF-Metadaten).
    // drucker.py liest die Marke aus und schreibt danach den sauberen Titel zurueck.
    if (wurzel.dataset.modus === "vorschau") {
      // In der App-Vorschau die Blaetter auf die Breite des Rahmens einpassen
      const passe = () => {
        const breite = (210 / 25.4) * 96 + 24;
        document.body.style.zoom = String(Math.min(1, window.innerWidth / breite));
      };
      passe();
      window.addEventListener("resize", passe);
    }
    if (wurzel.dataset.modus === "druck") {
      const info = `seiten=${wurzel.dataset.seiten || 1};ueberlauf=${wurzel.dataset.ueberlauf || 0};grad=${wurzel.dataset.schriftgrad || ""}`;
      document.title = `${document.title} [[${info}]]`;
    }
  }

  let gelaufen = false;
  function los() {
    if (gelaufen) return;
    gelaufen = true;
    anpassen();
    verteilen();
  }

  // Kein requestAnimationFrame: beim Drucken im Hintergrund gibt es keine Bildwechsel
  if (document.fonts && document.fonts.ready) {
    document.fonts.ready.then(() => setTimeout(los, 0));
  }
  window.addEventListener("load", () => setTimeout(los, 50));
  setTimeout(los, 1500);
})();
