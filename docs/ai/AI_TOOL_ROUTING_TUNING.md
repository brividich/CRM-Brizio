# Ritaratura del routing semantico dei tool AI

Quando si aggiungono nuovi domini/tool (es. Ondata 6: `contatori`, `schede_sicurezza`,
`suggestioni`) le soglie del routing semantico vanno **verificate e, se serve, ritarate**:
erano calibrate sui domini storici e su un dato modello di embedding.

Il **gate keyword** dei tool funziona sempre (indipendente dagli embeddings). Il routing
**semantico** aggiunge *recall* sulle frasi "fuori vocabolario" (quelle che non contengono
le parole-chiave). Questa procedura serve a garantire che anche quelle attivino il tool giusto.

## Come funziona (in breve)

Per ogni dominio in `ai_assistant/tools.py::_DOMAIN_ROUTING_SEEDS` si calcolano gli embedding
delle frasi-seme (cache di processo, chiave = modello effettivo). La domanda viene embeddata e
confrontata (coseno) coi seed; un dominio "si attiva" se supera la soglia ed è tra i top-K entro
un margine dal punteggio migliore (`ai_assistant/tools.py::_active_from_ranked`). Un tool gira se
il suo gate keyword scatta **oppure** se il suo dominio è semanticamente attivo (`_should_run`).

## Settings (default in `config/settings/base.py`)

| Setting | Default | Effetto |
|---|---|---|
| `AI_TOOL_ROUTING_ENABLED` | `True` | On/off del routing semantico (off = solo keyword). |
| `AI_TOOL_ROUTING_THRESHOLD` | `0.70` | Similarità minima per attivare un dominio. **Abbassare** se i nuovi domini non scattano. |
| `AI_TOOL_ROUTING_MARGIN` | `0.04` | Quanto sotto il top può stare un dominio per entrare comunque. |
| `AI_TOOL_ROUTING_TOP_K` | `2` | Max domini attivati per domanda. |
| `AI_TOOL_ROUTING_EMBED_TIMEOUT_SECONDS` | `6` | Timeout breve: se l'endpoint è lento degrada a keyword-only. |

## Procedura (in PROD, dove gli embeddings sono live)

Il routing semantico ha bisogno di TEI/Ollama attivi: **in locale/offline non si misura** (il
comando lo segnala e degrada a keyword-only).

1. **Verifica embeddings live**: `tools/ai_healthcheck_prod.ps1` (vedi runbook AI prod) e
   `ollama ps` / stato TEI. Ricorda: prod gira su `pclogsys`, embeddings `bge-m3` via TEI.
2. **Sonda il routing**:
   ```powershell
   python django_app\manage.py ai_routing_probe            # batch di sonde predefinite
   python django_app\manage.py ai_routing_probe --prompt "che precauzioni per l'acetone?"
   ```
   Legge una tabella per prompt: `top` (dominio=score…) e `attivi` (domini che scattano), con
   `OK`/`MISS` rispetto al dominio atteso delle sonde predefinite.
3. **Se i nuovi domini danno MISS**: abbassa `AI_TOOL_ROUTING_THRESHOLD` a piccoli passi
   (es. `0.70 → 0.66 → 0.62`), oppure alza `AI_TOOL_ROUTING_TOP_K`/`_MARGIN`. Ri-sonda.
4. **Controlla i falsi positivi**: verifica che le sonde NON attivino domini errati (un
   threshold troppo basso fa scattare tutto). Le sonde di baseline (`assets`, `carichi`)
   devono restare corrette.
5. **Persisti i valori scelti** in `config\.env` (persistente, sopravvive ai deploy — NON
   `current\django_app\.env`, che il deploy riscrive).
6. **Riavvia l'app-pool** (invalida la cache di processo dei seed `_ROUTING_SEED_CACHE`).

## Note

- **Cambio del modello di embedding** (es. `nomic → bge-m3`) invalida automaticamente la cache
  dei seed (la chiave include il modello effettivo): ri-tarare dopo un cambio modello.
- Se il routing è spento o gli embeddings sono giù, i tool restano raggiungibili via **keyword**:
  nessuna regressione funzionale, solo meno recall sulle frasi fuori vocabolario.
- Il comando `ai_routing_probe` è read-only (nessuna scrittura), sicuro da eseguire in prod.
