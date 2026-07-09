# Design — Assistente AI: qualità/argomentazione delle risposte (sotto-progetto 1/3)

**Data:** 2026-07-09
**Contesto:** l'utente vuole avvicinare l'assistente AI del portale (Ollama + RAG, `ai_assistant`) a un'esperienza tipo "Copilot locale": risposte più performanti, più argomentate, e in prospettiva un sistema che riconosce/ricorda l'utente. L'ambizione complessiva è stata **decomposta in 3 sotto-progetti indipendenti** (deciso in brainstorming):

1. **Qualità/argomentazione delle risposte** ← questo documento
2. Personalizzazione / memoria utente (prossimo brainstorming)
3. Performance/latenza percepita (dopo il punto 2)

Un 4° tema è emerso in discussione ma resta **fuori scope, in backlog**: fine-tuning/auto-miglioramento del modello (vedi "Fuori scope" sotto).

---

## Vincolo hardware (verificato, non negoziabile in questo sotto-progetto)

PCGAVANCINI (`10.0.0.34`) monta una **RTX A4000, 16 GB VRAM dedicata** (`docs/ai/OLLAMA_GPU_TUNING.md`). Budget attuale: Ollama `qwen2.5:14b-instruct` (~9 GB Q4) + TEI/`bge-m3` per gli embeddings (~2-3 GB) ≈ 11-12 GB, restano ~4-5 GB per la KV-cache della chat. Un modello 32B anche quantizzato Q4 non ci sta. **Conclusione**: qualunque miglioramento in questo sotto-progetto deve restare dentro la classe di modelli ~14B (stessa VRAM), oppure essere pura configurazione/prompting. Aggiungere hardware (GPU con più VRAM) è un'opzione ma è esplicitamente fuori scope qui — da riconsiderare solo se Approccio A+B non bastano.

## Vincolo di governance (invariato)

- **On-premise, nessun cloud** (`docs/ai/14_AI_EXPANSION_ROADMAP.md`).
- **Audit solo-metadati**: il portale non persiste prompt/risposte in generale. Fa eccezione `AiChatFeedback`, che salva prompt+risposta **solo quando l'utente clicca esplicitamente 👍/👎** (azione opt-in, non logging passivo) — è il segnale di qualità che questo design riusa.
- **"AI propone, umano firma"**: nessuna modifica automatica del comportamento del modello senza revisione umana.

---

## Obiettivo e metrica di successo

Migliorare la profondità/coerenza argomentativa delle risposte senza toccare l'hardware, misurando l'effetto con strumenti già esistenti (nessuna nuova infrastruttura di valutazione):

- **Segnale primario**: tasso di feedback 👎 su `AiChatFeedback`, confrontato nelle 1-2 settimane prima/dopo il rilascio.
- **Sanity check pre-rilascio**: un set fisso di ~10-15 domande "golden" rappresentative (riusabile sia per Approccio A che B), giudicate a occhio da un umano prima di promuovere qualunque cambiamento.
- Nessun harness di LLM-as-judge automatico: non giustificato per lo scope attuale (YAGNI).

---

## Approccio A — Tuning prompt/config (nessun cambio infrastrutturale) — PRIMARIO

### A1. Restyle del system prompt (`OLLAMA_CHAT_SYSTEM_PROMPT`, solo `.env`)

Oggi il prompt mescola in un blocco unico le regole di grounding ("non inventare nulla, se non hai il dato dillo") con la richiesta di essere discorsivo. Un modello 14B con regole anti-allucinazione rigide tende a diventare prudente e quindi laconico.

**Cambio**: separare esplicitamente in due paragrafi distinti:
1. **Regole di grounding** (invariate, vincolanti — sono la parte critica per compliance/HR/ISO): non inventare file/percorsi/comandi/dati, dichiarare l'incertezza, non descrivere dati live come se fossero letti quando non c'è CONTESTO LIVE.
2. **Regole di stile/argomentazione** (rinforzate): quando il modello *ha* dati/contesto sufficienti, deve strutturare la risposta con motivazione, alternative/trade-off quando pertinenti, un esempio pratico legato ai dati disponibili. Il rigore sui fatti non deve tradursi in rigore sulla forma.

Nessuna migration, nessun codice. Reversibile ripristinando il valore precedente in `.env`.

### A2. Finestra di storico conversazione (`OLLAMA_CHAT_MAX_HISTORY_MESSAGES`)

Oggi 10 messaggi (5 scambi). Contesto totale disponibile 16384 token (`OLLAMA_NUM_CTX`): c'è margine per allargare a ~16-20 messaggi via solo config, senza toccare la KV-cache in modo rischioso.

**Fase 2 (backlog, non in questo rilascio)**: se dopo la misurazione la finestra allargata non basta per conversazioni lunghe, si valuta un riassunto compatto dei turni più vecchi generato al volo quando lo storico supera la soglia. Costo: una chiamata Ollama aggiuntiva per turno sulle conversazioni lunghe, rilevante perché `OLLAMA_NUM_PARALLEL=1` (una richiesta alla volta) — da riconsiderare solo se necessario, non stimata in questo design.

---

## Approccio B — Benchmark di un modello alternativo a parità di VRAM — IN PARALLELO

Non si assume che `qwen2.5:14b-instruct` sia il miglior modello italiano-capace che entra in ~9 GB oggi disponibile per Ollama.

**Processo**:
1. Scaricare 1-2 modelli candidati di taglia compatibile (~9 GB in Q4) su PCGAVANCINI, senza toccare `OLLAMA_CHAT_MODEL` di produzione.
2. Confronto fianco a fianco sullo stesso set di domande golden (§ Obiettivo) + `manage.py ai_eval --rag` / `--rag-sgi` per verificare che routing/retrieval non peggiorino.
3. **Criterio di promozione**: si cambia il modello in produzione solo se il candidato è chiaramente migliore su argomentazione/coerenza a giudizio umano, e non peggiora latenza o recall in modo sensibile. In caso di dubbio, si resta su `qwen2.5:14b-instruct`.

Nessuna migration, nessun impatto ACL. Cambio di config (`.env` + pull modello sul box), reversibile ripristinando il nome del modello precedente.

---

## Approccio C — Ragionamento a due passaggi (draft interno → risposta finale) — BACKLOG, non ora

Il modello abbozzerebbe internamente un ragionamento/struttura prima della risposta finale. Migliorerebbe l'argomentazione senza cambiare modello, ma **raddoppia il tempo GPU per query complessa** su un box già seriale (`OLLAMA_NUM_PARALLEL=1`): rischia di allungare la coda quando più persone usano l'assistente insieme. Da rivalutare solo se A+B non bastano.

---

## Rollout e testing

- Tutte le modifiche di Approccio A/B sono **config-only** (`.env`), a parte l'eventuale piccolo tocco di codice se il limite storico richiedesse più della semplice variabile d'ambiente (da verificare in fase di implementazione: `OLLAMA_CHAT_MAX_HISTORY_MESSAGES` è già env-configurabile, quindi probabilmente zero codice).
- Verifica: rilancio del set golden prima/dopo ogni cambio, confronto affiancato; poi osservazione del trend `AiChatFeedback` nelle 1-2 settimane successive.
- Nessun test automatico nuovo necessario oltre a quelli esistenti (`ai_assistant` test suite, `ai_eval`).
- Nessuna migration.

---

## Fuori scope (annotato per il backlog, non di questo design)

- **Fine-tuning/auto-miglioramento del modello**: emerso in discussione ("l'AI si migliora da sola?"). Risposta: no, non automaticamente — richiederebbe una pipeline di training separata (LoRA quantomeno, full fine-tuning fuori portata su 16 GB), dati curati (oggi solo `AiChatFeedback` opt-in, volume verosimilmente insufficiente), e una valutazione automatica pre-promozione prima di sostituire il modello live. Confligge anche con la policy attuale di non persistere prompt/risposte se non opt-in. **4° sotto-progetto a sé**, da disegnare separatamente se e quando ci sarà volume/necessità.
- **Finestra oraria 22:00-6:00 (basso utilizzo)**: annotata dall'utente come leva per automazioni future a bassa contesa GPU. Non usata in questo design (A/B non ne hanno bisogno). Candidato concreto già identificato per un domani: job notturno che usa il modello (idle) per ripulire/deduplicare la coda di bozze `AiKnowledgeEntry` generate dai 👎 con correzione, pronte per l'approvazione umana al mattino — resta dentro "AI propone, umano firma", nessun training. Da valutare nel sotto-progetto 2 (personalizzazione/memoria) o come voce a sé.
