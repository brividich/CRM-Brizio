# Checklist «Registra insieme» — stessa operazione su più voci gemelle

Avviata il 02/11/2026. Schema già in produzione-candidata (release/prod `a2ecbe30`, non deployato):
**Scadenze amministrative → «Registra adempimento» → «Stessa scadenza su altri asset»** con filtro
«scadute o entro» (7 gg – un anno, default 30). Riferimento di codice:
`assets/views/deadlines.py` (`_same_deadline_other_assets`, `_register_deadline_completion`,
`_DEADLINE_SAME_OUTING_CHOICES`), template `asset_admin_deadline_list.html` + `components/_admin_deadline_also.html`,
test `assets/tests_admin_deadlines_riordino.py::StessaScadenzaAltriAssetTests`.

## Come lavorarci (più chat o subagent)

- Una voce = un branch/worktree: `git worktree add C:\Dev\pn-<tema> -B feature/assets-<tema> origin/main`.
- **Prima di iniziare** una voce: scrivi qui accanto `IN CORSO — <branch>` e pusha su main (solo questo file),
  così un'altra chat non la prende. A fine voce: spunta, scrivi commit di merge su main/release.
- Le voci 2, 3 e 4 toccano tutte `assets/views/deadlines.py`: farle **in sequenza** o aspettarsi conflitti
  (risolvibili, sezioni diverse). La voce 1 tocca solo `views_maintenance.py` + `occurrence_complete.html`.
- Regole comuni a ogni voce (vedi `CLAUDE.md`):
  - l'elenco delle gemelle si **ricalcola lato server** al POST: mai fidarsi degli id del modulo;
  - stessa **visibilità** della pagina (`filtra_per_asset(request, qs, MODULO_…)` dove la pagina la usa);
  - **audit** (`log_action`) per ogni voce registrata, con il riferimento alla voce principale;
  - costi/durate/fermi **solo sulla voce principale** (non si contano due volte), salvo dove detto;
  - allegati condivisi: nuova riga che punta allo **stesso file** (`file=altro.file.name`), nessuna copia;
  - una gemella che fallisce non annulla le altre: messaggio «Non registrata su …» e si prosegue;
  - CHANGELOG `[Unreleased]`, guida in-app (`assets/templates/assets/pages/guida.html`),
    Centro guide (`core/guide_moduli/contenuti/assets.py`), scheda `docs/moduli/assets.md`;
  - test solo dell'app: `manage.py test assets.<modulo> --keepdb --settings=config.settings.test`;
  - verifica a video (SQLite del worktree + seed sintetico + Playwright, chiaro/scuro/390px);
  - merge feature → main → release/prod.

## Voci

### 1. Registra esecuzione manutenzione: «Stesso piano su altre macchine» — [ ] IN CORSO (feature/assets-registra-insieme)
Pagina: `assets/manutenzione/occorrenze/<id>/registra/` (`views_maintenance.occurrence_complete`,
template `occurrence_complete.html`). Oggi c'è solo «Sulla stessa macchina entro 30 giorni»
(`_completion_suggestions` → `same_asset_open`, `_complete_same_outing`, campo `also_complete`).

- [ ] `_completion_suggestions`: aggiungere `same_plan_other_assets` = occorrenze **aperte**, stesso `plan_id`,
      asset diverso, visibili (`filtra_per_asset(..., MODULO_MANUTENZIONE)`), scadenza entro un anno dalla
      scadenza di questa (le scadute sempre); una per asset (la prima); con i giorni di distanza.
- [ ] Escludere le occorrenze **a contatore** (`is_meter_based`): servono letture diverse per macchina.
- [ ] Template: riquadro «Stesso piano su altre macchine» con filtro «scadute o entro» (stesse opzioni
      delle scadenze), «Spunta tutte», pulsante «Registra N manutenzioni» che conta entrambi i riquadri.
- [ ] POST: nuovo campo `also_complete_assets`; `_complete_same_outing` accetta anche quelle, ricalcolando
      l'elenco consentito (stesso piano, aperte, visibili, non a contatore). Fermo macchina solo sulla principale;
      stessa data, note, rapporto condiviso. Chiusura OdL collegati come oggi (`touched`).
- [ ] Test in `assets/tests_maintenance_flow.py` (o nuovo file): proposta, filtro contatore, id non consentiti ignorati.

### 2. Rinnovo licenze software: «Rinnova anche» — [ ] IN CORSO (feature/assets-registra-insieme)
Pagina: `assets/licenze-software/` (`deadlines.software_license_list`, azione `renew_software_license`,
template `software_license_list.html`, form `SoftwareLicenseRenewalForm` con prefisso `renew-<id>`).

- [ ] Gemelle = licenze **attive**, stesso `product_name` (senza maiuscole/spazi) e stesso `vendor`,
      con scadenza entro un anno da quella della licenza (le scadute sempre; senza scadenza escluse).
- [ ] Nel modulo «Rinnova» di ogni riga: elenco a spunta «Rinnova anche» con filtro periodo.
- [ ] POST: per ogni gemella consentita crea `SoftwareLicenseRenewal` con stessa nuova scadenza, data rinnovo,
      inizio periodo, fornitore, riferimento e note; `previous_expiry` della gemella; posti e costo **solo**
      sulla principale. Aggiorna `expiry_date`/`renewal_date`/`is_active` della gemella. Audit per ciascuna.
- [ ] Test.

### 3. Contratti di assistenza: «Rinnova» (+ «Rinnova anche») — [ ] IN CORSO (feature/assets-registra-insieme)
Pagina: `assets/contratti-assistenza/` (`deadlines.assistance_contract_list`). Oggi non c'è rinnovo:
si modifica la data fine a mano. Nessun modello di storico → niente migrazione: lo storico sta nell'audit
e in una riga aggiunta alle note («Rinnovato il gg/mm/aaaa: fine da A a B»).

- [ ] Azione `renew_assistance_contract` (solo admin assets): nuova data fine (obbligatoria, > attuale),
      riattiva il contratto, riga nelle note, audit con fine precedente/nuova.
- [ ] Pulsante «Rinnova» sulla riga con finestra/riquadro (pattern `details` delle licenze).
- [ ] «Rinnova anche»: contratti **attivi** dello **stesso fornitore**, data fine entro un anno da quella del
      contratto (scaduti sempre), visibili (`filtra_per_asset(..., MODULO_FORNITORI)`); stessa nuova data fine.
- [ ] Test.

### 4. Nuova scadenza amministrativa: «Crea anche su…» — [ ] IN CORSO (feature/assets-registra-insieme)
Pagina: `assets/scadenze/nuova/` (`deadlines.asset_administrative_deadline_create`,
template `asset_admin_deadline_form.html`, form `AssetAdministrativeDeadlineForm`). Stesso schema di
«Altri asset con la stessa manutenzione» nella creazione OdL (`workorders._create_sibling_workorders_from_request`).

- [ ] Dopo la scelta dell'asset: elenco degli asset della **stessa categoria** (`asset_category_id`), in uso,
      visibili, che **non** hanno già una scadenza attiva con lo stesso titolo e tipo (calcolato al salvataggio
      sul titolo inserito; in pagina proposta per categoria con nota).
- [ ] POST campo `extra_asset_ids`: ricalcolo lato server degli asset consentiti; copia di tipo, titolo,
      data, preavviso, periodicità, riferimento, ente, note; **senza componente**. Audit per ciascuna.
- [ ] Messaggio «Creata anche su N asset: …».
- [ ] Test.

## Avanzamento

| Voce | Stato | Branch | Merge main | Merge release/prod |
|---|---|---|---|---|
| 0. Scadenze amministrative (riferimento) | fatta | feature/assets-scadenze-altri-* | 12ec0c20 | a2ecbe30 |
| 1. Manutenzione stesso piano | in corso | feature/assets-registra-insieme | — | — |
| 2. Licenze rinnova anche | in corso | feature/assets-registra-insieme | — | — |
| 3. Contratti rinnova | in corso | feature/assets-registra-insieme | — | — |
| 4. Nuova scadenza crea anche | in corso | feature/assets-registra-insieme | — | — |
