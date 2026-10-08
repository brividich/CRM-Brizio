# BUILD_SPEC — Database SGI strutturato + Glossario tecnico metalmeccanico

> Destinatario: Claude Code, sessione autonoma sul repo NOVICROM HUB (`brividich/CRM-Brizio`, base v1.6.1).
> Committente: Brizio. Lingua di lavoro: italiano. Modalità: **a fasi con STOP obbligatori**.

---

## In breve (per chi apre il file)

**Obiettivo.** Oggi l'assistente AI dell'HUB legge i PDF della cartella SGI come testo indistinto. Alla fine **conosce i documenti**: cosa contengono, chi cita chi, quali requisiti ISO coprono, cosa significano i termini tecnici.

**Cosa c'è già.** La cartella SGI del file server viene sincronizzata ogni notte e i PDF sono già indicizzati per l'assistente.

**Cosa aggiunge il progetto.**
1. **Lettura migliore:** anche Word ed Excel, tabelle conservate, OCR opzionale sulle scansioni.
2. **Glossario tecnico** (es. lamatura = spot face = ⌴), validato dalla qualità. Fa trovare all'assistente anche termini brevi come `H7`, `Ra`, `NC`, che oggi ignora.
3. **Mappa dei riferimenti:** "se modifico MT CN 06, quali documenti devo controllare?". Ricavata leggendo i codici, senza AI.
4. **Clausole ISO:** l'AI propone a quale clausola risponde ogni documento, una persona conferma. Ne esce la tabella di copertura per gli audit.

**Tappe:** fotografia della cartella (sola lettura) → lettura migliore → glossario → glossario nella ricerca → mappa riferimenti → clausole ISO → schermate e domande all'assistente. Claude Code **si ferma a ogni tappa** e misura se l'assistente risponde meglio o peggio di prima.

**Garanzie:** ogni novità ha un interruttore spento di default; l'AI propone e decide una persona; i file della cartella SGI non vengono mai modificati; nel repository non entrano documenti reali, clienti o testi di norme.

---

## 0. Regole d'ingaggio (leggere PRIMA di tutto)

1. Rispetta integralmente `CLAUDE.md` della root: Session Isolation (worktree dedicato, mai `git checkout` nel checkout condiviso), Background Work Guard, Resource Constraints (solo test dell'app toccata, `--keepdb`), Patch Workflow (CHANGELOG `[Unreleased]` + `docs/moduli/<app>.md` aggiornati ad ogni modifica).
2. Branch: `feature/ai-sgi-database` (traccia A) e `feature/ai-glossario-tecnico` (traccia B). Merge path: feature → main → release/prod. **Non** fare merge tu: chiudi ogni fase con commit e report.
3. Principi AI non negoziabili (da `docs/ai/15_AI_NEXT_STEPS.md`): on-prem, read-only, **"l'AI propone, l'umano firma"**, audit solo-metadati, ACL server-side, tutto misurato con `ai_eval`.
4. **Deterministico prima, AI dopo.** Tutto ciò che si può estrarre con regex/parsing (codici documento, riferimenti incrociati, revisioni, simboli) si fa senza LLM. L'LLM interviene solo per proposte semantiche (clausole ISO, responsabilità, definizioni) che finiscono in coda di validazione umana.
5. **Vietato** inserire nel repo, nei test, nelle fixture o nei prompt: testo reale dei documenti SGI, nomi di clienti, dati personali, testo di norme ISO/UNI/ASTM. Fixture **solo sintetiche**. Delle norme si memorizzano solo **codice e titolo breve scritto con parole nostre**.
6. Feature flag per tutto ciò che cambia il comportamento runtime, **default OFF** in prod, ON in `settings/test.py` dove serve ai test.
7. Compatibilità: Python 3.11, Django 5.2, **SQL Server via mssql-django 1.7.4** (evita lookup JSON nelle query ORM: filtra in Python o usa colonne dedicate), Windows Server + waitress (24 thread, slot AI = `OLLAMA_MAX_CONCURRENT_REQUESTS`), path **UNC**.
8. django-q2: 2 worker, `timeout=120`. **Nessun task può superare ~90 s.** Lavori lunghi = un task per documento, accodati a catena; mai un loop su tutto il corpus dentro un solo task.
9. Nessuna nuova dipendenza pesante (torch, docling, transformers) sul server del portale. Ammesse: `python-docx` (leggera). Ogni nuova dipendenza va in `django_app/requirements.in` + `pip-compile` come da header del file. OCR solo se deciso allo STOP 0 (vedi §A1.4).
10. Ad ogni STOP produci il **Report di fase** (formato in §9) e fermati.

---

## 1. Contesto verificato nel codice (non riscoprirlo, usalo)

| Cosa | Dove | Stato |
|---|---|---|
| Anagrafica documenti SGI | `procedure_refresh/models.py`: `ProcedureDocument` (code unique, title, category, document_type MT/MTSI/ALTRO, `escludi_dal_rag`), `ProcedureRevision` (revision_code, `is_current`, `source_type` fileserver/sharepoint, `source_path` UNC, `file_hash` sha256), `SgiSyncLog` | in prod |
| Import da file server | `procedure_refresh/management/commands/import_sgi_da_share.py`: `parse_sgi_filename` (`_CODE_RE`, `_REV_RE`), `scan_share_candidates` (**solo `rglob("*.pdf")`**, esclude `SUPERAT*`), `dedup_candidates`, `upsert_candidate`, `filter_auto_safe` | in prod |
| Sync notturna | `procedure_refresh/tasks.py::run_sgi_auto_sync` (flag SiteConfig `pr_sgi_auto_sync_attivo`), watchdog `run_sgi_share_check`; re-index RAG schedulato 03:30 | in prod |
| Root share | `settings.PROCEDURE_REFRESH_SGI_SHARE_ROOT` (UNC) | config |
| Estrazione testo | `ai_assistant/services.py::_extract_pdf_text` (pymupdf `get_text()` piatto, tabelle perse), `_sgi_extract_procedure_text` (solo fileserver, cache per `file_hash` TTL 30 gg), `_sgi_sections` (heading `§n.n` via `_SGI_HEADING_RE`), `_sgi_chunks_from_text` | in prod |
| Cap corpus | `OLLAMA_RAG_SGI_MAX_PROCS=300`, `OLLAMA_RAG_SGI_MAX_PDF_CHARS=200000` | config |
| Retrieval | BM25 + embeddings bge-m3 su TEI (`RAG_EMBED_BACKEND`), RRF, indice **in memoria per processo** | in prod |
| Tokenizer | `services._tokenize`: regex `[a-z0-9_]{3,}` → **scarta token < 3 caratteri e simboli** (`H7`, `g6`, `Ra`, `NC`, `Ø`, `⌴` spariscono) | limite noto |
| Baseline qualità | `ai_eval --rag-sgi`: recall 29/32, MRR 0,634; KB: 26/26, MRR 0,981. Golden: `ai_assistant/eval/golden_sgi.jsonl` (33 righe) | misurata |
| Processi SGI | `sistema_gestione.Processo`: `procedure` (TextField libero), `punti_9100/45001/27001/pdr125` (CharField), `responsabile` FK | in prod |
| Apprendimento proposte | `ai_assistant.models.AiProposta` + `ai_assistant/apprendimento.py::registra_proposta / registra_decisione / lezioni_testo` | in prod |
| Tool live procedure | `ai_assistant/tools.py::_procedure_context` in `RUNTIME_TOOLS` | in prod |
| Glossario attuale | `ai_assistant/knowledge/08_glossario.md` (solo sigle del portale: ROL, OdL, OP…) | in prod |
| ACL API | `core/middleware.py::API_ACL_GATE_PATHS` (es. `/procedure-refresh/api/` → `/procedure-refresh/impostazioni/`); bootstrap `procedure_refresh/acl_bootstrap.py` | in prod |

Roadmap già esistente da rispettare: `docs/ai/15_AI_NEXT_STEPS.md` punti **3.1** (sinonimi/acronimi), **3.3** (chunking). Questo spec li implementa: aggiornane lo stato.

---

## 2. Obiettivi e non-obiettivi

**Traccia A — Database SGI strutturato.** Da "PDF indicizzati" a database interrogabile: testo persistito e di qualità (anche Word/Excel, tabelle), metadati (processo, clausole ISO, responsabile), **grafo dei riferimenti incrociati** tra documenti, viste "impatto modifica" e "copertura clausole", tool live per l'assistente.

**Traccia B — Glossario tecnico.** Termini di metalmeccanica/qualità/SGI con sinonimi, gergo, simboli, traduzione EN; usato per normalizzare query e indice (fix del tokenizer), rispondere a domande di terminologia, e (futuro) validare le quote estratte dai disegni.

**Non-obiettivi:** SharePoint, confronto disegni, DGX Spark/vLLM, reranker (3.2), indicizzazione di norme esterne, scrittura sui file della share (sempre **sola lettura**).

---

## 3. Sequenza delle fasi

```
F0 Ricognizione (read-only)          → STOP 0
A1 Estrazione testo persistita        → STOP A1
B1 Glossario: modello + seed + UI     → STOP B1
B2 Glossario nel retrieval (3.1)      → STOP B2
A2 Grafo riferimenti (deterministico) → STOP A2
A3 Profilo documento + clausole (AI)  → STOP A3
A4 Viste + tool live + golden         → STOP A4
```

---

## F0 — Ricognizione (sola lettura, nessuna migrazione)

Crea `procedure_refresh/management/commands/sgi_inventario.py` (riusa `scan_share_candidates` e `_SUPERATO_RE`, non duplicarli):

- `--root` (default `PROCEDURE_REFRESH_SGI_SHARE_ROOT`), `--json`, `--sample N` (default 0 = tutti).
- Conta per **estensione** (`.pdf .docx .doc .xlsx .xls .pptx` + altro) e per **cartella di primo livello** (= category), esclusi `SUPERAT*`.
- Per i PDF: pagine, caratteri estratti per pagina con pymupdf; classifica **"testo nativo" / "scansione"** (soglia: < 50 caratteri/pagina medi → scansione) e conta pagine con tabelle (`page.find_tables()`).
- Quanti file **non** matchano `parse_sgi_filename` (fallback) e quanti codici esistono **sia in PDF che in formato editabile**.
- Copertura heading: % documenti dove `_sgi_sections` trova ≥ 2 sezioni `§`.
- Confronto con il cap: n. revisioni correnti vs `OLLAMA_RAG_SGI_MAX_PROCS`.
- Esegui `ai_eval --rag-sgi --json` e salva la baseline in `docs/ai/baseline/rag_sgi_<data>.json` (solo metriche, nessun testo documento).

Output: report Markdown in console + JSON. **Nessuna scrittura DB, nessun file sulla share.**
Test: unit test su un albero sintetico in `tmp_path` (PDF generati con pymupdf, un .docx generato con python-docx se installata, cartella `SUPERATO`).

### STOP 0 — decisioni che Brizio deve prendere sul report
1. Formati da indicizzare oltre al PDF (default proposto: `.docx` e `.xlsx` sì, `.doc/.xls` legacy solo report).
2. Se esiste lo stesso codice+revisione in PDF ed editabile: quale vince (default proposto: **PDF**, copia controllata).
3. OCR per le scansioni: no / sì con Tesseract (già usato nello script referti) eseguito **solo da comando offline**, mai nel request path.
4. Nuovo valore di `OLLAMA_RAG_SGI_MAX_PROCS` se il corpus supera 300.

---

## A1 — Estrazione testo robusta e persistita

### A1.1 Modello
In `procedure_refresh/models.py`:

```python
class SgiTestoEstratto(models.Model):
    revision = models.OneToOneField(ProcedureRevision, on_delete=models.CASCADE, related_name="testo_estratto")
    file_hash = models.CharField(max_length=128, db_index=True)   # = revision.file_hash al momento dell'estrazione
    formato = models.CharField(max_length=10)                     # pdf|docx|xlsx
    metodo = models.CharField(max_length=30)                      # pymupdf_layout|pymupdf_ocr|python_docx|openpyxl
    testo = models.TextField()                                    # markdown leggero: heading, liste, tabelle in pipe-table
    n_pagine = models.PositiveIntegerField(null=True, blank=True)
    n_caratteri = models.PositiveIntegerField(default=0)
    n_sezioni = models.PositiveIntegerField(default=0)
    ha_testo_nativo = models.BooleanField(default=True)
    ocr_usato = models.BooleanField(default=False)
    avvisi = models.TextField(blank=True, default="")             # es. "2 tabelle non ricostruite", troncamenti
    estratto_il = models.DateTimeField(auto_now=True)
```
Migrazione reversibile. Admin read-only (solo metadati in lista; testo in dettaglio, riservato a superuser).

### A1.2 Estrattori — `procedure_refresh/sgi_testo.py` (modulo nuovo, funzioni pure + fail-safe)
- `estrai(path: Path) -> EstrazioneResult` con dispatch per estensione.
- **PDF**: pymupdf con `page.get_text("blocks", sort=True)` per ordine di lettura; tabelle via `page.find_tables()` → convertite in pipe-table Markdown e **non** duplicate nel testo dei blocchi (escludi i bbox delle tabelle); rimozione intestazioni/piè di pagina ripetuti (righe identiche presenti in ≥ 60% delle pagine, es. cartiglio "MT CN 06 Rev.21 pag. x di y").
- **DOCX** (`python-docx`): heading (stile `Heading n`/`Titolo n`) → `§`-compatible; tabelle → pipe-table; ignora header/footer.
- **XLSX** (`openpyxl`, già presente, `read_only=True, data_only=True`): un blocco per foglio, righe non vuote come pipe-table, max righe configurabile.
- Normalizzazione: NFC, spazi collassati, sillabazioni a fine riga ricomposte.
- Mai eccezioni verso il chiamante: errore → `testo=""` + `avvisi`.

### A1.3 Integrazione
- `scan_share_candidates`: estensioni da `settings.PROCEDURE_REFRESH_SGI_EXTENSIONS` (default `[".pdf"]` → **comportamento attuale invariato** finché non si cambia config). Regola di precedenza PDF vs editabile da decisione STOP 0, implementata in `dedup_candidates` con test.
- `_sgi_safe_pdf_path` → generalizza in `_sgi_safe_doc_path` con whitelist estensioni; mantieni l'alias per compatibilità.
- `_sgi_extract_procedure_text(rev)`: **prima** legge `SgiTestoEstratto` se `file_hash` coincide; altrimenti fallback al percorso attuale (pymupdf) → nessuna regressione se la tabella è vuota. Import lazy (`ai_assistant` resta senza import cross-app a livello di modulo, come oggi).
- Comando `sgi_estrai_testi [--solo CODICE] [--forza] [--ocr] [--limit N] [--dry-run]`: idempotente su `file_hash`.
- Task django-q `procedure_refresh.tasks.run_sgi_estrazione_un_documento(revision_id)` + accodamento a catena da `run_sgi_auto_sync` per le sole revisioni nuove/cambiate, poi re-index come oggi. Ogni task < 90 s; se OCR attivo, OCR **solo** da comando.

### A1.4 OCR (solo se approvato a STOP 0)
`pytesseract` + binario Tesseract installato sul server (documentare in `docs/ai/RUNBOOK_DEPLOY_AI.md`), lingua `ita+eng`, 300 dpi, solo pagine classificate "scansione". `ocr_usato=True`.

### A1.5 Chunking (roadmap 3.3)
In `_sgi_chunks_from_text`: ogni chunk porta **nel testo** l'intestazione `"{codice} Rev.{rev} — {§ titolo sezione}"` (oggi è solo nel titolo); dimensione portata a `OLLAMA_RAG_SGI_CHUNK_CHARS` (nuovo setting, default = `OLLAMA_RAG_CHUNK_CHARS` → nessuna variazione finché non lo si cambia); tabelle mai spezzate a metà riga.
⚠️ Cambiare il testo dei chunk **invalida la cache embeddings**: prevedi il re-warm (`index_sgi_documents`) e annotalo nel report.

### Acceptance A1
- Test: estrattori su file sintetici (PDF con tabella, PDF "scansione" = immagine, DOCX con heading e tabella, XLSX multi-foglio), header/footer rimossi, precedenza PDF/editabile, idempotenza su hash, fail-safe su file corrotto.
- `ai_eval --rag-sgi`: **recall ≥ baseline F0 e MRR ≥ baseline F0** con estrazione nuova attiva; riporta il delta. Se peggiora, STOP con analisi (non tarare a sensazione).

---

## B1 — Glossario: dati, seed, revisione

### B1.1 App
Nuova app `glossario_tecnico` (piccola, confini netti; sarà riusata dal futuro modulo disegni). Registrala come le altre (settings, urls, ACL bootstrap sul modello di `procedure_refresh/acl_bootstrap.py`, voce di navigazione sotto l'area SGI/Qualità).

### B1.2 Modelli
```python
class Termine(models.Model):
    CATEGORIE = [("lavorazione",...),("quotatura",...),("tolleranza_dimensionale",...),
                 ("gdt",...),("rugosita",...),("filettatura",...),("trattamento_termico",...),
                 ("trattamento_superficiale",...),("materiale",...),("controllo_qualita",...),
                 ("sgi_documentale",...),("sigla_aziendale",...)]
    STATI = [("bozza","Bozza"),("validato","Validato"),("deprecato","Deprecato")]
    termine = models.CharField(max_length=150)                 # forma canonica IT
    termine_en = models.CharField(max_length=150, blank=True)
    categoria = models.CharField(max_length=30, choices=CATEGORIE, db_index=True)
    definizione = models.TextField()                           # parole nostre, max ~600 car.
    simbolo = models.CharField(max_length=20, blank=True)      # unicode: ⌀ ⌴ ⌵ ⏤ ⏥ ○ ⌭ ⊥ ∠ ⫽ ⌖ ◎ ⌒ ⌓ ↗ ⌰
    esempio_disegno = models.CharField(max_length=200, blank=True)  # es. "⌴ ⌀12 ↧2"
    norma_rif = models.CharField(max_length=60, blank=True)    # SOLO codice: "ISO 1101", "ISO 286-1"
    stato = models.CharField(max_length=10, choices=STATI, default="bozza", db_index=True)
    fonte = models.CharField(max_length=20)                    # manuale|seed|ai_proposta|import_csv
    usa_nel_rag = models.BooleanField(default=True)
    note_interne = models.TextField(blank=True)                # mai al modello
    validato_da = FK(User, null=True, SET_NULL); validato_il = DateTimeField(null=True)
    created_at / updated_at
    class Meta: constraints = [UniqueConstraint(fields=["termine","categoria"], name="uq_termine_categoria")]

class Variante(models.Model):
    TIPI = [("sinonimo",...),("gergo",...),("abbreviazione",...),("simbolo",...),
            ("traduzione",...),("grafia_errata",...)]
    termine = FK(Termine, CASCADE, related_name="varianti")
    testo = models.CharField(max_length=150)
    tipo = models.CharField(max_length=15, choices=TIPI)
    lingua = models.CharField(max_length=2, default="it")
    chiave = models.CharField(max_length=150, unique=True, db_index=True)  # normalizzata: lower, accenti fold, spazi singoli
```
`chiave` unica = una variante non può puntare a due termini: conflitti esplicitati in validazione (form error), mai risolti in silenzio.

### B1.3 Seed
Fixture/data-migration `seed_glossario_base` con **~80 termini in stato `bozza`, `fonte=seed`**, definizioni brevi scritte da te con parole tue, coprendo: lavorazioni (tornitura, fresatura, rettifica, alesatura, lamatura, svasatura, maschiatura, brocciatura, elettroerosione a filo/tuffo, sbavatura, smussatura, raggiatura), quotatura e tolleranze (quota nominale, scostamento, campo di tolleranza, sistema foro base / albero base, accoppiamento, tolleranze generali), GD&T (tutte le 14 caratteristiche ISO 1101 + riferimento/datum, MMC/LMC, zona di tolleranza proiettata), rugosità (Ra, Rz, simbolo con/senza asportazione), filettature (M, MF, passo, classe 6H/6g, UNC/UNF), trattamenti (tempra, rinvenimento, cementazione, nitrurazione, distensione, anodizzazione, passivazione, pallinatura), controllo (FAI / AS9102, ballonatura, CMM, calibro passa-non passa, caratteristica chiave/KC), SGI documentale (MT, MTSI, IDOR, IDPR, MOD, CN, NC, AC, OFI, FAI).
Ogni termine con le varianti ovvie (gergo d'officina, EN, simbolo). **Niente valori numerici di tabelle nelle definizioni.**

### B1.4 Import / candidati
- `glossario_import_csv --file X.csv [--dry-run]`: colonne `termine;termine_en;categoria;definizione;simbolo;norma_rif;varianti` (varianti separate da `|`, formato `tipo:testo`). Pensato per un export IATE filtrato a mano. Righe importate → `bozza`.
- `glossario_candidati [--limit N]`: legge `SgiTestoEstratto`, estrae **deterministicamente** n-grammi 1–3 frequenti in ≥ 3 documenti e non presenti come variante, li ordina per frequenza documentale; **opzionale** `--ai`: per i top-N chiede all'LLM (via `ai_assistant.services.chat_with_ollama`, un task per batch < 90 s) una proposta JSON `{termine, categoria, definizione, varianti}` registrata con `registra_proposta(modulo="glossario", azione="nuovo_termine", ...)`. Le proposte non diventano `Termine` finché un umano non le accetta.

### B1.5 UI (SSR + HTMX, design system esistente)
- Elenco con filtri categoria/stato, ricerca su termine + varianti.
- Scheda termine con varianti inline (HTMX).
- **Coda di revisione**: bozze + proposte AI; azioni Valida / Correggi / Scarta → `registra_decisione(...)` così le lezioni tornano nei prompt successivi (`lezioni_testo`).
- ACL: lettura a tutti gli utenti autenticati; modifica/validazione a una risorsa ACL v2 nuova `glossario_tecnico:gestione` assegnata di default a qualità/UT (definita nel bootstrap; **STOP se non esiste un ruolo adatto** invece di inventarlo). Nuove route API registrate in `API_ACL_GATE_PATHS`.

### Acceptance B1
Test modelli (unicità chiave variante, normalizzazione), import CSV (righe valide/invalide, dry-run), comando candidati senza AI (deterministico su testi sintetici), ACL (403 JSON su API per utente senza permesso), coda revisione (decisione registrata in `AiProposta`).

---

## B2 — Glossario nel retrieval (roadmap 3.1)

### B2.1 Termini protetti nel tokenizer
Problema: `_tokenize` scarta `H7`, `g6`, `Ra`, `Rz`, `NC`, `M8`, simboli.
Soluzione, in `ai_assistant/services.py`, dietro flag `OLLAMA_RAG_GLOSSARIO_ENABLED` (default False):
1. Prima della regex, un **pre-pass** con un'unica regex compilata (cache invalidata su modifica glossario via signal + versione in cache Django) che riconosce le varianti **validate** con `usa_nel_rag=True`, incluse le forme brevi/simboliche, ed emette token canonici `gl_<id>` (es. "lamatura", "spot face", "⌴" → `gl_42`).
2. Pattern dimensionali deterministici sempre protetti: classi ISO 286 (`[A-Za-z]{1,2}\d{1,2}` adiacenti a un numero o a ⌀, es. `⌀20 H7` → token `iso286_h7`), filetti metrici (`M\d+(x\d+(\.\d+)?)?`), rugosità (`Ra\s?\d`).
3. Stesso pre-pass su **query e indice** (altrimenti BM25 non combacia). Gli embeddings non cambiano (lavorano sul testo originale) → nessun re-warm necessario per B2.
4. `_tokenize` resta invariato a flag spento (test di non regressione byte-per-byte sui token).

### B2.2 Glossario come conoscenza
Termini `validato` diventano chunk curati (`source="glossario:<id>"`, titolo = termine, testo = definizione + varianti + simbolo + norma_rif) caricati in `_load_knowledge_index` accanto a `_load_curated_knowledge_chunks`, con signature inclusa nella firma dell'indice. Il vecchio `08_glossario.md` resta (sigle portale).

### Acceptance B2
- Nuovo golden `ai_assistant/eval/golden_glossario.jsonl` (≥ 15 domande sintetiche: "cos'è una lamatura", "differenza tra planarità e parallelismo", "cosa indica H7"…), eseguibile con `ai_eval` (aggiungi `--rag-glossario` riusando la logica di `--rag-sgi`).
- `ai_eval --rag-sgi` con flag ON: recall e MRR **≥** baseline A1. Riporta delta.
- Test tokenizer: casi `⌀20 H7`, `M8x1.25`, `Ra 0,8`, `spot face`, termine con accenti, flag OFF = identico a oggi.

---

## A2 — Grafo dei riferimenti incrociati (deterministico, zero AI)

### Modello (`procedure_refresh/models.py`)
```python
class SgiRiferimento(models.Model):
    da_revisione = FK(ProcedureRevision, CASCADE, related_name="riferimenti_uscenti")
    codice_citato = models.CharField(max_length=60, db_index=True)   # come appare normalizzato con _safe_code
    a_documento = FK(ProcedureDocument, SET_NULL, null=True, related_name="riferimenti_entranti")
    sezione = models.CharField(max_length=160, blank=True)           # "§5.3 ..." dove compare
    occorrenze = models.PositiveIntegerField(default=1)
    risolto = models.BooleanField(default=False, db_index=True)      # a_documento trovato
    class Meta: constraints = [UniqueConstraint(fields=["da_revisione","codice_citato","sezione"], name="uq_sgi_rif")]
```
### Estrazione
- Riusa `_CODE_RE` (import dal modulo comando, non copiarlo) adattato per match **in qualunque punto del testo** (versione `search/finditer`, con word boundary); normalizza con `_safe_code`.
- Escludi l'autocitazione (cartiglio, intestazioni già rimosse in A1).
- Ricostruito per revisione a ogni nuova estrazione (delete+insert in transazione).
- Risoluzione `a_documento` per codice esatto, poi per codice disambiguato (`dedup_candidates`).
- Integrazione `Processo`: comando `sgi_collega_processi --dry-run/--apply` che parsa `Processo.procedure` (testo libero) e `fonte_documentale` con la stessa regex e produce la tabella `SgiDocumentoProcesso(documento FK, processo FK, origine="processo_testo", confermato bool)` — proposta da confermare in UI, mai sovrascrittura del testo di `Processo`.

### Acceptance A2
Test su testi sintetici: citazioni multiple, allegati (`IDOR CN 01 Allegato A`), sotto-numeri (`MT CN 125_10`), codici inesistenti (→ `risolto=False`), autocitazione esclusa. Report con: % riferimenti risolti, top 10 codici citati ma inesistenti (segnale di documenti mancanti o refusi: utile alla qualità).

---

## A3 — Profilo documento e clausole ISO (AI propone, umano valida)

### Modelli
```python
class SgiClausola(models.Model):
    NORME = [("9100","EN 9100"),("9001","ISO 9001"),("14001","ISO 14001"),("45001","ISO 45001"),
             ("27001","ISO/IEC 27001"),("pdr125","UNI/PdR 125")]
    norma = models.CharField(max_length=10, choices=NORME, db_index=True)
    codice = models.CharField(max_length=20)            # "8.4.2"
    titolo_breve = models.CharField(max_length=120)     # parole nostre, NON il testo della norma
    ordine = models.PositiveIntegerField(default=0)
    class Meta: constraints = [UniqueConstraint(fields=["norma","codice"], name="uq_sgi_clausola")]

class SgiDocumentoClausola(models.Model):
    ORIGINI = [("manuale",...),("processo",...),("ai",...)]
    STATI = [("proposta",...),("confermata",...),("scartata",...)]
    documento = FK(ProcedureDocument, CASCADE, related_name="clausole_sgi")
    clausola = FK(SgiClausola, PROTECT)
    origine / stato / sezione_evidenza (CharField 160) / deciso_da / deciso_il
    class Meta: constraints = [UniqueConstraint(fields=["documento","clausola"], name="uq_doc_clausola")]

class SgiProfiloDocumento(models.Model):
    documento = OneToOne(ProcedureDocument, CASCADE, related_name="profilo_sgi")
    funzione_responsabile = models.CharField(max_length=150, blank=True)   # ruolo, MAI nomi di persona
    registrazioni = models.TextField(blank=True)                          # moduli/registrazioni richieste, una per riga
    frequenze = models.TextField(blank=True)
    stato = models.CharField(choices=[("bozza_ai",..),("validato",..)], default="bozza_ai")
    validato_da / validato_il
```
- Seed clausole: data-migration con **solo codici e titoli brevi nostri** per 9100/45001/27001/14001 (le PdR125 a STOP se servono). Le clausole già scritte in `Processo.punti_*` vengono riconciliate (`origine="processo"`, `stato="proposta"`).

### Pipeline AI
- Comando `sgi_profila [--solo CODICE] [--limit N] [--dry-run]` + task per documento (< 90 s, un documento per task, accodamento a catena).
- Input al modello: **solo** intestazione documento + elenco sezioni (titoli `§`) + i primi N caratteri di ogni sezione (budget totale ≤ `OLLAMA_CHAT_MAX_PROMPT_CHARS` × fattore configurabile), + elenco chiuso delle clausole disponibili (codice + titolo breve), + `lezioni_testo(modulo="sgi", azione="profilo")`.
- Output richiesto: **solo JSON** `{clausole:[{norma,codice,sezione_evidenza}], funzione_responsabile, registrazioni:[...], frequenze:[...]}`; validazione rigida: clausole fuori elenco scartate, `sezione_evidenza` deve esistere tra le sezioni del documento, campi testuali troncati, nessun nome proprio di persona (scarta se il valore matcha un utente/dipendente noto).
- Registra con `registra_proposta(modulo="sgi", azione="profilo", oggetto_ref=documento.code, ...)`; nessuna scrittura su `SgiDocumentoClausola` confermata.
- Documenti con `escludi_dal_rag=True` esclusi anche qui.
- Rispetta lo slot AI (`_acquire_ai_slot`) per non saturare la chat degli utenti; esecuzione consigliata notturna.

### UI
Tab "Profilo SGI" nella scheda documento di `procedure_refresh`: proposte AI evidenziate, accetta/correggi/scarta per riga (HTMX) → `registra_decisione`. Permesso: la risorsa ACL che oggi gestisce i documenti SGI (verifica in `procedure_refresh/acl_bootstrap.py`; STOP se ambigua).

### Acceptance A3
Test con LLM **mockato**: JSON valido, JSON malformato (fail-safe, nessuna proposta), clausola inesistente scartata, sezione inesistente scartata, nome persona scartato, documento escluso saltato, decisione registrata. Report: su 10 documenti reali scelti da Brizio, % proposte accettate senza modifiche (misura, non obiettivo).

---

## A4 — Viste, tool live, golden

### Viste (SSR + HTMX, sotto `procedure_refresh`)
1. **Impatto modifica** `/procedure-refresh/sgi/impatto/<code>/`: documenti che citano il codice (A2), processi collegati, clausole confermate; utile prima di revisionare un documento.
2. **Copertura clausole** `/procedure-refresh/sgi/copertura/?norma=9100`: matrice clausola → documenti confermati; clausole senza alcun documento evidenziate; export CSV (con la protezione CSV-injection già presente in `procedure_refresh/test_csv_injection.py`).
3. **Salute corpus**: riferimenti non risolti, documenti senza testo/OCR, documenti senza profilo validato, ultima estrazione.

### Tool live assistente
Estendi `_procedure_context` in `ai_assistant/tools.py` (non creare un tool parallelo): intenti "chi cita X / cosa devo aggiornare se modifico X / quali documenti coprono la clausola N" → risposta da DB (A2/A3, solo dati **confermati**), con fonti. Aggiungi la voce in `RUNTIME_TOOL_CATALOG` e una `AiToolPrivacyReview` (nessun dato personale: annotalo) come richiesto dalla governance; gating con `sgi_rag_access`.

### Golden
Aggiungi a `golden_sgi.jsonl` ≥ 10 domande sintetiche su riferimenti/impatto/copertura e un test che verifica il routing al tool.

### Acceptance A4
Test viste (200 con permesso, 403 senza, query count limitato con `assertNumQueries` sulle viste matrice), tool live con dati sintetici, `ai_eval` completo: routing + `--rag` + `--rag-sgi` + `--rag-glossario` **senza regressioni** rispetto all'ultimo STOP.

---

## 8. Feature flag e settings nuovi (tutti in `config/settings/base.py`, documentati in `docs/ai/RUNBOOK_DEPLOY_AI.md`)

| Setting | Default | Fase |
|---|---|---|
| `PROCEDURE_REFRESH_SGI_EXTENSIONS` | `[".pdf"]` | A1 |
| `PROCEDURE_REFRESH_SGI_PREFER_PDF` | `True` | A1 |
| `SGI_ESTRAZIONE_PERSISTITA_ENABLED` | `False` | A1 |
| `SGI_OCR_ENABLED` | `False` | A1 |
| `OLLAMA_RAG_SGI_CHUNK_CHARS` | = `OLLAMA_RAG_CHUNK_CHARS` | A1 |
| `OLLAMA_RAG_GLOSSARIO_ENABLED` | `False` | B2 |
| `SGI_PROFILAZIONE_AI_ENABLED` | `False` | A3 |

---

## 9. Formato del Report di fase (ad ogni STOP)

```
## Report fase <ID> — <data>
Branch / commit: ...
File modificati: ... (anche CHANGELOG e docs/moduli)
Migrazioni: nome + reversibilità verificata (migrate avanti/indietro su DB test)
Test eseguiti: comando esatto + esito (n. test, durata)
Metriche ai_eval: tabella baseline vs ora (recall, MRR per KB / SGI / glossario)
Decisioni prese in autonomia: elenco + motivazione
Decisioni richieste a Brizio: elenco numerato con opzione consigliata
Rischi / debiti tecnici introdotti
Passi di deploy in prod (setting da impostare, comandi da lanciare, ordine)
```

---

## 10. Definition of Done complessiva
- Tutte le fasi chiuse con report; flag documentati; CHANGELOG e `docs/moduli/procedure_refresh.md`, `docs/moduli/glossario_tecnico.md`, `docs/ai/15_AI_NEXT_STEPS.md` (stato 3.1/3.3) aggiornati.
- Nessun testo reale di documenti, clienti o norme nel repo.
- `ai_eval` senza regressioni rispetto alla baseline F0; delta documentati.
- Il portale funziona identico a oggi con tutti i flag OFF (test di non regressione dedicati).
