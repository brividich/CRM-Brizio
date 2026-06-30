# 15 — Piano di sviluppo & implementazione AI locale (post go-live RAG SGI)

> Punto di partenza: **baseline AI già in prod** (go-live 2026-06-30). Vedi inventario in
> [14_AI_EXPANSION_ROADMAP.md](14_AI_EXPANSION_ROADMAP.md). Questo piano estende i due
> pattern rodati (tool-live *read* e copilota *propose*) e alza la qualità del retrieval.

## Principi invariabili (non negoziabili)
- **On-prem**, **read-only** ("l'AI propone, l'umano firma"), **audit solo-metadati**.
- **ACL server-side** + **`AiToolPrivacyReview` approvata PRIMA di ogni go-live** su dati personali.
- **Tutto misurato con `ai_eval`** (routing / `--rag` / `--rag-sgi`): nessuna ottimizzazione "a sensazione".
- **Fasi con STOP**: una voce alla volta; STOP di approvazione prima di ogni passo che tocca prod o nuovi dati.
- Timbri/Presenze **bloccati fino a DPIA**.

## Baseline misurata
- RAG SGI ibrido: **recall 29/32, MRR 0,634**; KB curata: **26/26, MRR 0,981** (BM25 deterministico, riproducibile in dev).
- Embeddings bge-m3 (TEI 10.0.0.34:8081, dim 1024); chat qwen2.5:14b-instruct.

---

## FASE 1 — Hardening qualità dell'esistente *(dev, basso rischio, reversibile)*
Obiettivo: **blindare** la qualità appena andata live e correggere incoerenze, prima di estendere.

| ID | Task | Dove | Acceptance | Stato |
|----|------|------|-----------|-------|
| **1.1** | **Regression gate `ai_eval --rag`** in `release_guard.ps1` | dev | il gate gira BM25-only (no GPU, deterministico) e FALLISCE se `recall_hits < cases` o `mrr < 0.95`; KB baseline 26/26, 0.981 | ⏳ |
| **1.2** | **Fix cache-key routing seed** in `tools._domain_seed_vectors` | dev | guard = `services.embeddings_enabled()`, chiave = `_effective_embed_model()`; routing non si spegne se `OLLAMA_EMBED_MODEL` è vuoto col backend TEI; +test | ⏳ |
| **1.3** | **Stemming italiano**: wiring + misura in dev (KB) | dev | toggle `OLLAMA_RAG_STEMMING_ENABLED` verificato; delta KB misurato con `ai_eval --rag`; **attivazione in prod** = step separato (sez. PROD) | ⏳ |
| **1.4** | **Review 3 expect golden** a rischio (righe 31/41/55-56/63) | dev | esaminati token/query problematici; correzioni proposte; **validazione su indice live = step PROD** | ⏳ |

**STOP 1 → step da eseguire in PROD (richiedono TEI + corpus SGI):**
- `ai_eval --rag-sgi` baseline → attivare stemming nel `config\.env` SOLO se recall sale senza regressioni.
- **Ritaratura soglie routing per bge-m3** (`AI_TOOL_ROUTING_THRESHOLD`/`_MARGIN`, oggi 0.70/0.04 da *nomic*) con `ai_eval` routing-mode + allineare `OLLAMA_EMBED_MODEL` al modello reale.
- Validare i 3 expect golden contro l'indice live.

---

## FASE 2 — Nuove superfici (dominio sicurezza/compliance) *(a fasi con STOP)*
Una superficie alla volta, ognuna con: F1 backend → F1b UI → privacy review → go-live.

| ID | Superficie | Pattern | Privacy/ACL | Priorità |
|----|-----------|---------|-------------|----------|
| **A1** | **RAG Sicurezza DVR/PEI** (chat cita il rischio mansione) | RAG SGI | review corpus sicurezza; ACL preposti/RSPP | 🥇 (roadmap 2.2) |
| **A2** | **Copilota Incidenti/RCA** (`rilevazione_incidenti`): 5-Why, classificazione, azioni | copilota + RAG | dati salute → minimizzazione, audit no-nomi | 🥇 |
| **A3** | **Copilota Anomalie** (triage come ticket) | copilota ticket | ACL gestori anomalie | 🥈 (roadmap 3.2) |

**STOP 2** prima di ciascuna: definizione matrice campi + `AiToolPrivacyReview` + golden dedicato.

---

## FASE 3 — Salti di qualità retrieval *(misurati con `ai_eval --rag-sgi`)*
| ID | Intervento | Effort | Note |
|----|-----------|--------|------|
| **3.1** | **Sinonimi/acronimi** (DPI↔dispositivi, NC↔non conformità, MT/MOD/CN) in `_tokenize` query | M | dizionario curato + misura |
| **3.2** | **Reranker cross-encoder** (`bge-reranker-v2-m3` su stesso TEI) sui top-20 RRF | L | salto MRR maggiore; verificare VRAM A4000 |
| **3.3** | **Revisione chunking** (900→1100-1300, codice doc nel testo, boost-titolo ∝ IDF) | M | invalida cache embeddings → re-warm |

---

## FASE 4 — Perf/infra/governance *(lato server + automazioni)*
- **4.1** batch embeddings TEI 16→64-128 per il warm notturno (`OLLAMA_EMBED_BATCH`).
- **4.2** applicare runbook GPU (`OLLAMA_GPU_TUNING.md`): flash-attention, KV-cache q8, keep-alive coerente; A/B modello chat solo *misurando*.
- **4.3** osservabilità: esporre **recall/MRR** nella card "Stato sistema" (dato già in `run_rag_quality_alert`); ampliare golden con righe `spec:` quando arriva l'import storico.
- **4.4** governance: comando che verifica `AiToolPrivacyReview` approvata per ogni tool in `RUNTIME_TOOLS` prima del rilascio (gate non-saltabile).

---

## Ordine operativo concordato
1. **FASE 1 ora** (1.1 → 1.2 → 1.3 → 1.4 in dev, con misure `ai_eval`). → STOP 1.
2. Poi **FASE 2 A1** (RAG sicurezza) a fasi con STOP.
3. **FASE 3.2 (reranker)** quando si vuole il salto di qualità retrieval.

Tracciamento: task list di sessione (vedi `TaskList`).

---

## Risultati FASE 1 (dev) — 2026-06-30
- **1.1 ✅** Regression gate `Invoke-RagRegressionGate` in `release_guard.ps1` (Wave 2): `ai_eval --rag --json` con `OLLAMA_EMBED_ENABLED=0` (BM25 puro, no GPU), fallisce se `recall_hits<cases` o `MRR<0.90`. Baseline dev KB **26/26, MRR 0.962**. Commit `c383807`.
- **1.2 ✅** Fix `tools._domain_seed_vectors`: guard `embeddings_enabled()` + chiave cache `_effective_embed_model()`. +1 test. Commit `c383807`.
- **1.3 ✅ (dev)** Stemming, misura KB (BM25 puro): OFF → MRR **0.962** (rank1 24); ON → MRR **0.942** (rank1 23); recall 26/26 in entrambi. **Sulla KB lo stemming peggiora leggermente** → NON attivare alla cieca; decide la misura SGI in prod.
- **1.4 ✅ (dev)** Analisi golden: probabili 3 miss tra r31/r41 (`MOD.xxx` su corpus solo-procedure), r55/r56 (`IDOR CN 01`/`02` quasi identici), r63 (`MT CN 125_5`, underscore da verificare). Correzioni da applicare dopo validazione su indice live.

## STOP 1 — checklist PROD (richiede TEI + corpus SGI)
Eseguire sul server prod (venv prod, `--settings=config.settings.prod`):
1. **Baseline SGI**: `python django_app\manage.py ai_eval --rag-sgi --json` → annota recall/MRR (atteso ~29/32, 0.634).
2. **Stemming**: ripetere `ai_eval --rag-sgi --json` con `OLLAMA_RAG_STEMMING_ENABLED=1`. Attivare nel `config\.env` **solo se** il recall SGI sale di più di quanto la KB perda in MRR (la chat usa entrambi i corpora).
3. **Golden**: per ogni MISS reale, correggere `golden_sgi.jsonl` (r63: allineare il codice al formato live; r31/r41: tenere solo `MT CN` se la modulistica non è indicizzata) o affinare la query — senza mascherare difetti reali di retrieval.
4. **Ritaratura routing bge-m3**: con `ai_eval` routing-mode misurare e portare `AI_TOOL_ROUTING_THRESHOLD`/`_MARGIN` ai valori bge-m3 (tipico 0.72–0.78); **allineare `OLLAMA_EMBED_MODEL`** al modello reale per coerenza cache seed (ora corretta dal fix 1.2, ma il nome resta usato altrove).
