# Checklist — Miglioramento Security Center IT (`/soc/`)

Branch: `feature/security-soc-migliorie` (worktree `C:\Dev\pn-soc-migliorie`, base `origin/main`).
Analisi: 2026-09-26 (codice + verifica a video con dati sintetici).
Aggiornare questa checklist a ogni blocco concluso.

## Istruzioni operative

- Rotte attive in `django_app/security/urls_hub.py` (NON `urls.py`, legacy non montata).
- Viste in `security/views.py` (+ `views_soc.py`); ACL via `ACLMiddleware`, non rimuovere i
  controlli `can_view_security_center` / `can_manage_security_config` esistenti.
- Solo dati **sintetici** (`seed_security_center_config`, `seed_security_uat_demo`,
  `ingest_sample_security_data`): mai mail/report reali nei test o nelle fixture.
- Il blocco anti-spoofing del parser Defender (`can_parse` basato SOLO sul mittente) resta
  fail-closed: si aggiunge visibilità, non si allenta il controllo.
- Test: `python django_app\manage.py test security --settings=config.settings.test --keepdb`.
- Verifica a video da worktree (SQLite isolato, mai `.env` copiato):
  1. `$env:DJANGO_DEBUG="1"; $env:DB_ENGINE="sqlite"; $env:LEGACY_AUTH_ENABLED="0"`
  2. `manage.py migrate` + i tre seed sopra + pipeline (`run_pending_parsers`,
     `evaluate_security_rules`, `build_daily_kpi_snapshots`)
  3. `runserver 127.0.0.1:8023 --noreload` (8000/8011 sono di altre sessioni; riavviare dopo
     ogni modifica a view/template)
  4. screenshot Playwright light + dark (`document.body.classList.add('theme-dark')`)
- A fine blocco: CHANGELOG `[Unreleased]`, README se cambia funzionalità visibile, commit,
  merge `main` → `release/prod` (da worktree, verificare i due genitori).

## A — Dati veri al posto dei valori finti (PRIORITÀ MASSIMA)

- [x] Postura sicurezza: sostituire i punteggi fissi 72/81/94/88 con indici calcolati
      (alert attivi per severità, esito backup, heartbeat/ingestione sorgenti, eventi rete)
      con formula documentata e tooltip «come è calcolato»; stato «n.d.» se mancano dati.
- [x] Trend alert ed eventi 7 giorni: serie reali per giorno (alert creati, eventi, critici),
      SVG server-side, assi/legenda, stato vuoto.
- [x] Grafico KPI: sostituito dal trend reale dei 7 giorni fino alla data scelta.
- [x] Test: i valori mostrati cambiano con i dati; nessun numero fisso nei template.
- [x] Card Pipeline: conteggi reali al posto di «18 / OK / ON / AI».

## B — Qualità del rilevamento

- [x] Registrare il motivo di scarto (`skip_reason`) sugli elementi SKIPPED:
      `no_parser` / `untrusted_sender` / `parser_disabled` — visibile in Inbox.
- [x] Mail «con aspetto Defender» da mittente non attendibile: evento/alert
      `possible_sender_spoofing` (severità «attenzione», un alert per fornitore+dominio, senza corpo mail) invece di sparire in silenzio.
- [x] `ingest_sample_security_data`: mittente Defender sintetico attendibile
      (`@microsoft.com` di esempio) così la demo produce la CVE critica.
- [x] Test su spoofing, skip reason, demo.

## C — Alert e ticket (UX operatore)

- [ ] Lista alert: tabella a tutta larghezza, filtri compatti sopra; conteggi reali per
      severità (non la parola «severita»); nessuna colonna tagliata.
- [ ] Dettaglio alert: «Perché è stato generato» da `decision_trace` (regola, soglia, valore);
      payload leggibile (chiave/valore) invece del dict Python; box principale senza vuoto.
- [ ] Riquadro ticket: campi CVE/CVSS solo per alert di vulnerabilità.
- [ ] Ticket: filtri stato/severità, link all'alert, colonne CVE solo se pertinenti.

## D — KPI, Inbox, Configurazione

- [ ] KPI: etichette leggibili per le metriche (mappa nome tecnico → italiano), tabella non troncata.
- [ ] Inbox/Pipeline: etichette in italiano, colonne non troncate, icona ricerca non sovrapposta.
- [ ] Sorgenti: righe compatte, etichette tradotte (`source_type`, finestra oraria), pattern
      come testo una-riga-per-voce invece di JSON grezzo.
- [ ] Autoconfig: pattern mittente/oggetto di default per le sorgenti note.

## Chiusura

- [ ] Verifica a video light + dark di tutte le pagine toccate
- [ ] CHANGELOG + README
- [ ] Merge main → release/prod
- [ ] Memoria di progetto aggiornata
