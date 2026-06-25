# ADR — Strategia AI per Gestione Carichi Macchina

- **Stato:** PROPOSTA — in attesa di approvazione (non implementata)
- **Data:** 2026-06-23
- **Ambito:** modulo `gestione_carichi_macchina` (Passo 5 del piano)
- **Decisore:** (da approvare)

> Questo documento **propone e motiva** come integrare l'AI. Non è ancora codice.
> Dopo l'approvazione si implementa a step revisionabili.

---

## 1. Contesto

### Cosa abbiamo già (deterministico, funzionante)
- **Parser celle** (`parsing.py`): da testo libero estrae pezzi, ore, operazioni, fase, famiglia
  (vocabolario a due passate). Copertura famiglia ~76%.
- **Affinità storica** (`MacchinaFamigliaAffinita`): per coppia macchina↔famiglia, occorrenze,
  ore medie, ultima data, **pool di equivalenza** (macchine intercambiabili, `da_confermare`).
- **CICLI** (`CicloStandard`/`Operazione`): sequenza op con **macchina preferita**, **alternative**
  (`regola_sostituzione`) e **tempo per pezzo** (`tempo_cent_cad`). → permette di stimare la durata
  di un lavoro: `ore ≈ qta × tempo_cent_cad / 100`.
- **Saturazione** (`saturazione.py`): carico/capacità per macchina e reparto (giorni lavorativi,
  doppio turno).
- **Commesse** (backlog) con quantità/pezzo.

### Integrazione AI locale del portale (verificata in `ai_assistant`)
- **Modello chat:** `qwen2.5:14b-instruct` su **Ollama** (`OLLAMA_BASE_URL`, on-prem).
- **Niente function/tool calling nativo.** Il "routing semantico" è lato Python
  (`tools.py::_rank_domains`, similarità coseno su frasi-seme) + **context injection**:
  si calcolano i dati con funzioni Django e si **iniettano nel prompt**
  (`build_runtime_context` → `chat_with_ollama`).
- **Embeddings:** `nomic-embed-text` via `/api/embed`, con **cache** per content-hash in
  `DatabaseCache`; **disabilitati di default** (`OLLAMA_EMBED_ENABLED=False`).
- **Sincrono** (worker-blocking, timeout configurabile). `ai_assistant` non usa django-q2.
- Helper riusabili: `chat_with_ollama`, `embeddings_enabled`, `embed_texts`, `cosine_similarity`.

### Principi vincolanti (dal prompt)
1. **Human-in-the-loop assoluto:** l'AI **propone**, l'operatore approva, poi la `Pianificazione`
   cambia. L'AI non scrive né applica nulla in autonomia.
2. **L'LLM non è mai il motore di calcolo.** Eligibilità e ranking sono codice Python
   deterministico e verificabile; l'LLM spiega e fa da interfaccia in linguaggio naturale.
3. **On-prem, nessun dato esce.** Tutto su Ollama interno.
4. **Fail-safe:** se l'AI non risponde, il modulo resta pienamente usabile.

---

## 2. Decisioni proposte (per i 5 ambiti)

### 2.1 Normalizzazione celle (testo → campi)
**Opzioni:** (A) solo parser deterministico; (B) LLM su ogni cella; (C) parser + LLM solo sui residui.

**Raccomandazione: C.** Il parser resta la fonte primaria (già ~76% famiglia, veloce, gratis).
L'LLM interviene **solo sulle celle non agganciate** (famiglia mancante), in **batch asincrono**,
proponendo una famiglia/alias. La proposta va a **conferma umana**; se accettata, si scrive in
`FamigliaAlias` → il vocabolario cresce e le volte successive il parser aggancia da solo
(**"accumula, non riaddestra"**). Nessun retraining, nessun costo a regime.

*Conseguenze:* miglioramento incrementale e tracciabile; l'AI non è nel percorso critico dell'import.

### 2.2 Motore di suggerimento (dove/quando mettere un lavoro)
Architettura a **3 strati**, in quest'ordine:

1. **Eligibilità (deterministica).** Insieme delle macchine ammissibili per un'operazione:
   `macchina_preferita` del ciclo ∪ `alternative` (da `regola_sostituzione`) ∪ membri dello stesso
   `pool_equivalenza` per la famiglia, filtrate a `stato_pianificazione = attiva` e categoria
   compatibile. *Mai* proporre macchine fuori da questo insieme.
2. **Ranking (Python, deterministico, spiegabile).** Punteggio per macchina eleggibile:
   - **affinità storica** (occorrenze / ore_medie su quella famiglia) — più alta = più adatta;
   - **saturazione attuale** della macchina nella finestra — preferisci la meno carica;
   - **rispetto consegna** — stima durata da `tempo_cent_cad × qta` e verifica la `data_consegna`;
   - bonus turno notte se disponibile.
   Output: lista ordinata con il **perché** di ogni posizione (numeri espliciti).
3. **LLM come spiegazione + linguaggio naturale.** Riceve i candidati già calcolati (JSON) e
   produce la spiegazione leggibile e risponde a domande ("dove conviene mettere 8 gimbal?",
   "quando posso consegnare la commessa X?") **citando i numeri ricevuti**. Tramite **context
   injection** (pattern reale di `ai_assistant`), **non** tool-calling nativo.

**Raccomandazione:** implementare gli strati 1–2 come modulo puro `suggerimenti.py` (testabile,
indipendente dall'AI); lo strato 3 riusa `chat_with_ollama` con i guardrail anti-invenzione già
presenti. Valutare in futuro il tool-calling nativo di qwen2.5, ma **non** ora (il portale non ha
quel path; il context-injection è sufficiente e coerente).

### 2.3 Matching famiglia
**Raccomandazione:** **dizionario-first** (`FamigliaPezzo` + `FamigliaAlias`). Embeddings
(`nomic-embed-text`) **opzionali e solo come assist** sui residui non agganciati: cosine
brute-force (≈76 famiglie × pochi token → nessuna infrastruttura vettoriale), con la **cache embed
esistente**. Attivare gli embeddings (`OLLAMA_EMBED_ENABLED`) solo se il dizionario lascia troppi
residui; fail-safe a dizionario se gli embeddings non sono disponibili.

### 2.4 Approvazione umana (UX)
Card **"proposta → accetta / rifiuta"** accanto alla cella/barra:
- **Accetta** → crea/aggiorna la `Pianificazione` (azione dell'operatore, `fonte = ai`→poi di fatto
  manuale-confermata); l'esito **rialimenta l'affinità** (la "memoria" del sistema).
- **Rifiuta** → registrato (segnale negativo), nessun retraining.
Nessuna modifica al piano avviene senza un click umano.

### 2.5 Sicurezza / performance
- **On-prem**, nessun dato esce; riuso del client Ollama interno.
- **Calcoli pesanti asincroni via django-q2** (normalizzazione batch, ricalcolo ranking massivo):
  qui si **diverge consapevolmente** da `ai_assistant` che è sincrono, perché questi job non sono
  interattivi. Le richieste interattive (spiegazione di una singola proposta) restano sincrone con
  **timeout + fallback** (mostra il ranking deterministico anche senza testo AI).
- **ACL:** gli endpoint AI rispettano l'ACL del modulo (Passo 6); nessun bypass.

### 2.6 Riuso del MOTORE LLM già integrato (gateway condiviso) — RACCOMANDATO
La scelta primaria **non** è "passare dalla chat", ma **riusare il software LLM già integrato** come
**backend condiviso**, a prescindere dalla chat e dalle altre funzioni.

`ai_assistant/services.py` è di fatto il **gateway LLM del portale**:
- client **Ollama** (URL/modello `qwen2.5:14b-instruct`) → `chat_with_ollama`;
- **embeddings** (`embed_texts`, `cosine_similarity`, `embeddings_enabled`) con **cache** per
  content-hash in `DatabaseCache`;
- **tuning runtime** (`keep_alive`, `num_ctx`, `num_predict`) e **warmup** anti cold-start.

**Proposta:** `gestione_carichi_macchina` **importa e usa direttamente queste primitive** per la
propria funzione AI (spiegazione dei suggerimenti, assist matching famiglia), **senza** toccare la
chat né il router dei domini. Ereditiamo "gratis" tutte le ottimizzazioni già fatte (cache, tuning,
warmup, fail-safe). I calcoli restano deterministici (`suggerimenti.py`/`saturazione.py`);
l'LLM solo spiega.

**Dipendenza:** è un **import in sola lettura** di `ai_assistant.services` (più leggero che
modificare quell'app). Se un domani il gateway andasse estratto in un modulo comune (es.
`core`/`hub_tools`), la nostra funzione non cambierebbe (stessa firma).

**Ottimizzazioni condivise che ne traiamo:** un solo modello caldo in memoria (keep_alive) servito a
chat + carichi; cache embeddings condivisa; warmup unico; un solo punto di configurazione Ollama.

**Opzionale (in aggiunta, non alternativo):** registrare anche un dominio `carichi_macchina` nella
**chat** `ai_assistant` per le domande in linguaggio naturale — ma è un di più, da valutare dopo,
e comporterebbe toccare quell'app.

### 2.7 AI PREDITTIVA (cuore della richiesta)
L'obiettivo non è solo spiegare i dati ma **prevedere**. Abbiamo la materia prima:
**70 snapshot settimanali** (serie storica), **affinità** (ore medie per macchina×famiglia),
**tempi di ciclo** (cent/cad), **saturazione**. Sono dati sufficienti per predizioni reali.

**Principio:** la **predizione la fa un modello sui dati** (statistico/ML), **non l'LLM** — gli LLM
non prevedono numeri in modo affidabile. L'LLM (riuso del gateway 2.6) **spiega** la previsione in
linguaggio naturale. Si parte da **baseline statistiche** spiegabili e si sale a ML solo se serve.

**Capacità predittive proposte (dalla più solida):**
1. **Durata/ore previste** di un lavoro quando le ore non sono scritte (la maggioranza delle celle):
   da `tempo_cent_cad × pezzi` se c'è il ciclo, altrimenti dalla **media storica** della famiglia su
   quella macchina (`ore_medie`). → riempie il buco più grosso.
2. **Macchina più probabile** per una famiglia/pezzo: dallo storico (frequenza/affinità + pool).
   "Questo lavoro storicamente va su DM3/DM6."
3. **Rischio ritardo commessa**: confronto durata prevista + saturazione vs `data_consegna`.
4. **Previsione carico/saturazione e colli di bottiglia** del reparto nelle prossime settimane
   (trend dagli snapshot).

**Come si addestra/aggiorna:** ricalcolo periodico (django-q2) delle statistiche dallo storico
deduplicato; nessun servizio esterno, tutto on-prem. Le conferme umane (accetta/rifiuta)
**rialimentano** i dati → le previsioni migliorano nel tempo senza retraining pesante.

**Misura di qualità:** poiché abbiamo lo storico, possiamo **validare** le previsioni (es. predire le
ore sull'ultimo snapshot e confrontarle col reale) e mostrare un'accuratezza, invece di "fidarsi".

---

## 3. Architettura complessiva (pipeline)

```
cella/commessa ─▶ [parser deterministico] ─▶ campi strutturati
                          │ (residui)
                          ▼
                 [AI assist famiglia] ─▶ proposta ─▶ conferma umana ─▶ FamigliaAlias

richiesta "dove metto X" ─▶ [eligibilità det.] ─▶ [ranking Python] ─▶ candidati+motivi (JSON)
                                                                          │
                                                                          ▼
                                                            [LLM context-injection]
                                                                          │
                                                                          ▼
                                                      card "proposta → accetta/rifiuta"
                                                                          │ (accetta)
                                                                          ▼
                                                              Pianificazione (umano)
```

L'LLM è **sempre a valle** dei calcoli e **mai** sul percorso che scrive i dati.

---

## 4. Piano di implementazione (dopo approvazione, a step)
1. `suggerimenti.py` puro: eligibilità + ranking + test (nessuna AI).
2. UI proposte (card accetta/rifiuta) sulla cella/Gantt, alimentata dal ranking.
3. Strato LLM di spiegazione (riuso `chat_with_ollama`, context injection, timeout/fallback).
4. Normalizzazione AI dei residui in batch via django-q2 + conferma che arricchisce `FamigliaAlias`.
5. (Opzionale) embeddings per il matching famiglia, dietro flag.
6. ACL endpoint + voce menu (allineato al Passo 6).

---

## 5. Rischi e mitigazioni
- **Dati di partenza incompleti** (commesse non collegate alle pianificazioni, 14 codici macchina da
  alias-are, tempi ciclo solo per i cicli presenti). → Il ranking degrada con grazia: usa ciò che
  c'è, segnala i dati mancanti, non inventa.
- **Pool di equivalenza euristico** (`da_confermare`). → L'eligibilità lo usa ma evidenzia le coppie
  non confermate.
- **Allucinazioni LLM.** → L'LLM riceve i numeri e ha istruzioni di citare solo quelli; i calcoli
  restano deterministici e testati.
- **Latenza Ollama.** → Async per i batch, timeout+fallback per l'interattivo.

## 6. Fuori scope (per ora)
- Tool-calling nativo del modello.
- Scheduling automatico/ottimizzatore (resta decisione umana).
- Vector DB / RAG dedicato (dataset troppo piccolo).

---

## 7. STOP — richiesta di approvazione
Prima di scrivere codice AI servono le tue decisioni su:
1. **Riuso AI esistente (2.6)**: registro un **dominio `carichi_macchina` in `ai_assistant`**
   (tocca quell'app, in lieve deroga all'isolamento) oppure resto **isolato** con un endpoint AI
   dentro il modulo che riusa solo `chat_with_ollama`?
2. **Strato LLM**: confermi **context-injection** e NON tool-calling nativo?
3. **Embeddings famiglia**: attivarli (assist) o restare **dizionario-first**?
4. **Async**: ok introdurre **django-q2** per i job AI batch (divergendo dall'AI sincrona esistente)?
5. **Priorità ranking**: confermi i pesi *affinità + saturazione + consegna* (+turno notte)?

Approva (anche con modifiche) e procedo con lo step 1 (`suggerimenti.py`, senza AI).

---

## 8. Decisione registrata (scope) e piano a fasi
**Scope approvato:** suite predittiva **completa** (tutte e 4 le capacità di 2.7). Predizione =
modello sui dati (statistico/ML, validabile); LLM (riuso gateway 2.6) = sola spiegazione.

**Fasi (in ordine di dipendenza, ognuna revisionabile):**
1. **Durata/ore previste** — `previsioni.py` puro (tempo ciclo×pezzi → media storica → fallback) +
   **backtest** sullo storico (accuratezza) + uso nel Gantt per la lunghezza barra quando le ore
   mancano (barra "stima"). *Senza LLM.* ← in corso.
2. **Macchina più probabile** per pezzo (frequenza/affinità + pool) + UI suggerimento.
3. **Rischio ritardo commessa** (durata prevista + saturazione vs consegna).
4. **Previsione carico/colli di bottiglia** (trend dagli snapshot).
5. **Strato LLM di spiegazione** sopra le predizioni (riuso `ai_assistant.services`), async dove serve.

Ricalcolo periodico via django-q2; conferme umane che rialimentano i dati; tutto on-prem.
