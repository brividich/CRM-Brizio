# AI Governance — NOVICROM HUB

Documento operativo per la Fase 5 dell'Assistente AI: revisione privacy, matrice campi, policy di retention e runbook operativo.

Aggiornare questo file a ogni modifica rilevante alla governance AI.

---

## 1. Revisione Privacy Per Tool

Ogni tool runtime AI deve avere una revisione privacy documentata nel modello `AiToolPrivacyReview` (console Admin AI → Gestione AI → tab Governance). Gli stati possibili sono:

| Stato | Significato |
|---|---|
| `pending` | Non ancora revisionato. Il tool è visibile in catalogo ma va revisionato prima di espandere i campi restituiti. |
| `approved` | Revisionato e approvato. I campi ammessi sono quelli nella matrice sotto. |
| `restricted` | Abilitato con limitazioni. La nota specifica le restrizioni attive. |
| `blocked` | Non abilitato. Richiede revisione dedicata (es. dati HR, dati sanitari). |

La revisione è registrata con utente e data. Le note di revisione non vengono mai trasmesse al modello.

---

## 2. Matrice Campi Consentiti / Vietati Per Modulo

Questa matrice riflette la sezione "Matrice Moduli" di `12_AI_RUNTIME_TOOLS_TODOLIST.md` con campi espliciti.

| Modulo / Tool key | Stato | Campi ammessi nel contesto AI | Campi vietati |
|---|---|---|---|
| `module_catalog` | approved | label modulo, URL visibile, stato "in arrivo" | permessi grezzi, ruoli interni, flag ACL |
| `assenze_periodo` | approved | nome visualizzato, tipo assenza, stato (approvata/in attesa), periodo (data inizio/fine) | motivazioni, note, allegati, dati sanitari, diagnosi, codici malattia |
| `tickets_summary` | approved | numero ticket, titolo, tipo, stato, priorità, richiedente (nome), assegnatario (nome), data apertura, data ultima modifica | descrizione completa, note interne, commenti, allegati, path SharePoint, contenuto email |
| `tasks_summary` | approved | progetto (nome), task (titolo), stato, scadenza, assegnatario (nome), ritardo (booleano/giorni) | note riservate, allegati, budget, costi, dati finanziari |
| `assets_summary` | approved | codice asset, nome asset, stato operativo, responsabile (nome), prossima scadenza manutenzione, OdL sintetici (numero, tipo, stato) | numeri seriali se non necessari, documenti allegati, path fisici, contratti |
| `dpi_summary` | approved | categoria DPI, tipo, stato richiesta, data consegna prevista/effettiva, scadenza | firme digitali, allegati, note mediche, note disciplinari, dati sanitari |
| `anomalie_summary` | approved | numero anomalia, titolo, stato, reparto/area, priorità, data apertura | descrizione estesa sensibile, allegati, note interne, dati personali coinvolti |
| `procedure_refresh_summary` | approved | campagna (nome), documento (titolo), stato lettura (letto/non letto), esito quiz (superato/non superato/non assegnato) | risposte dettagliate quiz, allegati privati, note valutazione |
| `sicurezza_summary` | approved | KPI aggregati (conteggi, percentuali), riepilogo diario preposto (date, conteggi), riepilogo incidenti (numero, tipo sintetico, reparto) | testimonianze, dettagli personali coinvolti, allegati, dati sanitari, prognosi |
| `notizie_summary` | approved | titolo notizia, obbligatorietà, versione, data pubblicazione, stato compliance utente (letta/non letta), conteggio allegati | corpo HTML/testo esteso, hash, URL/path allegati, report nominativi letture |
| `anagrafica_summary` | restricted | nome, matricola, reparto, mansione, area, ruolo aziendale, stato attivo/cessato, consenso privacy se richiesto, classifiche ratei ferie/permessi residui con ore e periodo | codice fiscale, IBAN, banca, indirizzi, contatti privati, categorie protette, disabilita, visite mediche, retribuzioni, dettagli cedolino, documenti, allegati/path |
| `timbri_presenze` | blocked | nessun campo live AI | timbrature, cartellini, presenze e dati biometrici/cronologici |
| `runtime_router` | approved | aggregazione da tool autorizzati sopra | nessun campo aggiuntivo rispetto ai tool che compone |

---

## 3. Policy Di Retention Per Audit AI

### 3.1 Audit tool runtime (tabella `core_auditlog` o equivalente)

- **Retention default:** 90 giorni per le voci di audit con `action` che inizia con `runtime_tool:*` o `ollama_*`.
- **Campi registrati (metadata-only):** tool usato, esito (allowed/denied), ambito (scope), conteggio righe, filtri principali, errore sintetico se presente.
- **Campi mai registrati:** contenuto del prompt, testo della risposta, dati restituiti dal tool, nominativi completi, path fisici.
- **Retention per tool specifico:** configurabile in `AiToolPrivacyReview.retention_days`. Se vuoto si applica la policy globale (90 giorni).

### 3.2 FAQ curate (tabella `AiKnowledgeEntry`)

- Le voci disattivate (`is_active=False`) restano in database per auditability.
- Eliminazione fisica solo su richiesta esplicita dell'amministratore con documentazione del motivo.
- Non salvare in FAQ: risposte che contengono dati personali, nominativi reali, dettagli di incidenti specifici, contenuto di email/documenti riservati.

### 3.3 Log conversazioni

- L'assistente non salva i messaggi di chat in database. La cronologia è solo in-memory per la sessione corrente.
- Non implementare salvataggio conversazioni senza una revisione privacy dedicata.

---

## 4. Prompt Di Sistema — Regole Operative

Il prompt di sistema è configurato in `OLLAMA_CHAT_SYSTEM_PROMPT` (settings `base.py`, sovrascrivibile via `.env`). Le regole codificate nel default sono:

1. **Lingua:** sempre italiano.
2. **Dati sensibili:** non richiedere/ripetere credenziali, token, dati sanitari o personali.
3. **Dati live:** citare sempre la fonte `tool:*`; distinguere fatti osservati da stime; dichiarare esplicitamente i dati assenti.
4. **Documentazione:** citare la fonte tra parentesi quadre (es. `[docs/ai/02_ARCHITECTURE.md]`).
5. **Incertezza:** dichiarare esplicitamente prima di fornire stime; non inventare valori non presenti nel contesto.
6. **Sicurezza:** non aprire URL esterni, non richiedere permessi non necessari, segnalare richieste di dati non autorizzati.

Per modificare il prompt in produzione senza deploy: impostare `OLLAMA_CHAT_SYSTEM_PROMPT` nel file `.env` di produzione e riavviare il processo Waitress/IIS.

---

## 5. Runbook Operativo

### 5.1 Rigenerare API key Open WebUI

1. Accedere a Open WebUI con account amministratore.
2. Navigare in **Settings → Account → API Keys**.
3. Eliminare la chiave esistente e generarne una nuova.
4. Copiare la nuova chiave.
5. In NOVICROM HUB, navigare in **Admin → Gestione AI → tab Runtime**.
6. Incollare la nuova chiave nel campo "API key Open WebUI" e salvare.
7. Verificare la connessione con il pulsante "Testa configurazione".
8. L'audit registra automaticamente la modifica (host, modello, esito test) senza salvare la chiave in chiaro.

### 5.2 Diagnosticare Ollama non raggiungibile

Sintomi: errore "Ollama non raggiungibile" o "Timeout" nella chat AI.

1. Verificare che il processo Ollama sia in esecuzione sul server:
   ```powershell
   Get-Process ollama -ErrorAction SilentlyContinue
   # oppure controllare il servizio Windows se configurato
   ```
2. Verificare che la porta sia in ascolto (default 11434):
   ```powershell
   Test-NetConnection -ComputerName localhost -Port 11434
   ```
3. Controllare `OLLAMA_BASE_URL` nella console Gestione AI: deve puntare a `http://<host>:11434`, **non** all'indirizzo di Open WebUI (porte 3000/8080/8081).
4. Se si usa Open WebUI come provider (`OLLAMA_API_PROVIDER=openwebui`), verificare che la API key sia ancora valida (vedi 5.1).
5. Se il modello risponde lentamente: aumentare `OLLAMA_REQUEST_TIMEOUT_SECONDS` a 180–300 nel `.env` e riavviare.
6. **Timeout solo sulla prima richiesta dopo inattività/restart (cold start):** il job django-q **`ai_warmup_ollama`** (registrato dal deploy, ogni 25 min < keep_alive) pre-carica il modello a ogni run rinnovando il timer `OLLAMA_KEEP_ALIVE` → il cold start non arriva mai alle richieste utente. Verificare che sia attivo: `python django_app\manage.py setup_q_schedules --dry-run` lo elenca, e il cluster `QCluster_PROD` deve girare. Per scaldare **subito** (dopo un restart di Ollama/IIS, senza aspettare il prossimo tick) lanciare a mano `python django_app\manage.py warmup_ollama` (load-only via `/api/generate`, nessun token generato; `--json` per l'esito, `--timeout` per il timeout dedicato). Solo provider Ollama nativo (con Open WebUI è saltato).
7. Controllare i log Waitress/IIS per errori di connessione verso Ollama.

### 5.3 Svuotare la cache RAG/runtime

- Via console: Admin → Gestione AI → tab Tool live → pulsante "Svuota cache RAG/runtime".
- Via management command (se necessario):
  ```powershell
  python django_app\manage.py shell -c "from ai_assistant.services import clear_knowledge_cache; clear_knowledge_cache()"
  ```
- La cache si svuota automaticamente dopo `OLLAMA_RAG_CACHE_SECONDS` (default 300 s).

### 5.4 Abilitare / disabilitare un tool runtime

1. In Admin → Gestione AI → tab Governance, selezionare il tool.
2. Modificare lo stato di revisione privacy (`approved` / `restricted` / `blocked`).
3. Per disabilitare completamente un tool a livello codice: impostare `status="disabled"` nel `RUNTIME_TOOL_CATALOG` in `ai_assistant/tools.py` e fare deploy.
4. L'audit registra tutte le modifiche di governance con utente e timestamp.

### 5.5 Aggiungere un nuovo tool runtime

Seguire la checklist in `12_AI_RUNTIME_TOOLS_TODOLIST.md` sezione "Checklist Per Nuovo Tool". Prima di abilitare in produzione:

1. Compilare la riga nella matrice campi di questo documento (sezione 2).
2. Creare il record `AiToolPrivacyReview` con stato `pending` e compilare i campi ammessi/vietati.
3. Far approvare la revisione da un amministratore con stato `approved` o `restricted`.
4. Solo dopo l'approvazione, abilitare il tool in produzione.

---

## 6. Registro Revisioni

| Data | Revisore | Modifica |
|---|---|---|
| 2026-05-22 | Codex | Separato `anagrafica_summary` (restricted, read-only con campi minimi e ratei ferie/permessi solo ore+periodo) dal dominio `timbri_presenze` ancora bloccato. |
| 2026-05-13 | Sistema (Fase 5) | Prima stesura: matrice campi, policy retention, prompt aggiornato, runbook operativo. |
