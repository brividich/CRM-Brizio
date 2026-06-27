# AI health-check prod — runbook breve

Verifica se l'assistente AI (chat + RAG citabile SGI) gira "a piena potenza" in
produzione. **Read-only.** Eseguire **sul server** `pclogsys`.

## Esecuzione
```powershell
# da C:\PortaleNovicrom\prod\current  (o passa i path come parametri)
.\tools\ai_healthcheck_prod.ps1
.\tools\ai_healthcheck_prod.ps1 -SkipSgiEval   # salta l'eval pesante (PDF/embeddings)
```
Output: una riga PASS/WARN/FAIL per controllo + riepilogo finale.

## Cosa guarda (e cosa fare se FAIL/WARN)
1. **settings.rag_src** — le sorgenti RAG devono includere `ai_assistant/knowledge`.
   FAIL ⇒ il `.env` persistente sovrascrive `OLLAMA_RAG_SOURCE_PATHS`: rimuovilo o
   includi la KB curata.
2. **env.dupes** — chiavi AI duplicate nel `.env` (vince l'ultima, ma è un bug
   latente). WARN ⇒ ripulisci il `.env` **persistente** (`config\.env`).
3. **ollama.chat / ollama.embed / tei.embed** — modello chat assente ⇒
   `ollama pull <modello>` sul host `OLLAMA_BASE_URL` (host dedicato, non localhost).
   Gli **embeddings** dipendono dal backend: con `RAG_EMBED_BACKEND=ollama` il modello
   embed deve stare in Ollama; con `=openai` (**TEI**) lo script sonda l'endpoint
   `RAG_EMBED_OPENAI_BASE_URL/v1/embeddings` (TEI su Docker, tipicamente porta 8081).
4. **rag.sgi_chunks** — `sgi_chunks` deve essere > 0. FAIL ⇒ corpus SGI non
   indicizzato: vedi punto 6 + `index_sgi_documents`.
5. **q.schedules / q.cluster** — mancano ⇒ `manage.py setup_q_schedules`; cluster
   giù ⇒ riavvia `QCluster_PROD` (Task Scheduler).
6. **sgi.procedures** — `source_path` deve essere **UNC** (`\\host\share\...`, non
   `Y:\...`) e leggibile. La lettura reale la fanno l'**app pool IIS** e
   **QCluster_PROD**: se hanno identità diverse, dai loro `Read` sulla share.

## Passaggio a TEI (embeddings su GPU, target di prod)
Per usare TEI invece di Ollama-nativo per gli embeddings, nel `.env` **persistente**:
```
OLLAMA_EMBED_ENABLED=1
RAG_EMBED_BACKEND=openai
RAG_EMBED_OPENAI_BASE_URL=http://10.0.0.34:8081
RAG_EMBED_OPENAI_MODEL=BAAI/bge-m3
# RAG_EMBED_OPENAI_API_KEY=        # vuoto: TEI senza auth
```
e **rimuovi** le righe duplicate `OLLAMA_EMBED_MODEL`/`OLLAMA_EMBED_ENABLED`. Poi:
TEI su (Docker, porta 8081) → riavvia IIS → **rigenera l'indice** (sotto). Sul server
Ollama imposta `OLLAMA_MAX_LOADED_MODELS=1` per liberare VRAM (gli embed sono su TEI).
Topologia e tuning completi: `docs/ai/OLLAMA_GPU_TUNING.md`.

## Promemoria (emersi dalla ricognizione 2026-06-27)
- Cambiando modello/backend di embedding **rigenera** l'indice (la cache vettori è per
  nome-modello): `manage.py index_sgi_documents --json --settings=config.settings.prod`.
- Il `.env` da modificare è **solo** quello persistente `config\.env`, mai l'attivo
  `current\django_app\.env` (riscritto dal deploy).

Runbook completo del rollout RAG SGI: `docs/ai/RAG_SGI_ROLLOUT.md`.
