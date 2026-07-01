# F7 — Conformità del portale alla Matrice di Workflow (ex ARXivar) + FLUSSO SPECIFICHE/MOD.133

> **Scopo**: verificare che `gestione_specifiche` implementi il workflow definito nei due file di
> analisi (`Matrice_Workflow_ARXivar.xlsx` — fogli Stati/Transizioni/Ruoli/Timer/Distribuzione/
> Campi/Checklist — e `FLUSSO SPECIFICHE + MOD.133.xlsx`). ARXivar è stato **scartato come
> piattaforma**: la Matrice vale ora come **specifica di conformità** e i «gruppi ARXivar»
> diventano **permessi ACL v2** del portale. I due Excel sono **dati reali non versionati**
> (repo-root gitignorati): qui se ne riporta solo la struttura/conformità, nessun dato.
>
> Legenda: ✅ conforme · 🟡 parziale · ❌ gap · 🔍 da verificare in prod. Ultimo agg.: 2026-07-01.

## Esito sintetico
Il portale è **sostanzialmente conforme** alla Matrice: macchina a stati (S1-S9), tutte le transizioni
(H1-H4, T1-T6, R1), motivi obbligatori, **master+motivo su duplicato** e **payload su errore**, pausa
timer in Sospeso/Errore, timer 7/14gg e verifica 6 mesi, **obbligatorietà condizionale della griglia
documenti**, distribuzione con **algoritmo copie cartacee + deroga** e presa visione, **mappa Ruolo→ACL
con seed**. Restano solo **affinamenti minori** (§8): UI master-picker per il duplicato, aggancio di
`PERM_DEROGA`, reminder di presa-in-carico S1, verifica in prod dei job schedulati.
*(La prima stesura di questo doc sovrastimava i gap: corretta dopo ricognizione puntuale del codice.)*

## 1. Stati (foglio «Stati») — ✅ conforme
S1 Bozza · S2 In flow-down · S3 In validità · S4 Superato · S5 Sospeso · S6 Annullato ·
S7 Duplicato · S8 Respinto/Non applicabile · S9 Errore tecnico → tutti presenti
(`constants.py STATO_*` + `models.Specifica.stato` FSMField protected).

## 2. Transizioni (foglio «Transizioni») — ✅ conforme
| Matrice | Portale (`models.py`) | Stato |
|---|---|---|
| H2 Avvio flow-down (S1→S2) | `avvia_flow_down` (crea MOD.133, start timer) | ✅ |
| H3 Approvazione MOD.133 OK (S2→S3) | `approva_flow_down` (guardia esito + **separazione compilatore≠approvatore** + set verifica 6 mesi) | ✅ |
| H4 Superamento auto (S3→S4) | `supera` + auto-supersessione della rev precedente dentro `approva_flow_down` | ✅ |
| T1 Annullamento | `annulla` (**motivo obbligatorio**) | ✅ |
| T2 Duplicato | `marca_duplicato` (S1/S2→S7): **master + motivo obbligatori**; master impostabile via API (`master` in `TransizioneIn`) | ✅ (manca solo il master-picker nella UI SSR) |
| T3 Sospensione | `sospendi` (**motivo+data obbligatori**, **pausa timer**) | ✅ |
| T4 Ripristino da sospeso | `ripristina` (motivo obbligatorio, ripristina stato_precedente) | ✅ |
| T5 Respinto/Non applicabile | `respingi_flow_down` (S2→S8) | ✅ |
| T6 Errore tecnico (qualunque→S9) | `errore_tecnico` (`source="+"`, **payload obbligatorio**, salvato in `EventoSpecifica.payload`) | ✅ |
| R1 Ripristino da errore | `ripristina_da_errore` (S9→precedente) | ✅ |

## 3. Ruoli (foglio «Ruoli») — ✅ mappa Ruolo→ACL (con affinamenti)
I «gruppi ARXivar» diventano **permessi ACL v2** (`acl_bootstrap.py`). Permessi canonici:
`specifica.view` · `specifica.claim` · `mod133.compila` · `mod133.approva` · `specifica.sospendi` ·
`specifica.annulla` · `distribuzione.distribuisci` · `distribuzione.deroga`. I grant di default sono
**seminati** da `acl_bootstrap._bootstrap_canonical()` (create-only, rifinibili in
`/admin-portale/acl-canonico/`).

**Ruolo Matrice → ruolo portale → permessi**:
| Ruolo Matrice | Ruolo portale | Permessi ACL di default |
|---|---|---|
| DM (owner workflow) | `amministrazione` | tutti (view/claim/compila/approva/sospendi/annulla/distribuisci/deroga) |
| Approvatore MOD.133 (RDD/MSM/MSO) · SGI | `qualita` | tutti (incl. **approva**) |
| IT Admin | `admin` | tutti |
| Destinatario MOD.133 (compilatore) · capi | `caporeparto` | view · claim · **compila** (NON approva → separazione compiti) |
| IN1 (inseritore) · utente | *(nessun grant automatico)* | — da abilitare a mano |

Affinamenti residui: `distribuzione.deroga` (`PERM_DEROGA`) è **definito ma non ancora agganciato**
a una route/guardia (oggi la deroga copie è concessa a chi ha `distribuisci`); i ruoli `IN1`/`utente`
non ricevono grant automatici. Le transizioni `marca_duplicato`/`errore_tecnico` sono **solo API**
(nessuna route SSR da bindare).

## 4. Timer (foglio «Timer») — ✅ / 🔍
- Reminder **7gg** e Escalation **14gg** sul MOD.133 (S2): `MOD133.reminder_inviato` /
  `escalation_inviata` / `timer_anchor` / `timer_pausa_at`; settings `REMINDER_GIORNI=7`,
  `ESCALATION_GIORNI=14`. **Pausa** in S5/S9 gestita in `sospendi`/`errore_tecnico`. ✅
- Verifica periodica **6 mesi** dall'ingresso in S3: `Specifica.data_verifica` +
  `VERIFICA_PERIODICA_MESI=6`. ✅
- 🔍 **Verificare in prod** che i job django-q2 (reminder/escalation/verifica) siano **schedulati**
  (`setup_q_schedules`) e girino sul cluster.
- 🟡 **Reminder S1 «presa in carico IN1 entro 7gg»** (FLUSSO R16): il reminder del portale è sul
  MOD.133 (S2). Il reminder di **presa-in-carico in Bozza (S1)** per IN1 non risulta esplicito.

## 5. Distribuzione (foglio «Distribuzione» + FLUSSO R25-27) — ✅
Modello `Distribuzione`: `canale`, `destinatari` (M2M reparti), `presa_visione_richiesta`, `cartacea`,
`n_copie_distribuite`, `n_copie_ritirate`, `deroga_giustificazione`, `data_distribuzione`, audit evento.
- ✅ **Algoritmo copie cartacee** (Matrice Checklist R08 + FLUSSO R27): implementato in
  `distribuzione.crea_distribuzione` — se `cartacea` e `n_copie_ritirate` ≠ copie distribuite
  dell'ultima distribuzione cartacea della **revisione precedente** (`copie_distribuite_rev_precedente`),
  serve la **deroga giustificata** (`deroga_giustificazione`), altrimenti solleva `DerogaCopieRichiesta`
  e la view `distribuzione_nuova` ripropone il form con avviso. Caso limite prima revisione → attese=0.
- ✅ Presa visione: `presa_visione_richiesta` + `ConfigPresaVisione` per (tipo doc × reparto).

## 6. Campi & MOD.133 (foglio «Campi» + FLUSSO «Flusso MOD.133») — ✅ / 🟡
- ✅ Griglia MOD.133 (`RigaMOD133`): rif. paragrafo, argomento, impatto documenti (Y/N),
  rif./§ documento CN, descrizione modifiche, impatto operativo (Y/N), descrizione impatto, TAG,
  note, OFI. Mapping verso il renderer in `composito.dati_mod133_da_spec` (F6a).
- ✅ **Obbligatorietà condizionale griglie** (Matrice Checklist R07): implementata nel
  `RigaMOD133Form.clean()` — se `impatto_documenti=True`, `rif_doc_cn` diventa obbligatorio (validato
  al salvataggio del formset in `mod133_compila`; test in `test_views_mod133`). La UI rivela la griglia
  al toggle. *(Affinamento opzionale: rendere obbligatorio anche `rif_paragrafo_cn`.)*
- ✅ Motivo obbligatorio su sospensione/ripristino/annullo (enforced nelle transizioni).
- ✅ Riferimento **master + motivo** obbligatori su Duplicato (T2, `marca_duplicato`) e **payload** su
  Errore (S9, `errore_tecnico`): enforced nelle transizioni; master impostabile via API.

## 7. FLUSSO — autocompilazioni e fasi
- ✅ MOD.133 eredita da Specifiche (OWNER/FONTE/N°DOC/REV/TITOLO/DATA) — mapping in F6a.
- ✅ Fasi 1-5 (inserimento → compilazione MOD.133 → approvazione → chiusura → distribuzione)
  coperte da FSM + Distribuzione.
- ✅ **Copiloti AI** oltre alla Matrice (valore aggiunto): pre-compilazione MOD.133 da PDF, TAG,
  **diff rev precedente↔nuova** (F5), composito ufficiale protetto (F6a).

## 8. Backlog di conformità (aggiornato 2026-07-01)
**Già conforme** (verificato nel codice, con test): griglia condizionale documenti
(`RigaMOD133Form.clean`), tabella + seed **Ruolo→ACL** (`acl_bootstrap`), **algoritmo copie cartacee**
(`crea_distribuzione` + `DerogaCopieRichiesta`), campi obbligatori **master+motivo** su duplicato e
**payload** su errore (transizioni). Restano solo **affinamenti minori**:
1. **[Bassa]** **UI master-picker** per il duplicato (oggi la master si imposta solo via API).
2. **[Bassa]** Agganciare `PERM_DEROGA` a una guardia effettiva sulla deroga copie; grant di default
   per `IN1`/`utente`.
3. **[Bassa]** Rendere obbligatorio anche `rif_paragrafo_cn` quando impatto_documenti=Y (opzionale).
4. **[Media]** **Reminder S1** «presa in carico IN1 entro 7gg» (oltre al reminder MOD.133 in S2).
5. **[Verifica prod]** Job django-q2 reminder/escalation/verifica **schedulati e attivi**.

*(Nessuna voce è bloccante; il portale è sostanzialmente allineato alla Matrice. La revisione iniziale
di questo documento sovrastimava i gap: corretta dopo ricognizione puntuale del codice.)*
