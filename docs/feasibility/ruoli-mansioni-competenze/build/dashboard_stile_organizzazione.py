"""Bozza della Dashboard di Anagrafica nello stile della pagina «Struttura organizzativa».

Parte dalla pagina vera «Struttura organizzativa» (HTML salvato da un test, dati di prova) e ne
sostituisce il contenuto con la Dashboard proposta, usando gli stessi componenti della pagina:
testata con i pulsanti, striscia di stato, numeri cliccabili, salti di pagina, riquadri.
I dati della bozza sono inventati.

    python dashboard_stile_organizzazione.py <pagina vera .html> <uscita .png>
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

PAGINA, USCITA = Path(sys.argv[1]), Path(sys.argv[2])


def ico(nome: str) -> str:
    return f'<svg class="fmd-ico"><use href="#i-{nome}"/></svg>'


def bottone(nome: str, icona: str, n: int = 0, primario: bool = False) -> str:
    conta = f' <span class="fmd-count">{n}</span>' if n else ""
    stile = "fmd-btn-primary" if primario else "fmd-btn-ghost"
    return f'<a class="fmd-btn {stile}" href="#">{ico(icona)}{nome}{conta}</a>'


def riquadro(ident: str, titolo: str, icona: str, a_lato: str, bottoni: list) -> str:
    return (f'<section class="fmd-panel fmd-block mns-box" id="{ident}" style="margin:0">'
            f'<div class="fmd-block-head"><div class="fmd-block-title">{ico(icona)}{titolo}</div>'
            f'<div class="fmd-block-aside">{a_lato}</div></div>'
            f'<div style="display:flex;flex-wrap:wrap;gap:8px">{"".join(bottoni)}</div></section>')


def riga(che_cosa: str, dettaglio: str, n: int, azione: str, urgente: bool = False) -> str:
    bordo = "box-shadow:inset 3px 0 0 #ea580c;" if urgente else ""
    return (f'<div style="display:flex;align-items:center;gap:14px;padding:11px 14px;border:1px solid #e2e8f0;'
            f'border-radius:12px;margin:0 0 8px;background:#fff;{bordo}">'
            f'<b style="flex:0 0 300px">{che_cosa}</b><span style="flex:1;color:#64748b">{dettaglio}</span>'
            f'<b style="font-size:16px">{n}</b>{bottone(azione, "arrow-right")}</div>')


CONTENUTO = f"""
<div class="fmd-pagehead">
  <div>
    <h1>{ico("grid").replace('class="fmd-ico"', 'class="fmd-ico" style="font-size:24px;color:var(--fmd-cyan);"')}Dashboard</h1>
    <p class="fmd-ph-sub">Persone, organizzazione, formazione, qualifiche e sicurezza: da qui si arriva a tutto.</p>
  </div>
  <div class="fmd-pagehead-actions">
    {bottone("Dipendenti", "users")}{bottone("Nuovo dipendente", "plus")}{bottone("Il mio team", "users")}
    {bottone("Nuova richiesta", "plus")}{bottone("Scadenzario", "calendar")}
    <a class="fmd-btn fmd-btn-ghost" href="#">? Guida</a>
  </div>
</div>

<div class="sto-rev sto-rev-bozza" role="status">
  <strong>Da fare: 5.</strong> 2 richieste da approvare, 3 corsi obbligatori scaduti.
  <a class="sto-rev-link" href="#">Vai a «Da fare» →</a>
</div>

<div class="mns-stats">
  <a class="mns-stat kpi-link" href="#"><b>128</b><span>persone in forza</span></a>
  <a class="mns-stat kpi-link" href="#"><b>39</b><span>reparti</span></a>
  <a class="mns-stat kpi-link" href="#"><b>253</b><span>mansioni</span></a>
  <a class="mns-stat kpi-link mns-mid" href="#"><b>4</b><span>mansioni da guardare</span></a>
  <a class="mns-stat kpi-link mns-mid" href="#"><b>3</b><span>qualifiche in scadenza</span></a>
  <a class="mns-stat kpi-link" href="#"><b>91%</b><span>obblighi in regola</span></a>
</div>

<nav class="fmd-chips sto-nav" aria-label="Sezioni della pagina">
  <a class="fmd-chip" href="#">Da fare <span class="fmd-count">5</span></a>
  <a class="fmd-chip" href="#">Persone</a><a class="fmd-chip" href="#">Organizzazione</a>
  <a class="fmd-chip" href="#">Formazione</a><a class="fmd-chip" href="#">Qualifiche</a><a class="fmd-chip" href="#">Sicurezza</a>
</nav>

<section class="fmd-panel fmd-block mns-box" id="dafare">
  <div class="fmd-block-head"><div class="fmd-block-title">{ico("alert-cir")}Da fare</div>
    <div class="fmd-block-aside">Le cose che aspettano te, la più urgente in cima</div></div>
  {riga("Richieste da approvare", "Assegnazioni di mansione nel tuo reparto", 2, "Decidi", True)}
  {riga("Formazione scaduta", "Corsi obbligatori oltre la scadenza", 3, "Apri", True)}
  {riga("Visite mediche in scadenza", "Entro 60 giorni", 6, "Apri")}
  {riga("Le mie richieste in attesa di altri", "Tocca a RDD", 1, "Apri")}
</section>

<div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:16px">
  {riquadro("persone", "Persone", "users", "128 in forza · 2 ingressi nel mese", [
      bottone("Elenco dipendenti", "users"), bottone("Nuovo dipendente", "plus"), bottone("Il mio team", "users"),
      bottone("Documenti", "doc"), bottone("Selezione", "search"), bottone("Inserimenti", "check")])}
  {riquadro("organizzazione", "Organizzazione", "building", "39 reparti · 253 mansioni · 4 da guardare", [
      bottone("Esplora la struttura", "grid"), bottone("Struttura organizzativa", "building"),
      bottone("Mansionario", "clipboard"), bottone("Reparti", "grid"), bottone("Richieste", "edit", 2),
      bottone("Nuova richiesta", "plus")])}
  {riquadro("formazione", "Formazione", "book", "3 corsi obbligatori scaduti", [
      bottone("Corsi", "book"), bottone("Sessioni", "calendar"), bottone("Piani formativi", "clipboard"),
      bottone("Corsi online", "cap"), bottone("Copertura", "filter"), bottone("Pianifica un corso", "plus")])}
  {riquadro("qualifiche", "Qualifiche e abilitazioni", "award", "3 qualifiche in scadenza", [
      bottone("Qualifiche", "award"), bottone("Processi qualificati", "gear"), bottone("P11TF12", "shield"),
      bottone("Skill matrix", "grid"), bottone("Abilitazioni macchina", "gear"), bottone("Scadenze", "cal-clock", 3)])}
  {riquadro("sicurezza", "Salute e sicurezza", "shield", "6 visite in scadenza · 1 referto da rivedere", [
      bottone("Visite mediche", "pill"), bottone("Referti da rivedere", "doc", 1), bottone("Libretto sanitario", "clipboard"),
      bottone("Conformità mansione", "check"), bottone("Cambi mansione", "refresh"), bottone("Mansioni di rischio", "alert-tri")])}
  {riquadro("altro", "Amministrazione e report", "coins", "Solo per chi ha l'accesso", [
      bottone("Cedolini", "coins"), bottone("Costo orario", "clock"), bottone("Ferie e permessi", "calendar"),
      bottone("Report", "download"), bottone("Chiedi un report", "mic")])}
</div>
"""

SCRIPT = """
(contenuto) => {
  document.querySelector('.fmd-wrap').innerHTML = contenuto;
  // Pilastro acceso: Dashboard al posto di Organizzazione; la seconda riga non serve.
  const voci = [...document.querySelectorAll('.hrnav-tabs a')];
  const org = voci.find(a => a.textContent.trim().startsWith('Organizzazione'));
  const dash = voci.find(a => a.textContent.trim().startsWith('Dashboard'));
  if (org && dash) { const c = org.className; org.className = dash.className; dash.className = c; }
  const sub = document.querySelector('.hrnav-sub'); if (sub) sub.remove();
  const percorso = document.querySelector('.hub-percorso');
  if (percorso) {
    [...percorso.querySelectorAll('*')].forEach(e => {
      if (!e.children.length && e.textContent.trim() === 'Struttura organizzativa') e.textContent = 'Dashboard';
      if (!e.children.length && e.textContent.trim() === 'Mansionario') (e.closest('li') || e).remove();
    });
  }
  document.querySelectorAll('.devgit').forEach(e => e.remove());
  return {pilastri: !!(org && dash), percorso: percorso ? percorso.innerText.replace(/\\s+/g, ' ').trim() : ''};
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
          "| altezza:", pg.evaluate("document.documentElement.scrollHeight"),
          "| pulsanti diretti:", pg.evaluate("document.querySelectorAll('.fmd-wrap .fmd-btn').length"),
          "| primo riquadro a:", pg.evaluate("Math.round(document.querySelector('#dafare').getBoundingClientRect().top + scrollY)"))
    USCITA.parent.mkdir(parents=True, exist_ok=True)
    pg.screenshot(path=str(USCITA), full_page=True)
    b.close()
