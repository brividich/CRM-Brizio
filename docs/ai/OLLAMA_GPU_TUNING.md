# Tuning GPU / modelli AI — Ollama + TEI (PCGAVANCINI)

Runbook operativo per ottimizzare l'uso della GPU dell'Assistente AI. Le leve sono
di **due tipi**: (1) *lato portale* (settings Django, già nel repo) e (2) *lato
server* su PCGAVANCINI (variabili d'ambiente di Ollama / parametri TEI). Le seconde
**non stanno nel repo**: vanno applicate sul server e validate con `nvidia-smi`.

> Principio: l'Assistente resta on-premise, fail-safe e read-only. Queste sono
> ottimizzazioni di risorse, **nessun cambio di comportamento** della chat.

## Topologia attuale

- **GPU**: NVIDIA RTX A4000 **16 GB** su `PCGAVANCINI` (10.0.0.34), dedicata.
- **Ollama** (chat) su `:11434`, modello `qwen2.5:14b-instruct` (~9 GB in Q4), avviato
  come servizio Windows via **NSSM**.
- **TEI** (Text Embeddings Inference, embeddings) su `:8081`, modello `BAAI/bge-m3`
  (~2-3 GB), in **Docker** con `--gpus all`.
- Il portale parla con Ollama per la chat e con TEI per gli embeddings
  (`RAG_EMBED_BACKEND=openai`, `RAG_EMBED_OPENAI_BASE_URL=http://10.0.0.34:8081`).

**Budget VRAM (stima):** Ollama 14B (~9 GB) + TEI bge-m3 (~2-3 GB) ≈ **11-12 GB**,
restano ~**4-5 GB** per la KV-cache della chat. È il margine da proteggere.

## Punto chiave: gli embeddings sono su TEI, non in Ollama

Da quando il backend embeddings è TEI, **Ollama deve ospitare un solo modello** (la
chat). Le vecchie note che parlavano di `OLLAMA_MAX_LOADED_MODELS=2` (chat + bge-m3 in
Ollama) sono **superate**: tenere 2 slot riserva VRAM inutilmente.

## 1) Lato server — variabili d'ambiente Ollama (PCGAVANCINI)

| Variabile | Valore consigliato | Perché |
|---|---|---|
| `OLLAMA_MAX_LOADED_MODELS` | `1` | Embeddings su TEI → a Ollama serve solo la chat. Libera VRAM. |
| `OLLAMA_NUM_PARALLEL` | `1` | Una richiesta chat alla volta: evita più contesti concorrenti in VRAM (causa tipica dei blocchi sotto carico). |
| `OLLAMA_FLASH_ATTENTION` | `1` | Attenzione più efficiente: **meno VRAM** per la KV-cache e **prefill più rapido** sulle domande lunghe (contesto RAG). |
| `OLLAMA_KV_CACHE_TYPE` | `q8_0` | KV-cache quantizzata a 8 bit: **forte risparmio VRAM** con perdita di qualità trascurabile → rende sicuro un `num_ctx` ampio. Richiede flash attention. |
| `OLLAMA_KEEP_ALIVE` | `30m` | Tiene il modello caldo; abbinato al warmup schedulato (ogni 25′) il primo token non paga il caricamento. |

> Nota: `OLLAMA_KEEP_ALIVE` esiste anche come setting portale (passato a ogni
> richiesta). Tenere i due valori coerenti.

### Come applicarle (servizio NSSM su Windows)

Ollama gira come servizio `Ollama` via NSSM. Aggiungere le env al servizio e riavviare:

```powershell
# Aggiunge/aggiorna le variabili d'ambiente del servizio Ollama (NSSM)
nssm set Ollama AppEnvironmentExtra `
  OLLAMA_MAX_LOADED_MODELS=1 `
  OLLAMA_NUM_PARALLEL=1 `
  OLLAMA_FLASH_ATTENTION=1 `
  OLLAMA_KV_CACHE_TYPE=q8_0 `
  OLLAMA_KEEP_ALIVE=30m
nssm restart Ollama
```

In alternativa, variabili **di sistema** (`Pannello di controllo → Variabili
d'ambiente`) + riavvio del servizio. Verificare che il processo le veda (sotto).

## 2) Lato TEI (Docker)

- Avvio tipico (immagine per l'architettura GPU corretta), con `--auto-truncate` per
  non far fallire i batch su chunk lunghi:

  ```bash
  docker run -d --gpus all -p 8081:80 --name tei \
    ghcr.io/huggingface/text-embeddings-inference:<arch> \
    --model-id BAAI/bge-m3 --auto-truncate
  ```

- TEI è un server pensato per il batch: non si pianta come Ollama sotto warm massicci.
- Se la VRAM è al limite, valutare di limitare il batch lato TEI; di norma bge-m3 sta
  bene nei ~2-3 GB.

## 3) Lato portale (già nel repo — `config/settings/base.py`)

| Setting | Default | Note |
|---|---|---|
| `OLLAMA_NUM_PREDICT` | `1536` | **Cap esplicito** della generazione: evita risposte runaway che occupano il worker per tutto il timeout e allocano KV-cache. Ampio per risposte discorsive. `0` = nessun cap dal portale. |
| `OLLAMA_NUM_CTX` | `16384` | Finestra di contesto. Con flash attention + KV-cache `q8_0` è sostenibile sull'A4000; abbassarlo (es. `12288`) libera ulteriore VRAM se serve. |
| `OLLAMA_KEEP_ALIVE` | `30m` | Vedi sopra. |
| `OLLAMA_REQUEST_TIMEOUT_SECONDS` | `180` | Tempo massimo per risposta; il cap su `num_predict` aiuta a non avvicinarlo. |

Override sempre possibile da `.env` (in prod: `config\.env` persistente).

## Verifica

Scorciatoia: `tools\ai_healthcheck_prod.ps1` (già nel repo) controlla in un colpo
Ollama/embeddings/endpoint. Usalo come primo check end-to-end, poi i comandi mirati:

```powershell
# 0) Healthcheck complessivo (Ollama + embeddings + RAG)
.\tools\ai_healthcheck_prod.ps1

# 1) Ollama vede le env? (processo)
Get-Process ollama | ForEach-Object { $_.StartInfo }   # oppure controlla via nssm

# 2) Modelli caricati e VRAM occupata da Ollama
ollama ps

# 3) Stato GPU complessivo (Ollama + TEI)
nvidia-smi

# 4) TEI risponde
curl http://10.0.0.34:8081/health

# 5) Warmup + latenza primo token (dal server del portale)
python django_app\manage.py warmup_ollama --json
```

Atteso dopo il tuning: in `nvidia-smi` **un solo modello chat** lato Ollama (no
secondo modello di embedding), VRAM totale con margine, latenza del primo token
stabile (modello caldo). `ollama ps` mostra `qwen2.5:14b-instruct` con TTL ~30m.

## Rollback

Tutte le leve sono reversibili:
- Server: rimuovere/azzerare le env e `nssm restart Ollama` (Ollama torna ai default).
- Portale: rimettere `OLLAMA_NUM_PREDICT=0` (o altro) in `.env`.
Nessuna migrazione, nessun dato toccato.

## Caveat

- `OLLAMA_KV_CACHE_TYPE=q8_0` richiede `OLLAMA_FLASH_ATTENTION=1`. Se la qualità
  percepita cala, tornare a KV-cache full (rimuovere la variabile).
- Le misure di VRAM/latenza vanno fatte **sull'hardware reale**: i numeri di questa
  guida sono stime per dimensionare, non risultati misurati.
- Non ridurre il modello chat per "fare spazio": la capacità del 14B è voluta. Per
  liberare VRAM agire prima su KV-cache (`q8_0`) e `max_loaded_models=1`.

## 4) Benchmark qualità argomentazione (chat) — Approccio A/B

Riferimento: `docs/superpowers/specs/2026-07-09-assistente-ai-qualita-argomentazione-design.md`.
Golden set: `docs/ai/GOLDEN_ARGOMENTAZIONE_CHAT.md` (12 domande, giudizio a occhio, nessun punteggio automatico).

### Validare un cambio di prompt/config (Approccio A)

1. Annotare le risposte del golden set **prima** della modifica (screenshot o copia-incolla, non serve altro).
2. Applicare la modifica (`.env` o `base.py` + redeploy).
3. Rilanciare lo stesso golden set, confrontare risposta per risposta col criterio di giudizio nel file del golden set.
4. Tenere d'occhio `AiChatFeedback` (tasso di 👎) nelle 1-2 settimane successive come conferma a lungo termine.

### Benchmark di un modello alternativo (Approccio B)

1. Scaricare il modello candidato su PCGAVANCINI, stessa classe di taglia (~9 GB in Q4, budget VRAM invariato — vedi tabella VRAM sopra):
   ```powershell
   ollama pull <nome-modello-candidato>
   ```
2. Puntare `OLLAMA_CHAT_MODEL=<nome-modello-candidato>` in un `.env` di **test**, mai direttamente in prod. Riavviare il servizio portale.
3. Rilanciare il golden set su questo modello, e in parallelo `manage.py ai_eval --rag` / `--rag-sgi` per verificare che il routing/retrieval non peggiori.
4. **Criterio di promozione**: si cambia il modello in produzione solo se il candidato è chiaramente migliore su argomentazione/coerenza a giudizio umano sul golden set, e non peggiora latenza (`ollama ps` / warmup) o recall RAG in modo sensibile. In caso di dubbio, si resta su `qwen2.5:14b-instruct`.
5. Rollback: ripristinare `OLLAMA_CHAT_MODEL=qwen2.5:14b-instruct` in `.env` e riavviare — nessuna migration, nessun dato toccato.
