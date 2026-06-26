# Roadmap espansione AI — NOVICROM HUB

Backlog ordinato per portare l'AI (oggi: chat + RAG citabile + 11 tool live + copilota
SGI) negli altri punti del portale. **Si esegue a ondate, a fasi con STOP di approvazione**
(come il build SGI), non tutto in una volta.

## Principi invariabili (valgono per OGNI voce)
- **On-premise** (Ollama per la chat, TEI per gli embeddings su GPU). Nessun cloud.
- **ACL server-side** sempre: ogni tool/feature filtra coi permessi dell'utente prima di esporre dati.
- **"AI propone, l'umano firma"**: nessuna scrittura/decisione automatica. L'output è una proposta.
- **Audit solo-metadati** (mai prompt/risposte/dati sensibili nei log).
- **Matrice campi** (docs/ai/13_AI_GOVERNANCE.md): whitelist/blacklist per modulo. Ogni nuovo tool
  va in produzione **solo dopo** un `AiToolPrivacyReview` approvato.
- **Timbri/Presenze**: bloccati finché non c'è la DPIA dedicata. Non toccare.

## Mattoni riusabili (non si reinventa nulla)
- **Tool live**: pattern in `ai_assistant/tools.py` (`RUNTIME_TOOLS`, `_wants_<dominio>` + funzione
  tool + gate ACL + seed per il routing semantico).
- **Copilota read-only**: pattern in `gestione_specifiche/ai_copilota.py` (`chat_with_ollama`,
  `_estrai_testo_pdf`, output `proposto=True`, nessuna scrittura).
- **RAG citabile**: `ai_assistant/services.py::_load_sgi_document_chunks` (aggiungere nuovi corpora).
- **Embeddings su GPU**: TEI via `RAG_EMBED_BACKEND=openai` (regge migliaia di chunk).
- **Resolver pronti**: `anagrafica/services/skillmatrix_resolver.py` (chi opera una macchina),
  `gestione_carichi_macchina` (saturazione/previsioni).

Effort: **S** = poche ore · **M** = 1–2 gg · **L** = multi-giorno.

---

## Ondata 1 — Quick win (infra già pronta, alto rapporto valore/sforzo)

| # | Voce | Dove / pattern | ACL · governance | Effort |
|---|---|---|---|---|
| 1.1 | **Tool live Skill Matrix** ("chi può operare la macchina X?", uomo-solo, copertura) | nuovo tool in `ai_assistant/tools.py` che chiama `skillmatrix_resolver` (read-only, già esiste) | `_check_hr_permission`; campi: legacy_id→nome, livello, macchina. **Vuoto finché baseline F2b non importata** | S |
| 1.2 | **Tool live Carichi macchina** ("carico/saturazione macchina X questa settimana") | nuovo tool che legge `gestione_carichi_macchina` (saturazione.py) | ACL modulo; espone macchina, % saturazione, n. lavori. No dettagli commessa | S–M |
| 1.3 | **Auto-quiz da procedura** (proponi domande dal PDF di una MT/procedura) | copilota in `procedure_refresh` (riusa `_estrai_testo_pdf` + `chat_with_ollama`); target: modello `ProcedureQuiz` già esistente | read-only, `proposto=True`; l'umano approva il quiz. Dati pronti (248 procedure importate) | M |

## Ondata 2 — Allargare il RAG citabile (la "memoria aziendale")
Il loader scala già a migliaia di chunk (TEI). Ogni corpus diventa interrogabile con citazione.

| # | Voce | Dove | Note |
|---|---|---|---|
| 2.1 | **Specifiche** nel RAG (oltre alle procedure) | il loader `_load_sgi_document_chunks` le supporta già | manca solo il dato (import storico specifiche, separato) |
| 2.2 | **Sicurezza** (DVR/PEI/informative) | nuovo ramo loader o `import_sgi_da_share` su quella cartella | "quali DPI per la mansione X", "cosa dice il DVR sul rischio Z" |
| 2.3 | **Formazione/e-learning** (slide, materiali) | loader su `anagrafica` training/slide | tutor che cita il corso |
| 2.4 | **Manuali macchina / contratti fornitori** | loader su asset/fornitori | supporto a chi opera |

Effort per corpus: **S–M** (il grosso è già fatto). Governance: solo revisioni correnti + citazione.

## Ondata 3 — Copiloti per-modulo ("AI propone, umano firma")
Clonare il pattern MOD.133 dove c'è data-entry strutturato. Tutti **read-only/proposta**.

| # | Voce | Modulo | Cosa propone | Effort |
|---|---|---|---|---|
| 3.1 | **Copilota ticket** | `tickets` | categoria/priorità/assegnatario dal testo + bozza risoluzione | M |
| 3.2 | **Copilota anomalie** | `anomalie` | bozza RDC / azione correttiva dalla descrizione | M |
| 3.3 | **Copilota DPI** | `dpi` | set DPI proposto dalla mansione (modelli di rischio già presenti) | M |
| 3.4 | **Copilota incidenti / diario preposto** | `rilevazione_incidenti`, `diario_preposto` | classificazione + cause proposte; sintesi | M |
| 3.5 | **Copilota KICK-OFF** | `tasks` | attività/milestone da brief progetto; **verbale riunione** dalla traccia | M–L |

## Ondata 4 — Generazione assistita & ricerca semantica
| # | Voce | Note |
|---|---|---|
| 4.1 | **"Cosa è cambiato"** tra revisioni MT/procedura (diff in prosa) per la presa visione | usa il RAG SGI; alto valore compliance |
| 4.2 | **Bozze comunicazioni** (`notizie`), **traduzioni** IT/EN (work instruction bilingui), **riassunti** | generazione ancorata + approvata |
| 4.3 | **Ricerca globale semantica** + **dedup/simili** (anomalie/ticket/specifiche) | sfrutta gli embeddings TEI oltre la chat |
| 4.4 | **Gap analysis qualità** (bozza documento vs requisiti dell'MT) | è il flow-down MOD.133, assistito |

## Ondata 5 — Predittivo/assistivo & digest (casi "sicuri" della policy)
| # | Voce | Guardrail |
|---|---|---|
| 5.1 | **Scadenze a rischio** (DPI, visite, tarature, verifiche periodiche) nel brief | fatti vs ipotesi vs azione, con fonte + finestra temporale |
| 5.2 | **Trend anomalie / rischio SLA ticket / manutenzione predittiva** (backlog asset AS10) | solo aggregati, mai caso individuale per decisioni |
| 5.3 | **Digest per caporeparto/reparto** + **briefing mattutino email** (schedulabile) | per-utente, ACL-gated |
| 5.4 | **KPI raccontati in prosa** (le dashboard hanno già i numeri) | narrativa, non nuovi dati |

## Bloccato (solo dopo DPIA)
- **Timbri/Presenze**: dato cronologico/sensibile. Nessun tool finché non c'è il sign-off privacy.

---

## Come si esegue
1. Una **ondata alla volta**, una **voce alla volta**, con **STOP di approvazione**.
2. Ogni nuova feature: read-only, ACL-gated, `AiToolPrivacyReview` approvata prima del live, test, audit metadata-only.
3. Commit per voce (no push automatico se non richiesto), CHANGELOG aggiornato.
4. Misurare dove ha senso (come `ai_eval` per il RAG).

**Ordine consigliato di partenza**: 1.3 (auto-quiz, dati pronti e modulo "nostro") → 1.2 (carichi) →
2.2 (RAG sicurezza) → 3.1/3.2 (copiloti ticket/anomalie).
