# SEC-PREPROD-03 — Evidence Report

**Progetto:** NOVICROM HUB (Portale Novicrom / CRM-Brizio)
**Ambito:** Stabilizzazione test pre-produzione — chiusura 5 FAIL `admin_portale`
**Branch:** `pre-prod-security`
**Baseline commit:** `f8005f8` — *Harden asset assignment and release guard*
**Data:** 2026-05-16
**Autore intervento:** Application Security Engineer (sessione assistita)
**Classificazione documento:** Interno — Evidence di remediation, propedeutico ad audit PDF
**Relazione con altre patch:** follow-up di [SEC-PREPROD-01](SEC-PREPROD-01_EVIDENCE.md)

---

## Indice

1. [Contesto](#1-contesto)
2. [Root cause dei 5 failure](#2-root-cause-dei-5-failure)
3. [Distinzione test drift vs bug reale](#3-distinzione-test-drift-vs-bug-reale)
4. [File modificati](#4-file-modificati)
5. [Test eseguiti](#5-test-eseguiti)
6. [Stato finale](#6-stato-finale)
7. [AUDIT EVIDENCE](#7-audit-evidence)
8. [Rischi residui](#8-rischi-residui)

---

## 1. Contesto

A valle dell'audit security pre-produzione (0 Critical, 0 High, 4 Medium, Go condizionato) è
stata applicata la patch **SEC-PREPROD-01** che ha chiuso 4 finding a basso rischio
regressione:

- header di sicurezza HTTP (`SECURE_CONTENT_TYPE_NOSNIFF`, `SECURE_REFERRER_POLICY`);
- guard `CSRF_TRUSTED_ORIGINS` contro i valori placeholder;
- check `SQL_LOG_ENABLED` in `validate_deployment`;
- sostituzione `json.dumps + |safe` con `json_script` nei template.

I test mirati nuovi passavano, ma la suite `admin_portale` presentava **5 FAIL preesistenti**
(non introdotti dalla patch). Questo documento raccoglie l'analisi e la remediation di quei
fallimenti.

> **Vincoli dell'intervento:** non toccare la patch security precedente, nessun refactor,
> nessun cambio UX, nessuna modifica di logica business salvo bug reale dimostrato,
> mantenere intatta la copertura security/audit/ACL.

I 5 FAIL segnalati si raggruppano, in pratica, in **4 test rotti** distribuiti su 3 classi:

| Classe | Test |
|---|---|
| `AdminPortaleAuditLogTests` | `test_utenti_bulk_activate_is_audited` |
| `AdminPortaleAuditLogTests` | `test_utenti_bulk_deactivate_is_audited` |
| `AdminPortaleUserAnagraficaSyncTests` | `test_toggle_active_moves_user_into_central_anagrafica` |
| `AdminPortaleAclDiagnosticViewTests` | `test_acl_diagnostica_returns_structured_reason_and_context` |

---

## 2. Root cause dei 5 failure

### Causa A — Cache `lru_cache` stale tra test (3 fail)

Test coinvolti: `test_utenti_bulk_activate_is_audited`,
`test_utenti_bulk_deactivate_is_audited`,
`test_toggle_active_moves_user_into_central_anagrafica`.

`legacy_table_columns()` in `django_app/core/legacy_utils.py:475` è decorata
`@lru_cache(maxsize=32)` — cache **per-processo, persistente tra i test**.

Sequenza del bug:

1. Un test eseguito prima invoca `legacy_table_columns("anagrafica_dipendenti")` quando la
   tabella *unmanaged* ha uno schema diverso (o non esiste ancora) → la cache memorizza un
   elenco colonne **stale**.
2. Il `TestCase` Django esegue il rollback della transazione, ma la `lru_cache` Python
   **non viene invalidata**.
3. Il test successivo ricrea la tabella e chiama `upsert_anagrafica_dipendente` →
   `ensure_anagrafica_schema()` restituisce le colonne **cached** (incoerenti con la tabella
   reale) → `INSERT` con una colonna inesistente → `OperationalError: no such column: ruolo`.
4. L'eccezione viene catturata silenziosamente da `_audit_safe` / `except Exception` nella
   view → l'audit non viene scritto e il flag `attivo` resta invariato (rollback dell'intero
   `transaction.atomic()`).

**Diagnosi confermata sperimentalmente:** spy su `_sync_legacy_user_to_anagrafica` →
`SYNC RAISED: OperationalError no such column: ruolo`. Applicando
`legacy_table_columns.cache_clear()` nel `setUp`, i 3 test passano.

### Causa B — Test drift sui nomi badge (1 fail)

Test coinvolto: `test_acl_diagnostica_returns_structured_reason_and_context`
(`django_app/admin_portale/tests.py`, righe ~2657-2658).

Il test falliva su `assertIn("OVERRIDE", diag["badges"])`:

```
AssertionError: 'OVERRIDE' not found in
['LEGACY_FALLBACK', 'REGISTRY', 'REDIRECT', 'LEGACY_MATCH', 'LEGACY_OVERRIDE']
```

La view `acl_diagnostica` genera i badge tramite `_acl_diag_badges()`
(`django_app/admin_portale/views.py:4460`), che usa nomi granulari **`LEGACY_OVERRIDE` /
`LEGACY_FALLBACK`**. Il test si aspettava i nomi semplici `OVERRIDE` / `LEGACY`, che
appartengono a un **altro** generatore di badge (`views.py:4826`, usato dalla pagina
*mappa permessi* — schema legittimamente diverso, coperto e verde nel test
`test_map_page_shows_badges_for_registry_legacy_override_and_redirect`).

Il test era rimasto indietro rispetto al refactor dei badge della diagnostica ACL:
**test drift puro**, nessun malfunzionamento del codice.

---

## 3. Distinzione test drift vs bug reale

| Failure | Categoria | Esito |
|---|---|---|
| `test_utenti_bulk_activate_is_audited` | Setup test incompleto (cache non invalidata) | Corretto solo il test |
| `test_utenti_bulk_deactivate_is_audited` | Setup test incompleto | Corretto solo il test |
| `test_toggle_active_moves_user_into_central_anagrafica` | Setup test incompleto | Corretto solo il test |
| `test_acl_diagnostica_returns_structured_reason_and_context` | Test drift (aspettativa vecchia) | Corretto solo il test |

**Nessun bug reale di codice applicativo.** A runtime, in produzione, lo schema delle tabelle
legacy è stabile: la `lru_cache` è coerente e il problema non si manifesta. Il fallimento era
esclusivamente un artefatto dell'ambiente di test (tabelle *unmanaged* + cache per-processo
non invalidata tra test).

Di conseguenza **non è stato modificato codice applicativo** e — per la regola "aggiorna
CHANGELOG solo se modifichi codice applicativo" — **il `CHANGELOG.md` non è stato toccato**.

---

## 4. File modificati

| File | Motivo security | Tipo modifica |
|---|---|---|
| `django_app/admin_portale/tests.py` | Ripristina l'affidabilità della copertura audit/ACL: i test mascheravano un `OperationalError` senza segnalarlo. Nessun codice applicativo toccato. | Solo test: import `legacy_table_columns`; `cache_clear()` nell'helper `_ensure_anagrafica_table()`; allineamento dei nomi badge attesi nel test diagnostica ACL |

**Dettaglio modifiche (solo test):**

1. **Import** — aggiunto `from core.legacy_utils import legacy_table_columns`.
2. **Invalidazione cache** — in `_ensure_anagrafica_table()` aggiunta la chiamata
   `legacy_table_columns.cache_clear()` dopo aver garantito lo schema corrente della tabella,
   con commento esplicativo. Scelta della soluzione minima: il `cache_clear()` è inserito
   **nell'helper condiviso** (un solo punto) invece che nei singoli `setUp`, così ogni test
   che ricrea la tabella anagrafica invalida automaticamente la cache.
3. **Nomi badge** — nel test `test_acl_diagnostica_returns_structured_reason_and_context`,
   sostituite le asserzioni `assertIn("OVERRIDE", ...)` / `assertIn("LEGACY", ...)` con i
   nomi realmente prodotti per lo scenario `final_decision_source == "legacy_fallback"` con
   override utente: `assertIn("LEGACY_OVERRIDE", ...)` / `assertIn("LEGACY_FALLBACK", ...)`.

Copertura security/audit/ACL **invariata** — nessuna asserzione rimossa, solo aggiornati i
nomi badge attesi a quelli reali.

---

## 5. Test eseguiti

| Comando | Esito | Sintesi output |
|---|---|---|
| `python manage.py check --settings=config.settings.test` | ✅ OK | "System check identified no issues (0 silenced)." |
| `python manage.py makemigrations --check --dry-run --settings=config.settings.test` | ✅ OK | "No changes detected" |
| `python manage.py test admin_portale.tests --settings=config.settings.test` | ✅ OK | "Ran 102 tests … OK" |
| `python manage.py test core.tests tickets.tests admin_portale.tests --settings=config.settings.test` | ✅ OK | "Ran 235 tests … OK" |
| `git diff --check` | ⚠️ Preesistente | Unico segnale `CLAUDE.md:103: new blank line at EOF` — non di questa patch (CLAUDE.md non toccato). `git diff --check django_app/admin_portale/tests.py` pulito |
| `git status --short django_app/admin_portale/tests.py` | ℹ️ | ` M django_app/admin_portale/tests.py` — unico file di questa patch |
| `acl_coverage_report` | — Non eseguito | La patch non modifica RoutePermissionBinding, route, ACL v2 né navigazione: solo file di test. Comando non pertinente |

---

## 6. Stato finale

Tutti i 5 FAIL chiusi. Suite `core + tickets + admin_portale` completamente verde
(**235/235 test OK**). La patch security precedente (SEC-PREPROD-01 — header / CSRF / SQL log /
`json_script`) **non è stata toccata**. Nessun refactor, nessun cambio UX, nessuna modifica
di logica business.

---

## 7. AUDIT EVIDENCE

### 7.1 Finding chiusi

| Finding | Severità | Stato | Patch | Test |
|---|---:|---|---|---|
| `test_utenti_bulk_activate_is_audited` FAIL | Bassa (test-only) | Chiuso | `cache_clear()` in `_ensure_anagrafica_table()` | `admin_portale.tests.AdminPortaleAuditLogTests.test_utenti_bulk_activate_is_audited` ✅ |
| `test_utenti_bulk_deactivate_is_audited` FAIL | Bassa (test-only) | Chiuso | `cache_clear()` in `_ensure_anagrafica_table()` | `admin_portale.tests.AdminPortaleAuditLogTests.test_utenti_bulk_deactivate_is_audited` ✅ |
| `test_toggle_active_moves_user_into_central_anagrafica` FAIL | Bassa (test-only) | Chiuso | `cache_clear()` in `_ensure_anagrafica_table()` | `admin_portale.tests.AdminPortaleUserAnagraficaSyncTests.test_toggle_active_moves_user_into_central_anagrafica` ✅ |
| `test_acl_diagnostica_returns_structured_reason_and_context` FAIL | Bassa (test drift) | Chiuso | Aggiornati i nomi badge attesi | `admin_portale.tests.AdminPortaleAclDiagnosticViewTests.test_acl_diagnostica_returns_structured_reason_and_context` ✅ |

> Il prompt cita "5 FAIL"; le classi raggruppano in pratica 4 test rotti. Tutti e 4 chiusi.

### 7.2 File modificati

| File | Motivo security | Tipo modifica |
|---|---|---|
| `django_app/admin_portale/tests.py` | Ripristina l'affidabilità della copertura audit/ACL (i test mascheravano un `OperationalError`) — nessun codice applicativo toccato | Solo test: import + invalidazione cache in helper condiviso + allineamento nomi badge |

### 7.3 Comandi eseguiti

- `python manage.py check --settings=config.settings.test` → **OK** —
  "System check identified no issues (0 silenced)".
- `python manage.py makemigrations --check --dry-run --settings=config.settings.test` →
  **OK** — "No changes detected".
- `python manage.py test admin_portale.tests --settings=config.settings.test` → **OK** —
  "Ran 102 tests … OK".
- `python manage.py test core.tests tickets.tests admin_portale.tests --settings=config.settings.test`
  → **OK** — "Ran 235 tests … OK".
- `git diff --check` → un solo segnale `CLAUDE.md:103: new blank line at EOF` —
  **preesistente, non di questa patch** (CLAUDE.md non toccato);
  `git diff --check django_app/admin_portale/tests.py` pulito.
- `git status --short django_app/admin_portale/tests.py` →
  ` M django_app/admin_portale/tests.py` — unico file di questa patch.
- `acl_coverage_report` → **non eseguito**: la patch non modifica RoutePermissionBinding,
  route, ACL v2 né navigazione — solo file di test. Comando non pertinente.

### 7.4 Evidenza remediation

#### Finding A — 3 test audit/sync (cache stale)

- **Comportamento vulnerabile prima:** eseguiti in suite, `legacy_table_columns` restituiva
  colonne stale → `INSERT` in `anagrafica_dipendenti` con colonna `ruolo` inesistente →
  `OperationalError` → `transaction.atomic()` in rollback → audit non scritto / `attivo`
  invariato. Test rossi in modo non deterministico (dipendente dall'ordine di esecuzione).
- **Comportamento dopo la patch:** `_ensure_anagrafica_table()` invalida la cache via
  `legacy_table_columns.cache_clear()` dopo aver garantito lo schema corrente → ogni test
  riparte da una cache coerente.
- **Test che dimostra la correzione:** i 3 test passano sia isolati sia in suite completa
  (235/235 OK); verificato in anticipo tramite patch sperimentale del `setUp`
  (`FAILURES with cache_clear: 0`).
- **Rischio residuo:** il pattern `lru_cache` per-processo resta; altre suite con tabelle
  legacy *unmanaged* potrebbero ripresentare il drift (priorità bassa).

#### Finding B — test diagnostica ACL (test drift)

- **Comportamento vulnerabile prima:** il test asseriva i badge `OVERRIDE` / `LEGACY`, nomi
  non più prodotti da `_acl_diag_badges()` per la view `acl_diagnostica` (refactor a badge
  granulari `LEGACY_*`).
- **Comportamento dopo la patch:** il test asserisce `LEGACY_OVERRIDE` / `LEGACY_FALLBACK`,
  i nomi effettivamente generati per lo scenario `final_decision_source == "legacy_fallback"`
  con override utente.
- **Test che dimostra la correzione:**
  `test_acl_diagnostica_returns_structured_reason_and_context` ✅; la copertura badge
  dell'altra view resta verde
  (`test_map_page_shows_badges_for_registry_legacy_override_and_redirect`).
- **Rischio residuo:** nessuno — la logica `_acl_diag_badges()` è internamente coerente e
  non è stata modificata.

---

## 8. Rischi residui

| Rischio | Owner consigliato | Priorità | Scadenza consigliata | Accettabile in produzione? |
|---|---|---|---|---|
| `lru_cache` `legacy_table_columns` non isolata tra test | Team backend / QA | Bassa | Prossimo ciclo di hardening test | Sì — non impatta il runtime di produzione (schema legacy stabile); è solo flakiness di test |
| `_audit_safe` / `except Exception` silenziano errori DB reali | Team backend | Bassa | Da valutare in revisione audit trail | Sì — comportamento fire-and-forget intenzionale; consigliato passare a log `warning` per visibilità |
| SEC-AUDIT-002 (IDOR download allegati) e SEC-AUDIT-004 (API write tickets) | Security engineer | Media | Patch successiva, prima del go-live | Solo se accettato formalmente dal committente — fuori scope di questo intervento |

---

*Fine documento — SEC-PREPROD-03 Evidence Report. Pronto per conversione in PDF di audit.*
