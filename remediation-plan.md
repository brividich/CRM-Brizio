# Remediation Plan — Anagrafica / DPI / Asset / MOD.133

> Analisi tecnica dei 22 punti raccolti. **Nessun codice è stato modificato.** Per
> ciascun punto: causa/analisi sul codice reale, proposta (con alternative), impatto
> su DB/schema/API, complessità stimata (S/M/L) e priorità. In coda: mappa delle
> dipendenze e note trasversali su permessi/audit/privacy.
>
> Riferimenti in formato `file:riga` (cliccabili). Prima di implementare **serve la
> tua conferma punto per punto**.

## Legenda

- **Complessità** — `S` = poche ore, modifica localizzata (view/template/CSS). `M` =
  1–3 giorni, tocca modello + form + UI + migrazione + test. `L` = epica, nuovo
  modello/registro, più moduli, dati storici.
- **Priorità** — `P1` bug che falsano dati o quick-win a rischio zero · `P2` feature
  ad alto valore con impatto medio · `P3` epiche strutturali da pianificare.

## Sintesi: scoperte che cambiano lo scope

Tre constatazioni sul codice esistente ridimensionano (in meglio) parecchi punti:

1. **La "mansione di rischio" è già parzialmente modellata.** Non come entità
   dedicata, ma come combinazione di `Mansione.dpi_richiesti` / `Mansione.visite_richieste`
   (`anagrafica/models.py:479`) + hub `FattoreRischio` → `EsposizioneRischio`
   (`anagrafica/models_rischi.py:29,137`) con M2M verso `dpi.CategoriaDPI` e
   `TipoVisitaMedica`. I punti **1.4 / 1.9 / 2.1 vanno trattati come UN'unica epica
   che ESTENDE questo strato**, non come tre fix indipendenti né come modello nuovo da zero.
2. **Diversi campi "da aggiungere" esistono già.** `area_aziendale` (FK dipendente,
   `models.py:1037`), `purchase_date` + `production_date` sull'Asset (`assets/models.py:76-77`,
   già nei form) — sono per lo più problemi di *esposizione in UI*, non di schema.
3. **Il registro OFI centralizzato NON esiste** ed è dichiarato blocker in codice
   (`gestione_specifiche/ofi.py:9-12`): oggi l'OFI è solo un intero. Il punto 4.2 è
   una build vera (L).

---

# 0. Analisi del contesto — git + dominio SGI

*Sezione richiesta dal prompt (§0). L'analisi git (0.1), che la sessione Cowork non poteva
fare, è stata eseguita qui in locale.*

### 0.1 Storia git (eseguita in locale)

Costruzioni Novicrom è fornitore aeronautico/MRO (Part 145, EN 9100, ISO 45001, ISO 27001;
clienti GE Avio, Leonardo, Piaggio, NADCAP). I quattro moduli toccati sono **tutti "vivi"** —
ultimo commit: `assets` 2026-07-17, `anagrafica` 2026-07-16, `gestione_specifiche`
2026-07-14, `dpi` 2026-07-09. Ogni modifica ha blast-radius reale su file condivisi.

**Lavori pregressi già a `main` che cambiano lo scope:**
- **1.14** — il WIP "MOD.128 requisiti di processo" (`d4a5436`) è **già mergiato in main**:
  i campi `corsi_richiesti/dpi_richiesti/visite_richieste` su `ProcessoQualificato` *sono*
  quel lavoro. 1.14 estende quella base, non parte da zero.
- **Epica mansione di rischio** — è già in main il tool AI "Rischi & requisiti per mansione"
  (`3ffb015`, D.Lgs. 81/08): la risoluzione mansione→rischi è **parzialmente presente**. Il
  `TODO PATCH-09` in `services/training_deadline_service.py:9` ("cross-reference
  mansione/area/ruolo con AnagraficaDipendente") conferma che il resolver è previsto ma
  incompleto — è il punto d'aggancio di 1.9/2.1.
- **1.1 / 1.5 visite** — `feature/anagrafica-visite-sessione` non ha commit unici oltre main:
  la giornata visite è già consolidata, nessun WIP in conflitto.

**Branch aperti che si sovrappongono (rischio duplicazione, da coordinare):**
- `feat/manutenzione-quickwin` (origin, ~323 test, merge in main **PENDING**) tocca
  assets/manutenzione → **coordinare con 3.4** (storico interventi → straordinari) prima di
  intervenire lì.
- `worktree-skm-f10-scadenzario` (SPEC F10 scadenzario abilitazioni, `dda7df3`) →
  sovrapposizione con **1.12 / 1.13** (skill matrix).
- `feature/anagrafica-permessi-acl`, `feature/anagrafica-dashboard-slim` → anagrafica: occhio
  ai conflitti su form/scheda dipendente (1.4, 1.11).

**OFI (4.2)** — il build log `abc7382` conferma che il registro centralizzato è un blocker
noto e volutamente rimandato (B1: "OFI su Excel per-reparto, dati storici later").

TODO reali pertinenti: `views.py:12990` (DPI scadenze / assenze programmate → 1.11),
`send_formazione_audit_digest.py:75` (% copertura per reparto → 1.13).

### 0.2 Dominio SGI (Appendice A)

Gli estratti SharePoint (MSG Rev.10, MT CN 06, MOD.128 Rev.15, analisi ARXivar, MOD.174)
**calibrano** le proposte, non sono specifica tecnica:
- **MT CN 06** (A.2) cita il gestionale come sistema di riferimento SGI per "mansionario
  aggiornato e scadenza qualifica personale" → 1.14/1.12 devono restare **audit-ready**.
- **MOD.128 Rev.15** (A.3): struttura per cliente/ente (Processo qualificato, Personale
  qualificato, Addetto, Controllore, Part 145, Scadenze, Distribuzione a reparto) → **già
  rispecchiata 1:1** da `ProcessoQualificato`/`AbilitazioneProcesso`.
- **MOD.174** (A.5): registro OFI/NC PDCA → schema di riferimento per 4.2.
- **Analisi ARXivar** (A.4): possibile migrazione Flusso Specifiche + MOD.133 → impatta la
  decisione su 4.1 (vedi punto).

---

# 1. ANAGRAFICA

## 1.1 — Bug filtro visite mediche in "Nuova sessione" · **S · P1**

**Causa (root).** Mismatch del nome parametro. Nel template il `<select>` "Filtra per
tipo" invia `name="_tipo_filtro"` via HTMX
(`anagrafica/templates/anagrafica/pages/visite_mediche_nuova_sessione.html:42-48`),
ma la view che ricostruisce la lista legge `request.GET.get("tipo")`
(`anagrafica/views.py:10482`). Il valore selezionato non arriva mai → la lista
ricade sempre su "tutti i tipi" e sembra non reagire. Il resto del meccanismo HTMX è
corretto: il partial ha `id="tbody-candidati"` e lo `hx-swap="outerHTML"` ricrea il
target (`partials/_visite_candidati.html:1`).

**"I filtri non funzionano affatto".** Nella pagina candidati **non esiste** una
ricerca testuale/colonna: l'unico filtro è quel select, rotto dallo stesso difetto.

**Proposta.** Fix minimo: allineare il nome (`name="tipo"`, o leggere `_tipo_filtro`
nella view). Opzionale (se serve davvero una "ricerca sottostante"): aggiungere un
campo testo con `hx-get` + debounce che filtri per nominativo lato view.
**Impatto DB/API:** nessuno. Root cause vs refactor: qui coincidono, è un one-liner.

## 1.2 — Nome dipendente al posto dell'ID nelle tabelle · **M/L · P2**

**Analisi.** Molte viste già risolvono ID→nome con mappe dedicate (`_build_nomi_map`,
`id_to_nome` in `views.py`), ma altre tabelle mostrano ancora il `legacy_anagrafica_id`
grezzo. Non c'è un difetto unico: è un **audit di superficie** su tutti i template che
renderizzano un id persona. Attenzione: il dipendente non è una FK ma un
`legacy_anagrafica_id` (nessun join ORM diretto) → la risoluzione passa da
`core.legacy_anagrafica.fetch_anagrafica_rows` e va fatta in bulk per evitare N+1.

**Proposta.** (1) Inventariare i template/tabelle con id grezzo (griglia MPQ, skill
matrix, storici, richieste DPI, ecc.). (2) Introdurre **un helper/`templatetag`
condiviso** `nome_dipendente(legacy_id)` con cache di richiesta, così ogni tabella usa
la stessa fonte. (3) Mantenere l'ID come tooltip/attributo per ricerca/debug.
**Impatto:** nessuno schema; rischio N+1 se non si centralizza il lookup.
*Da confermare: elenco esatto delle tabelle in scope (te lo produco come checklist).*

## 1.3 — Ex dipendenti nello scadenzario · **S · P1**

**Causa (root).** In `_build_scadenzario_voci` (`views.py:7167`) il filtro cessati è
applicato **solo** al ramo "contratti" (`views.py:7309-7325`). I rami **qualifiche
(7202), visite (7237) e formazione (7272) NON escludono i cessati**: iterano tutti i
record con scadenza e si limitano a fare lookup del nominativo. Esiste già l'helper
`_cessati_legacy_ids()` (`views.py:162`, basato su `data_cessazione`) ma non è usato qui.

**Proposta.** Calcolare `cessati = _cessati_legacy_ids()` una volta in testa alla
funzione e saltare `legacy_id in cessati` in tutti i rami (o filtrare i queryset con
`.exclude(legacy_anagrafica_id__in=cessati)`). Stessa fonte già usata altrove →
coerenza garantita. **Impatto DB/API:** nessuno. Ricade anche sulla dashboard "Cose da
gestire" che condivide questa funzione (bonus).

## 1.4 — Ristrutturazione campi "nuovo dipendente" · **M/L · P2** *(epica Mansione di rischio)*

**Analisi.** Form di creazione = `DipendenteLegacyForm` (`anagrafica/forms.py:70`);
template `pages/dipendente_create.html`. Stato attuale:
- `mansione` è un campo **libero/select singolo** (`forms.py:76`, template riga 175).
- `area_aziendale` **esiste già** come FK sul dipendente (`models.py:1037`) ma è sul
  form aziendale di *modifica*, non nella *creazione* → va aggiunto accanto a "reparto".
- Il template di creazione mostra le sezioni **"Ruoli operativi" e "Ruoli operativi di
  sicurezza"** (`dipendente_create.html:245,251`) — quelle da rimuovere dalla vista.
- Non esiste un campo "ruolo" distinto (c'è `ruolo_aziendale` CharField, `models.py:1052`).

**Proposta.**
1. *Quick (S, subito):* aggiungere `area_aziendale` alla creazione; aggiungere il campo
   "ruolo"; nascondere le due sezioni "ruoli operativi/di sicurezza" (solo display, il
   dato resta a DB come richiesto).
2. *Strutturale (epica):* separare **mansione lavorativa** ↔ **mansione di rischio**.
   Opzione consigliata (riuso): tenere `Mansione` come *mansione lavorativa* e usare lo
   strato rischio già presente (`FattoreRischio`/`EsposizioneRischio` +
   `Mansione.dpi_richiesti/visite_richieste`) come *profilo di rischio* derivato; la
   "mansione di rischio" diventa una vista/aggregato, non un nuovo CharField.
   Alternativa: entità `MansioneRischio` dedicata con M2M verso `Mansione` (vedi 1.9).
   **Da decidere insieme** perché è la chiave di 1.9 e 2.1.

**Impatto DB/schema:** nuove relazioni mansione-lavorativa ↔ mansione-di-rischio;
migrazione additiva; toccare `DipendenteLegacyForm` + template. **Dipendenze:** 1.9, 2.1,
e impatta 1.12 (skill matrix) e DPI.

## 1.5 — Visite inserite da profilo utente devono alimentare lo scadenzario · **S · P1 (verifica)**

**Analisi.** A livello di modello **il doppio percorso converge già**: sia la sessione
(`views.py:10565`) sia l'inserimento da profilo (`dipendente_visita_add`,
`views.py:9232`) creano una `VisitaMedica`, e `data_scadenza` è calcolata in
`VisitaMedica.save()` (`models.py:2273`) indipendentemente dal percorso. Lo scadenzario
seleziona `ultime_visite_correnti_ids()` (`services/visite.py:155`) **senza filtrare per
sessione** → una visita da profilo, se è l'ultima per (dipendente, tipo), compare.

**Proposta.** Probabile **già risolto** dall'unificazione. Prima di toccare codice:
riprodurre il caso segnalato dall'utente (quale scadenzario? quale visita?). Se il gap
è reale è in una vista secondaria o in una cache, non nel flusso principale.
**Impatto:** nessuno finché non si riproduce. Da confermare con un caso concreto.

## 1.6 — Formazione: colonna data sessione/corso in tabella · **S · P2**

**Analisi.** I dati esistono (`TrainingSession.data_inizio`, `TrainingLesson.data`,
`TrainingEmployeeRecord.data_completamento`). È una colonna mancante in una tabella di
lista. **Da confermare quale tabella** (elenco corsi, sessioni, o record dipendente):
il campo cambia di conseguenza.

**Proposta.** Aggiungere la colonna data alla lista indicata + relativo ordinamento.
**Impatto DB/API:** nessuno.

## 1.7 — Codice corso automatico e incrementale `<codice>-<N>` · **M · P2**

**Analisi.** `TrainingCourse.codice` è `CharField(30, unique=True)` inserito a mano
(`models_formazione.py:275`). Nessuna generazione automatica.

**Proposta.** Generatore transazionale sul pattern già in casa: `_next_numero_dpi`
(`dpi/models.py:200`) e `_prossimo_numero_ofi` (`gestione_specifiche/ofi.py:42`, con
`select_for_update` per la concorrenza su SQL Server). Logica: dato un prefisso base,
`MAX(N)+1`. **Da chiarire la semantica di `<codice corso>-<N>`:** `N` è progressivo
*globale*, *per piano*, o *per codice base*? Sul riuso in caso di cancellazioni:
consigliato **non riusare** i numeri (buchi ammessi) per auditabilità.
**Impatto DB:** eventuale colonna/counter; gestione concorrenza obbligatoria.

## 1.8 — Processi qualificati: selezione multiutente · **M · P2**

**Analisi.** L'abilitazione persona×processo è `AbilitazioneProcesso`
(`models_mpq.py:283`): **una persona per record** (unique su
`legacy_anagrafica_id + nominativo_esterno + processo`). Oggi si abilita un dipendente
alla volta.

**Ambiguità da chiarire.** "Il campo processi qualificati … scelta di più utenti":
- (a) *bulk*: da un processo, selezionare **N dipendenti insieme** e creare N
  abilitazioni in un colpo — interpretazione più probabile;
- (b) rendere multi un select che oggi è singolo su qualche form specifico.

**Proposta (per a).** Widget multi-select dipendenti + creazione bulk delle
`AbilitazioneProcesso` in transazione (idempotente sul unique). **Impatto DB:** nessuno
schema, solo UI/view. *Confermami quale "campo" per non sbagliare bersaglio.*

## 1.9 — Mansione di rischio a cascata (dipendente / mansione lavorativa) · **M/L · P2** *(epica)*

**Analisi.** Lo strato esiste ma la **cascata** e il collegamento *diretto al singolo
dipendente* non ci sono in modo esplicito:
- `EsposizioneRischio` collega fattore → **Mansione o Area** (`models_rischi.py:137`),
  non al singolo dipendente;
- l'eredità mansione→dipendente è demandata a un resolver (`services/mansionario.py`,
  citato nei commenti) via la mansione lavorativa del dipendente.

**Proposta.** Nel modello dell'epica (1.4): consentire l'assegnazione di una mansione
di rischio **(i)** direttamente a un `legacy_anagrafica_id`, **(ii)** a una o più
mansioni lavorative con eredità automatica. Il resolver unificato calcola l'insieme
effettivo per dipendente = requisiti diretti ∪ requisiti ereditati dalle mansioni.
**Impatto DB/schema:** relazione mansione-di-rischio ↔ mansione-lavorativa (M2M) +
override per singolo dipendente; è la stessa migrazione di 1.4. **Dipendenze:** 1.4
(schema), abilita 2.1.

## 1.10 — Ratei: filtri con operatori (`<`, `>`, `=`) · **M · P2**

**Analisi.** `ratei_list` (`views.py:7756`) offre filtri per periodo, dipendente e
reparto, più soglie di allerta (`ratei_alert.filtro_allerta_q`). Manca il filtro per
**valore** con operatori di confronto sui saldi (ferie/ROL/ex-festività).

**Proposta.** Widget "campo + operatore + valore" (es. `saldo_ferie > 40`). Poiché i
saldi sono aggregati, applicare il confronto via `annotate` + `filter` (o post-aggregazione
in Python se l'aggregato è già materializzato). Replicare la stessa logica nell'export
XLSX (`exports_hr._ratei_*`) per coerenza lista/export. **Impatto DB/API:** nessuno schema.

## 1.11 — Assenze: KPI annuali per tipologia · **M · P2**

**Analisi.** Le assenze/certificazioni presenza vivono in `assenze` (memoria:
`CertificazionePresenza`); la scheda dipendente ha già widget KPI (formazione es.
`views.py:2026`). Manca il conteggio annuale per tipologia (ferie, malattia, permesso…)
nella sezione assenze del dipendente.

**Proposta.** Aggregare le richieste/assenze del dipendente per anno×tipologia
(`values('tipo').annotate(Count)`) e renderizzare una riga KPI. **Da confermare** la
sorgente esatta (modulo `assenze`) e le tipologie da contare. **Impatto DB/API:** nessuno.

## 1.12 — Skill matrix: regola I→L + contatore abilitati · **M · P2** *(cluster competency)*

**Analisi.**
- `AbilitazioneMacchina.livello` è un `CharField` con choices I/L/U/O libero
  (`models_skillmatrix.py:209`): **nessun vincolo** che leghi I→L al completamento di un
  corso. Non c'è nemmeno un collegamento "competenza/asset → corso richiesto".
- Il "contatore abilitati per macchina" non è esposto in intestazione colonna; però il
  conteggio è banale (esiste già `is_operational`/resolver, `models_skillmatrix.py:257`).

**Proposta.**
1. *Blocco I→L:* definire il corso qualificante per macchina/competenza (nuovo campo su
   `CompetenzaSkm` o mapping asset→`TrainingCourse`), poi **validazione** nel flusso di
   modifica livello: livello ≥ L consentito solo se il dipendente ha il corso completato
   (`TrainingEmployeeRecord`/`TrainingDeadline`). Se un responsabile forza il passaggio,
   **log dell'eccezione** (append-only, riusa `AbilitazioneMacchinaStorico`,
   `models_skillmatrix.py:326`). Consigliato: stato *derivato+validato*, non calcolato
   silenziosamente, così l'override resta possibile ma tracciato.
2. *Contatore:* header per colonna macchina = `count` abilitazioni `in_lista`/operative.
   Solo query + template.

**Impatto DB:** campo "corso richiesto" per competenza (additivo). Allineato a EN 4179/
Part 145: qualifica = training **verificato** + evidenza. **Dipendenze:** utile dopo 1.14.

## 1.13 — Sezione "verifica copertura minima" (AS/EN 9100) · **M/L · P3** *(cluster competency)*

**Analisi + nota normativa.** Non esiste una sezione di copertura minima; esiste solo
`SkillMatrixConfig.soglia_uomo_solo` (min. 2 U/O, `models_skillmatrix.py:84`). Attenzione
alla terminologia: **"ISO 9100" non esiste** — lo standard QMS aeronautico è **AS/EN/JISQ
9100**. Dalla ricerca di settore: gli standard (AS9100 + Nadcap AC7xxx, EN 4179) impongono
**personale qualificato e competenza verificata**, ma **NON dettano una percentuale/numero
minimo fisso** di copertura: le soglie minime sono **definite dall'organizzazione o
flow-down del cliente**. Questo conferma la richiesta stessa: **soglie configurabili per
certificazione/processo**.

**Proposta.** Modello soglie (min. N abilitati ≥ livello X per asset/processo/ruolo
critico, configurabile e attribuibile a una certificazione) + vista "copertura minima"
che confronta soglia vs abilitati operativi (riuso resolver skill matrix) ed evidenzia i
gap. **Impatto DB/schema:** nuovo modello soglie + config. **Dipendenze:** poggia su 1.12.

## 1.14 — MOD.128: requisiti multipli per qualifica · **M · P2** *(ampliamento, web-research fatta)*

**Analisi.** La vista "Processi qualificati" del software **rispecchia già** il MOD.128
Rev.15 (A.3): `ProcessoQualificato` (`models_mpq.py:114`) è organizzato per
`ClienteQualificante` (GE Avio, Leonardo, NADCAP, Piaggio, Part 145…) con i ruoli
Qualificato/Addetto/Controllore/Part 145 su `AbilitazioneProcesso` (`models_mpq.py:307-310`),
distribuzione a reparto (M2M `reparti`) e doppia scadenza processo + individuale
(`CertificazioneIndividuale`). Il WIP "MOD.128 requisiti di processo" (`d4a5436`) è **già in
main**: esistono già i requisiti *tipizzati* `corsi_richiesti`, `dpi_richiesti`,
`visite_richieste` (`models_mpq.py:184-195`) + `RiferimentoProcesso` (≥1). **Manca** un
requisito **generico tipizzato con scadenza propria** (audit richiesto, certificato
specifico, rif. normativo) oltre ai tre tipi fissi — esattamente ciò che chiede il prompt.
Sul catalogo `TipoQualifica` (`models.py:506`) invece non c'è alcun requisito strutturato.

**Proposta (è un AMPLIAMENTO 1-N, non un refactor).** Nuova tabella `RequisitoQualifica`
(FK a `ProcessoQualificato`, opzionale a `TipoQualifica` per il catalogo) con:
`tipo ∈ {audit, corso, certificato, esame, esperienza, visione, DPI, rif_normativo, altro}`,
obbligatorietà, periodicità/scadenza propria, evidenza allegabile, stato. La verifica di
conformità (`services/mpq_conformita`) valuta il soddisfacimento di **tutti** i requisiti.
I tre M2M esistenti possono restare come scorciatoie o essere assorbiti nel nuovo modello
(migrazione additiva) — **da decidere** per non spezzare la UI attuale. Come da prompt: è il
caso semplice `qualifica_requisiti` 1-N collegata a `processo_qualificato`, **non** un refactor.

**Ricerca comparativa (Part 145 / EN 9100 / NADCAP).** In ambito MRO la qualifica è un
*insieme*: formazione + esperienza (ore/mesi) + esame (generale/specifico/pratico) + test
visivo + valutazione periodica + ricertificazione (EN 4179/NAS 410 per NDT; competence
assessment con record per Part 145). AS9100+Nadcap: personale qualificato per processi
speciali con requisiti **flow-down dal cliente**. → conferma il modello a N requisiti
tipizzati con evidenza e scadenza per requisito.

**Impatto DB/schema:** nuovo modello 1-N additivo; UI di gestione requisiti per riga.
**Dipendenze:** cluster competency (1.12/1.13); resta audit-ready (MT CN 06, A.2).

## 1.15 — Matricola: rimozione zeri superflui · **S · P3**

**Analisi.** La matricola arriva dai record legacy (`views.py` vari, es. 377/718/847) ed
è mostrata così com'è. È un problema di **formattazione in visualizzazione**.

**Proposta.** Strip degli zeri iniziali **solo in display** (templatetag/filter),
lasciando il dato legacy intatto. **Cautela:** verificare che le matricole siano
numeriche e che togliere il padding non rompa ricerca/ordinamento (se alcune sono
alfanumeriche o l'ordinamento è testuale, gestire il caso). **Impatto DB:** nessuno.

---

# 2. DPI

## 2.1 — Disponibilità DPI filtrata per mansione di rischio · **M · P2** *(dipende da epica 1.4/1.9)*

**Analisi.** `RichiestaDPI` (`dpi/models.py:220`) **non ha alcun legame** con la
mansione: in richiesta si vedono tutte le `CategoriaDPI`. Ma la catena per filtrare
**esiste già** lato anagrafica: dipendente → mansione → (`EsposizioneRischio` →
`FattoreRischio.categorie_dpi`) ∪ `Mansione.dpi_richiesti` → categorie DPI ammesse.

**Proposta.** In fase di richiesta, risolvere le categorie DPI ammesse per il
richiedente tramite un resolver condiviso (lo stesso di 1.9) e limitare le opzioni;
mantenere un override esplicito (con motivazione) per casi fuori profilo.
**Impatto DB/API:** nessuno schema nuovo se si riusa lo strato rischio; serve il resolver
di 1.9. **Dipendenze:** BLOCCATO da 1.4/1.9 (come è modellata la mansione di rischio).

---

# 3. ASSET

## 3.1 — Tag PART145: sfondo blu, testo bianco · **S · P1**

**Analisi.** Oggi il pill è **rosso**: `.af-pill--part145 { background:#dc2626; color:#fff }`
(`assets/templates/assets/pages/asset_detail.html:72`), variante dark `#b91c1c` (riga 394).

**Proposta.** Cambiare il background in blu (es. `#1d4ed8`, dark `#1e40af`), testo bianco
invariato. **Da decidere:** allineare anche l'identità rossa della lista
`part_145_list.html` (hero) per coerenza, o lasciarla. **Impatto:** solo CSS.

## 3.2 — Data acquisto + data fabbricazione · **S · P2 (quasi fatto)**

**Analisi.** I campi **esistono già**: `purchase_date` e `production_date`
(`assets/models.py:76-77`) e sono **già nei form** `AssetForm` (`forms.py:365-366`,
label "Data acquisto"/"Data produzione") e `WorkMachineAssetForm` (`forms.py:1363-1364`).

**Proposta.** Non serve schema. Al massimo: (1) rinominare la label "Data produzione" →
"Data fabbricazione" se si vuole quel wording; (2) verificare che entrambe compaiano nella
scheda `asset_detail.html`. **Impatto DB:** nessuno.

## 3.3 — N. interno progressivo · **M · P2**

**Analisi.** `Asset.internal_number` è `CharField` manuale (`assets/models.py:61`).
Esiste anche una colonna legacy `numero_interno` NOT NULL fuori ORM (migration
`0071_asset_numero_interno`, nota storica: ruppe `/assets/new/`). Recentemente il campo
N.INT è stato aggiunto al form macchine.

**Proposta.** Generazione progressiva `MAX(numero)+1` con `select_for_update` (pattern
`_next_numero_dpi`), lasciando l'override manuale possibile. Edge case da gestire
esplicitamente: **valori legacy non numerici**, import massivi (assegnare in blocco senza
collisioni), cancellazioni (buchi ammessi, no riuso), concorrenza. **Impatto DB:**
eventuale sequence/counter; attenzione alla colonna legacy NOT NULL.

## 3.4 — Rinominare "storico interventi" → "interventi straordinari" · **S/M · P3**

**Analisi.** Etichetta in `asset_detail.html:744-746`. **Da verificare se è solo
testuale o cambia il significato/filtro dei dati**: se la sezione elenca *tutti* gli
interventi, rinominarla in "straordinari" implica **filtrare** solo quelli straordinari
(cambio di semantica, non solo label) — altrimenti l'etichetta mentirebbe sul contenuto.

**Proposta.** (1) Se puramente testuale → S. (2) Se serve distinguere ordinari/
straordinari → verificare il modello manutenzione (esiste un tipo intervento?) e filtrare.
**Da confermare** l'intento. **Impatto DB:** nullo (caso 1) o filtro (caso 2).

---

# 4. GESTIONE SPECIFICHE — MOD.133

## 4.1 — Più documenti impattanti sulla stessa riga · **M · P2**

**Decisione (2026-07-22).** ARXivar NEXT **non verrà adottato**: il gestionale resta il
sistema di riferimento per Flusso Specifiche + MOD.133. Nessuna sospensione cautelativa —
si procede stand-alone. *(Rischio di sovrapposizione ARXivar rimosso dal piano.)*

**Analisi.** `RigaMOD133.rif_doc_cn` è un **singolo** `CharField(100)`
(`gestione_specifiche/models.py:325`); anche `AzioneOFI.documento_cn` è singolo (riga 353);
la generazione OFI legge `riga.rif_doc_cn` (`ofi.py:79`).

**Proposta.** Tabella figlia `RigaMOD133Documento` (FK a riga, ≥0 documenti) — o M2M se si
crea un registro documenti CN. Adeguare: form/UI riga, generazione OFI (una azione per
documento impattato), export/overlay MOD.133. **Impatto DB/schema:** nuovo modello +
migrazione dati (spostare i `rif_doc_cn` esistenti nelle righe figlie).

## 4.2 — Registro OFI centralizzato (allineato a MOD.174) · **L · P3** *(build vera)*

**Analisi.** **Non esiste** un registro OFI: oggi è un intero locale (`RigaMOD133.ofi` /
`AzioneOFI.ofi`) con numerazione di ripiego, dichiarato blocker in attesa del MOD.174
(`gestione_specifiche/ofi.py:9-12, 28`; build log `abc7382`). Nessun proprietario, owner di
processo, priorità o reminder oggi.

**Proposta (replicare MOD.174, non inventare — A.5).** Nuovo modello `RegistroOFI` con la
struttura PDCA del registro ufficiale: `REF, DATA, OFI, NC, normative (ISO 27001/45001/EN
9100), rif_norma, processo, opportunity, PLAN, allegato/link, DO, CHECK, ACT, data_required,
data_closed, OWNER` + i campi richiesti da Luca (**proprietario, owner di processo, priorità,
reminder** sulla scadenza) e i contatori P/D/C/A/TOT del ciclo PLAN-DO-CHECK-ACT. Le righe
MOD.133 con impatto (4.1) confluiscono automaticamente creando la voce di registro; aggancio
da altri moduli via riferimento generico (`modulo_origine` + `content_type`/`object_id`). Le
OFI MOD.133 diventano FK a questo registro (migrazione additiva dall'intero). Reminder su
django-q (pattern scadenze già in casa). Mantenendo la struttura MOD.174 il registro resta
coerente con quanto già certificato/auditato.

**Impatto DB/schema:** nuovo registro PDCA + refactor `ofi.py` + reminder + UI.
**Dipendenze:** con/dopo 4.1. Il registro resta un **hub trasversale multi-modulo** (le OFI
non nascono solo da MOD.133).

---

# 5. Osservazioni aggiuntive (proposte dal prompt §5, mia valutazione)

- **5.1 Audit trail modifiche anagrafiche — *consigliato, costo basso*.** Contesto EN 9100/
  45001/27001: mansione, mansione di rischio, ruolo, qualifica, scadenze (1.4/1.9/1.12/1.14)
  dovrebbero lasciare traccia (chi/cosa/quando) per gli audit interni (MT CN 12). **Riuso già
  disponibile:** `core.audit.log_action`, `DipendenteQualificaStorico`,
  `AbilitazioneMacchinaStorico`, `MpqStorico`, `EventoSpecifica`. Standardizzare su questi,
  senza nuovo meccanismo.
- **5.2 Modello dati unico competency — *è LA decisione architetturale*.** 1.4/1.9/1.12/1.14
  toccano lo stesso asse "chi è abilitato a cosa, fino a quando". Raccomando un modello
  condiviso **mansione lavorativa → mansione di rischio → processo qualificato →
  requisiti/scadenze → skill matrix** con un **resolver unico** (che estende
  `services/mansionario` + `training_deadline_service`, già avviati: vedi TODO PATCH-09)
  invece di 4 strutture parallele. Evita disallineamenti scadenzario ↔ skill matrix ↔
  MOD.128. **Va deciso prima di implementare le epiche A e B.**
- **5.3 Numerazione incrementale condivisa — *consigliato*.** 1.7 (codice corso) e 3.3 (N.
  interno asset) sono lo stesso problema; DPI e OFI già reimplementano il pattern. Un unico
  servizio `next_sequence(entity)` (tabella sequence + `select_for_update`) riduce debito.
- **5.4 Copertura minima come motore di regole — *se si fa 1.13, farlo generico*.** 1.13 può
  diventare un motore "soglia richiesta vs disponibile" riusabile da 1.12 (contatore) e da
  requisiti ISO 45001/27001, invece di feature isolata qualità.
- **5.5 Nota di metodo.** L'analisi git (§0.1) è stata eseguita in locale (risultati in
  §0). L'Appendice A è riferimento di dominio, non specifica tecnica.

---

# Dipendenze & ordine consigliato

| # | Punto | Compl. | Prio | Blocca / dipende da |
|---|-------|:------:|:----:|---------------------|
| 1.1 | Bug filtro nuova sessione | S | P1 | — (quick win) |
| 1.3 | Ex dipendenti scadenzario | S | P1 | — (quick win) |
| 3.1 | Tag PART145 blu | S | P1 | — (quick win) |
| 1.5 | Visite da profilo | S | P1 | solo verifica/repro |
| 3.2 | Date acquisto/fabbricazione | S | P2 | quasi fatto |
| **1.4** | Ristrutturazione campi + split mansione | M/L | P2 | **ancora dell'epica** → 1.9, 2.1 |
| **1.9** | Mansione di rischio a cascata | M/L | P2 | dipende da 1.4 |
| **2.1** | DPI filtrati per mansione rischio | M | P2 | dipende da 1.4 + 1.9 |
| 1.14 | Requisiti multipli qualifica | M/L | P2 | cluster competency |
| 1.12 | Skill matrix I→L + contatore | M | P2 | meglio dopo 1.14 |
| 1.13 | Copertura minima AS/EN 9100 | M/L | P3 | dipende da 1.12 |
| 4.1 | Più documenti impattanti | M | P2 | propedeutico a 4.2 |
| 4.2 | Registro OFI centralizzato | L | P3 | con/dopo 4.1 |
| 1.2 | ID→nome nelle tabelle | M/L | P2 | indipendente (audit) |
| 1.6 / 1.7 / 1.8 / 1.10 / 1.11 | Feature anagrafica | S–M | P2 | indipendenti |
| 3.3 / 3.4 / 1.15 | Asset/matricola | S–M | P2/P3 | indipendenti |

**Tre epiche da trattare unitariamente:**
- **Epica A — Mansione di rischio:** 1.4 → 1.9 → 2.1 (un'unica migrazione dati + resolver
  condiviso). È il prerequisito del filtro DPI.
- **Epica B — Competency aeronautica:** 1.14 (requisiti multipli) → 1.12 (blocco I→L) →
  1.13 (copertura minima). Concetto comune: "requisito verificato con evidenza".
- **Epica C — OFI/MOD.133:** 4.1 (più documenti) → 4.2 (registro centralizzato).

# Note trasversali: permessi, audit, privacy

- **Audit trail** — 1.12 (override I→L), 1.14, 4.2 richiedono log append-only. Riusare i
  pattern esistenti: `AbilitazioneMacchinaStorico`, `MpqStorico`, `EventoSpecifica`,
  `core.audit.log_action`. Nessun nuovo meccanismo.
- **Privacy / dato sensibile** — visite mediche (1.1/1.5) e ratei/retribuzioni (1.10) sono
  gated (`AnagraficaVisiteMedichePermission`, `_check_hr_permission`). Ogni modifica deve
  **preservare il gating**: non esporre id/nomi (1.2) o KPI (1.11) oltre chi già li vede.
- **ACL v2** — nuove rotte (1.13 copertura, 4.2 registro OFI) vanno inserite nei binding
  canonici e nelle `API_ACL_GATE_PATHS` se AJAX, altrimenti `ACL_STRICT_CANONICAL` le nega
  (403). MOD.128/MOD.133 hanno già i permessi canonici.
- **Terminologia** — 1.13: "ISO 9100" → **AS/EN 9100** nei testi UI.

---

## Decisioni

**Prese (2026-07-22):**
- ✅ **Epica A** — "mansione di rischio" modellata **a vista/aggregato** sullo strato
  `FattoreRischio`/`EsposizioneRischio` + `Mansione.dpi_richiesti/visite_richieste` (no entità
  dedicata parallela). Estende, non duplica. Vale per 1.4 → 1.9 → 2.1 e per il resolver §5.2.
- ✅ **4.1 / ARXivar** — non adottato: si procede sul gestionale, nessuna sospensione.

**Ancora aperte (non bloccanti — si procede intanto sull'approvato):**
- **1.7** — semantica di `<codice corso>-<N>` (N globale / per piano / per codice base).
- **1.8** — quale "campo processi qualificati" (bulk multi-dipendente, o select da rendere multi).
- **1.2 / 1.6** — elenco tabelle in scope (checklist da produrre).
- **3.4** — "storico interventi": solo rinomina o anche filtro straordinari? (coordinare con
  `feat/manutenzione-quickwin` prima di toccare l'area).

## Stato implementazione

**Approvato e in corso** (worktree dedicato, uno alla volta): quick-win P1 → **1.1, 1.3, 3.1**;
poi **Epica A** (1.4 → 1.9 → 2.1, modellazione a vista). Gli altri punti restano in attesa di
conferma esplicita.
