# RUNBOOK — Deploy batch AI/RAG (branch `feature/skill-matrix-mod187`)

> Procedura operativa per portare in prod il batch AI/RAG (fix latenza embeddings,
> panoramica documento, tool Skill Matrix, watchdog share SGI, system check di igiene).
> Prod gira su **pclogsys**, branch **`feature/skill-matrix-mod187`** (NON `main`).
> Tutti i comandi Django: venv prod + `--settings=config.settings.prod`, cwd = `current`.

---

## Cosa contiene il batch (già committato + pushato sul branch)

| Commit | Contenuto |
|---|---|
| `9640ff8` | fix latenza: lettura cache embeddings a batch (`OLLAMA_EMBED_CACHE_GET_BATCH`), RAG index status, dedup import SGI |
| `9042285` | `core/checks.py`: `core.E001` (`.env` duplicati → `check` fallisce) + `core.W001` (cache RAG piccola) |
| `d7461f5` | `monitoring/system_status`: card "Indice documentale (RAG)" |
| `e64d2c0` | watchdog `sgi_share_check` (solo-notifica) + schedule CRON 04:30 |
| `ea94243` | modalità "panoramica documento" (scopo + indice sezioni, no confabulazione) |
| `9444f3b` | tool live **Skill Matrix** (gated, safe-by-default) |
| `4e616f7` | comando `ai_seed_skillmatrix_privacy_review` + GUIDA_AI.html v1.6 |
| `1582870` | fix conflitto migrazioni gcm (merge `0005`) |

Il pacchetto si costruisce dal **working tree** (non da un commit): vedi pre-flight.

---

## 0) Pre-flight (su DEV)

- [ ] Sei sul branch giusto: `git rev-parse --abbrev-ref HEAD` → `feature/skill-matrix-mod187`.
- [ ] **Working tree = ciò che vuoi shippare.** `package-release.ps1` impacchetta il working tree corrente (allowlist: `django_app`, `deployment`, `tools`, `sql`, `VERSION/README/CHANGELOG/CLAUDE`).
  - Oltre all'AI work, il working tree contiene la **UI gcm non committata** della sessione `gestione_carichi_macchina` (verde, 108 test) e modifiche `CHANGELOG/README` di altre sessioni. **Decidi se shipparla** o falla finalizzare/committare prima dalla sua sessione.
  - La migrazione gcm `0005_merge` **è committata** ed è necessaria (leaf singolo): va inclusa comunque.
- [ ] `git status` pulito da file dati (`.xlsx/.csv/.pdf/.sqlite`) — l'allowlist li esclude, ma verifica.

## 1) Build pacchetto (su DEV)

```powershell
.\deployment\scripts\package-release.ps1          # +  -WithTests  per un batch AI significativo
```
- Esegue `release_guard.ps1`: Django `check`, `makemigrations --check`, `secret_hygiene_check`, `bootstrap_acl_v2 --apply`, `acl_coverage_report --max-missing 222`, `validate_deployment` (tutti su `config.settings.test`). **Exit ≠ 0 blocca il pacchetto.**
- Output zip in `C:\PortaleNovicrom\shared\packages\portale-novicrom-v<VER>-<timestamp>.zip`.
- Copia lo zip sul server **pclogsys**.

## 2) `.env` di prod (su SERVER, PRIMA del deploy)

Edita **SOLO** il persistente: `C:\PortaleNovicrom\prod\config\.env` (NON `current\django_app\.env`, effimero).

**Riattiva gli embeddings** (erano OFF come stopgap latenza; il fix è in `9640ff8`):
```ini
OLLAMA_EMBED_ENABLED=1
RAG_EMBED_BACKEND=openai
RAG_EMBED_OPENAI_BASE_URL=http://10.0.0.34:8081      # host TEI (PCGAVANCINI) — VERIFICA host/porta reali
RAG_EMBED_OPENAI_MODEL=BAAI/bge-m3                    # modello TEI — VERIFICA col tag effettivo
# RAG_EMBED_OPENAI_API_KEY=  (vuota se TEI non la richiede)
```
- **PULISCI le chiavi duplicate** (note: chiavi AI duplicate in prod). Con `9042285` attivo, `manage.py check` **FALLISCE** (`core.E001`) finché restano duplicati — quindi la pulizia è obbligatoria, non opzionale.
- Cache: `MAX_ENTRIES` è già 50000 di default (`core.W001` non scatta); non serve toccarla salvo override più bassi.
- ⚠️ **Drift**: se le pagine admin avevano scritto sull'attivo, `config\.env` e l'attivo divergono e il deploy **si ferma**. Allinea le modifiche in `config\.env` e rilancia; usa `-AllowEnvDrift` **solo** per forzare il ripristino da `config\.env`.

## 3) Deploy (su SERVER, shell admin)

```powershell
.\deploy-release.ps1 -Environment prod -PackagePath "C:\PortaleNovicrom\shared\packages\portale-novicrom-v....zip"
#  +  -AllowEnvDrift   se l'attivo era stato modificato a mano e vuoi forzare config\.env
```
- Fa: estrai → copia `config\.env`→release → `pip install` → `collectstatic --clear` → **ACL IIS static/media** (IIS_IUSRS/IUSR RX, media_private Modify) → **migrate GLOBALE** + `showmigrations` → `ensure_legacy_schema` → `createcachetable` → `setup_q_schedules` → `warmup_ollama`.
- Il **migrate globale** applica: `ai_assistant 0002_aitoolprivacyreview`, `gcm 0005_merge` (+`0003`,+`0004`×2) e ogni residuo (idempotente). Copre il pitfall del migrate selettivo del wizard (app opzionali non selezionate).
- ❌ **NON** usare `-SkipMigrate`: salterebbe anche `ensure_legacy_schema`, `allinea_tipo_assenza` e `setup_q_schedules` (il nuovo schedule **non** verrebbe registrato).

## 4) Attivazione (su SERVER)

```powershell
.\activate-release.ps1 -Environment prod -ReleaseTag <tag> -SkipSmokeTest
```
- ⚠️ **USA `-SkipSmokeTest`**: lo smoke punta a `http://localhost:80`, ma in prod l'app risponde per **host header** (Entra App Proxy) → lo smoke fallirebbe e innescherebbe un **rollback indesiderato**.
- Conferma interattiva `SI` (o `-SkipConfirmProd`).
- **Verifica a mano dal browser**: `https://cnhub-costruzioninovicrom.msappproxy.net/`
- Rollback rapido: `.\rollback-release.ps1 -Environment prod` (o automatico se lo smoke fallisce senza skip).

## 5) Go-live AI (su SERVER, venv prod, `--settings=config.settings.prod`, cwd `current`)

```powershell
# 1. GATE: deve passare (core.E001 = nessuna chiave .env duplicata)
python django_app\manage.py check --settings=config.settings.prod

# 2. RAG: re-index OBBLIGATORIO dopo aver riacceso gli embeddings
#    (l'indice attuale è BM25-only perché costruito con embeddings OFF;
#     questo passo calcola e CACHA i vettori bge-m3 via TEI)
python django_app\manage.py index_sgi_documents --json --settings=config.settings.prod
#    (solo se la share ha doc nuovi: prima import_sgi_da_share --json poi --apply, poi re-index)

# 3. ACCENDI il tool Skill Matrix (safe-by-default → inerte finché non approvato)
python django_app\manage.py ai_seed_skillmatrix_privacy_review --approve --settings=config.settings.prod

# 4. (Ri)registra gli schedule, incl. sgi_share_check (CRON 04:30)
python django_app\manage.py setup_q_schedules --settings=config.settings.prod

# 5. Healthcheck completo (TEI/Ollama, embed dim, RAG recall, schedule, cluster)
.\tools\ai_healthcheck_prod.ps1
```

## 6) Verifiche finali

- [ ] Chat: «di cosa parla MT CN 06» → **panoramica** (scopo + indice sezioni), non confabulazione.
- [ ] Chat: «chi può sostituire DM11» → il tool **Skill Matrix** legge il DB (solo se l'utente ha l'ACL canonico `anagrafica.skillmatrix.view`).
- [ ] `monitoring` → `/system_status` → card **"Indice documentale (RAG)"** popolata (`embeddings_ready`, n. chunk).
- [ ] `ai_healthcheck_prod.ps1` exit 0 (TEI raggiungibile, `dim 1024`, `sgi_chunks > 0`, retrieval ibrido).
- [ ] `Schedule.objects.filter(name='sgi_share_check')` presente (l'healthcheck NON lo verifica da solo).

---

## Gotcha (verificati nel codice)

- **Skill Matrix** resta inerte finché: (a) `--approve` eseguito **E** (b) l'utente ha l'ACL `anagrafica.skillmatrix.view`. Per **spegnerlo** dopo: `ai_seed_skillmatrix_privacy_review --status blocked` (rilanciarlo nudo NON lo spegne).
- **`index_sgi_documents` è fail-safe**: senza `--fail-on-error` non segnala se TEI/Ollama sono giù (resta BM25-only). Per un go-live che vuole davvero gli embeddings, valuta `--fail-on-error` o conferma via healthcheck (check 4).
- **`sgi_share_check`** è solo-notifica: apre/risolve una Issue LOW in `monitoring` se la share SGI ha doc nuovi/aggiornati; **l'import resta manuale**.
- **`setup_q_schedules`** salta (e cancella) gli schedule marcati `disabled` in `monitoring.ScheduleControl`: se `sgi_share_check` risultasse disabilitato nella centrale di comando, NON verrebbe registrato.
- **django-q2**: lo schedule usa `schedule_type='C'` (CRON) → niente crash dei tipi `'S'` (SECONDS). Cluster via Task Scheduler `QCluster_PROD`.
- **`.env`**: fonte di verità = `C:\PortaleNovicrom\prod\config\.env`. L'attivo `current\django_app\.env` è usa-e-getta (riscritto a ogni deploy).
- **Doppio flusso wizard**: le pagine `InstallPage` e `ReleaseRunPage` hanno entrambe il migrate + safety-net; una modifica futura va replicata in entrambe.
