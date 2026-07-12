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
| 1.2 | **✅ FATTO — Tool live Carichi macchina** ("carico/saturazione macchina X questa settimana") | `ai_assistant/tools.py::_carichi_context` (legge `gestione_carichi_macchina/saturazione.py`); gate `_wants_carico_context`, seed routing `"carichi"`, audit metadata-only, 4 test | ACL = confine reale modulo (oggi `@login_required`; TODO ACL v2 al Passo 6); espone macchina, % saturazione, ore carico/capacità, n. lavori. No dettagli commessa/cliente | S–M |
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
| 3.1 | **✅ FATTO — Copilota ticket** | `tickets` (`ai_copilota.py` + endpoint `api/copilota/` + UI dettaglio gestione) | categoria/priorità/assegnatario dal testo + bozza risoluzione; read-only, validato, fail-safe, audit metadata-only | M |
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

## Ondata 6 — Moduli introdotti dopo la stesura (ricognizione 2026-07-12)
Moduli arrivati *dopo* le onde 1–5 e **non ancora raggiunti dall'AI**. Assi: Valore · Sforzo
(S=ore, M=1–2gg) · Rischio governance. Fattibilità verificata sul codice reale.

| # | Voce | Modulo / pattern | ACL · governance | Valore | Sforzo | Rischio |
|---|---|---|---|---|---|---|
| 6.1 | **✅ FATTO — Tool live Contatori MFC** ("consumo/classifica reparti", "andamento trimestri", ripartizione BN/colore, stato rilevazioni) | `ai_assistant/tools.py::_contatori_context` (legge `contatori/services.py`: `consumo_per_trimestre`, `classifica_reparti`, `ripartizione`, `ultime_rilevazioni`); gate `_wants_contatori_context`, seed routing `"contatori"`, audit metadata-only, 4 test | Solo **aggregati** (nessun dato personale). Gate ACL v2 **`contatori.dashboard.view`** (non solo login). `AiToolPrivacyReview` seed `ai_seed_contatori_privacy_review` | Medio-Alto | **S** | **Basso** |
| 6.2 | **✅ FATTO — RAG citabile Schede Sicurezza** ("cosa dice la scheda del prodotto X su DPI/rischi/stoccaggio") | `services.py::_load_schede_sicurezza_chunks` (legge i **campi curati in DB** — CLP, frasi H/P, DPI, primo soccorso, incompatibilità, `estratto_grezzo`; **nessun PDF ri-parsato**), aggregato in `_load_sgi_document_chunks`; handle `sds:`, firma cache estesa, flag `OLLAMA_RAG_SDS_ENABLED`, 3 test | RAG citabile, read-only; contenuto sicurezza **non personale** → sempre citabile (kind None, no gate ACL per-utente). Concretizza l'**onda 2.2** | **Alto** | S–M | Medio |
| 6.3 | **Tool live Schede Sicurezza** ("quale scheda per prodotto X", "chi non ha preso visione", scadenze) | tool live su `schede_sicurezza` (`ProdottoChimico`, `SchedaSicurezza`, `PresaVisioneScheda`) | `PresaVisioneScheda` è nominativo → **whitelist campi** stretta nella matrice governance | Medio | **S** | Medio |
| 6.4 | **Tool + copilota Suggestion Corner** (stato PDCA per reparto; bozza categoria/azione dal testo) | `suggestion_corner` (tool live + copilota stile MOD.133) | ⚠️ i suggerimenti SMS possono essere **anonimi** → **mini-DPIA prima**: l'AI non deve de-anonimizzare né correlare l'autore | Medio | M | **Medio-Alto** |
| 6.5 | **Estensione tool Assets** a fornitori / OdL interne-esterne / checklist (overhaul manutenzione) | estendere `_asset_context` in `ai_assistant/tools.py` | eredita il gate ACL del tool assets | Basso-Medio | S–M | Basso |

**Ordine consigliato Ondata 6**: ~~6.1 (quick win, services pronti, rischio minimo)~~ ✅ → ~~6.2 (valore alto,
sblocca 2.2)~~ ✅ → 6.3 (complemento di 6.2, stesso modulo). 6.4 dopo la mini-DPIA anonimato. 6.5 opportunistico.

**Stato avanzamento Ondata 6**: ✅ 6.1 Tool live Contatori MFC · ✅ 6.2 RAG Schede Sicurezza (2026-07-12, branch `feat/modulo-security-center`).

> Nota: `strumenti_misura` è oggi **solo studio di fattibilità** (non è un'app installata) → fuori scope AI finché non esiste il modulo.

## Bloccato (solo dopo DPIA)
- **Timbri/Presenze**: dato cronologico/sensibile. Nessun tool finché non c'è il sign-off privacy.

---

## Come si esegue
1. Una **ondata alla volta**, una **voce alla volta**, con **STOP di approvazione**.
2. Ogni nuova feature: read-only, ACL-gated, `AiToolPrivacyReview` approvata prima del live, test, audit metadata-only.
3. Commit per voce (no push automatico se non richiesto), CHANGELOG aggiornato.
4. Misurare dove ha senso (come `ai_eval` per il RAG).

**Ordine consigliato di partenza**: 1.3 (auto-quiz, dati pronti e modulo "nostro") → ~~1.2 (carichi)~~ ✅ →
2.2 (RAG sicurezza) → 3.1/3.2 (copiloti ticket/anomalie).

**Stato avanzamento**: ✅ 1.2 Carichi macchina · ✅ 3.1 Copilota ticket (2026-06-27, branch `feature/skill-matrix-mod187`).
