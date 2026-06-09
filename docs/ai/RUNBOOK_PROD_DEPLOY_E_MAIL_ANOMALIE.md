# Runbook — Topologia deploy PROD & incidente mail anomalie (401)

> Nota operativa creata il 2026-06-09 a valle dell'incidente 401 sull'automazione
> mail anomalie CC/CAR. Le citazioni a file/righe possono invecchiare: verifica
> sempre sul codice corrente prima di darle per certe.

## 1. Topologia deploy PROD / TEST

Server **`pclogsys`** (IP **10.0.0.17**). Ispezionabile dalla workstation tramite share:

- **`X:` = `\\pclogsys\c$\portalenovicrom`** → root del deploy.
  (`Y:` = `\\pclbova\dev` = repo di **sviluppo**, NON è PROD.)
- **PROD**: `X:\prod\current` è una **junction** verso `X:\prod\releases\<timestamp>`.
  I rilasci sono pacchetti **ZIP scompattati** in `releases\` — in PROD **non** c'è un checkout git.
- **`.env` PROD**:
  - persistente: **`X:\prod\config\.env`** (caricato per primo)
  - copia di release: `X:\prod\current\django_app\.env`
  - il loader (`django_app/config/env_config.py`) usa `os.environ.setdefault`:
    **una variabile d'ambiente già presente nel processo MASCHERA il `.env`**.
- **Settings**: `DJANGO_SETTINGS_MODULE=config.settings.prod` (`from .base import *`);
  `env()` = `os.getenv`. `base.py` carica i `.env` con `iter_runtime_env_paths(PROJECT_DIR)`
  all'import del modulo (quindi **solo all'avvio del processo**).
- **IIS**: HttpPlatformHandler (`X:\prod\web.config`) lancia **Waitress** su porta dinamica
  `%HTTP_PLATFORM_PORT%` e **inoltra gli header**. Siti:
  - **`PortaleNovicrom-PROD`** — binding `https *:443:hub.costruzioninovicrom.it`, app pool `PortaleNovicrom-PROD` (identità **LocalSystem**), path `C:\PortaleNovicrom\prod`.
  - **`PortaleNovicrom-TEST`** — `testhub.cnovicrom.local`, path `C:\PortaleNovicrom\test`.
- **Log PROD**: `X:\prod\logs\` — `app.log` (con riga `waitress: Serving on http://0.0.0.0:<porta>`),
  `automation_queue.log`, `waitress_stdout.log_*`.
- **Split-DNS**: `hub.costruzioninovicrom.it` risolve a **10.0.0.17** sia dalla LAN sia dal server →
  le chiamate **interne** (incluso il motore automazioni) **NON passano dall'Entra Application Proxy**;
  l'Entra proxy lo vedono solo gli utenti da internet.
- **Riavvio** (rilegge il `.env` e il nuovo codice): da eseguire **sul server**
  `Restart-WebAppPool -Name 'PortaleNovicrom-PROD'` (oppure `iisreset`).
- **Repo git**: `github.com/brividich/CRM-Brizio` (codebase condiviso/whitelabel).

### Diagnostica rapida (dalla workstation, sola lettura)

```powershell
# valore del secret realmente caricato dal processo (esempio con AUTOMATION_INTERNAL_SECRET)
cd C:\PortaleNovicrom\prod\current\django_app
$env:DJANGO_SETTINGS_MODULE = "config.settings.prod"
C:\PortaleNovicrom\prod\venv\Scripts\python.exe -c "import django;django.setup();from django.conf import settings as s;print(bool(s.AUTOMATION_INTERNAL_SECRET))"

# test endpoint (split-DNS porta già su pclogsys)
curl.exe -s -k -w "`nHTTP=%{http_code}`n" -X POST "https://hub.costruzioninovicrom.it/<path>" -H "Content-Type: application/json" -d "{}"
```

## 2. Incidente: 401 sull'endpoint interno mail anomalie

**Sintomo**: la regola automazioni `http_request` verso `POST /api/anomalie/mail-action-trigger`
restituiva sempre `HTTP 401`, anche con `X-Automation-Secret` corretto.

**Causa radice**: l'endpoint è una chiamata **machine-to-machine senza sessione**
(`request.user.is_authenticated == False`) ed è JSON. Non essendo in
`MIDDLEWARE_EXEMPT_PREFIXES` (`django_app/config/settings/base.py`), l'**`ACLMiddleware`
(`core/middleware.py`) rispondeva `401` PRIMA della view** — corpo
`{"ok": false, "reason": "unauthenticated", "login_url": "..."}` — quindi il check del
secret nella view (`_verify_automation_secret`) non veniva **mai** eseguito e l'header era ignorato.

**Conferma diagnostica**: il *corpo* della 401 era quello del middleware
(`"reason":"unauthenticated"`), non quello della view (`{"error":"Unauthorized"}`).

**Fix**: aggiungere il path a `MIDDLEWARE_EXEMPT_PREFIXES`, come per gli altri surface a
token (`/automazioni/approvazione/`, `/approval-actions/`). È sicuro: l'endpoint si
autentica da solo via secret header.

> **Regola generale**: qualsiasi endpoint a **token/secret senza login** (incluso
> machine-to-machine) deve essere in `MIDDLEWARE_EXEMPT_PREFIXES`, altrimenti
> l'`ACLMiddleware` lo blocca con 401/redirect prima della view.

### Piste FALSE escluse durante la diagnosi (per non ripeterle)
- Secret mancante/diverso nel `.env` → era **corretto** (verificato dal processo).
- Variabile d'ambiente che maschera il `.env` (Machine / app pool) → **assente**.
- IIS che rimuove l'header → **no**, HttpPlatformHandler inoltra gli header.
- Entra Application Proxy → **no**, split-DNS fa restare interna la chiamata.

## 3. Divergenza implementazioni mail anomalie & unificazione branch

Due implementazioni divergenti della notifica mail anomalie CC/CAR:
- **Trigger-endpoint** (`/api/anomalie/mail-action-trigger` + `AUTOMATION_INTERNAL_SECRET`):
  commit `8843ed6`, branch `backup/wip-pre-align-20260609`, era **deployato in PROD**.
- **Token-link** (`/gestione-anomalie/mail-action/<token>`, `mail_action_views.py`,
  modello `AnomaliaMailActionToken`): su **`main`** (linea avanzata).

**Decisione (2026-06-09)**: unificare tutto su **`main`** con l'implementazione **token-link**
come canonica; il trigger-endpoint si archivia. Snapshot PROD preservato nel tag
**`prod-deployed-20260609`** (su `8843ed6`). Branch obsoleti rimossi; `main` allineato con
merge di `origin/main` (Dependabot/SEC). Quando `main` verrà deployato, PROD passerà al
token-link e il tema trigger-endpoint diventa superato.
