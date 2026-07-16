# Prompt di avvio — 6 sessioni Opus (punch-list 2026-07-16)

Regia: `2026-07-16-MASTER-coordinamento-punchlist.md`. Confermato: permesso min = 30 min.

**Ordine di lancio**
- **Ondata A (subito, in parallelo, nessun coordinamento):** sessioni 4, 5, 6 — app disgiunte, merge appena verdi.
- **Ondata B (anagrafica, merge serializzato dalla regia nell'ordine 2 → 0 → 1 → 3):** sessioni 2, 1, 3. Possono *implementare* in parallelo; il **merge** lo coordina la sessione di regia. Lo Stream 0 (visite) usa il piano `2026-07-16-visite-giornata-sessioni.md`.

---

## Sessione 1 — Scadenzario & Formazione-sessione

```
Sei una sessione di implementazione per NOVICROM HUB. Esegui il piano:
docs/superpowers/plans/2026-07-16-anagrafica-scadenzario-layout.md

Regole operative:
- Usa lo skill superpowers:executing-plans. Crea un TODO per ogni task e per ogni step.
- Il Task 1 crea il worktree C:\Dev\pn-anag-scadenzario su branch feature/anagrafica-scadenzario-layout da origin/main. Lavora SOLO lì. Mai nel checkout condiviso C:\Dev\Portale Novicrom, mai git checkout/switch lì.
- Venv assoluto: & "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe" (il worktree non ha .venv).
- Test solo per l'app anagrafica: --keepdb --settings=config.settings.test, timeout >=600000 ms. Prima run dopo una nuova migrazione SENZA --keepdb (rimigra 6-8 min), poi sempre --keepdb.
- TDD: test rosso PRIMA dell'implementazione. Mai git add -A / commit -a: staging con percorsi espliciti.
- CHANGELOG.md + README.md nel task finale. Niente version bump.
- Leggi la sezione "Coordinamento con il piano Giornata visite": aggiunte a scadenzario.html e a _build_scadenzario_voci vanno fatte in modo idempotente e non distruttivo (lo Stream 0 tocca gli stessi artefatti).
- A fine piano: commit su feature/anagrafica-scadenzario-layout + push. NON mergiare in main: lo coordina la regia.
- Rispondi in italiano.
```

---

## Sessione 2 — Organigramma & Report

```
Sei una sessione di implementazione per NOVICROM HUB. Esegui il piano:
docs/superpowers/plans/2026-07-16-anagrafica-organigramma-report.md

Regole operative:
- Usa lo skill superpowers:executing-plans. Crea un TODO per ogni task e per ogni step.
- Il Task 1 crea il worktree C:\Dev\pn-anag-organigramma su branch feature/anagrafica-organigramma-report da origin/main. Lavora SOLO lì. Mai nel checkout condiviso C:\Dev\Portale Novicrom, mai git checkout/switch lì.
- Venv assoluto: & "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe" (il worktree non ha .venv).
- Test solo per l'app anagrafica: --keepdb --settings=config.settings.test, timeout >=600000 ms. Prima run dopo una nuova migrazione SENZA --keepdb, poi sempre --keepdb.
- TDD: test rosso PRIMA dell'implementazione. Mai git add -A / commit -a: staging con percorsi espliciti.
- CHANGELOG.md + README.md nel task finale. Niente version bump.
- Nota dominio VINCOLANTE: l'albero organigramma è tra RUOLI (RuoloOperativo.riporta_a), mai tra persone; le persone sono foglie titolari. Il caporeparto effettivo viene dall'area aziendale quando differisce dal reparto.
- Minimizza la superficie su anagrafica/views.py e urls.py (logica in service module dedicati); leggi la sezione "Coordinamento" del piano.
- A fine piano: commit su feature/anagrafica-organigramma-report + push. NON mergiare in main: lo coordina la regia.
- Rispondi in italiano.
```

---

## Sessione 3 — Formazione/Compliance UI & Impostazioni

```
Sei una sessione di implementazione per NOVICROM HUB. Esegui il piano:
docs/superpowers/plans/2026-07-16-anagrafica-formazione-ui-settings.md

Regole operative:
- Usa lo skill superpowers:executing-plans. Crea un TODO per ogni task e per ogni step.
- Il Task 1 crea il worktree C:\Dev\pn-anag-formazione-ui su branch feature/anagrafica-formazione-ui-settings da origin/main. Lavora SOLO lì. Mai nel checkout condiviso C:\Dev\Portale Novicrom, mai git checkout/switch lì.
- Venv assoluto: & "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe" (il worktree non ha .venv).
- Test solo per l'app anagrafica: --keepdb --settings=config.settings.test, timeout >=600000 ms.
- TDD sui cambiamenti FUNZIONALI (chip "processi qualificati", Ruoli inline); render-test leggeri per il puro restyle CSS. Mai git add -A / commit -a.
- UI: riusa i token di theme.css e le classi hub- esistenti; niente React; rispetta tema chiaro/scuro. Subnav data-driven (NavigationItem), non hardcodata.
- CHANGELOG.md + README.md nel task finale. Niente version bump.
- Leggi la sezione "Coordinamento": tocchi qualifiche_list e impostazioni in views.py e impostazioni.html, condivisi con le sessioni 1 e 2 -> rebase su origin/main prima del merge.
- A fine piano: commit su feature/anagrafica-formazione-ui-settings + push. NON mergiare in main: lo coordina la regia.
- Rispondi in italiano.
```

---

## Sessione 4 — Assenze: regole durata (Ondata A, indipendente)

```
Sei una sessione di implementazione per NOVICROM HUB. Esegui il piano:
docs/superpowers/plans/2026-07-16-assenze-regole-durata.md

Regole operative:
- Usa lo skill superpowers:executing-plans. Crea un TODO per ogni task e per ogni step.
- Il Task 1 crea il worktree C:\Dev\pn-assenze-regole su branch feature/assenze-regole-durata da origin/main. Lavora SOLO lì. Mai nel checkout condiviso C:\Dev\Portale Novicrom, mai git checkout/switch lì.
- Venv assoluto: & "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe" (il worktree non ha .venv).
- Test solo per l'app assenze: --keepdb --settings=config.settings.test, timeout >=600000 ms (nessuna migrazione prevista -> sempre --keepdb).
- CONFERMATO: permesso durata minima = 30 minuti (0.30h), massimo 8h, stesso giorno. Ferie: piu di 1 giorno. Aggiorna coerentemente il test esistente test_invio_ferie_forces_full_day_times.
- TDD forte: un test per ogni regola (permesso >8h/<30min/multi-giorno respinti; ferie 1 giorno respinta/2 giorni ok; durata rapida orario-alterato respinto; personalizzato ok; subnav senza "riconciliazione"). Mai git add -A / commit -a.
- CHANGELOG.md + README.md nel task finale. Niente version bump.
- App disgiunta dagli altri stream: nessun conflitto. A fine piano commit su feature/assenze-regole-durata + push. NON mergiare in main da solo (ma per l'Ondata A il merge e' immediato appena verde: segnalalo alla regia).
- Rispondi in italiano.
```

---

## Sessione 5 — Polish multi-app (Ondata A, indipendente)

```
Sei una sessione di implementazione per NOVICROM HUB. Esegui il piano:
docs/superpowers/plans/2026-07-16-polish-multiapp.md

Regole operative:
- Usa lo skill superpowers:executing-plans. Crea un TODO per ogni task e per ogni step. Il piano copre 4 aree su app diverse (timbri, procedure_refresh, assets, tasks/kickoff) in blocchi con commit separati.
- Il Task 1 crea il worktree C:\Dev\pn-polish-multiapp su branch feature/polish-multiapp da origin/main. Lavora SOLO lì. Mai nel checkout condiviso C:\Dev\Portale Novicrom, mai git checkout/switch lì.
- Venv assoluto: & "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe" (il worktree non ha .venv).
- Test per-app toccata: <app>.<test_module> --keepdb --settings=config.settings.test, timeout >=600000 ms. Prima run dopo una migrazione SENZA --keepdb.
- TDD veri per il bug kickoff dashboard (_project_scope_filter_q) e la ricerca timbri-per-qualifica; render-test leggeri per rimozioni UI/lightbox/branding. Mai git add -A / commit -a.
- CHANGELOG.md + README.md nel task finale. Niente version bump.
- App disgiunte dagli altri stream: nessun conflitto. A fine piano commit su feature/polish-multiapp + push. Merge Ondata A immediato appena verde: segnalalo alla regia.
- Rispondi in italiano.
```

---

## Sessione 6 — GCM: bug Gantt weekend (Ondata A, indipendente)

```
Sei una sessione di implementazione per NOVICROM HUB. Esegui il piano:
docs/superpowers/plans/2026-07-16-gcm-gantt-weekend-fix.md

Regole operative:
- Usa lo skill superpowers:executing-plans. Crea un TODO per ogni task e per ogni step.
- Il Task 1 crea il worktree C:\Dev\pn-gcm-weekend su branch feature/gcm-gantt-weekend da origin/main. Lavora SOLO lì. Mai nel checkout condiviso C:\Dev\Portale Novicrom, mai git checkout/switch lì.
- Venv assoluto: & "C:\Dev\Portale Novicrom\.venv\Scripts\python.exe" (il worktree non ha .venv).
- Test solo per l'app gestione_carichi_macchina: --keepdb --settings=config.settings.test, timeout >=600000 ms.
- Bugfix mirato: reschedule() in views.py somma giorni di calendario invece di usare _sposta_giorni_lavorativi -> la barra atterra di sabato. Test RED che riproduce l'atterraggio sul weekend PRIMA del fix. Mai git add -A / commit -a.
- CHANGELOG.md + README.md nel task finale. Niente version bump.
- App disgiunta: nessun conflitto. A fine piano commit su feature/gcm-gantt-weekend + push. Merge Ondata A immediato appena verde.
- Rispondi in italiano.
```
