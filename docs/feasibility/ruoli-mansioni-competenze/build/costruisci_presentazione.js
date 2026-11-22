/* Presentazione per l'incontro con Direzione e Qualità (12 diapositive, 16:9).

   Uso:  NODE_PATH=<cartella con pptxgenjs>/node_modules  PPTX_SKILL=<cartella della skill pptx>
         node build/costruisci_presentazione.js      →  Fattibilita_RMC_Presentazione.pptx

   Stessi contenuti e stessi numeri della sintesi per la Direzione (build/pdf_direzione.html) e di 04_gap_sgi.md.
   Nomi e dati degli esempi sono inventati; i numeri sul presente sono conteggi, senza nominativi. */
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
pres.addSection({ title: "Il punto di partenza" });
{
  const s = diapositiva("TITOLO", "Il punto di partenza", "Le persone giuste sul lavoro giusto, con le prove in mano",
    "Apertura. In venti minuti: il problema, che cosa abbiamo già, la proposta, una prova dal vivo, le cinque decisioni che chiediamo oggi.");
  s.addText("Ruoli, mansioni e competenze nel portale. Proposta per Direzione e Qualità, novembre 2026", { placeholder: "body" });
  testo(s, [{ text: "CN ", options: { color: C.background1 } }, { text: "HUB", options: { color: C.accent1 } }], M, 0.7, 3, 0.5, { fontSize: 20, bold: true, charSpacing: 4 });
  bollo(s, 10.9, 4.35, 1.75, "5", C.accent1, 54);
  testo(s, "decisioni da prendere oggi", 10.4, 6.2, 2.75, 0.4, { fontSize: 14, color: C.accent6, align: "center" });
}

// ====================================================================== 2. Il problema
{
  const s = diapositiva("CONTENUTO", "Il punto di partenza", "Oggi non sappiamo dimostrare in pochi minuti chi è abilitato a fare che cosa",
    "I numeri sono conteggi letti dal portale il 21 novembre 2026, senza nominativi. Il punto non è che manchino le informazioni: sono sparse e scritte a mano. Per un audit EN 9100 e per i clienti aerospazio e motorsport è un punto debole.");
  const dati = [
    ["242", "mansioni nel portale", "Per nessuna il portale sa che cosa bisogna saper fare: è scritto solo sulla carta."],
    ["443", "livelli di abilitazione", "Tutti inseriti a mano. Quasi metà è al livello più alto."],
    ["56 su 135", "persone", "Non hanno alcuna mansione registrata nel portale."],
  ];
  const w = 3.85, g = 0.29;
  dati.forEach(([num, eti, riga], i) => {
    const x = M + i * (w + g);
    riquadro(s, x, 1.95, w, 3.6);
    const [grande, ...resto] = num.split(" ");
    testo(s, [{ text: grande, options: { fontSize: 54 } }, { text: resto.length ? " " + resto.join(" ") : "", options: { fontSize: 24, color: C.accent3 } }],
      x + 0.35, 2.2, w - 0.7, 1.1, { bold: true, fontFace: THEME.headFontFace, valign: "middle" });
    testo(s, eti.toUpperCase(), x + 0.35, 3.4, w - 0.7, 0.35, { fontSize: 13, bold: true, color: C.accent1, charSpacing: 1 });
    testo(s, riga, x + 0.35, 3.85, w - 0.7, 1.5, { fontSize: 16, color: C.text2 });
  });
  testo(s, "Audit, clienti, rischio: una persona con un corso scaduto può restare abilitata sulla carta senza che nessuno riceva un avviso.", M, 5.85, W - 2 * M, 0.75, { fontSize: 17, bold: true });
}

// ====================================================================== 3. Che cosa c'è già
{
  const s = diapositiva("CONTENUTO", "Il punto di partenza", "Le regole ci sono già: il portale non le applica ancora",
    "È il risultato del confronto con i documenti in vigore del sistema di gestione. Tre esempi. La procedura Risorse Umane definisce i livelli: a L si firma, il portale chiede U. La scheda personale contiene già le ricette, nel portale non sono caricate. La skill matrix firmata ad aprile ha circa 690 livelli, il portale 443.");
  const colonne = [["Nel sistema di gestione", C.accent5, C.accent2], ["Nel portale, oggi", C.accent4, C.accent1]];
  const righe = [
    ["I livelli", "Definiti dalla procedura Risorse Umane: dal livello L si firma.", "Si firma solo dal livello U: più severo della procedura."],
    ["Le ricette", "Scritte nella scheda personale, per ogni ruolo e ogni macchina.", "Nessuna caricata: il portale non ha nulla da confrontare."],
    ["La skill matrix", "Firmata dalla Direzione ad aprile: circa 690 livelli.", "443 livelli, senza firma: non è la copia di quella in vigore."],
  ];
  const x0 = M + 2.3, wc = 4.75, g = 0.2;
  colonne.forEach(([t, , col], i) => testo(s, t.toUpperCase(), x0 + i * (wc + g) + 0.25, 1.85, wc, 0.35, { fontSize: 13, bold: true, color: col, charSpacing: 1 }));
  righe.forEach(([tema, a, b], r) => {
    const y = 2.3 + r * 1.42;
    testo(s, tema, M, y + 0.1, 2.1, 1.1, { fontSize: 20, bold: true, valign: "middle" });
    [[a, C.accent5], [b, C.accent4]].forEach(([t, fondo], i) => {
      riquadro(s, x0 + i * (wc + g), y, wc, 1.22, fondo);
      testo(s, t, x0 + i * (wc + g) + 0.25, y + 0.1, wc - 0.5, 1.02, { fontSize: 16, valign: "middle" });
    });
  });
}

// ====================================================================== 4. Oggi e domani
pres.addSection({ title: "La proposta" });
{
  const s = diapositiva("CONTENUTO", "La proposta", "Quattro gesti di tutti i giorni, oggi e domani",
    "Le pagine che le persone usano già restano. Non si butta via niente: si aggiunge l'ordine che manca.");
  const righe = [
    ["Dare una mansione", "Il capo reparto la assegna direttamente e sceglie il livello a mano.", "Una richiesta a video: il portale mostra che cosa manca, firma chi deve."],
    ["Dire che una persona sa fare", "Una lettera scritta a mano nella matrice.", "Un giudizio del capo reparto dopo la formazione, con data e prova."],
    ["Accorgersi che qualcosa scade", "Tre scadenzari diversi, nessun avviso sulle competenze.", "Un solo elenco, con avvisi 90, 60 e 30 giorni prima."],
    ["Rispondere a un audit", "Tre matrici da confrontare fra loro.", "Una pagina: chi, che cosa, a che livello, con quale prova."],
  ];
  const x0 = M + 3.0, wc = 4.4, g = 0.2;
  testo(s, "OGGI", x0 + 0.25, 1.8, wc, 0.32, { fontSize: 13, bold: true, color: C.accent3, charSpacing: 2 });
  testo(s, "DOMANI", x0 + wc + g + 0.25, 1.8, wc, 0.32, { fontSize: 13, bold: true, color: C.accent2, charSpacing: 2 });
  righe.forEach(([tema, a, b], r) => {
    const y = 2.2 + r * 1.13;
    testo(s, tema, M, y, 2.8, 0.98, { fontSize: 18, bold: true, valign: "middle" });
    riquadro(s, x0, y, wc, 0.98, C.background2);
    testo(s, a, x0 + 0.25, y, wc - 0.5, 0.98, { fontSize: 15, color: C.text2, valign: "middle" });
    riquadro(s, x0 + wc + g, y, wc, 0.98, C.accent5);
    testo(s, b, x0 + wc + g + 0.25, y, wc - 0.5, 0.98, { fontSize: 15, valign: "middle" });
  });
}

// ====================================================================== 5. La ricetta
{
  const s = diapositiva("CONTENUTO", "La proposta", "Ogni mansione ha la sua ricetta: il portale controlla chi ha tutti gli ingredienti",
    "Esempio con nome e dati inventati, lo stesso del prototipo. La ricetta dice che cosa bisogna saper fare e quanto bene. La dispensa è ciò che la persona sa fare davvero. Il portale confronta e propone: non assegna nulla da solo. Ciò che la persona ha già dimostrato vale anche sulla nuova macchina.");
  const voci = [
    ["Lettura del disegno tecnico", "autonomo", true], ["Set-up macchina 5 assi", "autonomo", true],
    ["Programmazione a bordo macchina", "intermedio", false], ["Controllo dimensionale in macchina", "autonomo", true],
    ["Gestione utensili e presetting", "intermedio", true], ["Prevenzione FOD, con corso valido", "autonomo", true],
  ];
  const wc = 5.55, y0 = 1.95, hr = 0.47;
  [["LA RICETTA", "Fresatura 5 assi grande formato", M], ["LA DISPENSA", "Marco Rivalta, operatore", W - M - wc]].forEach(([eti, tit, x], k) => {
    riquadro(s, x, y0, wc, 3.95);
    testo(s, eti, x + 0.3, y0 + 0.18, wc - 0.6, 0.3, { fontSize: 12, bold: true, color: k ? C.accent1 : C.accent3, charSpacing: 2 });
    testo(s, tit, x + 0.3, y0 + 0.48, wc - 0.6, 0.45, { fontSize: 19, bold: true });
    voci.forEach(([v, liv, ha], i) => {
      const y = y0 + 1.05 + i * hr;
      if (k && !ha) riquadro(s, x + 0.15, y - 0.03, wc - 0.3, hr - 0.04, C.accent4);
      testo(s, v, x + 0.3, y, wc - 2.0, hr - 0.1, { fontSize: 14, valign: "middle" });
      testo(s, k ? (ha ? "c'è" : "manca") : liv, x + wc - 1.65, y, 1.35, hr - 0.1,
        { fontSize: 14, bold: true, align: "right", valign: "middle", color: k ? (ha ? C.accent2 : C.accent1) : C.text2 });
    });
  });
  freccia(s, M + wc + 0.2, 3.75, W - 2 * M - 2 * wc - 0.4);
  riquadro(s, M, 6.05, W - 2 * M, 0.75, C.text1);
  testo(s, [{ text: "5 ingredienti su 6. ", options: { bold: true, color: C.accent4 } }, { text: "Gli serve una sola formazione, non sei.", options: { color: C.background1 } }],
    M + 0.3, 6.05, W - 2 * M - 0.6, 0.75, { fontSize: 19, valign: "middle" });
}

// ====================================================================== 6. I livelli
{
  const s = diapositiva("CONTENUTO", "La proposta", "I livelli funzionano come la patente",
    "Sono i quattro livelli della procedura Risorse Umane in vigore. Si sale solo con un giudizio del capo reparto dopo la formazione, con una prova scritta. Nessun livello sale o scende da solo.");
  const liv = [
    ["I", "Foglio rosa", "In formazione", "Lavora solo con qualcuno accanto. Non firma."],
    ["L", "Patente appena presa", "Intermedio", "Lavora da solo sui lavori che conosce. Firma ciò che fa."],
    ["U", "Patente consolidata", "Autonomo", "Lavora da solo su tutto, seguendo le istruzioni. Firma."],
    ["O", "Istruttore", "Esperto", "Lavora da solo, firma e insegna ai colleghi."],
  ];
  const w = 2.85, g = 0.21, base = 5.75;
  liv.forEach(([let, pat, nom, cosa], i) => {
    const h = 2.9 + i * 0.3, x = M + i * (w + g), y = base - h;
    riquadro(s, x, y, w, h, i === 3 ? C.accent4 : C.background2);
    bollo(s, x + 0.25, y + 0.25, 0.75, let, i < 2 ? C.text2 : i === 2 ? C.accent2 : C.accent1, 26);
    testo(s, pat, x + 1.15, y + 0.25, w - 1.35, 0.75, { fontSize: 17, bold: true, color: C.accent1, valign: "middle" });
    testo(s, nom.toUpperCase(), x + 0.25, y + 1.15, w - 0.5, 0.3, { fontSize: 11, bold: true, color: C.accent3, charSpacing: 1 });
    testo(s, cosa, x + 0.25, y + 1.5, w - 0.5, 1.3, { fontSize: 15 });
  });
  testo(s, "Si sale solo con un giudizio del capo reparto, dopo la formazione e con una prova scritta. Mai in automatico.", M, 6.0, W - 2 * M, 0.7, { fontSize: 17, bold: true });
}

// ====================================================================== 7. Due atti
{
  const s = diapositiva("CONTENUTO", "La proposta", "Solo due atti cambiano le cose, e li firma sempre una persona",
    "È il cuore della richiesta della Qualità. La sessione formativa è l'unico atto che cambia le competenze. La richiesta di mansione è l'unico atto che assegna una mansione. Il portale confronta, segnala e propone; non decide. In più, ogni sei mesi RDD firma la skill matrix, come chiede la procedura.");
  const atti = [
    ["Sessione formativa", "Cambia ciò che la persona sa fare", ["Il capo reparto valuta e lascia la prova", "La Qualità verifica che sia tutto registrato", "Una sessione vale per più persone e più competenze"]],
    ["Richiesta di mansione", "Cambia ciò che la persona è autorizzata a fare", ["Il capo reparto la chiede, compilata dal portale", "RDD approva l'avvio", "A requisiti raggiunti, l'esito finale e la firma"]],
  ];
  const w = 5.95, g = 0.23;
  atti.forEach(([tit, sotto, passi], i) => {
    const x = M + i * (w + g);
    riquadro(s, x, 1.9, w, 3.75);
    bollo(s, x + 0.3, 2.15, 0.7, i + 1, C.accent1, 24);
    testo(s, tit, x + 1.2, 2.12, w - 1.5, 0.45, { fontSize: 22, bold: true });
    testo(s, sotto, x + 1.2, 2.58, w - 1.5, 0.4, { fontSize: 15, color: C.accent1, bold: true });
    testo(s, passi.map((p, k) => ({ text: p, options: { bullet: true, breakLine: k < passi.length - 1, paraSpaceAfter: 12 } })), x + 0.35, 3.3, w - 0.7, 2.2, { fontSize: 18 });
  });
  testo(s, "Il portale confronta, segnala e propone. Ogni sei mesi RDD firma la skill matrix.", M, 5.95, W - 2 * M, 0.7, { fontSize: 17, bold: true });
}

// ====================================================================== 8. Il percorso
{
  const s = diapositiva("CONTENUTO", "La proposta", "Il percorso di una persona, dall'ingresso all'autonomia",
    "Un solo filo, dalla pratica di inserimento che il portale ha già fino alla conferma semestrale. Oggi queste tappe stanno in quattro punti diversi del menu.");
  const tappe = [
    ["Ingresso", "La pratica di inserimento che il portale ha già."],
    ["Mansione avviata", "Livello I: lavora affiancata, non firma."],
    ["Formazione", "Sessioni: esperienza, affiancamento, corso."],
    ["Mansione effettiva", "Requisiti raggiunti: lavora e firma."],
    ["Conferma", "Ogni sei mesi. RDD firma la skill matrix."],
  ];
  const w = 2.2, g = 0.28, y = 2.0;
  tappe.forEach(([t, d], i) => {
    const x = M + i * (w + g);
    riquadro(s, x, y, w, 3.6, i === 3 ? C.accent5 : C.background2);
    bollo(s, x + 0.25, y + 0.25, 0.7, i + 1, i === 3 ? C.accent2 : C.accent1, 22);
    testo(s, t, x + 0.25, y + 1.15, w - 0.45, 0.75, { fontSize: 20, bold: true });
    testo(s, d, x + 0.25, y + 1.95, w - 0.45, 1.5, { fontSize: 16, color: C.text2 });
    if (i < tappe.length - 1) freccia(s, x + w + 0.02, y + 0.43, g - 0.04);
  });
  testo(s, "Le pagine restano quelle di oggi: cambia l'ordine in cui si incontrano.", M, 5.95, W - 2 * M, 0.7, { fontSize: 17, bold: true });
}

// ====================================================================== 9. Segnalare
{
  const s = diapositiva("CONTENUTO", "La proposta", "Se qualcosa scade, il portale segnala e il capo reparto decide",
    "Nessuna persona viene fermata da un automatismo. Il prezzo è che una segnalazione può essere ignorata: per questo ha un responsabile e un termine. Eccezione: sui controlli con liquidi penetranti la procedura impone già la sospensione, e lì il portale la applica.");
  const passi = [
    ["Che cosa accende la spia", "Un corso scade. La persona non fa quel lavoro da un anno. Salta la conferma semestrale."],
    ["Chi viene avvisato", "La persona e il capo reparto, 90, 60 e 30 giorni prima quando la scadenza è nota."],
    ["Che cosa succede", "Il capo reparto risponde entro dieci giorni lavorativi. Se non risponde, l'avviso sale a RDD."],
  ];
  const w = 3.85, g = 0.29;
  passi.forEach(([t, d], i) => {
    const x = M + i * (w + g);
    riquadro(s, x, 1.95, w, 2.75);
    bollo(s, x + 0.3, 2.2, 0.65, i + 1, C.accent1, 22);
    testo(s, t, x + 1.1, 2.2, w - 1.35, 0.65, { fontSize: 18, bold: true, valign: "middle" });
    testo(s, d, x + 0.3, 3.05, w - 0.6, 1.5, { fontSize: 15, color: C.text2 });
  });
  riquadro(s, M, 5.0, W - 2 * M, 1.5, C.accent4);
  testo(s, "L'eccezione", M + 0.35, 5.15, 3, 0.35, { fontSize: 13, bold: true, color: C.accent1, charSpacing: 1 });
  testo(s, "Sui controlli con liquidi penetranti la procedura impone già la sospensione: lì il portale blocca. Lo stesso si può estendere ad altre lavorazioni critiche, se lo decidiamo.", M + 0.35, 5.5, W - 2 * M - 0.7, 0.9, { fontSize: 16 });
}

// ====================================================================== 10. Demo
pres.addSection({ title: "La prova e le decisioni" });
{
  const s = diapositiva("CONTENUTO", "La prova e le decisioni", "Che cosa vedranno le persone: cinque minuti dal vivo",
    "Aprire il prototipo e seguire i quattro passi. I dati sono inventati e niente tocca il portale vero. Passo 1: il cruscotto. Passo 2: la matrice, un clic su una cella. Passo 3: la richiesta di mansione di Marco Rivalta. Passo 4: la scheda personale.");
  const wi = 6.9, hi = wi * 900 / 1440;
  s.addImage({ path: PNG("01_cruscotto_qualita.png"), x: M, y: 1.9, w: wi, h: hi, objectName: "schermata-cruscotto", altText: "Prototipo: cruscotto della Qualità" });
  testo(s, "Prototipo navigabile, dati inventati", M, 1.9 + hi + 0.1, wi, 0.3, { fontSize: 12, color: C.accent3 });
  const passi = [
    ["Il cruscotto", "Chi è in regola, reparto per reparto."],
    ["La matrice", "Una lettera per competenza. Un clic spiega il perché."],
    ["La richiesta di mansione", "Compilata dal portale, firmata dalle persone."],
    ["La mia scheda", "Che cosa posso fare, che cosa mi manca, che cosa scade."],
  ];
  const x = M + wi + 0.45, w = W - M - x;
  passi.forEach(([t, d], i) => {
    const y = 1.9 + i * 1.12;
    bollo(s, x, y + 0.05, 0.6, i + 1, C.accent1, 20);
    testo(s, t, x + 0.8, y, w - 0.8, 0.4, { fontSize: 18, bold: true });
    testo(s, d, x + 0.8, y + 0.4, w - 0.8, 0.62, { fontSize: 14, color: C.text2 });
  });
}

// ====================================================================== 11. Tappe
{
  const s = diapositiva("CONTENUTO", "La prova e le decisioni", "Si parte da un reparto, e ogni tappa si può fermare",
    "I tempi sono di sviluppo, per una persona. Il calendario vero lo detta la prima tappa: portare le ricette nel portale. Per il reparto pilota sono undici competenze e dieci macchine: il file è già pronto, restano due colonne da compilare. Nessuna nuova licenza prevista.");
  const tappe = [
    ["Subito", "Le ricette nel portale", "Reparto pilota: undici competenze, dieci macchine. Due colonne da compilare."],
    ["7-11 settimane", "Livelli con la prova, e le spie", "Sessioni di formazione e avvisi, nel reparto pilota."],
    ["Altre 3-4 settimane", "La richiesta di mansione", "Compilata e firmata a video."],
    ["4-7 mesi in tutto", "Il resto", "Pagine di sintesi, scheda stampabile, menu riordinato."],
  ];
  const w = 2.85, g = 0.21, y = 1.95;
  tappe.forEach(([q, t, d], i) => {
    const x = M + i * (w + g);
    riquadro(s, x, y, w, 2.75, i === 0 ? C.accent4 : C.background2);
    testo(s, q.toUpperCase(), x + 0.25, y + 0.2, w - 0.5, 0.3, { fontSize: 12, bold: true, color: C.accent1, charSpacing: 1 });
    testo(s, t, x + 0.25, y + 0.55, w - 0.5, 0.8, { fontSize: 18, bold: true });
    testo(s, d, x + 0.25, y + 1.4, w - 0.5, 1.25, { fontSize: 14, color: C.text2 });
  });
  const chi = [["Qualità", "Risponde alle domande, completa le ricette, aggiorna la procedura."], ["Capi reparto", "Valutano dopo la formazione, confermano ogni sei mesi."],
    ["Risorse umane", "Organizzano la formazione da ciò che manca."], ["RDD e MSO", "Approvano e firmano a video."]];
  chi.forEach(([t, d], i) => {
    const x = M + i * (w + g);
    testo(s, t, x, 5.0, w, 0.35, { fontSize: 16, bold: true });
    testo(s, d, x, 5.38, w - 0.1, 1.2, { fontSize: 14, color: C.text2 });
  });
}

// ====================================================================== 12. Decisioni
{
  const s = diapositiva("CHIUSURA", "La prova e le decisioni", "Cinque decisioni per oggi",
    "Sono le stesse del foglio delle decisioni, che si compila e si firma a fine riunione. Subito dopo: la Qualità riceve il questionario, 9 domande aperte e 9 da confermare, e il catalogo del reparto pilota.");
  const dec = [
    ["Segnalare o bloccare", "Proposta: segnalare; bloccare sui liquidi penetranti, come da procedura."],
    ["Il reparto pilota", "Proposta: fresatura a 5 assi grande formato."],
    ["La data di partenza e lo storico", "Proposta: gennaio 2027, dopo aver allineato il portale alla skill matrix firmata."],
    ["Chi firma, e da quale livello", "Proposta: come la procedura Risorse Umane, dal livello L."],
    ["La prima tappa", "Da 7 a 11 settimane di sviluppo, senza nuove licenze."],
  ];
  dec.forEach(([t, d], i) => {
    const y = 1.85 + i * 0.98;
    bollo(s, M, y, 0.7, i + 1, C.accent1, 24);
    testo(s, t, M + 1.0, y - 0.02, W - 2 * M - 1.0, 0.4, { fontSize: 21, bold: true, color: C.background1 });
    testo(s, d, M + 1.0, y + 0.4, W - 2 * M - 1.0, 0.4, { fontSize: 15, color: C.accent6 });
  });
}

(async () => {
  await pres.writeFile({ fileName: USCITA });
  await applyTheme(USCITA, THEME);
  console.log(USCITA);
})();
