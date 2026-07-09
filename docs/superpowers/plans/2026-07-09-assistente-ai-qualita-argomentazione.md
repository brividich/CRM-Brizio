# Assistente AI — Qualità/Argomentazione Risposte Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rendere le risposte dell'assistente AI del portale più argomentate e coerenti (system prompt + finestra di storico conversazione) senza cambi infrastrutturali, e predisporre il runbook/fixture per confrontare `qwen2.5:14b-instruct` con un modello alternativo a parità di VRAM.

**Architecture:** Nessun nuovo componente. Due modifiche di **default di configurazione** in `django_app/config/settings/base.py` (system prompt, finestra storico), più un runbook operativo e un set di domande golden checked-in per la validazione manuale (Approccio A) e il benchmark futuro (Approccio B). Tutto reversibile via `.env`, nessuna migration.

**Tech Stack:** Django settings (`env()` helper esistente), Ollama chat (`qwen2.5:14b-instruct`), test Django (`TestCase`/`override_settings`).

## Global Constraints

- **On-premise, nessun cloud** — invariato (`docs/ai/14_AI_EXPANSION_ROADMAP.md`).
- **Hardware**: RTX A4000 16 GB VRAM su PCGAVANCINI (`10.0.0.34`), budget già stretto (~11-12 GB Ollama+TEI). Nessun cambio di modello a taglia >14B in questo piano.
- **Nessuna migration.**
- **CHANGELOG.md aggiornato ad ogni commit di codice** (regola di progetto, `CLAUDE.md`), con i file modificati e una descrizione sotto `[Unreleased]`.
- **`django_app/.env` non è modificabile da Claude** (permessi negati sui file `.env`, per policy di sicurezza sui file sensibili). Se un default cambiato in `base.py` risulta già sovrascritto in un `.env` di un ambiente (dev/test/prod), va segnalato esplicitamente come nota operativa per l'utente — non si può fare per lui in questa sessione.
- Riferimento spec: `docs/superpowers/specs/2026-07-09-assistente-ai-qualita-argomentazione-design.md`.

---

### Task 1: Restyle del system prompt di default (separare stile/argomentazione da grounding)

**Files:**
- Modify: `django_app/config/settings/base.py:392-420` (valore di default di `OLLAMA_CHAT_SYSTEM_PROMPT`)
- Test: `django_app/ai_assistant/tests.py` (nuova classe `SystemPromptDefaultsTests`, da inserire dopo `OllamaTuningTests` che termina alla riga 3260)

**Interfaces:**
- Consuma: nessuna funzione nuova, solo la costante `settings.OLLAMA_CHAT_SYSTEM_PROMPT` e `settings.OLLAMA_CHAT_MAX_SYSTEM_PROMPT_CHARS` già esistenti.
- Produce: nessuna nuova interfaccia — il testo del prompt resta un valore di settings consumato da `build_ollama_messages` (`ai_assistant/services.py:1547`), invariato nella firma.

- [ ] **Step 1: Scrivere il test che fallisce**

Aggiungere in `django_app/ai_assistant/tests.py`, subito dopo la fine della classe `OllamaTuningTests` (riga 3260, prima di `class EmbedTimeoutTests(TestCase):`):

```python
class SystemPromptDefaultsTests(TestCase):
    """Il prompt di sistema di default separa stile/argomentazione dalle regole di grounding."""

    def test_default_prompt_separates_style_from_grounding_and_fits_cap(self):
        prompt = settings.OLLAMA_CHAT_SYSTEM_PROMPT
        cap = int(settings.OLLAMA_CHAT_MAX_SYSTEM_PROMPT_CHARS)
        self.assertIn("STILE E ARGOMENTAZIONE", prompt)
        self.assertIn("REGOLA ASSOLUTA", prompt)
        self.assertLess(
            prompt.index("STILE E ARGOMENTAZIONE"),
            prompt.index("REGOLA ASSOLUTA"),
        )
        self.assertLessEqual(len(prompt), cap)
```

`settings` è già importato in cima al file (`from django.conf import settings`, riga 11).

- [ ] **Step 2: Eseguire il test e verificare che fallisca**

Run: `".venv\Scripts\python.exe" django_app\manage.py test ai_assistant.tests.SystemPromptDefaultsTests --settings=config.settings.test -v 2`
Expected: FAIL — `AssertionError: 'STILE E ARGOMENTAZIONE' not found in ...` (il testo di default attuale non contiene quell'intestazione).

- [ ] **Step 3: Riscrivere il default del prompt in `base.py`**

Sostituire il blocco `OLLAMA_CHAT_SYSTEM_PROMPT = env(...)` (righe 392-420) con:

```python
OLLAMA_CHAT_SYSTEM_PROMPT = env(
    "OLLAMA_CHAT_SYSTEM_PROMPT",
    (
        "Sei l'assistente interno di NOVICROM HUB. "
        # Stile/argomentazione: separato dalle regole di grounding cosi' il rigore
        # sui fatti non si traduce in risposte laconiche (vedi design 2026-07-09).
        "STILE E ARGOMENTAZIONE (quando hai dati/contesto sufficienti): rispondi in italiano in modo "
        "chiaro e discorsivo, mai telegrafico. Spiega il perche', non solo il cosa: contestualizza, "
        "quando pertinente valuta alternative o casi limite, e aggiungi un breve esempio pratico o i "
        "passi concreti basato sui dati che hai davvero. Struttura le risposte piu' lunghe con paragrafi "
        "o elenchi puntati quando aiuta la lettura. Il rigore sui fatti (sotto) non deve tradursi in "
        "risposte piu' corte: puoi essere articolato restando comunque ancorato al contesto. "
        # Gerarchia fonti — prima regola, non troncabile
        "PRIORITA' FONTI (obbligatoria): "
        "1) CONTESTO LIVE: se presente, e' la fonte principale. Rispondi usando quei dati, "
        "cita tool:* e ignora i documenti interni sulla stessa domanda. "
        "2) DOCUMENTI INTERNI (SGI e KB): usali per spiegare procedure, regole e funzionamento del portale. "
        "3) Conoscenza generale: mai per inventare dati aziendali. "
        # Anti-invenzione
        "REGOLA ASSOLUTA: non inventare file, percorsi, URL, procedure, comandi, codici, numeri o sezioni "
        "assenti dal contesto. Se non hai il dato, dillo senza aggiungere fantasia. "
        "Se l'utente chiede dati operativi (registrazioni, movimenti, elenchi) e non e' presente "
        "un CONTESTO LIVE, rispondi che non hai accesso diretto a quei dati e invita ad aprire il modulo nel "
        "portale; non descrivere il funzionamento come se stessi leggendo i dati reali. "
        # Citazione documenti SGI
        "Quando spieghi a partire da un documento SGI cita sempre codice, revisione e sezione "
        "(es. «MT CN 04 Rev.0 §5.1»). "
        # Dati sensibili
        "Non ripetere password, token o credenziali. Per dati sanitari, disciplinari o riservati "
        "invita a usare il modulo dedicato. "
        # Qualita risposta
        "Se non sei certo, dichiaralo. Non aprire URL esterni."
    ),
)
```

(1652 caratteri, sotto il cap di 1800 di `OLLAMA_CHAT_MAX_SYSTEM_PROMPT_CHARS` — verificato con uno script ad-hoc prima di scrivere il task.)

- [ ] **Step 4: Eseguire di nuovo il test e verificare che passi**

Run: `".venv\Scripts\python.exe" django_app\manage.py test ai_assistant.tests.SystemPromptDefaultsTests --settings=config.settings.test -v 2`
Expected: `OK` (1 test).

- [ ] **Step 5: Eseguire l'intera suite `ai_assistant` (regressione)**

Run: `".venv\Scripts\python.exe" django_app\manage.py test ai_assistant --settings=config.settings.test --keepdb -v 1`
Expected: nessuna nuova failure rispetto allo stato precedente (i test esistenti su `build_ollama_messages` usano `override_settings(OLLAMA_CHAT_SYSTEM_PROMPT="Sistema", ...)`, quindi non sono influenzati dal nuovo default).

- [ ] **Step 6: Aggiornare CHANGELOG.md e committare**

Aggiungere sotto `## [Unreleased]` in `CHANGELOG.md` una voce che descrive il restyle del system prompt (file: `django_app/config/settings/base.py`, `django_app/ai_assistant/tests.py`), citando che separa regole di grounding (invariate) da stile/argomentazione (rinforzato) — sotto-progetto 1/3 della qualità assistente AI, spec `docs/superpowers/specs/2026-07-09-assistente-ai-qualita-argomentazione-design.md`.

```bash
git add django_app/config/settings/base.py django_app/ai_assistant/tests.py CHANGELOG.md
git commit -m "feat(ai): system prompt separa stile/argomentazione dal grounding"
```

**Nota operativa (non automatizzabile da qui):** se un ambiente (`config\.env` in test/prod, o `django_app/.env` in dev) sovrascrive esplicitamente `OLLAMA_CHAT_SYSTEM_PROMPT`, il nuovo default in `base.py` non avrà effetto finché quella riga non viene rimossa o aggiornata manualmente in quel file — verificato che l'`.env` di sviluppo attuale **non** lo sovrascrive (usa già il default di `base.py`), ma non è verificabile da qui per test/prod.

---

### Task 2: Allargare la finestra di storico conversazione (6 → 16 messaggi)

**Files:**
- Modify: `django_app/config/settings/base.py:265`

**Interfaces:**
- Consuma: nessuna funzione nuova. Il valore alimenta `_clean_history(raw_history, max_messages=..., max_chars=...)` (`ai_assistant/services.py:1530`), già testato per il comportamento di troncamento con qualunque valore di `max_messages` (non serve un nuovo test sul meccanismo, già coperto).
- Produce: nessuna nuova interfaccia.

**Nota su TDD per questo task**: un test che verifichi "il default e' 16" leggendo `settings.OLLAMA_CHAT_MAX_HISTORY_MESSAGES` sarebbe **falsato dall'ambiente** (l'`.env` di sviluppo attuale già sovrascrive questo valore a 10, quindi il test vedrebbe 10 indipendentemente da cosa scriviamo in `base.py`, e fallirebbe per un motivo sbagliato). Un test che bypassa l'`.env` per leggere solo il valore letterale nel file sarebbe circolare (dovrebbe duplicare lo stesso numero “16” nel test, senza verificare nulla di reale). Per questo qui **non si scrive un test dedicato**: si tratta di un cambio di default a una riga, verificato tramite la suite esistente (Step 2) e la validazione manuale del Task 3.

- [ ] **Step 1: Modificare il default in `base.py`**

Riga 265, da:

```python
OLLAMA_CHAT_MAX_HISTORY_MESSAGES = int(env("OLLAMA_CHAT_MAX_HISTORY_MESSAGES", "6") or "6")
```

a:

```python
OLLAMA_CHAT_MAX_HISTORY_MESSAGES = int(env("OLLAMA_CHAT_MAX_HISTORY_MESSAGES", "16") or "16")
```

- [ ] **Step 2: Eseguire la suite `ai_assistant` (regressione)**

Run: `".venv\Scripts\python.exe" django_app\manage.py test ai_assistant --settings=config.settings.test --keepdb -v 1`
Expected: nessuna nuova failure (i test sul troncamento storico usano `override_settings` con valori espliciti, indipendenti dal default).

- [ ] **Step 3: Aggiornare CHANGELOG.md e committare**

Aggiungere sotto `## [Unreleased]` una voce per il cambio (file: `django_app/config/settings/base.py`), spiegando che allarga la memoria conversazionale di default da 5 a 8 scambi (10→16 messaggi), dentro il margine di `OLLAMA_NUM_CTX=16384` — sotto-progetto 1/3, stessa spec del Task 1.

```bash
git add django_app/config/settings/base.py CHANGELOG.md
git commit -m "feat(ai): allarga il default della finestra di storico conversazione a 16 messaggi"
```

**Nota operativa (non automatizzabile da qui)**: l'`.env` di sviluppo attuale sovrascrive già `OLLAMA_CHAT_MAX_HISTORY_MESSAGES=10`. Il nuovo default (16) **non avrà effetto in questo ambiente dev** finché qualcuno non alza (o rimuove) quella riga in `django_app/.env` — da segnalare all'utente, non modificabile da qui. Verificare anche `config\.env` di test/prod per lo stesso motivo.

---

### Task 3: Set di domande golden + runbook di validazione (Approccio A) e benchmark (Approccio B)

**Files:**
- Create: `docs/ai/GOLDEN_ARGOMENTAZIONE_CHAT.md`
- Modify: `docs/ai/OLLAMA_GPU_TUNING.md` (append, fine file dopo la riga 130)

**Interfaces:**
- Nessuna: task interamente documentale, nessun codice/test coinvolto (per policy repo: "Nessun test richiesto per modifiche solo-documentazione").

- [ ] **Step 1: Creare il set di domande golden**

Creare `docs/ai/GOLDEN_ARGOMENTAZIONE_CHAT.md` con questo contenuto:

```markdown
# Golden set — qualità/argomentazione risposte chat AI

Set fisso di domande per validare a occhio (nessun punteggio automatico, per
scelta di design — vedi `docs/superpowers/specs/2026-07-09-assistente-ai-qualita-argomentazione-design.md`)
se una modifica al system prompt, alla finestra di storico, o al modello di chat
migliora la profondità argomentativa delle risposte. Rilanciare l'intero set
prima/dopo ogni modifica (Approccio A) o per ogni modello candidato (Approccio B)
e confrontare le risposte affiancate.

1. Perché è importante rispettare i tempi di reintegro dei DPI in scadenza, e cosa rischia chi non lo fa?
2. Qual è la differenza tra un'anomalia e un ticket, e quando devo usare l'uno o l'altro?
3. Come funziona il flusso di approvazione di un'assenza, dal dipendente al responsabile?
4. Che rischi comporta operare una macchina senza l'abilitazione richiesta, e come si ottiene l'abilitazione?
5. Quali sono i passi concreti per segnalare un near miss, e perché conviene farlo anche se non è successo nulla di grave?
6. Cosa cambia tra le procedure SGI in vigore e quelle superate, e come faccio a sapere qual è la revisione corrente?
7. Perché il portale a volte mi dice che non ha accesso a certi dati, invece di rispondere direttamente?
8. Come si collega la formazione obbligatoria alle mansioni e ai rischi specifici del mio ruolo?
9. Quali sono i vantaggi e gli svantaggi di aprire un ticket invece di segnalare direttamente al reparto IT?
10. Cosa devo considerare prima di richiedere un permesso invece delle ferie ordinarie?
11. Come cambia la procedura di gestione DPI tra un dipendente nuovo e uno che deve solo rinnovare?
12. Quali passi seguire se il mio responsabile non risponde a una richiesta urgente in tempo?

## Criterio di giudizio (a occhio, non automatico)

Per ogni risposta, chiedersi: spiega il perché oltre al cosa? Usa un esempio o
passi concreti quando pertinente? Resta ancorata al contesto/documenti reali
(nessuna invenzione di codici/procedure)? Se la risposta a una di queste è "no"
mentre nella versione precedente era "sì", la modifica è una regressione.
```

- [ ] **Step 2: Aggiungere la sezione di benchmark a `OLLAMA_GPU_TUNING.md`**

Aggiungere in fondo al file (dopo la riga 130, ultima riga esistente "  liberare VRAM agire prima su KV-cache (`q8_0`) e `max_loaded_models=1`."), questo nuovo blocco:

```markdown

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
```

- [ ] **Step 3: Verificare i file creati**

Run: `ls "docs/ai/GOLDEN_ARGOMENTAZIONE_CHAT.md"` (o `Get-Item` in PowerShell) e rileggere al volo `docs/ai/OLLAMA_GPU_TUNING.md` per controllare che la sezione 4 sia ben formattata (markdown valido, nessun blocco di codice non chiuso).

- [ ] **Step 4: Aggiornare CHANGELOG.md e committare**

Aggiungere sotto `## [Unreleased]` una voce per i due file doc (`docs/ai/GOLDEN_ARGOMENTAZIONE_CHAT.md` nuovo, `docs/ai/OLLAMA_GPU_TUNING.md` sezione 4 aggiunta), spiegando che completano il sotto-progetto 1/3 con il runbook di validazione manuale.

```bash
git add docs/ai/GOLDEN_ARGOMENTAZIONE_CHAT.md docs/ai/OLLAMA_GPU_TUNING.md CHANGELOG.md
git commit -m "docs(ai): golden set e runbook benchmark per qualità argomentazione chat"
```

---

## Self-review (fatta durante la stesura di questo piano)

- **Copertura spec**: Approccio A → Task 1 (A1, prompt) + Task 2 (A2, storico). Approccio B → Task 3 (runbook + golden set riusato anche da A). Approccio C e il 4° tema (fine-tuning) restano volutamente **fuori da questo piano** (backlog, come da spec). Metrica `AiChatFeedback` richiamata nel runbook (Task 3), nessuna nuova infrastruttura di valutazione creata (coerente con la spec).
- **Niente placeholder**: ogni step ha contenuto/codice reale; dove un test sarebbe stato circolare o falsato dall'ambiente (Task 2) è spiegato esplicitamente perché si omette, invece di inventare un test finto.
- **Coerenza dei nomi**: `OLLAMA_CHAT_SYSTEM_PROMPT`, `OLLAMA_CHAT_MAX_SYSTEM_PROMPT_CHARS`, `OLLAMA_CHAT_MAX_HISTORY_MESSAGES` usati identici in Task 1/2 e nel codice reale (`ai_assistant/services.py`); nessuna funzione nuova quindi nessun rischio di firme disallineate tra task.
- **Nessuna migration, nessun impatto ACL** in nessuno dei 3 task — confermato.
