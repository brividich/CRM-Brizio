# ANALISI DI IMPLEMENTAZIONE — MOD.128 (MPQ) digitale in `anagrafica` (F0)

> **Stato:** F0 — analisi + decisioni bloccate. Nessun codice scritto.
> **Prossima fase:** F1 (models_mpq + migration + admin + test in TDD).
> **Data:** 2026-07-06 · **Branch di lavoro:** `feature/skill-matrix-mod187` (prod gira qui, non `main`).
>
> **PII / privacy:** questo documento è **depurato da dati personali**. Il MOD.128 reale
> contiene nomi di persone e numeri di certificato individuali: **non sono riportati qui**.
> Tutti gli esempi persona/numero sono **fittizi** (es. "Operatore A", "cert. NN-000/0").
> I nomi cliente/ente e le denominazioni di processo sono conservati perché descrivono la
> struttura del modulo e non sono dati personali.

---

## 0) Documenti-fonte e loro stato

| Documento | Stato | Note |
|-----------|-------|------|
| `docs/anagrafica/MOD.128 - MPQ - Mansionario Processi Qualificati Rev.16.pdf` | ✅ letto | **Rev.16** (il brief citava Rev.15). 3 pagine, è una tabella. |
| `docs/anagrafica/MT CN 06 Rev.21_Risorse Umane.pdf` | ✅ letto | Procedura di sistema che disciplina il MOD.128 (23 pagine). |
| `skill CN - 22apr 2024.xlsx` | ❌ assente | Serviva solo per gli agganci Skill Matrix (F6). Bridge lasciato come placeholder logico. |

Estrazione PDF fatta con PyMuPDF (`fitz`) nel venv (il tool di rendering pagine non è
disponibile su questa macchina — manca poppler).

---

## 1) Struttura reale del MOD.128 (ricavata dalla tabella, non da riassunti)

Il modulo è **una tabella** con due layout di intestazione:

- **Layout pieno (8 colonne):**
  `CLIENTE | PROCESSO QUALIFICATO | PERSONALE QUALIFICATO | PERSONALE ADDETTO | PERSONALE CONTROLLORE | PART 145 | SCADENZE | DISTRIBUZIONE A REPARTO`
- **Layout ridotto (5 colonne):**
  `CLIENTE | PROCESSO QUALIFICATO | PERSONALE QUALIFICATO | SCADENZE | DISTRIBUZIONE A REPARTO`
  (usato quando i ruoli non sono distinti: certificati NADCAP, attestati GE Avio, riconoscimenti Piaggio).

### Entità e cardinalità reali
- **CLIENTE** = committente **oppure** ente di accreditamento. Valori reali osservati:
  *Leonardo Helicopter, GE Avio, Piaggio Aerospace, NADCAP*. → **NADCAP non è un cliente ma
  un ente di accreditamento**. Una riga può avere **più clienti/enti** (es. l'ispezione PT LVL3
  è riconosciuta contemporaneamente da NADCAP + Leonardo + GE Avio + Piaggio).
- **PROCESSO QUALIFICATO** = nome descrittivo **+ uno o più codici/riferimenti** di
  approvazione/specifica **+ livello opzionale** (LVL2 / LVL3). Esempi di forma dei codici (non PII):
  approvazioni cliente (`COP0xx`, `CTO0xx`, `DMF0xx`, `MCG0xx`), specifiche (`AMS####`, `MIL DTL ####`),
  attestati/certificati (`####Q N° ...`, `GTxxx-CERT......`), dichiarazioni (`LH/#### del gg.mm.aaaa`).
- **PERSONALE QUALIFICATO** — due modalità:
  - **NOMINALE**: elenco persone, ciascuna con flag di ruolo + eventuale **certificazione
    individuale** (schema + numero + scadenza propri). Una stessa persona può avere **più
    certificati con scadenze diverse** (es. schema ITA + schema ASNT sullo stesso processo).
  - **ORGANIZZATIVA**: nessun nominativo, ma **rimando a una dichiarazione/approvazione
    aziendale** (es. "Elenco Personale ... Rif. MO-ID-...", "Rif. Dichiarazione Approvazione LH/...").
- **Ruoli sul processo** (flag SI/NO **per persona**): **QUALIFICATO** (implicito = essere in
  lista), **ADDETTO**, **CONTROLLORE**, **PART 145**. Combinabili (in un processo reale i primi
  N operatori sono Addetto, i restanti Controllore, tutti Part145 — è una **matrice persona×ruolo**).
- **SCADENZE (livello processo/attestato)** — tre forme:
  - `Illimitata a meno di revoca o sospensione`;
  - `Validità N anni/mesi (Scad. gg.mm.aaaa)` (periodo + scadenza calcolata);
  - data secca (`gg.mm.aaaa`).
- **DISTRIBUZIONE A REPARTO** — uno o più reparti (es. `CND PT`, `Aggiustaggio`, `Cleanliness
  Check`, oppure due insieme `Aggiustaggio CND PT`).

### Casi limite (tutti presenti nel documento)
1. **Doppia scadenza**: scadenza a livello processo (colonna SCADENZE) **+** scadenza
   individuale per-persona sulla certificazione nominale — **due date distinte e coesistenti**.
2. **Ruoli multipli** per persona: Qualificato/Addetto/Controllore/Part145 come booleani indipendenti.
3. **Dismissione tracciata**: riga *"Non più rinnovato: NON Processo Speciale (mail ... del gg.mm.aa)"*
   → stato **dismesso/non-rinnovato** con **motivo + riferimento** (una mail datata).
4. **"Illimitata a meno di revoca o sospensione"**: validità illimitata, stato pilotato da eventi
   *revoca/sospensione*.
5. **Personale organizzativo vs nominale** (righe con/senza persone).
6. **Multi-cliente su un processo** e **stessa capability con più approvazioni cliente** (la stessa
   ispezione PT compare più volte, con clienti/scadenze/personale diversi).
7. **Multi-reparto** nella distribuzione.
8. **Livello sul processo** (LVL2/LVL3 = livelli CND/NDT tipo EN 4179/NAS 410).

---

## 2) Regole imposte da MT CN 06 Rev.21 (cosa il modulo deve rispettare)

- **Correzione a un'interpretazione iniziale**: il MOD.128 **non è un motore di autorizzazione
  alla firma**. I timbri (fisici, apposti sugli OP) e la Skill Matrix restano la fonte
  dell'autorizzazione alla firma. Il MOD.128 è il **registro di identificazione del personale
  qualificato per (cliente, processo speciale)** con i documenti applicabili e le scadenze.
- **Chi gestisce**: la funzione **Qualità (MSM/MSO/MSA)** garantisce la coerenza tra MOD.187 (SKM),
  MOD.040, **MOD.128** e MOD.130 e la reperibilità delle evidenze (MT CN 06 §7.2, pag. 9).
- **§8.2.1**: per i **processi qualificati e speciali i requisiti minimi sono definiti nel MOD.128**
  (poi recepiti dalla Skill Matrix).
- **§11.2**: autorizzazioni/qualifiche sui processi qualificati/speciali **disciplinate dal MOD.128**;
  *"la Skill Matrix recepisce l'esito di tali qualifiche ai fini dell'autorizzazione operativa"*.
- **§11.4**: requisiti **cliente-specifici** gestiti nel MOD.128 = *"riferimento operativo per
  l'identificazione del personale abilitato, i documenti formativi applicabili e le relative
  scadenze"*; **aggiornato ad ogni variazione di requisiti cliente/qualifiche/documenti senza
  revisione della MT** → è un **registro vivo, versionato** (oggi Rev.16).
- **§10.3** (rilevante per l'integrazione timbri): il timbro è **ritirato o sospeso** da MSM nei
  casi cessazione/cambio ruolo/**revoca o sospensione dell'autorizzazione**/smarrimento/uso
  improprio; la sospensione richiede **data inizio + data rientro (o condizioni)** per essere
  tracciabile e dimostrabile.
- **Cosa deve restare dimostrabile (EN 9100)**: personale abilitato per (cliente, processo, ruolo),
  documenti/certificati applicabili, scadenze (processo + individuali), **storicità** dei cambiamenti
  (ingressi/dismissioni/revoche con motivo e riferimento), e **versione** del modulo.

---

## 3) Esito verifica assunti 1–7 (con file:riga)

| # | Assunto | Esito | Evidenza |
|---|---------|-------|----------|
| 1 | File additivi importati in `models.py`; `models_mpq.py` seguirebbe il pattern | ✅ | `anagrafica/models.py:2264-2271` (`from .models_rischi/_formazione/_skillmatrix import *`); convenzioni in `models_skillmatrix.py:1-16`. |
| 2 | Dipendente via `legacy_anagrafica_id` (IntegerField, no FK) risolto con `fetch_anagrafica_rows` | ✅ | Dichiarato in `models_skillmatrix.py:8`; `DipendenteQualifica.legacy_anagrafica_id` `models.py:524`; `fetch_anagrafica_rows` in **`core.legacy_anagrafica`** (usi: `import_retribuzioni.py:149`, `services/attestato_pdf.py:87-102`). |
| 3 | `Reparto` è il modello per "DISTRIBUZIONE A REPARTO" | ✅ (con caveat) | `Reparto` `models.py:751` (`nome` unique, `area_aziendale` FK). **Caveat**: il legame persona→reparto è **per stringa** (`DipendenteAnagraficaAziendale.area`), non FK. Per MOD.128 il legame è **processo→reparto** = M2M nuova, pulita. |
| 4 | Non esiste un modello Cliente riusabile | ✅ | In `gestione_specifiche/models.py` il cliente è **stringa** (`cliente = CharField` `:43`); l'unica entità è `ClienteCartellaShare` `:607` (mappa stringa→cartella, `:615`). → serve **anagrafica cliente/ente propria**. |
| 5 | `DipendenteQualifica`/`TipoQualifica` coprono la "qualifica individuale con scadenza"; MOD.128 le collega via **FK opzionale** | ✅ | `DipendenteQualifica` `models.py:522` ha `numero/livello/ente` (`:558-566`), `data_scadenza` (`:529`), `documento` privato (`:571`), `verificata` (`:579`), storico append-only `DipendenteQualificaStorico` `:674`. **Ma** è per **(persona, tipo)**, senza cliente/ruolo/2ª-scadenza. |
| 6 | Subnav seminata come 0064/0072 (`SubnavLinkAnagrafica`, gruppo Qualifiche sotto Competenze) | ✅ | `migrations/0064_subnav_qualifiche.py` (categoria "Qualifiche") e `0072_subnav_skill_matrix.py` (`CATEGORIA="Competenze"`, `GRUPPO="Skill Matrix"`, `SubnavLinkAnagrafica` con `gruppo/categoria/ordine`). → MOD.128 = `CATEGORIA="Competenze"`, `GRUPPO="Qualifiche"`. |
| 7 | ACL: permessi canonici + `RoutePermissionBinding` come Skill Matrix | ✅ | `anagrafica/acl_bootstrap.py:24-96` (`PermissionDefinition` + `RoutePermissionBinding` + `RolePermissionGrant`, cache-key versionata `:14`). **Vincolo critico**: nuove **route API** anche in `core/middleware.py` `API_ACL_GATE_PATHS` (`:17-29`), o strict-mode le nega ai non-superuser. |

**Correzione all'assunto 3**: `Reparto` esiste ma non lo si riusa per il legame persona→reparto
(che è per stringa); per MOD.128 si crea una relazione nuova **processo→reparto** (M2M).

---

## 4) Sovrapposizioni / riuso — cosa c'è già e cosa manca

**Riuso diretto (esiste, si aggancia via FK opzionale):**
- `DipendenteQualifica` + `TipoQualifica` + `DipendenteQualificaStorico`: **certificazione
  individuale** (numero/livello/ente/scadenza/documento/verifica/storico). Aggancio dalla
  certificazione MOD.128.
- `QualificaSessione` (`models.py:611`, `scadenza_effettiva` `:653`): pattern **scadenza
  collettiva/aziendale** con auto-calcolo da `durata_mesi` → riusare per la scadenza processo.
- `Reparto` (`:751`): DISTRIBUZIONE A REPARTO (nuova M2M processo→reparto).
- `services/conformita.py` (`stato_conformita_batch` `:362`, `_idoneita_batch` `:256`): semaforo
  idoneità/conformità → estendere per far pesare le abilitazioni MOD.128.
- `matrice_competenze` (`views.py:13089`) e scadenzari (`scadenzario` `:6825`,
  `qualifiche_scadenzario` `:5960`): pattern UI da affiancare.
- `import_asr` (`management/commands/import_asr.py`): blueprint import idempotente (per futuri import massivi).
- **Skill Matrix** (`models_skillmatrix.py`): il "processo" esiste già come abilitazione macchina
  I/L/U/O + `ProcessoCriticoContinuita`/`ContinuitaOperativa` (`:367`,`:403`, con stato `SOSPESA`
  `:199` e vincolo `skm_uniq_continuita_persona_processo` `:434`). **Grana diversa** dal processo
  speciale cliente-approvato: modelli separati + bridge opzionale (F6). **Il pattern
  "continuità persa → abilitazione sospesa" è il precedente da imitare** per la propagazione timbri.

**Serve nuovo (manca):**
- Anagrafica **cliente/ente qualificante** (+ enti esterni + certificatore) — assente.
- **Processo qualificato/speciale** (nome + codici + livello + regime + reparto + scadenza + stato/dismissione + versione) — assente.
- **Abilitazione persona×processo** con ruoli Qualificato/Addetto/Controllore/Part145 — assente.
- **Certificazione individuale** (schema+numero+scadenza, ≥1 per persona/processo) — assente come entità dedicata.
- **Storico append-only del MOD.128** — assente.
- Nel modulo **timbri**: stato **SOSPESO** e **FK all'abilitazione** — assenti (vedi §6).

---

## 5) Modello dati proposto (tutto in `models_mpq.py`; FK opzionali verso l'esistente)

> SQL-Server-safe come `models_skillmatrix.py:7-12`: niente indici parziali, niente
> `UniqueConstraint` con `condition`, niente `unique` nullable. Solo tabelle nuove →
> migration additiva a basso rischio; nessuna modifica ai modelli Qualifiche esistenti.

1. **`ClienteQualificante`** — `nome` (unique), `tipo` ∈ {**CLIENTE, ENTE_ACCREDITAMENTO,
   ENTE_ESTERNO, ORGANISMO_CERTIFICAZIONE**}, `codice`, `is_active`, `note`.
   **Enti esterni + certificatore** (requisito): self-FK opzionale `certificatore`
   (→`ClienteQualificante`) = l'organismo che certifica/accredita quell'ente o schema.
2. **`ProcessoQualificato`** — `nome`; `cliente` FK→ClienteQualificante; `clienti_addizionali`
   **M2M** opzionale→ClienteQualificante (solo per il raro riconoscimento condiviso multi-cliente);
   `ente_certificatore` FK opzionale→ClienteQualificante; `livello` (opz.); `regime`
   {PART145, NADCAP, CLIENTE_SPECIFICO, SPECIALE}; `reparti` **M2M**→Reparto; **scadenza processo**:
   `tipo_validita` {ILLIMITATA, PERIODO, DATA} + `durata_mesi` (null) + `data_scadenza` (null),
   con auto-calcolo tipo `QualificaSessione.scadenza_effettiva`; `stato` {ATTIVO, SOSPESO, REVOCATO,
   DISMESSO, NON_RINNOVATO} + `motivo_stato` + `riferimento_stato`; `tipo_qualifica` FK opzionale
   →TipoQualifica; `personale_modalita` {NOMINALE, ORGANIZZATIVO} + `riferimento_dichiarazione`;
   **versione modulo**: `numero_revisione`, `responsabile_qualita`, `data_revisione` (registro vivo,
   §7.2/§11.4 — **non** il workflow firma RDD pesante del MOD.187 §8.5, che resta fuori scope).
3. **`RiferimentoProcesso`** (figlio) — `processo` FK, `codice`, `tipo` {approvazione, specifica,
   certificato, dichiarazione} — per i **codici multipli** per processo.
4. **`AbilitazioneProcesso`** (riga persona) — `legacy_anagrafica_id` (IntegerField, no FK);
   `processo` FK; **flag ruoli** `is_qualificato`/`is_addetto`/`is_controllore`/`is_part145`;
   `stato` {ATTIVA, SOSPESA, REVOCATA, DISMESSA} + `data_ingresso` + `data_dismissione` + `motivo`;
   **`dipendente_qualifica` FK opzionale**→DipendenteQualifica. Vincolo:
   **`unique_together = (legacy_anagrafica_id, processo)`** (plain, SQL-Server-safe).
5. **`CertificazioneIndividuale`** (figlio di AbilitazioneProcesso) — `abilitazione` FK; `schema`
   (es. "ITA", "ASNT"); `numero`; `livello`; `data_scadenza` (**scadenza individuale**);
   `ente_certificatore` FK opzionale→ClienteQualificante; `dipendente_qualifica` FK opzionale
   →DipendenteQualifica; `documento` (storage privato); `stato`. Modella il caso "una persona → più
   cert con scadenze diverse".
6. **`MpqStorico`** (append-only) — snapshot dei cambi su processo/abilitazione con `origine`,
   `registrato_da`, `registrato_il` (auto_now_add), come `DipendenteQualificaStorico`.

**Doppia scadenza** → risolta: aziendale su `ProcessoQualificato.data_scadenza`; individuale su
`CertificazioneIndividuale.data_scadenza` (e/o `DipendenteQualifica` linkata).

---

## 6) REQUISITO — Integrazione bidirezionale con il modulo `timbri`

Ispezione fatta su `timbri/models.py`. Stato attuale di `RegistroTimbro` (`:87`):
`qualifica = CharField(200)` testo libero (`:111`); `data_consegna`/`data_ritiro` (`:113-114`);
`is_attivo`/`is_archived` (`:117-118`); `stato_label` conosce solo **Archiviato / Attivo / Superato**
(`:156-161`). **Non esiste lo stato SOSPESO** né alcun aggancio strutturato a qualifica/processo.

**Interventi (minimi, in `timbri/models.py`):**
1. **Aggancio timbro → abilitazione**: nuova **FK opzionale** `RegistroTimbro.abilitazione_processo`
   →`AbilitazioneProcesso` (null/blank). Il campo `qualifica` (testo) resta per i timbri storici
   importati. La FK vive **sul timbro** (è il timbro che punta all'abilitazione che lo giustifica);
   selettore da aggiungere nella form/view di creazione/assegnazione timbro.
   **Decisione confermata**: il legame va ad **`AbilitazioneProcesso` (persona×processo)**, non a
   `ProcessoQualificato` — è *quella persona su quel processo* a essere abilitata e a poter decadere.
   *Caveat*: per i processi `ORGANIZZATIVO` (senza righe-persona) non esiste una AbilitazioneProcesso;
   in quei casi la FK resta nulla (il timbro non è giustificato da una riga MOD.128 nominale).
2. **Stato SOSPESO in timbri**: aggiungere stato **SOSPESO** + campi `sospeso_dal` / `sospeso_al` /
   `sospeso_motivo` / `sospeso_riferimento` (rif. all'abilitazione che l'ha causato), ed estendere
   `stato_label`. Richiesto da MT CN 06 §10.3 (data inizio + data rientro/condizioni).
3. **Propagazione (sospensione E segnalazione, entrambe)**: un service in `anagrafica` — quando una
   `AbilitazioneProcesso` (o la sua `CertificazioneIndividuale`) passa a SCADUTA/REVOCATA/SOSPESA —
   deve **(a)** mettere in **SOSPESO** il timbro collegato (con motivo+riferimento) **e**
   **(b)** notificare **MSM/Qualità**. Non alternative. Doppia sorgente del "sospeso": lato
   qualifica (qui) **e** lato timbri (cessazione/smarrimento/ritiro §10.3), stato visibile da
   entrambi i lati. Pattern di riferimento: `skillmatrix` continuità (`ContinuitaOperativa` che
   sospende l'abilitazione macchina).
4. **Promemoria scadenza**: **non reimplementare**. Riusare/estendere l'infrastruttura esistente
   `automazioni` — `report_scadenze_settimanale` (management command +
   `tasks.py:43 run_report_scadenze_settimanale` + `schedules.py` + `scadenze_config.py`, pacchetto
   `au12`). Includere: scadenze processo, scadenze certificazione individuale, timbri collegati in
   scadenza. Se `au12` non copre questi tipi, **estenderlo**, non duplicarlo.

---

## 7) Punti d'integrazione
- **Scheda dipendente**: sezione "Processi qualificati" (cliente, processo, ruoli, scadenze processo+individuale, timbro collegato).
- **Cruscotto qualifiche**: card/tab MOD.128.
- **Scadenzario unificato**: scadenze processo + certificazione individuale + timbri collegati.
- **Conformità/idoneità** (`conformita.py`): abilitazioni-processo richieste dalla mansione nel semaforo.
- **Timbri**: vedi §6 (FK + stato SOSPESO + propagazione + report).
- **Skill Matrix** (§11.2): bridge opzionale `CompetenzaSkm`↔`ProcessoQualificato` — **F6, placeholder logico**.
- **Export "vista MOD.128"**: **sia** replica fedele della tabella Word/PDF per cliente **sia** vista nativa portale (deliverable d'audit).

---

## 8) Impatti / rischi / cosa NON toccare
- **NON toccare** i modelli Qualifiche/Formazione/SkillMatrix esistenti (solo FK opzionali dai
  modelli nuovi) → retrocompat con `import_asr` e con lo storico ASR garantita.
- **timbri**: le aggiunte sono additive (FK nullable + stato nuovo + campi sospensione); non
  cambiare la semantica di `is_attivo`/`is_archived` esistente.
- **PII reale nel PDF**: mai in seed/fixture/commit **né** in doc di analisi/spec. Solo dati fittizi.
  Documenti evidenza fuori webroot (storage privato, come `DipendenteQualifica.documento`).
- **ACL strict-mode**: nuove route in `acl_bootstrap` **e** route API in `core/middleware.py`
  `API_ACL_GATE_PATHS`, altrimenti 403 ai non-superuser (i test con superuser non lo scoprono).
- **Branch**: lavorare su `feature/skill-matrix-mod187` (prod), non `main`.

---

## 9) Piano a fasi (ognuna rilasciabile)
- **F0** — questo documento (spec + decisioni). ✅
- **F1** — `models_mpq.py` (ClienteQualificante, ProcessoQualificato, RiferimentoProcesso,
  AbilitazioneProcesso, CertificazioneIndividuale, MpqStorico) + migration additiva + admin +
  **test TDD**. Model-only, rilasciabile.
- **F2** — UI cruscotto MOD.128 + dettaglio processo + link subnav (Competenze → Qualifiche).
- **F3** — Export "vista MOD.128" (replica tabella per cliente **e** vista nativa).
- **F4** — ACL: `PERM_MPQ_VIEW/MANAGE` + `RoutePermissionBinding` + `API_ACL_GATE_PATHS` + gate view.
- **F5** — Integrazione **timbri** (FK + stato SOSPESO + service propagazione + estensione report
  scadenze `au12`) + agganci scheda dipendente + scadenzario + conformità.
- **F6** — Bridge **Skill Matrix** §11.2 (placeholder logico; recupero `skill CN ....xlsx` se serve).
  *Vicino di casa, fuori scope:* atto di approvazione RDD della Skill Matrix (MT CN 06 §8.5).

---

## 10) BLOCCO DECISIONI (confermate dall'utente 2026-07-06)

- **Correzione**: il MOD.128 **non** è motore di autorizzazione alla firma (i timbri sono fisici,
  apposti sugli OP). Nessun modello in quella direzione. (Recepito in §2.)
- **D1 (multi-cliente)**: grana riga = **(cliente, processo)**. `ClienteQualificante.tipo`
  {CLIENTE, ENTE_ACCREDITAMENTO, …} per NADCAP. **M2M cliente solo** per il raro riconoscimento condiviso.
- **D2 (organizzativo vs nominale)**: `personale_modalita=ORGANIZZATIVO` + riferimento dichiarazione,
  senza righe-persona.
- **D3 (cert individuale)**: **child table dedicato `CertificazioneIndividuale`** (schema+numero+
  scadenza propri; caso doppio schema stessa persona) con FK opzionale a `DipendenteQualifica`.
- **D4**: ruoli **booleani** (Qualificato/Addetto/Controllore/Part145) + nota.
- **D5**: scadenza **ILLIMITATA pilotata dallo stato** (revoca/sospensione).
- **D6 (revisione/approvazione)**: **NON rimandare**. Tracciare già in F1 `numero_revisione` +
  `responsabile_qualita` + `data_revisione` sul modulo (registro vivo §7.2/§11.4). **Non** il
  workflow firma RDD del MOD.187 §8.5 (fuori scope).
- **D7 (export)**: **sia** replica-Word **sia** vista nativa.
- **D8 (auto-calcolo scadenza)**: sì, riusando il pattern `QualificaSessione.scadenza_effettiva`.
- **D9 (skill xlsx)**: bridge SKM come **placeholder logico** (F6); file non recuperato ora.
- **Requisito NUOVO — enti esterni + certificatore**: `ClienteQualificante` prevede
  `tipo=ENTE_ESTERNO`/`ORGANISMO_CERTIFICAZIONE` e un `certificatore` (self-FK); il processo e la
  certificazione individuale possono riferire un `ente_certificatore`. (Recepito in §5.)
- **Requisito NUOVO — integrazione timbri**: vedi §6 (FK abilitazione, stato SOSPESO, propagazione
  bidirezionale sospensione+segnalazione, report scadenze via `au12`). Legame timbro →
  **AbilitazioneProcesso** confermato.

---

## 11) Conferme/decisioni residue per l'avvio di F1
Nessun blocco aperto sui modelli. Da confermare solo in corso d'opera:
- etichetta esatta della voce subnav (es. *"Mansionario Processi (MOD.128)"*) nel gruppo Qualifiche;
- se il `regime` del processo va derivato dal cliente o tenuto esplicito (proposta: esplicito);
- granularità del service di propagazione (sincrono alla transizione di stato vs job `au12`).
