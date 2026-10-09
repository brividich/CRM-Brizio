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
| `c383807` | **Fase 1**: regression gate RAG in `release_guard` + fix cache-key routing bge-m3 |
| `3ffb015` | **Fase 2/A1**: tool live "Rischi & requisiti per mansione" (attivo al deploy, gate ACL Formazione) |
| `687e5c1` + `c6d34c8` | **Fase 2/A3**: copilota Anomalie (triage) backend + UI React (pannello suggerimenti) |
| `4728cca` + `ce81196` | **Fase 2/A2**: copilota Incidenti/RCA (5-Why) backend + UI + mappa `API_ACL_GATE_PATHS` |
| GUIDA v1.9 | doc copiloti Anomalie/Incidenti |

Nessuna nuova chiave `.env` né migrazione dalle Fasi 1/2 (i copiloti usano la config Ollama esistente; il gate RAG è dev-only in `release_guard`). Il pacchetto si costruisce dal **working tree** (non da un commit): vedi pre-flight.

---

## 0) Pre-flight (su DEV)

- [ ] Sei sul branch giusto: `git rev-parse --abbrev-ref HEAD` → `feature/skill-matrix-mod187`.
- [ ] **Working tree = ciò che vuoi shippare.** `package-release.ps1` impacchetta il working tree corrente (allowlist: `django_app`, `deployment`, `tools`, `sql`, `VERSION/README/CHANGELOG/CLAUDE`).
  - Oltre all'AI work, il working tree contiene la **UI gcm non committata** della sessione `gestione_carichi_macchina` (verde, 108 test) e modifiche `CHANGELOG/README` di altre sessioni. **Decidi se shipparla** o falla finalizzare/committare prima dalla sua sessione.
  - La migrazione gcm `0005_merge` **è committata** ed è necessaria (leaf singolo): va inclusa comunque.
- [ ] `git status` pulito da file dati (`.xlsx/.csv/.pdf/.sqlite`) — l'allowlist li esclude, ma verifica.
- [ ] ⚠️ **UI React non verificata in browser.** Le UI copilota (A2 `rilevazione-incidenti/nuovo`, A3 `apertura_segnalazione` **React**) compilano lato Django e hanno endpoint testati, ma il rendering **JSX/Babel** si valida solo a runtime. **Subito dopo l'attivazione apri** `apertura_segnalazione` e `rilevazione-incidenti/nuovo`: conferma che i form renderizzano e che i pulsanti «Proponi…» rispondono. Se il **form React non appare** → errore JSX → **rollback** (`rollback-release.ps1`). Consigliato: provarle prima in **test/UAT**.

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

---

## Database SGI — setting e passi (traccia A, fase A1)

Tutti con default che lasciano il comportamento invariato. Si impostano nel `.env` persistente (`config\.env`).

| Setting | Default | Effetto |
|---|---|---|
| `PROCEDURE_REFRESH_SGI_EXTENSIONS` | `.pdf` | estensioni scandite sulla share (lista con `,`); la share oggi ha solo PDF |
| `PROCEDURE_REFRESH_SGI_PREFER_PDF` | `True` | a parità di codice+revisione vince il PDF |
| `SGI_ESTRAZIONE_PERSISTITA_ENABLED` | `False` | l'assistente legge `SgiTestoEstratto` (se l'hash coincide) e la sync notturna accoda l'estrazione |
| `OLLAMA_RAG_SGI_CHUNK_CHARS` | = `OLLAMA_RAG_CHUNK_CHARS` | dimensione chunk SGI |
| `OLLAMA_RAG_SGI_CHUNK_HEADER` | `False` | intestazione «codice Rev.n — § sezione» nel testo del chunk |
| `OLLAMA_RAG_SGI_CHUNK_TITLE` | `False` | titolo del documento nell'etichetta dei chunk SGI. **Consigliato `True`**: in dev SGI recall 27→31/32, MRR 0,623→0,772, KB invariata. Poi `index_sgi_documents` |
| `OLLAMA_RAG_SGI_MAX_PROCS` | `400` (era 300) | tetto revisioni procedura nel corpus RAG |
| `OLLAMA_RAG_GLOSSARIO_ENABLED` | `False` | glossario tecnico nella ricerca (token comuni per le varianti, H7/M8/Ra protetti, termini validati come conoscenza). Da accendere solo dopo che la Qualità ha validato i termini |
| `OLLAMA_RAG_GLOSSARIO_INCLUDE_BOZZE` | `False` | **MAI in prod**: include le bozze, serve solo per misurare in dev |

Dopo `index_sgi_documents`: `glossario_varianti_comuni` aggiorna la sezione «Parole comuni» della pagina «Da rivedere» del glossario (sola lettura sui documenti, scrive solo in cache).

Passi (solo quando si decide di accendere l'estrazione persistita, dopo misura `ai_eval --rag-sgi` non peggiorativa):
1. `migrate procedure_refresh` (0008, solo nuova tabella).
2. `sgi_estrai_testi --dry-run`, poi `sgi_estrai_testi` (~7 min per ~250 PDF, sola lettura sulla share).
3. `SGI_ESTRAZIONE_PERSISTITA_ENABLED=True` nel `.env`, riavvio sito e qcluster.
4. `index_sgi_documents`: il testo dei chunk cambia, quindi **gli embeddings vanno ricalcolati** (stesso discorso se si cambiano `OLLAMA_RAG_SGI_CHUNK_CHARS` o `OLLAMA_RAG_SGI_CHUNK_HEADER`).
5. `ai_eval --rag-sgi` e confronto con `docs/ai/baseline/`.

Riferimenti tra documenti (A2, nessun flag: dati deterministici, non toccano l'assistente):
1. `migrate procedure_refresh` (0009, due tabelle nuove).
2. Dopo `sgi_estrai_testi`: `sgi_riferimenti` (primo popolamento + report; poi si aggiornano da soli a ogni nuova estrazione).
3. `sgi_collega_processi --dry-run`, poi `--apply`: le proposte restano da confermare in admin (Procedure › Documenti SGI di processo).

## Checklist deploy — blocco database SGI (A1, A2) + glossario tecnico (B1, B2), v2

Su SERVER, venv prod, `--settings=config.settings.prod`. Tempi stimati da dev (la reindicizzazione con embeddings va misurata in prod). Dopo `migrate` nulla è distruttivo: i comandi scrivono solo tabelle nuove o metadati.

| # | Passo | Tempo | Rollback |
|---|---|---|---|
| 0a | **Backup completo del DB SQL Server**, verificato (`RESTORE VERIFYONLY`), prima di qualsiasi `migrate` o `--apply` | 5–15 min | è il punto di ripristino di tutto il blocco |
| 0b | **Baseline di produzione, PRIMA del deploy**: `ai_eval --rag --json` e `ai_eval --rag-sgi --json`, salvati FUORI dal repo e dalla cartella di release (es. `D:\backup\ai_baseline_prod_<data>_rag.json`, `..._rag_sgi.json`) | ~10 min | — (solo lettura) |
| 0c | **Verifiche prod**: `PROCEDURE_REFRESH_SGI_SHARE_ROOT` valorizzato nel `config\.env`; l'utente del pool IIS legge la share (`import_sgi_da_share` in dry-run mostra utente e file elencati); in django-q presenti e attivi `pr_sgi_auto_sync`, `sgi_share_check`, `ai_index_sgi_documents` (03:30), `ai_rag_quality_alert`; valore di SiteConfig `pr_sgi_auto_sync_attivo` | 10 min | — |
| 0d | **Permessi MTSI (decisione Brizio)**: se l'utente di servizio vede documenti riservati, impostare `escludi_dal_rag` sui relativi `ProcedureDocument` PRIMA del passo 8 | 5–15 min | togliere il flag e reindicizzare |
| 1 | Merge `main` → `release/prod`, pacchetto da `release/prod`, deploy | ~15 min | ridistribuire il pacchetto precedente |
| 2 | `migrate procedure_refresh` (0008, 0009, 0010) e `migrate glossario_tecnico` (0001, 0002) | < 1 min | `migrate procedure_refresh 0007`, `migrate glossario_tecnico zero` (reversibilità verificata) |
| 3 | `.env`: `OLLAMA_RAG_SGI_CHUNK_TITLE=True`, `OLLAMA_RAG_GLOSSARIO_ENABLED=False`, `SGI_ESTRAZIONE_PERSISTITA_ENABLED=False`, mai `OLLAMA_RAG_GLOSSARIO_INCLUDE_BOZZE`; riavvio sito e qcluster | 2 min | ripristinare il `.env`, riavvio |
| 4 | `import_sgi_da_share --json` (dry-run: controllare utente, file elencati, eventuale avviso), poi `--apply` | 5–10 min | i documenti restano storicizzati; disattivazione manuale |
| 5 | `sgi_estrai_testi --dry-run`, poi `sgi_estrai_testi` (**obbligatorio**, sola lettura sulla share; popola anche i riferimenti A2) | ~7 min | innocuo con la lettura spenta; `migrate procedure_refresh 0007` elimina la tabella |
| 6 | `sgi_riferimenti` (allinea tutti i riferimenti + report) | 1–2 min | `migrate procedure_refresh 0008` o lasciare i dati |
| 7 | `sgi_collega_processi --dry-run` (`--apply` solo dopo revisione) | < 1 min | dopo un `--apply`: cancellare in admin i collegamenti non confermati |
| 8 | `index_sgi_documents` (ricalcola gli embeddings: il titolo cambia il testo dei chunk) | 10–30 min (da misurare) | `CHUNK_TITLE=False` + reindicizzare |
| 9 | `glossario_varianti_comuni` (usa il testo del passo 5; PDF solo per i documenti senza testo) | < 1 min | nessuno (solo cache) |
| 10 | `riorganizza_topbar --apply` | < 1 min | nascondere la voce «Glossario» in Admin › Navigazione |
| 11 | Admin › ACL: `glossario_tecnico.gestione` all'Ufficio tecnico | 2 min | revocare il permesso |
| 12 | `ai_eval --rag --json` e `ai_eval --rag-sgi --json` confrontati **caso per caso con la baseline 0b** (non con quella dev): KB nessun caso peggiorato; SGI atteso migliore (titolo nei chunk). Il golden SGI ora ha un caso in più (FAI, il 33°): confrontare i 32 comuni | ~10 min | se peggiora: rollback del passo 3 + reindicizzazione |
| — | **Dopo il deploy, a carico Qualità**: validazione del glossario (prima i ~20 termini prioritari), revisione del CSV delle clausole, rinomina dei file con nome non standard, decisione sui 10 documenti senza traccia | — | — |

Il glossario nell'assistente si accende dopo, come passo separato: `OLLAMA_RAG_GLOSSARIO_ENABLED=True`, riavvio, `ai_eval` contro la baseline del passo 12.
