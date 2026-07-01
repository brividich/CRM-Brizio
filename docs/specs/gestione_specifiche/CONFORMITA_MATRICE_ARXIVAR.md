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
Il portale è **ampiamente conforme**: la macchina a stati (S1-S9), tutte le transizioni
(H1-H4, T1-T6, R1), i motivi obbligatori, la pausa timer in Sospeso/Errore, i timer 7/14gg e la
verifica 6 mesi, la distribuzione con copie cartacee e presa visione **esistono già**. Restano
alcuni affinamenti (algoritmo copie cartacee, obbligatorietà condizionale griglie, campi
obbligatori su duplicato/errore, reminder di presa-in-carico S1, tabella Ruolo→ACL).

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
| T2 Duplicato | `marca_duplicato` (S1/S2→S7) | 🟡 manca l'obbligo di **riferimento master + motivo** (Matrice: obbligatori in T2) |
| T3 Sospensione | `sospendi` (**motivo+data obbligatori**, **pausa timer**) | ✅ |
| T4 Ripristino da sospeso | `ripristina` (motivo obbligatorio, ripristina stato_precedente) | ✅ |
| T5 Respinto/Non applicabile | `respingi_flow_down` (S2→S8) | ✅ |
| T6 Errore tecnico (qualunque→S9) | `errore_tecnico` (`source="+"`) | 🟡 verificare che il **payload errore** venga salvato (Matrice: obbligatorio in S9) |
| R1 Ripristino da errore | `ripristina_da_errore` (S9→precedente) | ✅ |

## 3. Ruoli (foglio «Ruoli») — 🟡 mappare Ruolo→ACL
La Matrice elenca DM, IN1, Destinatario MOD.133, Approvatore (RDD/MSM/MSO), SGI, IT Admin. Nel
portale i «gruppi ARXivar» diventano **permessi ACL v2** (`acl_bootstrap.py`: `PERM_COMPILA`,
`PERM_APPROVA`, `PERM_DISTRIBUISCI`, `PERM_SOSPENDI`, `PERM_ANNULLA`, `PERM_VIEW`).
**Da fare**: tabella esplicita **Ruolo → permesso ACL → azioni** (claim/compila/approva/sospendi/
annulla/deroga) in doc + seed grant di default (Matrice Checklist R09, priorità Alta).

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

## 5. Distribuzione (foglio «Distribuzione» + FLUSSO R25-27) — 🟡
Modello `Distribuzione`: `presa_visione_richiesta`, `n_copie_distribuite`, `n_copie_ritirate`,
canale/data/audit (evento). Campi **presenti**.
- 🟡 **Algoritmo copie cartacee** (Matrice Checklist R08 + FLUSSO R27): «n° copie **ritirate** nella
  nuova revisione = n° copie **distribuite** nella revisione precedente», con **casi limite** e
  **deroga+giustificazione** (DM). I campi ci sono ma **la validazione/riconciliazione automatica
  non è formalizzata** → da implementare (priorità Media).
- ✅ Presa visione: `presa_visione_richiesta` + `ConfigPresaVisione` per (tipo doc × reparto).

## 6. Campi & MOD.133 (foglio «Campi» + FLUSSO «Flusso MOD.133») — ✅ / 🟡
- ✅ Griglia MOD.133 (`RigaMOD133`): rif. paragrafo, argomento, impatto documenti (Y/N),
  rif./§ documento CN, descrizione modifiche, impatto operativo (Y/N), descrizione impatto, TAG,
  note, OFI. Mapping verso il renderer in `composito.dati_mod133_da_spec` (F6a).
- 🟡 **Obbligatorietà condizionale griglie** (Matrice Checklist R07): «se Impatto Documenti=N →
  griglia documenti non obbligatoria/nascosta; se Y → obbligatoria». I flag esistono; l'**enforcement
  condizionale** (validazione/UI) è **da verificare/rendere esplicito** (priorità Alta).
- ✅ Motivo obbligatorio su sospensione/ripristino/annullo (enforced nelle transizioni).
- 🟡 Riferimento **master** obbligatorio su Duplicato (T2) e **payload** su Errore (S9): da rendere
  obbligatori come da Matrice.

## 7. FLUSSO — autocompilazioni e fasi
- ✅ MOD.133 eredita da Specifiche (OWNER/FONTE/N°DOC/REV/TITOLO/DATA) — mapping in F6a.
- ✅ Fasi 1-5 (inserimento → compilazione MOD.133 → approvazione → chiusura → distribuzione)
  coperte da FSM + Distribuzione.
- ✅ **Copiloti AI** oltre alla Matrice (valore aggiunto): pre-compilazione MOD.133 da PDF, TAG,
  **diff rev precedente↔nuova** (F5), composito ufficiale protetto (F6a).

## 8. Backlog di conformità (prioritizzato)
1. **[Alta]** Obbligatorietà **condizionale griglia documenti** (impatto_documenti=Y ⇒ righe
   obbligatorie) — validazione + UI.
2. **[Alta]** Tabella **Ruolo→ACL→azioni** + seed grant di default (governance permessi).
3. **[Media]** **Algoritmo copie cartacee**: ritirate(nuova rev)=distribuite(rev precedente),
   casi limite, **deroga+giustificazione** DM.
4. **[Media]** Campi obbligatori mancanti: **master+motivo** su `marca_duplicato` (T2),
   **payload** su `errore_tecnico` (S9).
5. **[Media]** **Reminder S1** «presa in carico IN1 entro 7gg» (oltre al reminder MOD.133 in S2).
6. **[Verifica prod]** Job django-q2 reminder/escalation/verifica **schedulati e attivi**.

*(Nessuna di queste voci è bloccante per il workflow PDF/MOD.133 già costruito; sono affinamenti
di conformità alla Matrice.)*
