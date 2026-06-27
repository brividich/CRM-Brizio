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
3. **ollama.chat / ollama.embed** — modello assente ⇒ `ollama pull <modello>` sul
   host `OLLAMA_BASE_URL` (in prod è un host dedicato, non localhost).
4. **rag.sgi_chunks** — `sgi_chunks` deve essere > 0. FAIL ⇒ corpus SGI non
   indicizzato: vedi punto 6 + `index_sgi_documents`.
5. **q.schedules / q.cluster** — mancano ⇒ `manage.py setup_q_schedules`; cluster
   giù ⇒ riavvia `QCluster_PROD` (Task Scheduler).
6. **sgi.procedures** — `source_path` deve essere **UNC** (`\\host\share\...`, non
   `Y:\...`) e leggibile. La lettura reale la fanno l'**app pool IIS** e
   **QCluster_PROD**: se hanno identità diverse, dai loro `Read` sulla share.

## Promemoria (emersi dalla ricognizione 2026-06-27)
- Modello embed effettivo in prod = **bge-m3** (1024d). Se lo cambi, **rigenera**
  l'indice: `manage.py index_sgi_documents --json --settings=config.settings.prod`.
- Il `.env` da modificare è **solo** quello persistente `config\.env`, mai l'attivo
  `current\django_app\.env` (riscritto dal deploy).

Runbook completo del rollout RAG SGI: `docs/ai/RAG_SGI_ROLLOUT.md`.
