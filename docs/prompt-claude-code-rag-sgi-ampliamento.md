# Prompt Claude Code — Ampliamento RAG SGI dentro `ai_assistant` (NOVICROM HUB)

> Incolla dalla root di NOVICROM HUB (CRM-Brizio). NON creare nuovi moduli.
> È un'**estensione mirata** dell'assistente esistente. Esecuzione **a fasi con
> STOP di approvazione**: non procedere senza il mio "ok".

---

## OBIETTIVO
Far sì che il Copilot esistente (`ai_assistant`, Ollama `qwen2.5:14b-instruct`)
risponda con accuratezza e **citazione** a domande sul corpus documentale SGI
(es. *"in che MT si fa riferimento ai timbri?"* → *"MT CN 06 Rev.7 §4.2"*),
indicizzando i documenti SGI già presenti nel portale e ottimizzando il retrieval.
**Ampliamento + ottimizzazione dell'esistente, non un modulo nuovo.**

## CONTESTO CODICE (già verificato — non reinventare)
- RAG in `ai_assistant/services.py`: `_load_knowledge_index()` aggrega chunk da
  file (`_iter_knowledge_files`→`_chunk_document`→`_split_long_section`) e DB
  curato (`_load_curated_knowledge_chunks` su modello `AiKnowledgeEntry`).
  `_build_index` precalcola BM25 (IDF/avgdl). Retrieval ibrido RRF in
  `_select_chunk_indices`/`_rrf_fuse` (k=`OLLAMA_RAG_HYBRID_RRF_K`, default 60),
  attivo solo se `embeddings_enabled()` (`OLLAMA_EMBED_ENABLED`), altrimenti
  BM25-only. Embedding via `_ollama_embed_texts` (`/api/embed` poi `/api/embeddings`),
  cache per content-hash su DatabaseCache. Chunk = `KnowledgeChunk(source, title,
  content, tokens)`; la citazione esce da `KnowledgeContext.sources`.
- Tokenizzazione: `_tokenize` con `_fold_accents` + `_RAG_STOPWORDS` (NESSUNO stemmer).
- Registri documentali SGI già esistenti:
  - `gestione_specifiche.models.Specifica` (codice, revisione, titolo, tipo, fonte,
    cliente, tag, `allegato` FileField PDF, `revisione_precedente`, stato/FSM).
    Estrazione PDF già fatta in `gestione_specifiche/ai_copilota.py::_estrai_testo_pdf`.
  - `procedure_refresh.models.ProcedureDocument` / `ProcedureRevision`
    (`revision_code`, `file_hash`, `is_current`, `source_path/url`, `file_name`).
- Stack: Django 5.2.13, django-ninja, django-q2, django-htmx, mssql-django (SQL
  Server prod / SQLite dev), pymupdf, `requests`. **Nessun vector DB, per scelta.**

## VINCOLI NON NEGOZIABILI (coerenza con l'esistente)
1. **Niente nuovo modulo, niente vector DB, niente nuove dipendenze pesanti.**
   Gli embedding restano via Ollama nativo; il vettore non esce dal processo.
2. **Fail-safe assoluto**: qualunque errore (PDF illeggibile, Ollama offline,
   modello embedding assente) deve degradare in modo silenzioso (BM25-only / chunk
   saltato), **mai** bloccare una risposta in chat. Segui lo stile try/except già
   presente nei loader.
3. **Solo revisioni correnti** nel RAG (Specifica corrente; `ProcedureRevision.
   is_current=True`): nessuna revisione obsoleta nelle risposte.
4. **On-premise**: nessuna chiamata cloud. SQL Server compatibile. Tutto in italiano.
5. **Riuso**: estrazione PDF, chunking, cache e pattern loader già esistenti — non
   duplicarli.

## INTERVENTI

### 1. Nuovo loader documenti SGI (`ai_assistant/services.py`)
Aggiungi `_load_sgi_document_chunks() -> list[KnowledgeChunk]` sul modello esatto
di `_load_curated_knowledge_chunks`, e agganciala in `_load_knowledge_index()`
insieme alle sorgenti attuali. Deve:
- Iterare le `Specifica` correnti e le `ProcedureRevision` con `is_current=True`.
- Estrarre il testo PDF (riusa il pattern `_estrai_testo_pdf`), con **cache del
  testo estratto per `file_hash`** su DatabaseCache (per `Specifica` calcola l'hash
  del file se assente) — così non riestrae a ogni rebuild dell'indice.
- **Chunking sezione-aware**: rileva sezioni/paragrafi numerati (regex tipo
  `^\d+(\.\d+)*` e titoli) e riusa `_split_long_section` per lo split lungo+overlap.
- Per ogni chunk impostare:
  - `source` = handle citabile stabile, es. `spec:{codice}#rev{revisione}` /
    `proc:{code}#rev{revision_code}`;
  - `title` = `f"{codice} Rev.{revisione} — {sezione}"` (così la citazione è leggibile);
  - `content` = testo della sezione;
  - `tokens` = `Counter(_tokenize(...))` come gli altri loader.
- Cap dedicati e configurabili (il corpus SGI supera i 200 di `OLLAMA_RAG_MAX_DB_ENTRIES`).

### 2. Citazione nelle risposte
Dove `chat_with_ollama` costruisce il system prompt / il blocco RAG: aggiungi la
regola che, quando i source sono SGI (`spec:`/`proc:`), la risposta **deve** citare
codice + revisione + sezione, e se il contesto non basta dichiararlo
("non disponibile nei documenti indicizzati"). Non toccare il comportamento sugli
altri domini.

### 3. Ottimizzazione retrieval (con misurazione)
- **Accendi l'ibrido**: rendi `OLLAMA_EMBED_ENABLED=True` configurabile e documenta
  il pull del modello. NON cambiare la logica RRF (già corretta).
- **Modello embedding**: parametrizza per confrontare `bge-m3` (1024d) vs
  `nomic-embed-text`; verifica allineamento dimensioni/`/api/embed`.
- **Stemming italiano (opt-in, misurato)**: aggiungi a `_tokenize` uno stemmer
  Snowball italiano dietro flag `OLLAMA_RAG_STEMMING_ENABLED` (default False),
  dipendenza minima `snowballstemmer` (pure-python). Applica lo stesso stemming a
  query e chunk. Fail-safe se la dipendenza manca.
- **Tuning** esposto da settings: `OLLAMA_RAG_HYBRID_RRF_K`, chunk chars/overlap,
  numero chunk selezionati.

### 4. Valutazione (`ai_assistant/management/commands/ai_eval.py`)
Estendi/aggiungi un set di **golden questions SGI** (file dati, es.
`ai_assistant/eval/golden_sgi.jsonl`: domanda → documento atteso, es.
"timbri" → `MT CN 06`). Il comando deve riportare **recall@k / hit-rate** per
misurare prima/dopo ogni leva (copertura, ibrido on/off, modello embedding,
stemming on/off). Niente rete nei test.

### 5. Comando di indicizzazione / warm
Aggiungi un management command (es. `index_sgi_documents`) che forza la build
dell'indice + il precalcolo/caching degli embedding del corpus SGI (la prima build
è la più costosa; poi è in cache per `file_hash`/content-hash). Schedulabile via
django-q2.

## SETTINGS (`config/settings/base.py`) — aggiungi, con default sicuri
`OLLAMA_RAG_SGI_ENABLED` (True), cap dedicati per il loader SGI,
`OLLAMA_RAG_STEMMING_ENABLED` (False). Lascia invariati i default esistenti.
NON impostare `OLLAMA_EMBED_ENABLED=True` di default: va acceso esplicitamente in
`.env` dopo il pull del modello.

## TEST (pytest, stile esistente)
- Loader SGI: estrazione+chunking deterministici, solo revisioni correnti, cache per
  `file_hash`, fail-safe su PDF illeggibile/Ollama offline.
- Citazione: la risposta su source SGI riporta codice/revisione/§; "non disponibile"
  quando il contesto manca.
- Stemming: unificazione timbri/timbro/timbrare quando attivo; nessun effetto quando off.
- Eval: il comando calcola recall@k su un golden set fittizio.
- Ollama/embedding **mockati**; nessun test tocca la rete o la prod.

## NON-GOAL
Vector DB esterni; nuovi moduli; persistenza/scrittura sui documenti dall'AI
(resta read-only, "AI propone, umano firma"); modifica del comportamento dei tool
di dominio esistenti.

## CONVENZIONI
Segui lo stile dei loader esistenti (try/except difensivi, DatabaseCache,
`_tokenize`/`_fold_accents`, `_split_long_section`). Docstring/commenti in italiano.
Modifiche minime e chirurgiche: estendere, non riscrivere.

---

## PIANO A FASI (STOP dopo ognuna — attendi "ok")
**F0** — Leggi `ai_assistant/services.py` (`_load_knowledge_index`, loader, retrieval),
`gestione_specifiche/ai_copilota.py`, i modelli `Specifica`/`ProcedureRevision`, e
dove `chat_with_ollama` costruisce il prompt. Proponi il punto d'innesto preciso del
loader e il formato `source`/`title` per le citazioni. **STOP.**
**F1** — Implementa `_load_sgi_document_chunks` + cache estrazione + aggancio in
`_load_knowledge_index` + cap settings. Test loader. **STOP.**
**F2** — Regola di citazione nel prompt + comando `index_sgi_documents`. Mostra una
risposta citata reale su un documento d'esempio. **STOP.**
**F3** — Ottimizzazione: flag embedding/modello, stemming opt-in, golden set +
`ai_eval` con recall@k. Riporta i numeri prima/dopo. **STOP.**
**F4** — Riepilogo, settings documentati, note di rollout (pull modello embedding,
schedulazione indicizzazione).

Inizia dalla **F0**.
