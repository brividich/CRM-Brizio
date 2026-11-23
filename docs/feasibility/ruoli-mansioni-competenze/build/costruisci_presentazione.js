/* Presentazione per l'incontro con Direzione e Qualità (9 diapositive, 16:9).

   Uso:  NODE_PATH=<cartella con pptxgenjs>/node_modules  PPTX_SKILL=<cartella della skill pptx>
         node build/costruisci_presentazione.js      →  Fattibilita_RMC_Presentazione.pptx

   Stessi contenuti e stessi numeri della sintesi per la Direzione (build/pdf_direzione.html) e di 04_gap_sgi.md.
   Nomi e dati degli esempi sono inventati; i numeri sul presente vengono dalla skill matrix firmata in vigore, senza nominativi.
   I dati oggi nel portale per questa parte sono caricamenti di prova: non compaiono. */
const path = require("path");
const pptxgen = require("pptxgenjs");
const { applyTheme } = require(path.join(process.env.PPTX_SKILL, "scripts", "apply_theme.js"));

const RADICE = path.resolve(__dirname, "..");
const PNG = (f) => path.join(RADICE, "prototipo", "png", f);
const USCITA = path.join(RADICE, "Fattibilita_RMC_Presentazione.pptx");

const THEME = {
  name: "CN HUB competenze",
  headFontFace: "Arial",
  bodyFontFace: "Calibri",
  colors: {
    dk1: "10233F", lt1: "FFFFFF", dk2: "1D3A63", lt2: "F1F5FA",
    accent1: "D9480F", accent2: "17663A", accent3: "64748B", accent4: "FFF1E6", accent5: "E6F4EC", accent6: "C5CED9",
    hlink: "1D3A63", folHlink: "64748B",
  },
};

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.33 × 7.5 pollici
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
pres.title = "Ruoli, mansioni e competenze";
pres.subject = "Proposta per Direzione e Qualità";
pres.author = "CN HUB · analisi di fattibilità";
const C = pres.SchemeColor;
const W = 13.33;
const M = 0.6; // margine

const PIEDE = [{ text: { text: "CN HUB  ·  Ruoli, mansioni e competenze", options: { x: M, y: 6.98, w: 6, h: 0.3, fontSize: 10, color: C.accent3, margin: 0 } } }];

pres.defineSlideMaster({
  title: "TITOLO", background: { color: THEME.colors.dk1 },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: M, y: 2.2, w: 10.6, h: 2.2, fontSize: 40, bold: true, color: C.background1, valign: "top", align: "left", margin: 0 }, text: "Titolo" } },
    { placeholder: { options: { name: "body", type: "body", x: M, y: 4.7, w: 9.4, h: 1.2, fontSize: 20, color: C.accent6, valign: "top", align: "left", margin: 0 }, text: "Sottotitolo" } },
  ],
});
pres.defineSlideMaster({
  title: "CONTENUTO", background: { color: THEME.colors.lt1 },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: M, y: 0.45, w: W - 2 * M, h: 1.15, fontSize: 30, bold: true, color: C.text1, valign: "top", align: "left", margin: 0 }, text: "Titolo" } },
    ...PIEDE,
  ],
  slideNumber: { x: W - M - 0.6, y: 6.98, w: 0.6, h: 0.3, fontSize: 10, color: C.accent3, align: "right" },
});
pres.defineSlideMaster({
  title: "CHIUSURA", background: { color: THEME.colors.dk1 },
  objects: [
    { placeholder: { options: { name: "title", type: "title", x: M, y: 0.55, w: W - 2 * M, h: 1.0, fontSize: 34, bold: true, color: C.background1, valign: "top", align: "left", margin: 0 }, text: "Titolo" } },
  ],
  slideNumber: { x: W - M - 0.6, y: 6.98, w: 0.6, h: 0.3, fontSize: 10, color: C.accent6, align: "right" },
});

// ---------- attrezzi ----------
let n = 0;
const nome = (p) => `${p}-${++n}`;
function testo(s, t, x, y, w, h, o = {}) {
  s.addText(t, { x, y, w, h, margin: 0, isTextBox: true, fontSize: 15, color: C.text1, valign: "top", objectName: nome("testo"), ...o });
}
function riquadro(s, x, y, w, h, colore = C.background2, o = {}) {
  s.addShape(pres.ShapeType.roundRect, { x, y, w, h, rectRadius: 0.08, fill: { color: colore }, line: { color: colore, width: 0 }, objectName: nome("riquadro"), ...o });
}
function bollo(s, x, y, d, t, colore = C.accent1, dim = 16) {
  s.addShape(pres.ShapeType.ellipse, { x, y, w: d, h: d, fill: { color: colore }, line: { color: colore, width: 0 }, objectName: nome("bollo") });
  s.addText(String(t), { x, y, w: d, h: d, margin: 0, isTextBox: true, align: "center", valign: "middle", fontSize: dim, bold: true, color: C.background1, objectName: nome("numero") });
}
function freccia(s, x, y, w, colore = C.accent1) {
  s.addShape(pres.ShapeType.rightArrow, { x, y, w, h: 0.34, fill: { color: colore }, line: { color: colore, width: 0 }, objectName: nome("freccia") });
}
function diapositiva(layout, sezione, titolo, note) {
  const s = pres.addSlide({ masterName: layout, sectionTitle: sezione });
  s.addText(titolo, { placeholder: "title" });
  if (note) s.addNotes(note);
  return s;
}

// ====================================================================== 1. Titolo
pres.addSection({ title: "La proposta" });
{
  const s = diapositiva("TITOLO", "La proposta", "Le persone giuste sul lavoro giusto, con le prove in mano",
    "Apertura. In un quarto d'ora: dove siamo, l'idea, i livelli, come funziona, una prova dal vivo, le decisioni.");
  s.addText("Ruoli, mansioni e competenze nel portale. Proposta per Direzione e Qualità, novembre 2026", { placeholder: "body" });
  testo(s, [{ text: "CN ", options: { color: C.background1 } }, { text: "HUB", options: { color: C.accent1 } }], M, 0.7, 3, 0.5, { fontSize: 20, bold: true, charSpacing: 4 });
}

// ====================================================================== 2. Dove siamo
{
  const s = diapositiva("CONTENUTO", "La proposta", "Oggi chi è abilitato a fare che cosa sta scritto sulla carta",
    "Il riferimento è il sistema di gestione: la skill matrix firmata ad aprile e la scheda personale. Nel portale questa parte è ancora in prova e non la consideriamo. Il punto debole non è la regola, che c'è: è che dimostrarla richiede di raccogliere fogli diversi.");
  const dati = [
    ["La skill matrix", "Un foglio firmato due volte l'anno. Una lettera per persona e per mansione."],
    ["La scheda personale", "Compilata a mano all'ingresso. Contiene già che cosa bisogna saper fare su ogni macchina."],
    ["Le scadenze", "Scritte nei documenti. Nessuno riceve un avviso quando un corso scade."],
  ];
  const w = 3.85, g = 0.29;
  dati.forEach(([t, d], i) => {
    const x = M + i * (w + g);
    riquadro(s, x, 2.0, w, 3.0);
    bollo(s, x + 0.35, 2.3, 0.75, i + 1, C.text2, 24);
    testo(s, t, x + 0.35, 3.25, w - 0.7, 0.5, { fontSize: 22, bold: true });
    testo(s, d, x + 0.35, 3.8, w - 0.7, 1.1, { fontSize: 16, color: C.text2 });
  });
  testo(s, "Per un audit o per un cliente, la risposta si costruisce a mano ogni volta.", M, 5.45, W - 2 * M, 0.7, { fontSize: 20, bold: true });
}

// ====================================================================== 3. La ricetta
{
  const s = diapositiva("CONTENUTO", "La proposta", "Ogni mansione ha la sua ricetta: il portale controlla chi ha gli ingredienti",
    "Esempio con nome e dati inventati. La ricetta dice che cosa bisogna saper fare. La dispensa è ciò che la persona sa fare davvero. Il portale confronta e propone: non assegna nulla da solo. La Qualità sta già scrivendo le ricette: 253 mansioni e 208 competenze, con «sì» o «no» per ogni incrocio. Sono compilati gli uffici; manca la produzione.");
  const voci = [
    ["Lettura del disegno tecnico", true], ["Set-up macchina 5 assi", true], ["Programmazione a bordo macchina", false],
    ["Controllo dimensionale in macchina", true], ["Gestione utensili e presetting", true], ["Prevenzione FOD", true],
  ];
  const wc = 5.55, y0 = 1.95, hr = 0.5;
  [["LA RICETTA", "Fresatura 5 assi grande formato", M], ["LA DISPENSA", "Marco Rivalta, operatore", W - M - wc]].forEach(([eti, tit, x], k) => {
    riquadro(s, x, y0, wc, 4.1);
    testo(s, eti, x + 0.3, y0 + 0.18, wc - 0.6, 0.3, { fontSize: 12, bold: true, color: k ? C.accent1 : C.accent3, charSpacing: 2 });
    testo(s, tit, x + 0.3, y0 + 0.48, wc - 0.6, 0.45, { fontSize: 20, bold: true });
    voci.forEach(([v, ha], i) => {
      const y = y0 + 1.05 + i * hr;
      if (k && !ha) riquadro(s, x + 0.15, y - 0.03, wc - 0.3, hr - 0.04, C.accent4);
      testo(s, v, x + 0.3, y, wc - 1.9, hr - 0.1, { fontSize: 16, valign: "middle" });
      if (k) testo(s, ha ? "c'è" : "manca", x + wc - 1.65, y, 1.35, hr - 0.1, { fontSize: 16, bold: true, align: "right", valign: "middle", color: ha ? C.accent2 : C.accent1 });
    });
  });
  freccia(s, M + wc + 0.2, 3.85, W - 2 * M - 2 * wc - 0.4);
  testo(s, "5 ingredienti su 6: gli serve una sola formazione, non sei.", M, 6.2, W - 2 * M, 0.6, { fontSize: 20, bold: true });
}

// ====================================================================== 4. I livelli
{
  const s = diapositiva("CONTENUTO", "La proposta", "I livelli funzionano come la patente",
    "Sono i quattro livelli della procedura Risorse Umane in vigore. Si sale solo con un giudizio del capo reparto dopo la formazione, con una prova scritta.");
  const liv = [
    ["I", "Foglio rosa", "Lavora solo con qualcuno accanto. Non firma."],
    ["L", "Patente appena presa", "Lavora da solo sui lavori che conosce. Firma."],
    ["U", "Patente consolidata", "Lavora da solo su tutto. Firma."],
    ["O", "Istruttore", "Insegna ai colleghi."],
  ];
  const w = 2.85, g = 0.21, base = 5.75;
  liv.forEach(([let, pat, cosa], i) => {
    const h = 3.0 + i * 0.3, x = M + i * (w + g), y = base - h;
    riquadro(s, x, y, w, h, i === 3 ? C.accent4 : C.background2);
    bollo(s, x + 0.3, y + 0.3, 0.85, let, i < 2 ? C.text2 : i === 2 ? C.accent2 : C.accent1, 30);
    testo(s, pat, x + 0.3, y + 1.3, w - 0.6, 0.75, { fontSize: 18, bold: true, color: C.accent1 });
    testo(s, cosa, x + 0.3, y + 2.1, w - 0.6, 0.85, { fontSize: 16 });
  });
  testo(s, "Si sale solo con un giudizio del capo reparto. Mai in automatico.", M, 6.1, W - 2 * M, 0.6, { fontSize: 20, bold: true });
}

// ====================================================================== 5. Come funziona
{
  const s = diapositiva("CONTENUTO", "La proposta", "Come funziona: cinque passi, e firma sempre una persona",
    "Un solo filo, dall'ingresso alla conferma. La richiesta di mansione è l'unico atto che assegna una mansione; la formazione valutata è l'unico atto che cambia un livello. Ogni sei mesi RDD firma la skill matrix, come oggi. Se qualcosa scade il portale avvisa e decide il capo reparto; sui liquidi penetranti blocca, come impone già la procedura.");
  const tappe = [
    ["Ingresso", "La persona entra in azienda."],
    ["Richiesta di mansione", "Il capo reparto chiede, RDD approva."],
    ["Formazione", "Il capo reparto valuta e lascia la prova."],
    ["Mansione effettiva", "La persona lavora e firma."],
    ["Conferma", "Ogni sei mesi RDD firma la skill matrix."],
  ];
  const w = 2.2, g = 0.28, y = 2.0;
  tappe.forEach(([t, d], i) => {
    const x = M + i * (w + g);
    riquadro(s, x, y, w, 3.3, i === 3 ? C.accent5 : C.background2);
    bollo(s, x + 0.25, y + 0.25, 0.75, i + 1, i === 3 ? C.accent2 : C.accent1, 24);
    testo(s, t, x + 0.25, y + 1.2, w - 0.45, 0.75, { fontSize: 20, bold: true });
    testo(s, d, x + 0.25, y + 2.0, w - 0.45, 1.2, { fontSize: 16, color: C.text2 });
    if (i < tappe.length - 1) freccia(s, x + w + 0.02, y + 0.45, g - 0.04);
  });
  testo(s, "Se qualcosa scade, il portale avvisa. Decide il capo reparto.", M, 5.7, W - 2 * M, 0.6, { fontSize: 20, bold: true });
}

// ====================================================================== 6. Demo
{
  const s = diapositiva("CONTENUTO", "La proposta", "Che cosa vedranno le persone: cinque minuti dal vivo",
    "Aprire il prototipo. I dati sono inventati e niente tocca il portale vero. Mostrare: la copertura, un clic su una lettera della skill matrix, la richiesta di mansione, la scheda personale.");
  const wi = 8.2, hi = wi * 900 / 1440;
  s.addImage({ path: PNG("01_cruscotto_qualita.png"), x: M, y: 1.75, w: wi, h: hi, objectName: "schermata-cruscotto", altText: "Prototipo: cruscotto della Qualità" });
  const passi = ["La copertura", "La skill matrix", "La richiesta di mansione", "La mia scheda"];
  const x = M + wi + 0.5, w = W - M - x;
  passi.forEach((t, i) => {
    const y = 1.95 + i * 1.05;
    bollo(s, x, y, 0.65, i + 1, C.accent1, 22);
    testo(s, t, x + 0.85, y, w - 0.85, 0.65, { fontSize: 19, bold: true, valign: "middle" });
  });
  testo(s, "Prototipo con dati inventati", x, 6.2, w, 0.35, { fontSize: 13, color: C.accent3 });
}

// ====================================================================== 7. Il menu
{
  const s = diapositiva("CONTENUTO", "La proposta", "Dove si trova: il menu passa da tre livelli a due",
    "Oggi il menu di Anagrafica ha tre livelli e 60 voci, e le voci si vedono una sezione alla volta. La proposta: sei pilastri, al massimo sei voci ciascuno, tutte visibili. Le parole sono quelle dei documenti della Qualità. Gli indirizzi delle pagine e i permessi non cambiano.");
  const wi = 8.2, hi = wi * 818 / 1800;
  s.addImage({ path: path.join(RADICE, "menu", "07_proposta_barre.png"), x: M, y: 1.9, w: wi, h: hi, objectName: "schermata-menu", altText: "Il menu proposto, pilastro per pilastro" });
  const punti = [["Sei pilastri", "Al massimo sei voci ciascuno."], ["Si entra da «Oggi»", "Ognuno vede ciò che lo aspetta."], ["Una pagina per tipo", "Una skill matrix, uno scadenzario."]];
  const x = M + wi + 0.5, w = W - M - x;
  punti.forEach(([t, d], i) => {
    const y = 1.95 + i * 1.25;
    bollo(s, x, y, 0.65, i + 1, C.accent1, 22);
    testo(s, t, x + 0.85, y - 0.05, w - 0.85, 0.4, { fontSize: 19, bold: true });
    testo(s, d, x + 0.85, y + 0.38, w - 0.85, 0.6, { fontSize: 15, color: C.text2 });
  });
  testo(s, "Da 60 voci a 34, con dentro le funzioni nuove.", M, 6.1, W - 2 * M, 0.6, { fontSize: 20, bold: true });
}

// ====================================================================== 8. I tempi
{
  const s = diapositiva("CONTENUTO", "La proposta", "Quanto ci vuole: si parte in due settimane",
    "Sono giorni di sviluppo di una persona. Il primo passo usa il modulo che esiste già: si carica la skill matrix firmata e RDD la firma nel portale. Il calendario vero lo detta il lavoro sui contenuti: le ricette della produzione sono ancora da scrivere.");
  const tappe = [
    ["1-2 settimane", "Si parte", "La skill matrix firmata entra nel portale, e RDD la firma lì."],
    ["7-11 settimane", "Prima tappa", "Livelli con la prova accanto e avvisi sulle scadenze, su un reparto."],
    ["6-11 mesi", "Tutto", "Richieste di mansione, firme, uffici, clienti, indicatori, menu."],
  ];
  const w = 3.85, g = 0.29;
  tappe.forEach(([quanto, t, d], i) => {
    const x = M + i * (w + g);
    riquadro(s, x, 2.0, w, 3.3, i === 0 ? C.accent5 : C.background2);
    testo(s, quanto, x + 0.35, 2.3, w - 0.7, 0.7, { fontSize: 30, bold: true, color: i === 0 ? C.accent2 : C.accent1 });
    testo(s, t, x + 0.35, 3.2, w - 0.7, 0.5, { fontSize: 22, bold: true });
    testo(s, d, x + 0.35, 3.8, w - 0.7, 1.3, { fontSize: 16, color: C.text2 });
  });
  testo(s, "Il calendario vero lo detta il lavoro sulle ricette della produzione.", M, 5.75, W - 2 * M, 0.6, { fontSize: 20, bold: true });
}

// ====================================================================== 9. Le scelte
{
  const s = diapositiva("CHIUSURA", "La proposta", "Tre scelte di fondo",
    "Sono le tre scelte del foglio per la Direzione. Proposta: sì alla prima, sì alla seconda, segnalare alla terza, con il blocco solo dove la procedura lo impone già. Tutto il resto, dal reparto di partenza alle date, lo definiscono la Qualità e il responsabile del progetto.");
  const dec = [
    ["Il portale diventa il registro ufficiale?", "Skill matrix e scheda personale nel portale, firmate lì da RDD."],
    ["Adottiamo il nuovo modello della Qualità?", "Competenze valutate una per una; mansioni assegnate con una richiesta approvata."],
    ["Se una competenza non è più valida: segnalare o fermare?", "Proposta: segnalare. Fermare solo dove la procedura lo impone già."],
  ];
  dec.forEach(([t, d], i) => {
    const y = 2.0 + i * 1.45;
    bollo(s, M, y, 0.85, i + 1, C.accent1, 28);
    testo(s, t, M + 1.2, y - 0.05, W - 2 * M - 1.2, 0.5, { fontSize: 25, bold: true, color: C.background1 });
    testo(s, d, M + 1.2, y + 0.5, W - 2 * M - 1.2, 0.5, { fontSize: 17, color: C.accent6 });
  });
}

(async () => {
  await pres.writeFile({ fileName: USCITA });
  await applyTheme(USCITA, THEME);
  console.log(USCITA);
})();
