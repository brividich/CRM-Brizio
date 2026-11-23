"""Bozza della Dashboard della sezione «Organizzazione» di Anagrafica.

Parte dalla pagina vera «Struttura organizzativa» (HTML salvato da un test, dati di prova): tiene
barra del portale, menu e stile, e sostituisce il contenuto con la pagina di ingresso proposta per
la sezione: che cosa c'è da fare, i collegamenti diretti alle pagine, i numeri. I dati della bozza
sono inventati.

    python dashboard_organizzazione.py <pagina vera .html> <uscita .png>
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

PAGINA, USCITA = Path(sys.argv[1]), Path(sys.argv[2])


def ico(nome: str, stile: str = "") -> str:
    return f'<svg class="fmd-ico"{f" style={chr(34)}{stile}{chr(34)}" if stile else ""}><use href="#i-{nome}"/></svg>'


def bottone(nome: str, icona: str = "", primario: bool = False) -> str:
    stile = "fmd-btn-primary" if primario else "fmd-btn-ghost"
    return f'<a class="fmd-btn {stile}" href="#">{ico(icona) if icona else ""}{nome}</a>'


def riga(che_cosa: str, dettaglio: str, n: int, azione: str, urgente: bool = False) -> str:
    bordo = "box-shadow:inset 3px 0 0 #ea580c;" if urgente else ""
    return (f'<div style="display:flex;align-items:center;gap:14px;padding:10px 14px;border:1px solid #e2e8f0;'
            f'border-radius:12px;margin:0 0 8px;background:#fff;{bordo}">'
            f'<b style="flex:0 0 290px">{che_cosa}</b><span style="flex:1;color:#64748b">{dettaglio}</span>'
            f'<b style="font-size:16px;min-width:34px;text-align:right">{n}</b>{bottone(azione, "arrow-right")}</div>')


def tessera(nome: str, icona: str, spiega: str, numero: str = "", attesa: int = 0) -> str:
    conta = f'<span class="fmd-count" style="margin-left:auto">{attesa}</span>' if attesa else ""
    num = f'<div style="margin-top:8px;font-size:12.5px;font-weight:700;color:#0c2545">{numero}</div>' if numero else ""
    return (f'<a href="#" style="display:block;padding:14px 16px;border:1px solid #e2e8f0;border-radius:14px;background:#fff;'
            f'text-decoration:none;color:#0f172a">'
            f'<div style="display:flex;align-items:center;gap:10px">'
            f'<span style="display:inline-flex;width:36px;height:36px;border-radius:10px;background:#e8f3fb;color:#1f6fb0;'
            f'align-items:center;justify-content:center;font-size:18px">{ico(icona)}</span>'
            f'<b style="font-size:15px">{nome}</b>{conta}</div>'
            f'<div style="margin-top:8px;font-size:12.5px;color:#64748b;line-height:1.4">{spiega}</div>{num}</a>')


CONTENUTO = f"""
<div class="fmd-pagehead">
  <div>
    <h1>{ico("building", "font-size:24px;color:var(--fmd-cyan);")}Organizzazione</h1>
    <p class="fmd-ph-sub">Chi fa che cosa: centri di costo, reparti, ruoli, mansioni e competenze.</p>
  </div>
  <div class="fmd-pagehead-actions">
    {bottone("Nuova richiesta", "plus", primario=True)}
    <a class="fmd-btn fmd-btn-ghost" href="#">? Guida</a>
  </div>
</div>

<section class="fmd-panel fmd-block mns-box">
  <div class="fmd-block-head"><div class="fmd-block-title">{ico("alert-cir")}Da fare</div>
    <div class="fmd-block-aside">Solo ciò che aspetta te in questa sezione</div></div>
  {riga("Richieste da approvare", "Assegnazioni di mansione: tocca a te", 2, "Decidi", True)}
  {riga("Mansioni senza competenze", "La matrice della Qualità non le copre ancora", 182, "Apri")}
  {riga("Reparti senza responsabile", "Manca il ruolo responsabile del reparto", 3, "Apri")}
  {riga("Rischi da confermare", "Mansioni di rischio proposte dal portale", 4, "Conferma")}
</section>

<section class="fmd-panel fmd-block mns-box" style="margin-top:16px">
  <div class="fmd-block-head"><div class="fmd-block-title">{ico("arrow-right")}Vai a</div>
    <div class="fmd-block-aside">Tutte le pagine della sezione</div></div>
  <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px">
    {tessera("Esplora la struttura", "grid", "Dal centro di costo alla mansione: che cosa richiede e chi ce l'ha.", "26 centri di costo")}
    {tessera("Mansioni", "clipboard", "Tutte le mansioni, le competenze richieste e le persone.", "253 mansioni")}
    {tessera("Richieste", "edit", "Assegnare, sospendere o rimuovere una mansione; acquisire una competenza.", "7 aperte", 2)}
    {tessera("Reparti e capi", "users", "Reparti, aree, responsabili e ruoli previsti.", "39 reparti")}
    {tessera("Centri di costo", "coins", "Quali reparti stanno in quale centro di costo.", "26 centri")}
    {tessera("Organigramma", "building", "Il disegno dell'azienda: chi riporta a chi.")}
    {tessera("Prova un cambiamento", "refresh", "Confronta oggi e dopo, prima di spostare persone o ruoli.")}
    {tessera("Revisioni della struttura", "doc", "La struttura approvata dalla Qualità e le sue emissioni.", "4 modifiche non emesse")}
  </div>
</section>

<section class="fmd-panel fmd-block mns-box" style="margin-top:16px">
  <div class="fmd-block-head"><div class="fmd-block-title">{ico("check")}In numeri</div>
    <div class="fmd-block-aside">Ogni numero apre il suo elenco</div></div>
  <div class="mns-stats" style="margin:0">
    <a class="mns-stat kpi-link" href="#"><b>26</b><span>centri di costo</span></a>
    <a class="mns-stat kpi-link" href="#"><b>39</b><span>reparti</span></a>
    <a class="mns-stat kpi-link" href="#"><b>44</b><span>ruoli</span></a>
    <a class="mns-stat kpi-link" href="#"><b>253</b><span>mansioni</span></a>
    <a class="mns-stat kpi-link" href="#"><b>208</b><span>competenze</span></a>
    <a class="mns-stat kpi-link" href="#"><b>128</b><span>persone in forza</span></a>
  </div>
</section>
"""

SCRIPT = """
(contenuto) => {
  document.querySelector('.fmd-wrap').innerHTML = contenuto;
  // Nella seconda riga compare la voce nuova «Panoramica», accesa, prima delle altre.
  const voci = document.querySelector('.hrnav-sub-voci');
  let fatto = false;
  if (voci) {
    const prima = voci.querySelector('a');
    const attiva = voci.querySelector('a.active') || prima;
    const nuova = attiva.cloneNode(true);
    nuova.textContent = 'Panoramica';
    voci.querySelectorAll('a').forEach(a => { a.classList.remove('active'); a.removeAttribute('aria-current'); });
    nuova.classList.add('active');
    voci.insertBefore(nuova, prima);
    fatto = true;
  }
  const percorso = document.querySelector('.hub-percorso');
  if (percorso) {
    [...percorso.querySelectorAll('*')].forEach(e => {
      if (!e.children.length && e.textContent.trim() === 'Struttura organizzativa') e.textContent = 'Organizzazione';
      if (!e.children.length && e.textContent.trim() === 'Mansionario') (e.closest('li') || e).remove();
    });
  }
  document.querySelectorAll('.devgit').forEach(e => e.remove());
  return {voce_panoramica: fatto, voci: voci ? [...voci.querySelectorAll('a')].map(a => a.textContent.trim()) : []};
}
"""

with sync_playwright() as p:
    b = p.chromium.launch(channel="chrome", headless=True)
    pg = b.new_page(viewport={"width": 1440, "height": 900})
    pg.goto(PAGINA.as_uri())
    pg.wait_for_timeout(600)
    print(pg.evaluate(SCRIPT, CONTENUTO))
    pg.wait_for_timeout(300)
    print("sborda:", pg.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1"),
          "| altezza:", pg.evaluate("document.documentElement.scrollHeight"))
    USCITA.parent.mkdir(parents=True, exist_ok=True)
    pg.screenshot(path=str(USCITA), full_page=True)
    b.close()
