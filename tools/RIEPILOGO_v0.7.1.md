# Riepilogo aggiornamento — BrizioHUB v0.7.1

**Data:** 2026-03-14
**Versione precedente:** 0.7.0
**Versione corrente:** 0.7.1

---

## Cosa è cambiato in questa release

### 1. Setup Wizard — da 9 a 12 step

Il wizard di prima configurazione (`/setup/`) è stato esteso con 3 nuovi step e il passo finale è stato completamente riscritto.

#### Nuovi step

| Step | Titolo | Contenuto |
|------|--------|-----------|
| 9 | **Moduli** | Selezione moduli opzionali con toggle (assenze, anomalie, assets, tasks, tickets, notizie, anagrafica, automazioni, timbri, planimetria). I moduli core sono sempre attivi e non modificabili. |
| 10 | **Utente Admin** | Creazione primo superuser Django: username, password (con strength meter), email, nome, cognome. Validazione client-side prima di procedere. |
| 11 | **Info Operative** | Nome azienda, indirizzo, telefono, email, fuso orario, lingua, formato data. |
| 12 | **Installa & Avvia** | (sostituisce il vecchio Step 9 "Riepilogo & Salva") Esegue l'installazione guidata in 4 fasi con progress indicator visuale in tempo reale. |

#### Flusso di installazione Step 12

```
[1] Salva configurazione  →  POST /setup/api/save/
        ↓ OK
[2] Esegui migrazioni     →  POST /setup/api/run-migrations/
        ↓ OK              (subprocess manage.py migrate, timeout 180s)
[3] Crea utente admin     →  POST /setup/api/create-admin/
        ↓ OK              (skip silenzioso se utente esiste già)
[4] Attiva moduli         →  POST /setup/api/set-modules/
        ↓ OK              (scrive SiteConfig module_visible_*)
    → Redirect /login/    (dopo 4 secondi)
```

Se una fase fallisce, il processo si interrompe mostrando l'errore con il pulsante "Riprova".

#### Nuovi endpoint API wizard

| Endpoint | Funzione |
|----------|----------|
| `POST /setup/api/run-migrations/` | Esegue `manage.py migrate` come sottoprocesso. Rileva automaticamente `config.settings.dev` o `prod` in base all'`ENGINE` nel `.env` appena scritto. |
| `POST /setup/api/create-admin/` | Crea un superuser Django. Se l'utente esiste già restituisce warning non bloccante (non errore). |
| `POST /setup/api/set-modules/` | Scrive `SiteConfig.module_visible_<key>=1/0` per ogni modulo opzionale. |

---

### 2. Hub Tools — nuova app di gestione

**App:** `hub_tools` — `django_app/hub_tools/`
**URL base:** `/admin-portale/hub/`
**Accesso:** solo utenti `is_staff=True`

#### Module Manager — `/admin-portale/hub/moduli/`

Permette di attivare/disattivare i moduli visibili nell'interfaccia **senza riavviare il server**.

- Toggle switch per ogni modulo opzionale → richiesta AJAX → aggiorna `SiteConfig`
- Effetto immediato sulla navigazione
- I moduli core sono visualizzati ma non modificabili
- Toast di conferma/errore in basso a destra

**Moduli gestibili:**

| Modulo | Default |
|--------|---------|
| assenze | ✓ attivo |
| anomalie | ✓ attivo |
| assets | ✓ attivo |
| tasks | ✓ attivo |
| tickets | ✓ attivo |
| notizie | ✓ attivo |
| anagrafica | ✓ attivo |
| automazioni | ✓ attivo |
| timbri | ✗ disattivato |
| planimetria | ✗ disattivato |

#### Database Manager — `/admin-portale/hub/database/`

Pannello con 5 operazioni, compatibile con **SQLite** e **SQL Server**.

| Operazione | SQLite | SQL Server |
|------------|--------|------------|
| **Statistiche** | `sqlite_master` + `COUNT(*)` per tabella | `sys.tables + sys.partitions + sys.allocation_units` |
| **Backup** | Copia `db.sqlite3` → `backup/db/db_backup_YYYYMMDD_HHMMSS.sqlite3` | `BACKUP DATABASE [name] TO DISK = 'path.bak' WITH FORMAT, INIT` |
| **Pulizia** | Sessioni scadute, log automazioni >90gg, event queue processati, notifiche lette >30gg | Idem |
| **Ottimizzazione** | `VACUUM` + `ANALYZE` | `UPDATE STATISTICS` su tutte le tabelle + `ALTER INDEX REBUILD` per indici frammentati >30% |
| **Ripristino** | Copia da lista backup; salva corrente come `.pre_restore` | `RESTORE DATABASE FROM DISK WITH REPLACE, RECOVERY` |

I backup SQLite vengono salvati in `backup/db/` (nella root del progetto).
I backup SQL Server vengono eseguiti sul server SQL — specificare il percorso di destinazione nel form.

---

## File modificati/creati

### Modificati

| File | Modifica |
|------|----------|
| `django_app/setup_wizard/templates/setup_wizard/wizard.html` | Aggiunti step 9–12, nuovo flow JS `runInstall`, `buildPayload`, `renderModuleStep`, strength meter password, `validateAdmin`. TOTAL da 9 → 12. |
| `django_app/setup_wizard/views.py` | Aggiunte 3 nuove view: `api_run_migrations`, `api_create_admin`, `api_set_modules`. |
| `django_app/setup_wizard/urls.py` | Aggiunte 3 nuove route API. |
| `django_app/config/settings/base.py` | Aggiunta `hub_tools.apps.HubToolsConfig` in `INSTALLED_APPS`. Aggiunto `/admin-portale/hub/` in `MIDDLEWARE_EXEMPT_PREFIXES`. `APP_VERSION` → `0.7.1`. |
| `django_app/config/urls.py` | Aggiunto path `admin-portale/hub/` con namespace `hub_tools`. |
| `django_app/CHANGELOG.md` | Aggiunta voce v0.7.1. |
| `django_app/VERSION` | `0.7.0` → `0.7.1`. |

### Creati

| File | Contenuto |
|------|-----------|
| `django_app/hub_tools/__init__.py` | (vuoto) |
| `django_app/hub_tools/apps.py` | `HubToolsConfig` |
| `django_app/hub_tools/urls.py` | Route moduli e database |
| `django_app/hub_tools/views.py` | Tutte le view + logica backup/ottimizzazione/pulizia |
| `django_app/hub_tools/templates/hub_tools/moduli.html` | UI module manager con toggle switch |
| `django_app/hub_tools/templates/hub_tools/database.html` | UI database manager con 5 panel operativi |
| `tools/RIEPILOGO_v0.7.1.md` | Questo file |

---

## Prossimi passi consigliati

1. **Aggiungere link Hub Tools nella navigazione admin_portale** — inserire voci "Moduli" e "Database" nel menu laterale dell'area admin per renderle facilmente raggiungibili.
2. **`module_visible_*` nella navigazione** — agganciare la lettura di `SiteConfig.module_visible_<key>` nella pipeline di navigazione (`NavigationRegistry`) affinché i moduli disattivati spariscano anche dalla nav laterale.
3. **`__init__.py` hub_tools** — verificare che il file esista (necessario per il discovery delle app Django).
4. **Backup directory** — creare `backup/db/` o aggiungere al `.gitignore`; la directory viene creata automaticamente al primo backup.
5. **Test wizard step 9–12** — testare il flusso completo su ambiente dev con SQLite prima di portarlo in produzione SQL Server.
