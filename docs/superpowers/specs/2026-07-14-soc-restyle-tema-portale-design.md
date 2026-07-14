# SOC (Security Center) — restyle sul tema del portale

Data: 2026-07-14 · Stato: approvato dall'utente (opzione "Tema del portale", scope "tutto il modulo")

## Problema

Il modulo SOC (`django_app/security`, montato su `/soc/` via `urls_hub.py`) è innestato
dentro `core/base.html` ma porta con sé un tema "console SOC" scuro hard-coded, scopato
sotto `.soc-module` in `security/static/security/security.css`. Il risultato nel portale
(tema chiaro) è rotto:

- i titoli `h2`/`h3` delle card prendono il colore scuro dal CSS core → scuro su scuro,
  quasi invisibili ("Postura sicurezza", "Trend alert ed eventi", "Inbox prioritaria"…);
- la `thead` delle tabelle prende lo sfondo chiaro del core dentro il pannello scuro;
- il blocco scuro "galleggia" nella shell verde/chiara dell'HUB, con fondale a gradient
  e `min-height:100vh` che lascia buchi vuoti scuri;
- la nav interna del modulo è stilizzata inline in `_base_soc.html`, senza stato attivo.

## Decisione

Eliminare il tema dark proprietario e ristilizzare l'intero modulo sui token di
`core/static/core/css/theme.css`, come il resto dell'HUB. Approccio: **riscrivere
`security.css` mantenendo i nomi delle classi `sec-*`** — i ~25 template che estendono
`_base_soc.html` restano intatti; l'unica modifica template è la subnav in `_base_soc.html`.

Alternative scartate: (B) migrare i template al design system `hub-` → tocca ~30 template,
rischio regressioni sproporzionato; (C) mantenere la console dark sistemando i conflitti →
resta un corpo estraneo nel portale.

## Dettaglio

### 1. `security/static/security/security.css` (riscrittura, sempre scopata `.soc-module`)

- Via `color-scheme: dark`, fondale a gradient, `min-height:100vh`, font-family propria:
  la pagina resta sul `--bg`/font del portale.
- Pannelli/card/KPI (`sec-panel`, `sec-card`, `sec-kpi-card`): `--surface` + `--border`
  + `--radius` + `--shadow`, come le card core.
- Titoli di sezione (`sec-section-head h2/h3`): `color: var(--text)` esplicito
  (leggibili in light e dark), dimensioni/uppercase conservati.
- Badge severità e stato: stile "soft" sui token semantici — critical/open →
  `--danger`/`--danger-bg`; high/warning/medium/acknowledged/in_progress/snoozed →
  `--warning`/`--warning-bg`; low/info/closed/resolved/ok → `--success`/`--success-bg`;
  false_positive/suppressed/muted/disabled → `--text-light`; misconfigured → danger.
- Tabelle (`sec-table*`): allineate al look core; **`--thead-bg`, `--surface-alt`,
  `--tbody-hover`, `--hover-bg`, `--badge-*` esistono solo in `body.theme-dark` → usarli
  sempre con fallback chiaro** (trappola nota, memoria `theme_token_surface_alt_solo_dark`).
- Anelli postura (`sec-ring*`): conic-gradient con `--ring` sui token (`--warning`,
  `--success`, `--primary-mid`…), traccia `--border`, interno `--surface`.
- Chart placeholder (`sec-chart*`) e barre (`sec-bars`): griglia su `--border`, linee su
  `--primary-mid`/`--warning`/`--danger`, niente glow.
- Form (`input`, `select`, `button`, `.sec-button*`): bordi `--border`, superfici
  `--surface`, primario su `--primary`.
- Rimozione CSS morto: `sec-shell`, `sec-sidebar`, `sec-topbar`, `sec-brand`,
  `sec-nav-item`, `sec-selectlike`, `sec-search`, `sec-ingestion`, `sec-workspace`,
  `sec-page-title`, `sec-sidebar-foot`, `sec-main` — usati solo dallo standalone
  `security/base.html` che nessuna view/template referenzia più.
- Breakpoint responsive conservati (1180/820/520) al netto delle regole morte.

### 2. `security/templates/security/_base_soc.html`

- La nav interna perde gli stili inline e diventa `.soc-nav` a tab, con stato attivo
  calcolato su `request.resolver_match.url_name` (dashboard/security_dashboard,
  alerts_list+alert_detail, tickets_list, kpis, pipeline, assets, admin_*).

### 3. Fuori scope

- `security/base.html` (standalone morto): resta; la rimozione è pulizia separata.
- Nessuna modifica a view, modelli, URL, `htmx-lite.js`.

## Test e qualità

- Le pagine sono coperte da `tests_soc.py`: rilanciare i test dell'app
  (`python django_app\manage.py test django_app.security --keepdb --settings=config.settings.test`).
  La modifica è CSS + un template: i test proteggono da errori di template/URL.
- Verifica visiva su `/soc/` (dev server) in tema chiaro e scuro.
- CHANGELOG e README aggiornati come da regola di progetto.
