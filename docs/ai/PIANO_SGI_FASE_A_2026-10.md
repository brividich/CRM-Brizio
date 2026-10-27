# Piano SGI «Fase A» — affidabilità, registri di legge, indici, KPI, riesame, ISMS, PdR 125

> Documento di avanzamento **autosufficiente** (stesso schema di `CHECKLIST_SISTEMA_GESTIONE_AUDIT.md`): chi lo
> riprende, persona o LLM, deve poter continuare senza altro contesto. Aggiornare le caselle `[ ]` → `[x]` e la
> tabella «Stato» a ogni blocco, nello stesso commit del codice.
>
> Origine: analisi del 27/10/2026 (confronto fra i sistemi su `X:` — 9100, 45001, 27001, UNI/PdR 125, PART 145 —
> e i moduli del portale). Scelta dell'utente: blocchi **0, 1, 2, 3, 4, 5, 6** qui sotto, in quest'ordine.
> Restano fuori (da pianificare a parte): lista master documenti/TABDOC, NC fornitore/8D, strumenti di misura,
> FAI/FOD, RFC/gestione cambiamenti, OTD, whistleblowing.

- **Ultimo aggiornamento**: 2026-10-27
- **Riferimenti SGI** (solo nomi dei documenti, mai il contenuto nel repository): MT CN 13 (KPI), MT CN 19 (riesame),
  MOD.062 (VRS), MOD.063 (RIO), MOD.147 (PLE), MT CN 453/2710 (requisiti legali), MOD.166 (RGI), MOD.170 (CNBACKUP),
  MOD.173 (BRP), MOD.200 (ADR), MT CN 2712 (business continuity), MT CN 125_13 (KPI parità), MT CN 125_4 (pianificazione).

---

## 0. Stato in sintesi

> Migrazioni: le `sistema_gestione` 0019 (audit ISMS) e 0020 (checklist per norma) sono già occupate dal
> 27/10/2026; i numeri 0019-0021 indicati nei blocchi qui sotto vanno presi come «la prossima libera».

| Blocco | Contenuto | Effort | Stato | Commit / note |
|---|---|---|---|---|
| 0 | Affidabilità A1.1–A1.4 del doc 16 (timeout MSAL, `DB_QUERY_TIMEOUT` web, FAIL anche di notte, sonda esterna `/readyz`) | 1–2 gg | `[ ]` | — |
| 1 | Indici infortunistici reali (ore lavorate + prognosi → IF, IG, TRIR) | 2 gg | `[ ]` | — |
| 2 | Registro prescrizioni legali MOD.147 (`core` o `sistema_gestione`) | 3–4 gg | `[ ]` | — |
| 3 | Catalogo KPI MT CN 13 con alimentazione automatica (estende `RilevazioneKpi`) | 4–5 gg | `[ ]` | — |
| 4 | Riesame della direzione come flusso (MOD.062) + riunione operativa (MOD.063) | 4–5 gg | `[ ]` | — |
| 5 | Registri ISMS vivi: MOD.166, MOD.170, MOD.200, MOD.173 | 4–5 gg | `[ ]` | — |
| 6 | KPI UNI/PdR 125 (MT CN 125_13) + piano strategico | 3 gg | `[ ]` | — |

Ordine vincolante: **0 → 1 → 2 → 3 → 4 → 5 → 6**. Il blocco 3 è prerequisito del 4 (il riesame legge i KPI);
il 2 alimenta il 3 (KPI «prescrizioni verificate») e il 4 (input §9.3 «conformità legale»).
Ogni blocco è un giro chiuso: branch → test → merge `main` → merge `release/prod` (regola del 02/10/2026) →
riga nel CHANGELOG. Deploy possibile dopo ogni blocco.

---

## 1. Regole di lavoro (obbligatorie, valgono per tutti i blocchi)

1. Worktree dedicato: `git worktree add C:\Dev\pn-<tema> -B feature/<area>-<tema> origin/main`. Mai `git checkout`
   nel condiviso `C:\Dev\Portale Novicrom`; mai `git add -A`.
2. Test solo dell'app toccata, `--keepdb`, `--settings=config.settings.test`; nei worktree manca `.env`
   (`DEFAULT_FROM_EMAIL=noreply@example.com`), **mai copiarlo**. Poi `check`, `makemigrations --check --dry-run`.
3. ACL v2: ogni route nuova in `_ROUTE_BINDINGS` di `<app>/acl_bootstrap.py` **e** `_has_perm(...)` fail-closed
   nella view; permesso nuovo registrato in `<app>/registro_permessi.py` (procedura in `PERMESSI_ROLI.md`).
   Default grant con `get_or_create`, mai `update_or_create` su `NavigationItem`.
4. Dati personali: nei report PdR 125 e negli indici infortunistici **solo aggregati**; soglia minima di 5 persone
   per cella, altrimenti «n.d.» (stessa regola di privacy di `report_conformita`). Mai nomi nei test o fixture.
5. Stesso commit della funzione visibile: guida in-app del modulo («? Guida»), `core/guide_moduli/contenuti/<modulo>.py`,
   `docs/moduli/<app>.md`, `CHANGELOG.md [Unreleased]`, `hub_tools/schema_db.py` se nascono tabelle.
6. Template: `{# #}` solo monoriga; filtri con argomento mai `None`; `DateInput(format="%Y-%m-%d")`; stili con i
   token di `theme.css` (tema chiaro **e** scuro verificati a video prima di dire «fatto»).
7. SQL Server: niente `~Q` in `UniqueConstraint`; `.values().annotate()` → `.order_by()` esplicito; migrazioni
   `makemigrations --check` prima del merge (collisioni di numero fra branch paralleli).
8. Norme: EN 9100, UNI EN ISO 9001/45001, UNI CEI EN ISO/IEC 27001:2022, UNI/PdR 125:2022, D.Lgs. 81/08, GDPR,
   NIS2 (D.Lgs. 138/2024), UNI 7249 per gli indici infortunistici. Nessun riferimento a fonti extra-UE.

---

## 2. Blocco 0 — Affidabilità (A1.1–A1.4 del doc 16)

Riferimento: `16_AFFIDABILITA_E_PRODOTTO_MODULARE.md` §A1. Nessuna migrazione, nessuna UI.

| # | Intervento | File | Note |
|---|---|---|---|
| 0.1 | Timeout e lock a tempo sull'acquisizione token Graph | `core/graph_utils.py:60-70`, `core/m365_graph.py:92` | `ConfidentialClientApplication(..., timeout=15)`; `_TOKEN_LOCK.acquire(timeout=20)` → se scade, `GraphTokenError`; non loggare `result` intero. Unificare le due implementazioni in `core/graph_utils.py` (m365 importa da lì). |
| 0.2 | `DB_QUERY_TIMEOUT` anche per il web | `config/settings/base.py:662-668`, `deployment/*.env.example`, `validate_deployment` | Default web 60 s (qcluster resta 300). Check di deploy che avvisa se `0`. **Prod: variabile nel `.env` persistente** (`prod_env_source_of_truth`). |
| 0.3 | FAIL sempre notificati, quiet hours solo per WARN | `monitoring/health.py:832-870` (`_within_alert_quiet_hours`, `emit_monitoring_alert`) | Parametro `severity`; `force=True` implicito per `STATUS_FAIL` su db, qcluster, disco, backup. Test in `monitoring/tests*`: FAIL alle 03:00 invia, WARN alle 03:00 no. |
| 0.4 | Sonda esterna di `/readyz` | nuovo `deployment/watch_readyz.ps1` (modello `watch_qcluster.ps1`) + `deployment/setup_wizard.py` (attività pianificata) | Ogni 60 s `GET /readyz`; 3 fallimenti consecutivi → mail SMTP diretta (non passa dal portale) + log. Da installare **preferibilmente su un'altra macchina** (es. host backup); il wizard la registra sull'host web come minimo. Se si tocca `setup_wizard.py`: rigenerare `SetupWizard.exe`. |

Checklist:
- [ ] 0.1 timeout MSAL + lock a tempo + un solo client
- [ ] 0.2 `DB_QUERY_TIMEOUT` web + check deploy + nota runbook prod
- [ ] 0.3 FAIL notturni + test
- [ ] 0.4 `watch_readyz.ps1` + attività pianificata + doc `RUNBOOK_PROD_DEPLOY_E_MAIL_ANOMALIE.md`
- [ ] CHANGELOG, `docs/moduli/monitoring.md`, `docs/ai/16_…` (spuntare A1.1–A1.4)

---

## 3. Blocco 1 — Indici infortunistici reali

**Perché**: `report_conformita` dichiara il limite «servono ore lavorate e giorni di prognosi»; il KPI S1 della
dashboard mostra solo conteggi. ISO 45001 §9.1.1 e il riesame vogliono IF/IG (UNI 7249).

### Modello (migrazione `rilevazione_incidenti` 0009)
Su `RilevazioneIncidente` (`rilevazione_incidenti/models.py`):
- `giorni_prognosi = PositiveSmallIntegerField(null=True, blank=True)` — giorni di assenza prescritti (prognosi iniziale);
- `giorni_assenza_effettivi = PositiveSmallIntegerField(null=True, blank=True)` — a chiusura RSPP;
- `con_assenza = BooleanField(default=False)` — infortunio con assenza > 0 gg (criterio INAIL/UNI 7249);
- `in_itinere = BooleanField(default=False)` — escluso dagli indici di stabilimento, conteggiato a parte.
Solo `tipologia_scheda = Accident` li espone nel form; compilabili da RSPP/preposto (`acl_rspp`/`acl_preposti`).

### Ore lavorate (nessun modello nuovo)
Servizio `rilevazione_incidenti/services/ore_lavorate.py` con `ore_lavorate(periodo, reparto=None) -> Decimal`:
1. Fonte primaria: `assenze.CertificazionePresenza` (entrata/uscita mattina + pomeriggio) sommate per giorno
   e persona, **solo personale in forza** (regola `people.cessati_ids` di `report_conformita`).
2. Fallback configurabile quando le presenze certificate non coprono il periodo (copertura < 80 % dei giorni
   lavorativi): headcount × ore teoriche giorno (da `SiteConfig` `sicurezza.ore_giorno_teoriche`, default 8)
   × giorni lavorativi, meno giornate di assenza approvate (`assenze` legacy). La riga del report dice quale
   fonte ha usato.
3. Nessun dato nominativo esce dal servizio: ritorna solo totali per periodo/reparto.

### Calcolo (`rilevazione_incidenti/services/indici.py`)
- IF (indice di frequenza) = infortuni con assenza × 1.000.000 / ore lavorate
- IG (indice di gravità) = giorni di assenza × 1.000 / ore lavorate
- TRIR = infortuni registrabili × 200.000 / ore lavorate (lo si tiene perché già citato nel backlog S1, con
  nota «indice a fini di confronto interno»)
- Durata media = giorni assenza / infortuni con assenza
- Serie mensile e annua, per stabilimento e per reparto; in itinere a parte.

### Dove appare
- [ ] Report «Infortuni, quasi infortuni e situazioni pericolose» (`report_conformita/reports/sicurezza.py`):
      indicatori IF/IG/TRIR/durata media + fonte ore; togliere la riga dai «Limiti noti» in `docs/moduli/report_conformita.md`
- [ ] Widget KPI S1 della `dashboard` (`DashboardConfig`): IF e IG anno corrente vs precedente
- [ ] Pagina `/rilevazione-incidenti/indici/` (HTMX, filtro anno/reparto, export xlsx col mixin C2)
- [ ] KPI `SIC-IF`, `SIC-IG` registrati nel catalogo del Blocco 3 (provider automatico)
- [ ] Form incidente: campi prognosi (solo Accident), validazione `giorni_assenza_effettivi` richiesto alla chiusura RSPP
      se `con_assenza`
- [ ] Test: calcolo con ore note; fallback headcount; esclusione in itinere; soglia privacy per reparto (< 5 persone → n.d.)
- [ ] Guida in-app `rilevazione_incidenti` + `core/guide_moduli/contenuti/rilevazione_incidenti.py` + CHANGELOG

---

## 4. Blocco 2 — Registro prescrizioni legali (MOD.147, MT CN 453, MT CN 2710)

**Perché**: zero codice oggi; richiesto da 45001 §6.1.3/§9.1.2, 27001 A.5.31, 9001 §4.2. Il report
«Scadenziario degli obblighi di legge» di `report_conformita` conta solo scadenze di formazione/visite/impianti:
manca la lista delle norme applicabili con la verifica di conformità.

### Dove vive
App `sistema_gestione` (menu **Qualità**, già sede dei documenti di governo), sotto-sezione
`/sistema-gestione/prescrizioni/`. Niente app nuova: riusa ACL bootstrap, guida e stile del modulo.

### Modelli (migrazione `sistema_gestione` 0019)
- `PrescrizioneLegale`: `codice` (auto `PLE-<anno>-<n>`), `ambito` (choices: SICUREZZA, AMBIENTE, INFORMAZIONI,
  QUALITA, PARITA, PRIVACY, AERONAUTICO, ALTRO), `norma` (titolo), `riferimento` (articoli), `fonte_url`,
  `descrizione_obbligo`, `applicabilita` (APPLICABILE / NON_APPLICABILE con motivo / DA_VALUTARE),
  `processi` M2M `Processo`, `responsabile` FK user, `frequenza_verifica_mesi`, `data_ultima_verifica`,
  `prossima_verifica` (calcolata), `stato` (CONFORME / NON_CONFORME / PARZIALE / DA_VERIFICARE),
  `evidenza_descrizione`, `documento_sgi` (testo: es. «MT CN 453»), `attivo`, `created/updated`.
- `PrescrizioneVerifica` (storico): FK prescrizione, `data`, `esito`, `note`, `evidenza` (FileField storage
  privato cifrato come `AuditAllegato`), `verificata_da`, `azione` FK opzionale `core.ActionItem` (CAPA, se non
  conforme).
- `PrescrizioneAggiornamento`: log «cambio norma» (data, descrizione, impatto, chi) — serve a 27001 A.5.31 e
  a MT CN 454 (cambiamento normativo come input del MOC futuro).

### Flussi
- Lista con filtri ambito/stato/scadute/responsabile; scheda con storico verifiche; «Registra verifica» (HTMX):
  se esito NON_CONFORME obbliga a creare o collegare un `ActionItem` (`core/services/capa.py`).
- Import iniziale `manage.py importa_prescrizioni "<xlsx>" [--apply]` dal MOD.147 compilato (dry-run di default,
  dati solo nel DB).
- Provider `collect_prescrizioni` in `dashboard/scadenze_providers.py` (verifiche in scadenza ≤ 60 gg) e
  notifica `core.Notifica` al responsabile; job settimanale `sistema_gestione_prescrizioni_scadute` (lunedì 07:30,
  stesso pattern di `sistema_gestione_scadenze_esterni`) a RSGI/RSPP.
- Sorgente automazioni `sistema_gestione_prescrizionelegale` (insert + changed su `stato`) per chi vorrà
  regole proprie.

### Aggancio ad altri moduli
- Report `report_conformita` «Scadenziario degli obblighi di legge»: nuova sezione «Prescrizioni legali»
  (totale applicabili, conformi, non conformi, da verificare, scadute) + nuovo report «Registro prescrizioni»
  area sicurezza/IT con clausole 45001 §6.1.3, 27001 A.5.31, 9001 §4.2.
- Scheda processo (`sistema_gestione/Processo`): pannello «Prescrizioni collegate».
- SoA 27001: i controlli 5.31–5.34 linkano l'evidenza viva (`sistema_gestione/evidenze.py`).
- KPI Blocco 3: `LEG-CONF` = % prescrizioni conformi, `LEG-VER` = % verifiche nei termini.

### ACL
`sistema_gestione.prescrizioni.view` (qualità, sicurezza, IT, admin), `.edit` (RSGI, RSPP, admin).
Binding in `sistema_gestione/acl_bootstrap.py`, cache bootstrap bumpata.

Checklist:
- [ ] Modelli + migrazione 0019 + admin
- [ ] Lista / scheda / registra verifica / import command
- [ ] Provider scadenze + job settimanale + sorgente automazioni
- [ ] Report conformità (sezione + report nuovo) + evidenze SoA + pannello processo
- [ ] ACL + test (fail-closed, verifica NC crea CAPA, scadenza calcolata, import idempotente)
- [ ] Guida `sistema_gestione/guida.py` (capitolo + `PAGE_HELP`), `core/guide_moduli`, `docs/moduli/sistema_gestione.md`,
      `hub_tools/schema_db.py`, CHANGELOG

---

## 5. Blocco 3 — Catalogo KPI MT CN 13 con alimentazione automatica

**Stato di partenza**: `sistema_gestione.RilevazioneKpi` esiste già (per processo, numeratore/denominatore,
target, verso, riferimento VRS, commento) ma è **a inserimento manuale** e senza catalogo: codice libero,
nessuna formula collegata ai dati del portale, nessuna serie. Gli indicatori calcolati vivono sparsi in
`report_conformita`, `dashboard`, `security.SecurityKpiSnapshot`, `anagrafica/reportistica`.

### Modelli (migrazione `sistema_gestione` 0020)
- `IndicatoreSGI` (catalogo): `codice` univoco (es. `QUA-OTD`, `SIC-IF`, `LEG-CONF`, `PAR-GAP`), `nome`,
  `processo` FK `Processo`, `norme` (M2M o JSON delle norme, stesse scelte di `Audit`), `formula_descrizione`
  (testo MT CN 13), `unita` (%, numero, giorni, €), `verso` (MIN/MAX), `target` corrente + `target_valido_dal`,
  `frequenza` (MENSILE/TRIMESTRALE/ANNUALE), `responsabile` FK user, `provider` (stringa: chiave del registro
  dei provider, vuota = manuale), `attivo`, `riferimento_documento` («MT CN 13 §x», «MOD.062»).
- `RilevazioneKpi`: aggiungere `indicatore` FK nullable a `IndicatoreSGI`, `origine` (MANUALE/AUTOMATICA),
  `valore` calcolato persistito, `job_run_id`. Le rilevazioni manuali esistenti restano valide (codice libero,
  FK nulla) e il comando `collega_rilevazioni_kpi` le aggancia per `codice` quando il catalogo è pronto.
- `IndicatoreTargetStorico` (data, target, approvato con riferimento riesame) — i target cambiano al riesame.

### Provider (registro, stesso schema di `report_conformita/reports/registry`)
`sistema_gestione/kpi/providers/__init__.py` con `register("SIC-IF", builder)`; ogni builder riceve
`(periodo_da, periodo_a)` e ritorna numeratore, denominatore, valore, fonte_filtri. Primi provider:

| Codice | Fonte | Esiste già |
|---|---|---|
| `SIC-IF`, `SIC-IG`, `SIC-NM` (near miss / mese) | Blocco 1 | dopo blocco 1 |
| `LEG-CONF`, `LEG-VER` | Blocco 2 | dopo blocco 2 |
| `QUA-NC-INT` (NC interne / mese), `QUA-NC-CHIUSE-TERMINI` | `anomalie.AnomaliaNC` | sì |
| `QUA-OFI-ACT` (A/P ≥ 90 % come MOD.174) | `registro_ofi` contatori | sì |
| `QUA-AUDIT-COPERTURA`, `QUA-CAR-EFFICACIA` | cruscotto audit `sistema_gestione` | sì |
| `FOR-COPERTURA` (% formazione obbligatoria in regola) | `anagrafica/reportistica/calcoli.py` | sì |
| `FOR-VISITE` (% visite in regola) | idem | sì |
| `MAN-PM-COMPLIANCE` (AS10) | `assets` `maintenance_kpi` | parziale (AS10 aperto) |
| `TCK-SLA`, `TCK-MTTR` | `tickets` (A1) + `AU25` | sì |
| `ISMS-PATCH`, `ISMS-BACKUP-OK` | `security.SecurityKpiSnapshot`, `monitoring.BackupRun` | sì |
| `PAR-*` | Blocco 6 | dopo blocco 6 |
| `QUA-VENDOR`, `QUA-OTD` | restano **manuali** finché non si collega il gestionale (fuori ambito) | no |

Job django-q `sistema_gestione_kpi_rileva` (1° del mese 06:00 per i mensili; trimestrali/annuali in cascata):
crea una `RilevazioneKpi` AUTOMATICA per ogni indicatore attivo con provider, idempotente su
(indicatore, periodo). Il responsabile riceve una `core.Notifica` se il valore è **sotto target** e deve
compilare `commento` (analisi cause) entro N giorni: finché manca, la rilevazione è «da commentare».

### UI
- `/sistema-gestione/kpi/` cruscotto: tabella indicatori con ultimo valore, target, semaforo, sparkline 12 mesi
  (SVG inline, token del tema; skill `dataviz` per i colori), filtri processo/norma/responsabile/sotto target.
- Scheda indicatore: serie storica, target storico, rilevazioni con commenti, «Rileva ora» (manuale o
  ricalcolo), export xlsx.
- Scheda processo: sezione «Indicatori» (sostituisce il testo libero `indicatori` quando esistono record).
- `priorita-v3` degli audit: la voce «KPI sotto target» legge il catalogo invece della rilevazione libera.
- Report conformità: nuovo report «Indicatori di performance» (9001 §9.1.1, 9100 §9.1.1) nel pacchetto riesame.

Checklist:
- [ ] Modelli + migrazione 0020 + comando `collega_rilevazioni_kpi` + seed dei codici base (`carica_catalogo_kpi`, idempotente, senza valori)
- [ ] Registro provider + i provider marcati «sì» nella tabella
- [ ] Job mensile + notifica sotto target + stato «da commentare»
- [ ] Cruscotto, scheda indicatore, pannello processo, aggancio `priorita-v3`, report conformità
- [ ] ACL `sistema_gestione.kpi.view` / `.edit` (target e catalogo solo RSGI/admin)
- [ ] Test: provider puro con dati sintetici, idempotenza job, semaforo verso MIN/MAX, rilevazioni vecchie intatte
- [ ] Guida, `core/guide_moduli`, `docs/moduli/sistema_gestione.md`, schema_db, CHANGELOG

---

## 6. Blocco 4 — Riesame della direzione (MOD.062, MT CN 19) e riunione operativa (MOD.063)

**Stato di partenza**: `report_conformita/riesame/` produce il **PDF degli input** (§9.3.2). Manca la riunione:
verbale, decisioni, azioni, confronto col riesame precedente, firma.

### Modelli (migrazione `sistema_gestione` 0021)
- `Riesame`: `numero` (`VRS-<anno>-<n>`), `tipo` (DIREZIONE / OPERATIVA → copre anche MOD.063), `data`,
  `periodo_da/a`, `sede`, `stato` (BOZZA → CONVOCATO → SVOLTO → APPROVATO → CHIUSO), `partecipanti` M2M user +
  `partecipanti_esterni` testo, `norme` (JSON), `pacchetto_input` FileField (PDF cifrato, SHA-256) generato
  da `report_conformita.riesame` alla convocazione e **congelato**, `outlook_event_id` (riuso
  `core/outlook_calendar.py` come `KickoffMeeting`), `verbale_pdf` emesso una volta con SHA-256 (pattern
  `AuditRapportoVersione`), `approvato_da`/`approvato_il`, `copia_firmata` (storage privato).
- `RiesameVoce`: una per punto di ingresso §9.3.2 (a…f) + punti MT CN 19: `codice_voce`, `titolo`,
  `sintesi` (precompilata dai report/KPI), `valutazione` (testo direzione), `ordine`. Per il tipo OPERATIVA
  l'elenco voci è quello del MOD.063.
- `RiesameDecisione` (§9.3.3): `testo`, `tipo` (OPPORTUNITA / MODIFICA_SGI / RISORSE / OBIETTIVO),
  `azione` FK `core.ActionItem` (CAPA, responsabile + scadenza + verifica), `indicatore` FK `IndicatoreSGI`
  con `nuovo_target` (scrive `IndicatoreTargetStorico` all'approvazione).
- `RiesameObiettivo`: obiettivi dell'anno (MT CN 272 per le informazioni, 45001 §6.2, 125 piano): `descrizione`,
  `indicatore`, `target`, `scadenza`, `responsabile`, `stato`; il riesame successivo li riporta con esito.

### Flussi
1. **Convoca**: sceglie periodo e norme; il sistema genera il pacchetto input (PDF da `report_conformita`, già
   esistente) e precompila le voci: KPI del Blocco 3 (valori, sotto target, commenti), NC/OFI (MOD.174), CAR e
   efficacia, audit interni ed esterni (`AuditEsterno`), prescrizioni legali (Blocco 2), incidenti e indici
   (Blocco 1), stato obiettivi del riesame precedente, azioni aperte del riesame precedente. Invito Outlook.
2. **Svolgi**: compilazione voci e decisioni in riunione (HTMX, salvataggio riga per riga, come l'editor audit
   da tablet).
3. **Approva**: Direzione ≠ redattore (stessa separazione dei ruoli degli audit); emissione verbale PDF unica,
   azioni CAPA create, target aggiornati, obiettivi pubblicati.
4. **Chiudi**: tutte le azioni chiuse o riportate al riesame successivo.
- Promemoria: job `sistema_gestione_riesame_promemoria` — riesame annuale non convocato entro 11 mesi dal
  precedente → RSGI; azioni scadute → già coperte dal CAPA.
- `/sistema-gestione/riesami/` lista; storico; «Confronta con precedente» (voce per voce).

### Aggancio
- Report conformità «Riesame» diventa il pacchetto input del flusso (link «Convoca riesame da questo pacchetto»).
- Audit: `priorita-v3` tiene conto delle decisioni del riesame sul processo (+5).
- SoA 27001 5.1/5.35 e PdR 125 (piano strategico, Blocco 6) linkano il riesame come evidenza.

Checklist:
- [ ] Modelli + migrazione 0021 + seed voci §9.3.2 / MOD.063
- [ ] Convoca (pacchetto + precompilazione + Outlook) / Svolgi / Approva (PDF unico, SHA-256) / Chiudi
- [ ] Decisioni → CAPA, target → storico, obiettivi → riesame successivo
- [ ] Job promemoria + ACL `sistema_gestione.riesame.view/.edit/.approva`
- [ ] Test: separazione ruoli, precompilazione con dati sintetici, PDF emesso una volta, obiettivi riportati
- [ ] Guida, `core/guide_moduli`, `docs/moduli/sistema_gestione.md` e `report_conformita.md`, schema_db, CHANGELOG

---

## 7. Blocco 5 — Registri ISMS vivi (MOD.166, MOD.170, MOD.200, MOD.173)

**Stato di partenza** (verificato nel codice): `security.SecurityIncident` esiste con campi NIS2 (significatività,
early warning, notifica, report finale, GDPR, CSIRT); `monitoring.BackupRun` + `RestoreDrill` registrano backup e
prove di ripristino **del portale**; `security.BackupExpectedJobConfig`/`BackupJobRecord` seguono i job Veeam;
`admin_portale/riesame_accessi.py` genera l'xlsx della revisione accessi M365. Quindi il blocco è soprattutto
**mappatura ai moduli SGI + ciò che manca**, non modelli nuovi dove già ci sono.

| Modulo SGI | Cosa c'è | Cosa manca | Dove |
|---|---|---|---|
| **MOD.166 RGI** rapporto incidente | `SecurityIncident` + log | PDF «RGI» con la struttura del MOD.166 (cronologia, classificazione, impatto, cause, azioni, lezioni, firme), numerazione `RGI-<anno>-<n>`, emissione unica con SHA-256; collegamento a `core.ActionItem` per le azioni; voce nel Registro OFI se l'incidente genera NC | `security/views_incidents.py`, nuovo `security/services/rgi_pdf.py`; campo `rgi_numero`, `rgi_emesso_il`, `rgi_sha256` su `SecurityIncident` (migrazione `security` 0034) |
| **MOD.170 CNBACKUP** lista backup | `BackupExpectedJobConfig` (Veeam), `BackupRun`/`RestoreDrill` (portale) | Registro unico «Lista backup»: per ogni job atteso → sistema, contenuto, frequenza, retention, destinazione (Synology/offsite), cifratura, responsabile, **ultima prova di ripristino** con esito; report PDF/xlsx MOD.170; prova di ripristino come record (`BackupRestoreTest`: job, data, esito, RTO misurato, verificato da) anche per Veeam/Synology, non solo DB portale | `security/models.py` (campi su `BackupExpectedJobConfig`: retention, destinazione, cifratura, responsabile, `restore_test_frequenza_mesi`) + `BackupRestoreTest`; pagina `/security/backup/registro/`; job «prova di ripristino scaduta» → RSGI |
| **MOD.200 ADR** registro AD | sync LDAP, `riesame_accessi` (M365), `account_m365` | Registro degli account AD/Entra con owner, tipo (persona/servizio/admin), gruppi privilegiati, data ultima revisione, esito; **revisione periodica firmata** (chi, quando, scostamenti, azioni); `revisione_accessi` da xlsx una tantum a record `RevisioneAccessi` + righe | `admin_portale` (`riesame_accessi.py` → servizio che produce anche record), modelli `RevisioneAccessi`/`RevisioneAccessiRiga` (migrazione `admin_portale`), pagina `/admin-portale/accessi/revisioni/`; evidenza viva SoA 5.15–5.18 |
| **MOD.173 BRP** business response plan | `MT CN 2712` solo documento; `RestoreDrill` per il DB | `PianoContinuita`: scenario (perdita server, ransomware, perdita sede, fornitore cloud…), servizi critici (FK `SecurityAsset`), RTO/RPO obiettivo, procedura, responsabile, contatti; `TestContinuita` (data, scenario, esito, RTO misurato, lezioni, azioni CAPA); promemoria test annuale | `security` (migrazione 0035), pagina `/security/continuita/`; evidenza viva SoA 5.29/5.30/8.14 |

Tutti alimentano: KPI `ISMS-*` del Blocco 3, voce ISMS del riesame (Blocco 4), report conformità area IT
(«Backup, vulnerabilità e rimedi» esteso con prove di ripristino e continuità; nuovo report «Incidenti di
sicurezza delle informazioni» con soli conteggi/tempi, mai dettagli).

Checklist:
- [ ] MOD.166: PDF RGI + numerazione + emissione unica + azioni CAPA + test
- [ ] MOD.170: campi registro + `BackupRestoreTest` + pagina + report + job prova scaduta + test
- [ ] MOD.200: `RevisioneAccessi` + pagina + firma + evidenza SoA + test
- [ ] MOD.173: `PianoContinuita` + `TestContinuita` + pagina + promemoria + evidenza SoA + test
- [ ] ACL (`security.*`, `admin_portale.*`) fail-closed; nessun redirect HTML su endpoint JSON
- [ ] Guide `security/guide/`, `core/guide_moduli` (security, amministrazione), `docs/moduli/security.md` e
      `admin_portale.md`, schema_db, CHANGELOG

---

## 8. Blocco 6 — KPI UNI/PdR 125 (MT CN 125_13) e piano strategico

**Stato di partenza**: la PdR 125 compare in 59 file (audit, OFI, norme) ma **nessun calcolo** dei KPI. I dati
ci sono: `genere` nei dati civili (tenuto apposta per le statistiche, cfr. `anagrafica/services/retention.py`),
`livello_inquadramento`, `tipologia_contratto`, `data_assunzione_ultima`, `data_cessazione`, `StoricoContratto`,
assenze (congedi), formazione, recruiting (MOD.202 selezione). **Manca la retribuzione**: i KPI retributivi
restano manuali (import xlsx da HR) finché non c'è una fonte; non introdurre campi RAL nel portale senza
decisione esplicita (dato riservato, `anagrafica.hr.view`).

### Le 6 aree della PdR 125 (§6) e come si calcolano
| Area | KPI (esempi dal MT CN 125_13) | Fonte nel portale | Automatico |
|---|---|---|---|
| 1 Cultura e strategia | piano approvato, comunicazioni, formazione sul tema | `Riesame`/obiettivi (Blocco 4), `notizie`, formazione | parziale |
| 2 Governance | comitato guida nominato, % donne negli organi/ruoli apicali | ruoli anagrafica (`ruolo_aziendale`, ambiti), MOD.188 | sì |
| 3 Processi HR | % donne assunte / candidate (MOD.202), % promozioni per genere, % formazione per genere | `recruiting`, `StoricoContratto` (cambio livello), formazione | sì |
| 4 Opportunità di crescita | % donne per livello di inquadramento, % part-time per genere | `livello_inquadramento`, `tipologia_contratto` | sì |
| 5 Equità remunerativa | gap retributivo per livello | **manuale** (import xlsx HR) | no |
| 6 Genitorialità e conciliazione | congedi fruiti per genere, rientri dopo congedo, smart working | `assenze` (tipi congedo), `ILA` lavoro agile | parziale |

### Implementazione
- Report `anagrafica/reportistica` **o** `report_conformita/reports/parita.py` (preferito: sola lettura, PDF/xlsx,
  ACL per area): nuova area «Parità di genere» (`report_conformita.parita.view`, default HR + admin), report
  «KPI UNI/PdR 125» con le 6 aree, periodo annuale, **solo aggregati e soglia 5** (celle sotto soglia → «n.d.»),
  riferimenti §6.1–6.6 della prassi.
- Catalogo KPI (Blocco 3): codici `PAR-GOV`, `PAR-ASS`, `PAR-PROM`, `PAR-LIV`, `PAR-PT`, `PAR-CONG` con provider;
  `PAR-GAP` manuale. Target = quelli del piano strategico.
- `PianoStrategicoParita` (migrazione `sistema_gestione` 0022): anno, obiettivi (riuso `RiesameObiettivo` con
  `ambito=PARITA`), comitato guida (M2M user), approvazione Direzione, verbali del comitato (riuso `Riesame`
  tipo OPERATIVA con `norme=["PdR125"]`). Niente modelli nuovi oltre il contenitore.
- Pagina `/sistema-gestione/parita/`: piano dell'anno, KPI con semaforo, comitato, verbali, documenti (riferimenti
  MT CN 125_x), «Rapporto annuale» PDF (input per l'audit dell'ente).
- Registro OFI: già supporta la norma PdR 125; aggiungere il filtro rapido dalla pagina parità.

Checklist:
- [ ] Report «KPI UNI/PdR 125» + area ACL + soglia privacy + test con dati sintetici (genere bilanciato, celle < 5)
- [ ] Provider `PAR-*` nel catalogo + import xlsx manuale per `PAR-GAP` (dry-run, nessun dato nel repo)
- [ ] `PianoStrategicoParita` + pagina + rapporto annuale PDF
- [ ] Verbali comitato via `Riesame` OPERATIVA; obiettivi via `RiesameObiettivo`
- [ ] Guida, `core/guide_moduli`, `docs/moduli/report_conformita.md` e `sistema_gestione.md`, schema_db, CHANGELOG

---

## 9. Deploy (cumulativo, da ripetere per ogni blocco rilasciato)

- Migrazioni: `rilevazione_incidenti` 0009 (B1); `sistema_gestione` 0019–0022 (B2, B3, B4, B6); `security`
  0034–0035 e `admin_portale` (B5). Verificare i numeri reali al momento del merge (branch paralleli).
- Bootstrap: `bootstrap_acl_v2` (nuovi permessi), `carica_catalogo_kpi`, `collega_rilevazioni_kpi` (B3), seed voci
  riesame (B4), `importa_prescrizioni` (B2, con il MOD.147 reale, solo in prod, mai nel repo).
- qcluster **riavviato** dopo ogni deploy (nuovi job: `sistema_gestione_prescrizioni_scadute`,
  `sistema_gestione_kpi_rileva`, `sistema_gestione_riesame_promemoria`, prova ripristino scaduta).
- `.env` prod: `DB_QUERY_TIMEOUT=60` (B0.2); attività pianificata `watch_readyz` (B0.4).
- `collectstatic` se cambiano CSS/JS (sparkline KPI).
- Release guard `tools/release_guard.ps1`; bump versione (`06_TESTING_AND_QUALITY_GATES.md`).

## 10. Decisioni da confermare con l'utente lungo la strada (non bloccanti, assunzione in corsivo)

1. B1: ore teoriche/giorno per il fallback (*8*) e se gli infortuni in itinere entrano nel report (*a parte*).
2. B2: dove vive il registro (*`sistema_gestione`*) e chi è il responsabile di default (*RSPP per SICUREZZA, RSGI per il resto*).
3. B3: giorni concessi per il commento sotto target (*10*) e se i KPI manuali Vendor Rating/OTD restano manuali (*sì*).
4. B4: il MOD.063 riunione operativa si tratta come riesame di tipo OPERATIVA (*sì*) o modulo a parte.
5. B5: la retention delle prove di ripristino e dei RGI (*10 anni, come i rapporti di audit*).
6. B6: retribuzione mai nel portale (*import xlsx aggregato*), soglia privacy (*5*).
