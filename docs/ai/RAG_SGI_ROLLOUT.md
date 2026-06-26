# RAG SGI — Riepilogo e runbook di rollout

Ampliamento mirato del Copilot esistente (`ai_assistant`, Ollama) per rispondere **con
citazione** sul corpus documentale SGI già presente nel portale. **Non** è un modulo
nuovo, non introduce vector DB. Read-only: «l'AI propone/cita, l'umano firma».

Esempio obiettivo: *«in che MT si fa riferimento ai timbri?»* → *«MT CN 06 Rev.7 §4.2»*.

## Cosa fa (F1–F3)

- **F1 — Loader** (`ai_assistant/services.py::_load_sgi_document_chunks`): indicizza le
  **specifiche in vigore** (`gestione_specifiche.Specifica`, stato S3 `in_validita`) e le
  **revisioni procedura correnti** (`procedure_refresh.ProcedureRevision.is_current` su
  documento attivo). Fonti citabili stabili `spec:{codice}#rev{rev}` / `proc:{code}#rev{rev}`,
  titolo `codice Rev.x — §sezione` (chunking sezione-aware). Estrazione PDF (pymupdf)
  cachata per `file_hash`. On-premise: procedure solo da **file server locale**; SharePoint
  e PDF illeggibili → **fallback metadati** (sempre citabili). Tutto fail-safe.
- **F2 — Citazione + warm**: il prompt RAG impone, per fonti `spec:`/`proc:`, di citare
  codice+revisione+sezione e di dichiarare «Non disponibile nei documenti indicizzati» se il
  contesto non basta. Comando `index_sgi_documents` + task `run_index_sgi_documents`.
- **F3 — Ottimizzazione misurata**: stemming italiano opt-in; golden set SGI +
  `ai_eval --rag-sgi` (recall@k/MRR); modello embedding parametrizzato e dimension-safe.

## Settings (tutti con default sicuri, in `config/settings/base.py`)

| Setting | Default | Note |
| --- | --- | --- |
| `OLLAMA_RAG_SGI_ENABLED` | `True` | Indicizza il corpus SGI. Opt-out con `0`. |
| `OLLAMA_RAG_SGI_MAX_SPECS` | `300` | Cap specifiche in vigore indicizzate. |
| `OLLAMA_RAG_SGI_MAX_PROCS` | `300` | Cap revisioni procedura correnti. |
| `OLLAMA_RAG_SGI_MAX_PDF_CHARS` | `200000` | Tetto testo estratto per documento. |
| `OLLAMA_RAG_SGI_TEXT_CACHE_TTL` | `2592000` (30g) | TTL cache testo estratto per `file_hash`. |
| `OLLAMA_RAG_STEMMING_ENABLED` | `False` | Stemming italiano (Snowball). **Misurare prima di attivare.** |
| `OLLAMA_EMBED_ENABLED` | `False` | Retrieval ibrido (embeddings). Opt-in, richiede pull modello. |
| `OLLAMA_EMBED_MODEL` | `nomic-embed-text` | Confrontabile con `bge-m3` (1024d). |
| `OLLAMA_RAG_HYBRID_RRF_K` | `60` | Fusione RRF BM25+semantico (non modificare senza misura). |

Il chunking SGI riusa `OLLAMA_RAG_CHUNK_CHARS` / `OLLAMA_RAG_CHUNK_OVERLAP_CHARS`.

## Runbook di rollout (prod)

> Il `.env` da modificare in prod è **solo** quello persistente (`config\.env`), non
> l'attivo `current\django_app\.env` (riscritto dal deploy).

1. **Verifica BM25-only (zero costo, già attivo)** — con i default, l'SGI è già indicizzato
   in BM25 al primo utilizzo. Misura la copertura sul corpus reale:
   ```powershell
   python django_app\manage.py ai_eval --rag-sgi --json
   ```
   `sgi_chunks` nel summary > 0 conferma che le specifiche/procedure correnti sono indicizzate.
   Cura `django_app/ai_assistant/eval/golden_sgi.jsonl` aggiungendo una riga per ogni documento
   SGI tipico (domanda → frammento codice atteso) e rimisura recall@k/MRR.

2. **(Opzionale) Stemming italiano** — confronta prima/dopo, poi attiva solo se migliora:
   ```powershell
   python django_app\manage.py ai_eval --rag-sgi --json                  # baseline
   $env:OLLAMA_RAG_STEMMING_ENABLED='1'; python django_app\manage.py ai_eval --rag-sgi --json
   ```
   Se il recall sale senza regressioni, imposta `OLLAMA_RAG_STEMMING_ENABLED=1` nel `.env`
   persistente (la dipendenza `snowballstemmer` è in `requirements.txt`; fail-safe se assente).

3. **(Opzionale) Retrieval ibrido (embeddings)** — solo provider Ollama nativo:
   ```powershell
   ollama pull nomic-embed-text        # oppure: ollama pull bge-m3
   ```
   Imposta nel `.env` persistente `OLLAMA_EMBED_ENABLED=1` (e `OLLAMA_EMBED_MODEL=bge-m3`
   se hai scelto bge-m3), poi riavvia Django/IIS. Confronta i modelli con
   `ai_eval --rag-sgi`. Cambiare modello richiede di rigenerare l'indice (passo 4): la cache
   vettori è per `(modello, content-hash)` e il coseno è dimension-safe, quindi nessuna
   contaminazione tra modelli di dimensione diversa.

4. **Warm dell'indice + embeddings** — la prima build è la più costosa (estrazione PDF +
   embedding); poi è in cache. Lancialo a mano dopo aver attivato gli embeddings:
   ```powershell
   python django_app\manage.py index_sgi_documents --json
   ```
   **Schedulazione**: la schedule `ai_index_sgi_documents` (django-q2, CRON 03:30, fail-safe)
   è già registrata in `automazioni/schedules.py`; si attiva al prossimo deploy con
   `python manage.py setup_q_schedules`. Anticipa la build notturna così non è la prima chat
   della giornata a pagarla.

## Procedure su file server / share di rete (lettura del corpo PDF)

Le procedure (`procedure_refresh.ProcedureRevision`) non hanno il PDF dentro il portale: il
corpo viene letto **solo** quando `source_type=fileserver` e `source_path` punta a un file
`.pdf` esistente e leggibile **dal processo Django** (e dal cluster django-q per il warm
schedulato). SharePoint (`source_type=sharepoint`) e file non raggiungibili → **fallback
metadati** (il documento resta citabile per codice/titolo, ma senza §sezione). Mai un blocco.

Due regole **non negoziabili** perché la lettura da share funzioni in prod:

1. **Percorso UNC completo, NON la lettera di drive mappato.**
   - ✅ `\\pclogsys\sgi\procedure\MT_CN_06.pdf`
   - ❌ `Y:\procedure\MT_CN_06.pdf`
   Le lettere mappate (`Y:`, `X:`) esistono solo nella sessione interattiva di un utente; un
   servizio/app-pool che gira non-interattivo **non le vede** → la lettura fallirebbe. Il path
   UNC non dipende da alcun mapping. Imposta quindi `ProcedureRevision.source_path` in UNC.

2. **L'account del servizio deve avere `Read` sulla share** (a livello share **e** NTFS):
   l'identità dell'**app pool IIS** (Django/Waitress) **e** l'account del **Task Scheduler
   `QCluster_PROD`** (django-q). Se la share è autenticata e l'account non ha accesso, la
   lettura fallisce e si ripiega sui metadati.

Lo stesso vale per le **specifiche** se `GESTIONE_SPECIFICHE_PRIVATE_ROOT` è su una share
(qui però il PDF è letto via storage Django, non via `source_path`).

Verifica che la lettura del corpo funzioni: dopo `index_sgi_documents --json`, nel summary
`sgi_chunks` deve essere > 0 e maggiore del numero di documenti se i PDF sono spezzati in più
sezioni (segno che ha indicizzato il **corpo**, non solo i metadati). Performance: leggere
molti PDF via SMB a ogni rebuild è costoso → la doppia cache (testo per `file_hash`, hash per
`(pk, updated_at)`) evita di rileggere la share finché i file non cambiano, e il warm notturno
assorbe la prima passata.

## Verifica funzionale

- In chat, una domanda su un documento SGI deve produrre una risposta **citata**
  (es. «… come da MT CN 06 Rev.7 §4.2») con la fonte `spec:`/`proc:` nei chip.
- Se il contesto non basta, la risposta deve dire «Non disponibile nei documenti indicizzati»
  invece di inventare codici/revisioni.

## Vincoli rispettati

On-premise (nessuna chiamata cloud), fail-safe assoluto (PDF corrotto / Ollama offline →
chunk saltato o BM25-only, mai un blocco in chat), solo revisioni correnti (nessun documento
obsoleto nelle risposte), read-only (l'AI non scrive sui documenti). Nessuna modifica ad ACL,
routing o privacy dei tool di dominio esistenti.
