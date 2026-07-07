# FATTIBILITÀ — Modulo "Gestione Strumenti di Misura" (measurement instrument management)

**Data:** 2026-07-05
**Stato:** analisi di fattibilità — il modulo **NON esiste** nel portale; nessun codice scritto, nessun file di progetto modificato.
**Contesto dichiarato (da verificare):** procedura MT CN 68 Rev.7 · sistema legacy Codhex · FSM a 8 stati · ISO/IEC 17025:2017 · distinzione report accreditato/interno · generazione certificati di taratura.
**Metodo:** ricognizione read-only del repo + fattibilità per area sul pattern dei moduli esistenti (gestione_specifiche, skill matrix MOD.187, assets, attrezzature).

---

## 1. Ricognizione — cosa esiste già vs cosa è tutto da fare

### 1.1 Cosa NON è stato trovato (esplicito)

| Voce | Esito ricerca |
| ---- | ------------- |
| **"Codhex"** | **0 occorrenze** in tutto il repo (docs/, doc/, tools/, app Django, CHANGELOG root e django_app). Nel repo **non esiste alcuna informazione tecnica sul sistema legacy**: né formato dati, né DB, né export, né screenshot. Tutto ciò che riguarda Codhex va scoperto fuori dal repo — questa analisi **non inventa** specifiche del legacy. |
| **"ISO/IEC 17025" / "17025"** | 0 occorrenze. |
| **FSM strumenti (8 stati)** | Nessuna bozza trovata: né ADR, né spec, né modello. La FSM proposta al §2.b è una **proposta nuova** da validare contro MT CN 68. |
| **MT CN 68 (testo)** | Il documento **non è nel repo**. È però nel **corpus RAG SGI** sulla share aziendale: l'assistente AI lo ha già citato in una risposta reale («MT CN 68 §8.3», [django_app/CHANGELOG.md:79](django_app/CHANGELOG.md#L79)). La revisione citata dall'utente (Rev.7) non è verificabile da qui. |
| App/spec dedicata | Nessuna app `strumenti`/`metrologia`/`tarature`; nessun file in docs/specs/ sul tema. |

### 1.2 Cosa esiste già (footprint riusabile)

1. **`assets` ha già l'ossatura "taratura come manutenzione"** — il punto di partenza naturale:
   - `WorkOrder` con `KIND_CALIBRATION = "Taratura"` ([assets/models.py:1786](django_app/assets/models.py#L1786)) — ordini di lavoro di taratura già oggi registrabili, con costi, fornitore, durata;
   - `PeriodicVerification` ([assets/models.py:1320](django_app/assets/models.py#L1320)): frequenza in mesi, `last/next_verification_date`, M2M su asset, fornitore — il "richiamo periodico" esiste già come meccanica generica;
   - `AssetEvent` con `KIND_PERIODIC_VERIFICATION` ([assets/models.py:2289](django_app/assets/models.py#L2289)) per la timeline per-asset;
   - `AssetDocument` (categorie SPECIFICHE/INTERVENTI/MANUALI, [assets/models.py:1467](django_app/assets/models.py#L1467)) per allegati per-asset — con il caveat IDOR già segnalato (F4 di ANALISI_01: download senza controllo per-oggetto);
   - storage privato **cifrato** già in uso nel modulo (`PrivateAssetAdministrativeDeadlineStorage`, [assets/models.py:837](django_app/assets/models.py#L837)).
   - **Limiti attuali:** `Asset.asset_type` non ha un tipo "strumento di misura" ([assets/models.py:33-47](django_app/assets/models.py#L33-L47): PC/CNC/WORK_MACHINE/…/OTHER — gli strumenti reali oggi finiscono in OTHER, es. «FORNO EUROTHERM MISURATORE» in [docs/skill-matrix/Risultati.csv:127](docs/skill-matrix/Risultati.csv#L127)); `Asset.status` è un CharField a 4 stati generici, **non** una FSM.
2. **La skill matrix sa già chi è qualificato a tarare**: «Taratura strumenti» è una competenza di tipo *processo* nel catalogo MOD.187 ([docs/anagrafica/skillmatrix/skm_catalogo_competenze.csv:80](docs/anagrafica/skillmatrix/skm_catalogo_competenze.csv#L80)) con livelli I/L/U/O assegnati a ~7 persone (skm_matrice_livelli.csv). Il vincolo "solo personale qualificato esegue/firma tarature interne" è **interrogabile via resolver** già oggi (`anagrafica/services/skillmatrix_resolver.py`, read-only, pensato apposta per altri moduli). *Nota a margine: quei CSV committati contengono nomi reali — ricadono nella nota di progetto "seed con nomi reali da non committare".*
3. **FSM tooling e pattern consolidati**: `django-fsm-2==4.2.4` già in requirements ([django_app/requirements.txt:19](django_app/requirements.txt#L19)); gestione_specifiche è il riferimento completo (FSMField `protected`, audit centralizzato `post_transition` con esattamente-un-evento, `GET_STATE`, slot separati pre-sospensione/pre-errore). Le lezioni di ANALISI_02 (F1: concorrenza; F2: atomicità side-effect; F3: guardie di stato sulle superfici collegate) vanno incorporate **dal giorno 1**.
4. **Generazione PDF già in casa**: reportlab + PyMuPDF (fitz) usati da gestione_specifiche per export storico, composito MOD.133 con overlay timbri e **protezione owner-password** (`pdf_compose.py`, `composito.py`, `timbri_overlay.py`) — la toolchain per certificati PDF con timbro/firma immagine e protezione esiste.
5. **Pattern import legacy con preview**: `attrezzature` ha `ImportBatch`/`ImportRow` con stato PREVIEW→IMPORTED, hash riga, payload originale JSON ([attrezzature/models.py:365-410](django_app/attrezzature/models.py#L365)); gestione_specifiche ha `import_storico` + intake CSV con dry-run; la skill matrix ha l'import gated dalla conferma match asset (F2a). Tre precedenti riusabili per l'import da Codhex.
6. **Pattern trasversali pronti**: bootstrap ACL canonico per-modulo (visto identico in 3 moduli), gate API nel middleware (`API_ACL_GATE_PATHS` — ogni nuova API va mappata), audit append-only immutabile (`EventoSpecifica` come modello), convenzione `legacy_anagrafica_id` senza FK per le persone, schedulazione django-q2 CRON, convenzione di pianificazione modulo `docs/specs/<modulo>/BUILD_SPEC.md + BUILD_LOG.md` (gestione_specifiche e skill matrix la usano).
7. **Roadmap AI** già prevede le tarature come dato di scadenza: «Scadenze a rischio (DPI, visite, **tarature**, verifiche periodiche) nel brief» ([docs/ai/14_AI_EXPANSION_ROADMAP.md:72](docs/ai/14_AI_EXPANSION_ROADMAP.md#L72)) — il modulo avrebbe un consumatore AI naturale.

**Conclusione ricognizione:** il modulo è tutto da fare, ma il portale offre più mattoni riusabili del previsto; l'unico buco informativo totale è **Codhex** e il testo di **MT CN 68 Rev.7** (recuperabile dalla share SGI, non dal repo).

---

## 2. Analisi di fattibilità tecnica

### 2.a Modellazione dati

**Approccio raccomandato: il pattern skill matrix / carichi macchina** — nuova app `gestione_strumenti` (o strato in `assets`) che **si appoggia a `assets.Asset` senza duplicarlo**, come `Macchina` (OneToOne su Asset, [gestione_carichi_macchina/models.py:60](django_app/gestione_carichi_macchina/models.py#L60)) e `CompetenzaSkm.asset` (FK nullable con gate di conferma match):

- **`StrumentoMisura`** — OneToOne su `assets.Asset` (`on_delete=PROTECT`, come Macchina): identità (tag, nome, ubicazione) resta sull'asset; qui solo gli attributi metrologici: grandezza misurata, campo di misura, risoluzione, classe/tolleranza, criticità (accettazione prodotto sì/no), periodicità di taratura, laboratorio abituale (interno/esterno), `stato` FSM (§2.b).
- **`Taratura`** (evento) — FK a StrumentoMisura: data esecuzione, esecutore (interno via `legacy_anagrafica_id` **senza FK**, convenzione skill matrix, oppure fornitore/laboratorio esterno), esito (conforme / non conforme / conforme con aggiustamento / declassato), riferimento certificato, scadenza risultante, condizioni ambientali, campioni usati (vedi sotto).
- **`CertificatoTaratura`** (documento) — FK a Taratura: numero univoco, tipo (accreditato esterno / rapporto interno), emittente, file su **storage privato cifrato** (pattern `PrivateAnagraficaStorage`/`PrivateAssetAdministrativeDeadlineStorage`, mai webroot), metadati 17025 (§2.c), flag validazione.
- **`CampioneRiferimento`** — per la **catena di riferibilità**: i campioni aziendali (blocchetti, anelli, masse) sono a loro volta strumenti con certificato accreditato e scadenza; una taratura interna referenzia i campioni usati (M2M) → la catena "strumento ← campione ← certificato LAT/SI" diventa **navigabile e dimostrabile**, che è il cuore della riferibilità metrologica ISO 17025 §6.5. Un campione scaduto deve invalidare/allertare le tarature che lo userebbero.
- **Storico/audit**: evento immutabile per transizione FSM (pattern `EventoSpecifica`) + storico append-only per le tarature (pattern `AbilitazioneMacchinaStorico`).
- **Scadenze**: riusare la meccanica `PeriodicVerification`/reminder esistente **oppure** un timer dedicato stile MOD.133 (`data_scadenza_taratura` + job django-q2 CRON giornaliero con preavviso configurabile, come `preavviso_refresh_giorni` della skill matrix). Config singleton stile `SkillMatrixConfig` per periodicità di default, preavvisi, regola decisionale.

**Vincoli di progetto da rispettare** (già codificati nei moduli fratelli): compatibilità SQL Server (no indici parziali, no unique con condition, no unique nullable); persone via `legacy_anagrafica_id`; ogni rotta bound nel bootstrap ACL; API nel gate middleware; documenti fuori webroot.

**Attenzione (bloccante di coordinamento):** è **in corso in un'altra sessione il refactor di fusione `asset_category` + `asset_type`** (nota di progetto). Il nuovo modulo non deve introdurre dipendenze dalla classificazione asset attuale (es. un nuovo `TYPE_STRUMENTO`) finché quel refactor non è chiuso: meglio agganciarsi via OneToOne + catalogo proprio (come ha fatto la skill matrix con `CompetenzaSkm` + conferma match, proprio per lo stesso motivo).

**Fattibilità: ALTA** — nessun ostacolo tecnico; il pattern è replicato tre volte nel repo.

### 2.b FSM a 8 stati — bozza proposta (da validare contro MT CN 68 Rev.7)

Nessuna bozza esiste nel repo: questa è una proposta costruita sul ciclo di vita tipico di uno strumento di misura e sulla grammatica FSM già in uso (django-fsm-2, stati S1–S9 di gestione_specifiche). **Va fatta collimare con gli stati reali della procedura MT CN 68 prima di scrivere codice.**

| # | Stato | Significato |
| --- | ----- | ----------- |
| S1 | `censito` | Inserito a sistema (nuovo o migrato da Codhex), non ancora qualificato all'uso |
| S2 | `in_servizio` | Tarato, conforme, entro scadenza — **unico stato in cui l'uso è ammesso** |
| S3 | `in_taratura` | Consegnato al laboratorio (interno o esterno) — timer attivo |
| S4 | `in_valutazione` | Rientrato: esito/certificato in verifica (conferma metrologica) |
| S5 | `non_conforme` | Taratura fallita → analisi impatto sulle misure già accettate (NC/recall) |
| S6 | `sospeso` | Uso vietato temporaneo: scadenza superata, urto/danno, smarrimento — reversibile |
| S7 | `fuori_servizio` | Declassato (solo indicazione) o ritirato dall'uso metrologico — non usato per accettazione prodotto |
| S8 | `dismesso` | Rottamato/alienato — terminale |

Transizioni principali: S1→S3 (prima taratura) · S3→S4 (rientro con esito) · S4→S2 (conforme) · S4→S5 (non conforme) · S2→S3 (richiamo periodico) · S2→S6 (scadenza/danno; candidata ad automatismo, vedi rischi) · S5→S3 (dopo aggiustamento/riparazione) · S5→S7 (declassamento) · S6→S3 / S6→S2 (rientro dal sospeso, con memoria dello stato precedente — pattern `stato_precedente` di gestione_specifiche) · S7→S3 (riqualifica) · S7→S8 e S5→S8 (dismissione).

Guardie tipiche (equivalenti delle guardie MOD.133): S4→S2 richiede certificato registrato + esito conforme + (per tarature interne) esecutore con livello adeguato su «Taratura strumenti» nella skill matrix; S4→S5 richiede motivo; S2→S6 automatica alla scadenza è una **decisione di processo**, non tecnica (§3).

Implementazione: `FSMField(protected=True)` + audit centralizzato `post_transition` (riuso quasi letterale di `state_machine.py` di gestione_specifiche), **con le correzioni di ANALISI_02 incorporate da subito**: `ConcurrentTransitionMixin` (F1), transizione+save sempre in `transaction.atomic` (F2), guardie di stato su ogni superficie che modifica dati collegati al documento ufficiale (F3).

**Fattibilità: ALTA** — è il terzo giro dello stesso pattern; il rischio è di dominio (stati sbagliati rispetto alla procedura), non tecnico.

### 2.c Generazione certificati — requisiti (non codice)

Distinzione preliminare fondamentale (da confermare, §3): un **certificato di taratura "ISO/IEC 17025"** in senso proprio può emetterlo solo un laboratorio **accreditato** (in Italia: ACCREDIA-LAT) e **solo dentro il proprio scope di accreditamento**. Se il laboratorio interno Novicrom non è accreditato, il modulo genera **rapporti di taratura interna / conferme metrologiche** (senza marchio di accreditamento) e **archivia** i certificati accreditati emessi dai fornitori esterni. Le due cose hanno requisiti diversi ed è per questo che la distinzione accreditato/interno attraversa dati, template e ACL (§2.e).

Contenuti minimi che il modello dati deve saper rappresentare per un report conforme a ISO/IEC 17025:2017 §7.8 (valgono come requisiti sia per generare l'interno sia per validare/archiviare l'esterno):

- identificazione univoca del certificato (numero + pagina n di N) e data di emissione — serve un **registro di numerazione** affidabile (lezione OFI/MOD.174: evitare il MAX+1 senza vincolo, F6 di ANALISI_02);
- identificazione del laboratorio e del cliente/richiedente;
- identificazione **inequivocabile** dello strumento (asset_tag/serial/modello) e suo stato al ricevimento;
- metodo/procedura di taratura usata (riferimento a MT CN 68 o istruzione operativa specifica);
- date di esecuzione; condizioni ambientali se influenti;
- **risultati con unità SI** e, punto qualificante, **incertezza estesa di misura** (tipicamente k=2, livello di fiducia ≈95%) — per le tarature interne va deciso da dove arriva il budget di incertezza (per famiglia di strumenti? per punto di misura?);
- **riferibilità metrologica**: dichiarazione della catena (campioni usati → loro certificati accreditati → SI) — è il motivo del modello `CampioneRiferimento` in §2.a;
- eventuale **dichiarazione di conformità** a specifica con **regola decisionale** esplicita (§7.8.6 — binaria semplice vs guard-banding: decisione di qualità, §3);
- chi **autorizza il rilascio** (firma): nome, funzione — collegabile alla skill matrix (livello O su «Taratura strumenti»?) e a un timbro/firma immagine (pattern `TimbroCapocommessa` già esistente);
- marchio di accreditamento **solo** su certificati emessi sotto scope accreditato.

Tecnicamente: template PDF via reportlab/fitz (toolchain in casa), protezione del PDF depositato (owner-password, pattern composito MOD.133), snapshot immutabile dei dati al momento dell'emissione (il certificato non deve cambiare se cambia l'anagrafica strumento — pattern "snapshot nel payload" di `EventoSpecifica`), numerazione transazionale con vincolo unique.

**Fattibilità: ALTA per il rapporto interno** (tutta la toolchain esiste); **la validità "17025" del certificato è una questione di accreditamento, non di software** — il software può al massimo rendere il contenuto conforme al §7.8.

### 2.d Integrazione/migrazione da Codhex

**Nel repo non c'è alcuna informazione su Codhex** (0 occorrenze): non è possibile valutare formati, DB, export o API senza una sessione di discovery fuori repo. Detto questo, le **opzioni realistiche** — tutte già praticate nel progetto per altri legacy — sono tre, in ordine di rischio crescente per il processo e decrescente per la durata della convivenza:

1. **Import one-shot dello storico + switch** (pattern: migrazione formazione/visite DEV→PROD via `legacy_anagrafica_id`; import storico gestione_specifiche con dry-run→apply): si esporta da Codhex (CSV/Excel/backup DB — da scoprire), si importa con pipeline a preview (pattern `ImportBatch`/`ImportRow` di attrezzature: hash riga, payload originale conservato, stati PREVIEW→IMPORTED), gate di riconciliazione strumento↔asset **con conferma umana** (pattern F2a skill matrix: mai baseline senza match confermato — molti strumenti probabilmente non sono ancora censiti in `assets`). Richiede un periodo di congelamento delle scritture su Codhex durante lo switch.
2. **Doppio binario transitorio** (pattern: doppio motore ACL legacy/canonico — che ANALISI_01 F10 documenta come debito oneroso): Codhex resta master per l'operatività, il portale importa periodicamente in sola lettura (scadenzario, KPI, brief AI) finché la copertura non è completa, poi inversione del master. È l'opzione più sicura per il processo ma **va dichiarata a termine** — il progetto ha già sperimentato quanto costa mantenere due fonti di verità.
3. **Dismissione immediata senza import** (solo anagrafica corrente + prossime scadenze, storico consultabile su Codhex archiviato): minimo effort, ma perde la storia delle tarature nel portale — probabilmente inaccettabile per audit qualità (la storia È il requisito).

Raccomandazione condizionata: **1 con una coda breve di 2** (import storico completo, un ciclo di tarature in doppio binario di verifica, poi switch). Ma la scelta dipende interamente da cosa emerge dalla discovery su Codhex (§3).

**Fattibilità: NON VALUTABILE nel merito** finché non si vede un export Codhex; la **meccanica** di import è a fattibilità alta (tre precedenti nel repo).

### 2.e Report accreditato vs interno — implicazioni

- **Dati**: `tipo_certificato` (accreditato_esterno / interno) come dimensione di primo livello su `CertificatoTaratura`; per gli esterni: ente emettitore, numero certificato del laboratorio, scope; per gli interni: esecutore, campioni usati, budget di incertezza, regola decisionale.
- **Template**: due template distinti (l'interno NON deve poter mostrare marchi di accreditamento — è un errore grave, non una svista grafica). L'esterno tipicamente non si genera: si **archivia** il PDF del fornitore (upload, storage cifrato, validazione).
- **ACL**: sul pattern canonico dei moduli fratelli: `strumenti.view` (elenco/scadenzario) · `strumenti.gestione` (anagrafica, invio in taratura, transizioni) · `strumenti.taratura_interna` (registrare esecuzioni — incrociabile con la qualifica skill matrix dell'esecutore) · `strumenti.certifica` (validare/emettere certificati: è la firma, va tenuta separata dalla gestione — stessa logica della segregazione compilatore≠approvatore del MOD.133) · `strumenti.admin` (config). Binding per rotta nel bootstrap + eventuale API nel gate middleware.
- **Firma/validazione**: distinguere *chi esegue* da *chi autorizza il rilascio* (17025 lo richiede): due ruoli, guardia FSM sull'emissione (pattern approvatore≠compilatore già rodato). La firma grafica può riusare il pattern timbri; una eventuale firma digitale qualificata (PAdES) è fuori dalla toolchain attuale e andrebbe valutata a parte.
- **Audit**: ogni emissione/validazione/annullamento = evento immutabile con snapshot (pattern `EventoSpecifica`). Un certificato emesso non si modifica: si **revoca e riemette** (nuovo numero, catena visibile) — parallelo esatto della catena revisioni di gestione_specifiche.

**Fattibilità: ALTA** — è ricombinazione di pattern esistenti.

### 2.f Stampa etichette di taratura (aggiunta 2026-07-06, richiesta utente)

Il portale ha **già un motore etichette per asset**: `AssetLabelTemplate` ([assets/models.py:1562](django_app/assets/models.py#L1562)) con template a tre scope (generale / per tipologia asset / per singolo asset) e posizionamento QR. Il classico **bollino di taratura** (matricola, data ultima taratura, prossima scadenza, esito, sigla firmatario) è un'estensione naturale: un template alimentato dai dati di `StrumentoMisura`/`Taratura` invece che dalla sola anagrafica asset, con QR che porta alla scheda strumento nel portale.

Regole di processo da definire col materiale reale (etichette attuali in Appendice B): ristampa automatica proposta a ogni taratura conforme (S4→S2); stampa **bloccata** (o etichetta "FUORI SERVIZIO") quando lo strumento non è in `in_servizio` — così l'etichetta non può contraddire lo stato FSM. Requisiti hardware da verificare: che stampante/etichettatrice si usa oggi (termica a rotolo tipo Zebra/Dymo vs fogli adesivi A4) e in che formato — determina se si genera PDF su misura (toolchain esistente) o serve un formato/driver dedicato.

**Fattibilità: ALTA, effort S** — il motore esiste, si aggiunge un template e la sorgente dati.

---

## 3. Rischi e domande aperte (decisioni per Brizio/qualità PRIMA del codice)

1. **Accreditamento — ✅ DECISO (2026-07-05, Brizio):** **rapporti interni + archivio dei certificati accreditati esterni.** Novicrom NON emette certificati sotto scope di accreditamento: l'ente taratore interno verifica e produce l'**attestato interno** (senza marchio di accreditamento); i certificati accreditati arrivano dai fornitori LAT e vengono archiviati/validati. Conseguenze: un solo template di generazione (attestato interno), upload+validazione per gli esterni, nessun requisito formale ACCREDIA sul documento generato; i contenuti §2.c restano la checklist di buona pratica per l'attestato interno (incertezza e riferibilità inclusi, se MT CN 68 li richiede).
2. **Chi firma:** l'azienda ha un **ente taratore interno che verifica e crea l'attestato** (confermato 2026-07-05). Da chiarire in che forma: (a) l'attestato porta **una firma sola** (chi tara firma anche) o due (esecutore + responsabile che approva)? (b) l'ente taratore è una persona, un gruppo o un ruolo — e coincide con le persone a livello U/O su «Taratura strumenti» nella skill matrix? (c) il portale deve **imporre** la segregazione esecutore≠firmatario (pattern MOD.133) o basta registrare chi ha firmato? Con la decisione §3.1 la doppia firma non è un obbligo normativo: è una scelta di processo (MT CN 68 potrebbe comunque richiederla).
3. **Perimetro strumenti:** quali classi rientrano (calibri/micrometri, blocchetti, termocoppie/forni — nel repo compaiono «FORNO EUROTHERM MISURATORE» — bilance, strumenti CMM)? Quanti sono in Codhex? Quanti sono già censiti in `assets` (probabilmente pochi, come OTHER)? Il censimento incrociato è il primo deliverable dell'import.
4. **MT CN 68 Rev.7:** il testo non è nel repo — va recuperato dalla share SGI e la FSM §2.b va **collimata sugli stati reali della procedura** (gli 8 stati proposti sono una bozza plausibile, non la procedura).
5. **Codhex discovery:** che cos'è tecnicamente (applicazione locale? DB su server? SaaS?), che export offre, chi lo usa oggi e con che frequenza, licenza/scadenza contratto? Senza queste risposte la stima dell'area d) resta a forchetta larga. → **Checklist operativa in Appendice A** (in raccolta risposte dal 2026-07-05).
6. **Automatismo di sospensione a scadenza:** lo strumento scaduto va in `sospeso` **automaticamente** (job django-q2) o serve conferma umana? Attenzione al precedente: la regola bloccante analoga della skill matrix (continuità) è rimasta **non schedulata** (F15 di ANALISI_02) — se si sceglie l'automatismo, lo schedule va registrato nello stesso commit della regola.
7. **Regola decisionale di conformità** (17025 §7.8.6): binaria semplice o guard-banding con l'incertezza? Va scritta nel certificato — decisione di qualità, non di sviluppo.
8. **Non conformità retroattiva:** strumento non conforme → cosa succede alle misure/accettazioni fatte dall'ultima taratura buona? Si integra con `anomalie`/NC esistenti o resta fuori scope del modulo?
9. **Coordinamento refactor asset:** la fusione `asset_category`+`asset_type` è in corso in un'altra sessione — serve un punto di sincronizzazione prima di decidere se lo "strumento di misura" diventa un tipo asset o resta solo profilo OneToOne.
10. **Incertezza di misura per tarature interne — ✅ RISPOSTO (2026-07-06):** budget di incertezza documentati **non esistono**. L'attestato interno v1 avrà quindi il campo incertezza **facoltativo/vuoto** (niente valori inventati); se in futuro la qualità produce budget per famiglia, il modello dati li accoglie senza migrazioni concettuali. Resta da verificare su MT CN 68 se la procedura richiede una dichiarazione alternativa (es. rapporto di tolleranza/TUR o semplice esito conforme/non conforme rispetto alla classe).
11. **Numerazione certificati:** serie unica aziendale o per laboratorio/anno? Chi assegna i numeri oggi (Codhex?) e come si evita il buco/duplicato nello switch?

---

## 4. Stima di effort (ordine di grandezza) e dipendenze

| Area | Effort | Note e dipendenze |
| ---- | ------ | ----------------- |
| **D0 — Decisioni preliminari + lettura MT CN 68 + discovery Codhex** | **S** (ma bloccante) | Nessun codice: 1 sessione con qualità + 1 discovery tecnica su Codhex. **Prerequisito di tutto.** |
| **a) Modellazione dati** | **M** | Dopo D0. OneToOne su Asset + catalogo + tarature + certificati + campioni + config + storico. Rischio solo sul coordinamento col refactor asset (§3.9). |
| **b) FSM 8 stati + UI scadenzario** | **M** | Dipende da (a) e dalla validazione stati su MT CN 68. Il pattern è il terzo riuso; includere da subito i fix di concorrenza/atomicità (ANALISI_02 F1/F2). S se la UI v1 è solo elenco+dettaglio+azioni; M con scadenzario/KPI. |
| **c) Certificati PDF (rapporto interno + archivio esterni)** | **M** | Dipende da (a); toolchain PDF esistente. Diventa **L** solo se si vuole firma digitale PAdES (nuova capability). Numerazione transazionale inclusa. |
| **d) Import/migrazione Codhex** | **L–XL** (forchetta larga finché manca la discovery) | Dipende da (a) e da D0. **L** se esiste un export tabellare pulito (pipeline preview+conferma match, tre precedenti nel repo); **XL** se serve reverse-engineering del DB o doppio binario lungo. È l'area con la varianza maggiore. |
| **e) Report accreditato/interno: ACL, template, firma** | **S–M** | Dipende da (a) e (c). Ricombinazione di pattern esistenti (bootstrap ACL, segregazione firmatario, storage cifrato, audit). |
| **f) Stampa etichette di taratura** (§2.f) | **S** | Dipende da (a) e (c). Motore etichette già in assets (`AssetLabelTemplate`); si aggiunge il template "bollino" con dati taratura/scadenza + QR. Da verificare solo l'hardware di stampa (Appendice B). |

**Sequenza consigliata:** D0 → a → b → c → e → d (l'import per ultimo, su modello dati stabilizzato; in parallelo a b/c si può però già fare il **censimento incrociato** Codhex↔assets, che è anche il modo più rapido di scoprire la qualità dei dati legacy).

**Ordine di grandezza complessivo del modulo: L** (paragonabile alla build Skill Matrix MOD.187, che ha lo stesso profilo: app additiva su assets+anagrafica, import legacy con gate di conferma, config singleton, ACL canonico) — **esclusa** la variabile Codhex, che da sola può oscillare tra L e XL.

**Verdetto di fattibilità: FATTIBILE** con rischio tecnico basso — tutti i mattoni (FSM, PDF, storage cifrato, ACL, import con preview, qualifiche del personale) esistono già nel portale ed è il terzo/quarto riuso degli stessi pattern. I rischi reali sono di **dominio e di processo**: accreditamento (§3.1), fedeltà alla procedura MT CN 68 (§3.4) e l'incognita Codhex (§3.5). Nessuna di queste tre si scioglie scrivendo codice.

---

## Appendice A — Checklist discovery Codhex (le risposte sbloccano l'area d)

1. **Natura**: applicazione desktop locale, client/server, web o SaaS? Chi è il fornitore/produttore?
2. **Dati**: dove vivono (file proprietario, Access, SQL Server, altro)? Su quale macchina/server? Il DB è accessibile direttamente?
3. **Export**: esistono export CSV/Excel o stampe/report? Si riesce a estrarre **tutto** (anagrafica strumenti + storico tarature + scadenze) o solo viste parziali?
4. **Volumi**: quanti strumenti attivi? Quante tarature storiche e da che anno parte lo storico?
5. **Identificativi**: che codice/matricola usa Codhex per gli strumenti? Esiste già una corrispondenza con gli `asset_tag` del portale o è una numerazione indipendente? (Determina il lavoro di riconciliazione strumento↔asset.)
6. **Attestati**: oggi gli attestati interni li genera Codhex? Con quale numerazione/serie? I PDF dei certificati esterni sono archiviati *dentro* Codhex o su file system/cartelle?
7. **Utilizzo**: chi lo usa oggi (l'ente taratore interno? altri?), per quali funzioni (scadenzario, attestati, etichette…) e con che frequenza?
8. **Contratto**: licenza/assistenza ancora attive? C'è una scadenza che detta i tempi della migrazione?
9. **Requisito storico**: nel portale serve **tutto** lo storico tarature (posizione consigliata per audit qualità) o basta ultima taratura + prossima scadenza per strumento?

---

## Appendice B — Materiale da raccogliere (consegna prevista 2026-07-06)

**Dove depositarlo:** in una cartella FUORI dal repo (es. `...\Documenti Portale Novicrom\strumenti_misura\` su OneDrive) — gli export Codhex e gli attestati contengono dati reali e NON vanno committati (stessa regola dei seed skill matrix).

**Documenti di processo (qualità):**

1. ⬜ **MT CN 68 Rev.7** (PDF) — serve per collimare la FSM a 8 stati e i campi dell'attestato.
2. ⬜ **Un attestato di taratura interna reale** (recente, compilato) — diventa la base del template di generazione.
3. ⬜ **Un certificato esterno accreditato** (esempio da fornitore LAT) — per definire i metadati da archiviare/validare.
4. ✅ ~~Eventuali **istruzioni operative collegate** a MT CN 68 (budget di incertezza per famiglia, metodi di taratura)~~ — **RISPOSTA (2026-07-06): non esistono.** Conseguenza: l'attestato interno v1 nasce **senza incertezza quantificata** (campo facoltativo, si compila solo se MT CN 68 la richiede in altra forma); il metodo si riferisce direttamente alla procedura.
5. ⬜ Eventuali **moduli/registri cartacei** citati da MT CN 68 (scheda strumento, registro strumenti).
6. ⬜ **Elenco campioni di riferimento aziendali** (blocchetti, anelli, masse…) con i rispettivi certificati, se esiste.

**Da Codhex:**

1. ⬜ **Export più completo possibile** (anagrafica strumenti + storico tarature + scadenze) in CSV/Excel; in mancanza, le stampe/report standard in PDF.
2. ⬜ **Screenshot delle schermate principali**: scheda strumento, scadenzario, maschera di registrazione taratura — per capire i campi senza reverse-engineering.
3. ⬜ **Dove sta**: percorso di installazione / tipo di file dati o DB (basta anche solo la cartella del programma).
4. ⬜ **Versione, fornitore, stato contratto/assistenza** (manuale o fattura vanno benissimo).
5. ⬜ Se genera gli attestati: **un attestato emesso da Codhex** con la sua numerazione.

**Etichette di taratura (aggiunta 2026-07-06, per l'area f):**

1. ⬜ **Foto/scansione delle etichette-bollino attuali** applicate sugli strumenti (fronte, con i campi leggibili).
2. ⬜ **Con cosa si stampano oggi**: etichettatrice termica a rotolo (marca/modello, es. Zebra/Dymo/Brother) o fogli adesivi A4? Dimensioni etichetta.
3. ⬜ **Cosa deve esserci sopra** (campi obbligatori) e se interessa il **QR** che apre la scheda strumento nel portale.

**Risposte organizzative (bastano a voce):**

1. ⬜ Chi è l'**ente taratore interno** (persone/ruolo) e se coincide con i livelli U/O su «Taratura strumenti» della skill matrix.
2. ⬜ **Firma singola o doppia** sull'attestato interno (e se il portale deve imporre esecutore≠firmatario).
3. ⬜ **Quanti strumenti** circa e quali famiglie (calibri, micrometri, forni, bilance…).
4. ⬜ **Storico**: migrare tutto o solo ultima taratura + prossima scadenza.

---

*Analisi di sola lettura: nessun modello Django creato, nessun file di progetto modificato. Le affermazioni su ISO/IEC 17025:2017 sono requisiti di contenuto a livello di analisi (§7.8, riferibilità §6.5), da verificare con la funzione qualità sul testo della norma e della procedura MT CN 68 Rev.7.*
