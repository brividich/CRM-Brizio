# SEC-PREPROD-01 — Evidence Report

**Progetto:** NOVICROM HUB (Portale Novicrom / CRM-Brizio)
**Ambito:** Patch security pre-produzione — header HTTP, guard CSRF, SQL logging, `json_script`
**Branch:** `pre-prod-security`
**Baseline commit:** `f8005f8` — *Harden asset assignment and release guard*
**Data:** 2026-05-16
**Autore intervento:** Application Security Engineer (sessione assistita)
**Classificazione documento:** Interno — Evidence di remediation, propedeutico ad audit PDF
**Patch correlate:** [SEC-PREPROD-02](SEC-PREPROD-02_EVIDENCE.md) (object-level authorization),
[SEC-PREPROD-03](SEC-PREPROD-03_EVIDENCE.md) (stabilizzazione 5 test `admin_portale`)

---

## Indice

1. [Riepilogo modifiche](#1-riepilogo-modifiche)
2. [File modificati](#2-file-modificati)
3. [Test eseguiti — esito](#3-test-eseguiti--esito)
4. [Test non eseguiti](#4-test-non-eseguiti)
5. [Rischi residui](#5-rischi-residui)
6. [Prossima patch consigliata](#6-prossima-patch-consigliata)

---

## 1. Riepilogo modifiche

Patch security pre-produzione conservativa che chiude **4 finding di audit** a basso rischio
regressione. Nessun refactor, nessuna nuova dipendenza, nessun cambio UX o di logica
business.

**A) Header security** — In `prod.py` aggiunti `SECURE_CONTENT_TYPE_NOSNIFF = True` e
`SECURE_REFERRER_POLICY = "same-origin"`.

**B) Guard CSRF** — In `prod.py` aggiunto blocco `ImproperlyConfigured` (stesso pattern di
`SECRET_KEY`) che impedisce l'avvio se `CSRF_TRUSTED_ORIGINS` è vuoto o contiene ancora
`app.example.local` / `example.local`.

**C) SQL logging** — In `validate_deployment.py` (`check_security()`) aggiunto check
`SQL_LOG_ENABLED`: **FAIL** in ambiente prod, **WARN** fuori prod (non rompe dev/test).

**D) json_script** — Sostituito `{{ var|safe }}` con `{{ var|json_script:"id" }}` in 3
template; il JS legge il JSON da `getElementById(...).textContent` con fallback `[]` / `{}`.
Nomi delle variabili JS (`ASSETS`, `overrides`, `RISPOSTE_INIT`) invariati. Per
`overrides_map` aggiunta una riga al context di `utente_edit` (l'oggetto Python già esisteva
nella view).

---

## 2. File modificati

10 file modificati.

| File | Modifica |
|---|---|
| `django_app/config/settings/prod.py` | header security + guard CSRF |
| `django_app/core/management/commands/validate_deployment.py` | check `SQL_LOG_ENABLED` |
| `django_app/admin_portale/views.py` | `+ "overrides_map"` nel context |
| `django_app/admin_portale/templates/.../utente_edit.html` | 2× `json_script` |
| `django_app/tickets/templates/tickets/pages/nuovo.html` | `json_script` per `ASSETS` |
| `django_app/tickets/templates/tickets/pages/gestione_detail.html` | `json_script` per `ASSETS` |
| `django_app/core/tests.py` | +3 test `ValidateDeploymentSecurityChecksTests` |
| `django_app/tickets/tests.py` | +1 test `TicketNuovoAssetsJsonScriptTests` |
| `django_app/admin_portale/tests.py` | +1 test smoke render `utente_edit` |
| `CHANGELOG.md` | voce `### Security` sotto `[Unreleased]` |

> **Nota operativa:** 6 file target avevano l'attributo Windows read-only (`R`); rimosso
> temporaneamente, patchato, flag ripristinato. Verifica finale: tutti e 6 di nuovo `A  R`.

---

## 3. Test eseguiti — esito

| Comando | Esito |
|---|---|
| `manage.py check --settings=config.settings.test` | ✅ 0 issues |
| `manage.py makemigrations --check --dry-run` | ✅ No changes detected |
| `core.tests + tickets.tests + admin_portale.tests` (234 test) | ⚠️ 229 OK, 5 FAIL preesistenti |
| 5 nuovi test mirati (`json_script` + `SQL_LOG` check + smoke `utente_edit`) | ✅ tutti OK |

**Verifica regressioni:** i 5 fail (`AdminPortaleAuditLogTests`,
`AdminPortaleUserAnagraficaSyncTests.test_toggle_active...`,
`AdminPortaleAclDiagnosticViewTests`) sono stati confermati **preesistenti**: revertando
l'unica modifica di logica di questa patch (`overrides_map` nel context) i fail persistono
identici. Non sono causati dalla patch. Riguardano audit log bulk activate/deactivate, sync
anagrafica e reason ACL `OVERRIDE` — aree non toccate.

> **Aggiornamento:** i 5 FAIL preesistenti sono stati analizzati e chiusi con la patch
> dedicata [SEC-PREPROD-03](SEC-PREPROD-03_EVIDENCE.md) — erano artefatti dell'ambiente di
> test (cache `lru_cache` non invalidata + test drift sui nomi badge), nessun bug
> applicativo.

---

## 4. Test non eseguiti

- Suite completa `manage.py test` (tutti i moduli) — eseguite solo le 3 suite richieste per
  tempi. Consigliato un run completo in CI prima del go-live.
- Test funzionale end-to-end del rendering JS in browser reale (la patch `json_script` è
  coperta da test di contenuto HTML, non da test di esecuzione JS).

---

## 5. Rischi residui

- **5 test preesistenti rotti in `admin_portale`** — non introdotti da questa patch.
  *(Chiusi successivamente da SEC-PREPROD-03.)*
- **SEC-AUDIT-002 e SEC-AUDIT-004 non chiusi** — IDOR download allegati e API write tickets
  restano aperti. *(Affrontati successivamente da SEC-PREPROD-02.)*
- **`json_script`** — se altri template/JS leggessero `assets_list` / `overrides_map_json`
  con il vecchio pattern non sono stati modificati: verificato che `module_vis_json` è
  inutilizzato e che `overrides_map_json` resta usato solo dal check template `!= '{}'`
  (lasciato intatto).
- **Guard CSRF** — il guard in `prod.py` farà fallire l'avvio di un deploy che non ha
  valorizzato `DJANGO_CSRF_TRUSTED_ORIGINS`: comportamento voluto (fail-fast), ma va
  comunicato a chi gestisce il deploy.

---

## 6. Prossima patch consigliata

**SEC-PREPROD-02 — Object-level authorization** (i due Medium rimasti):

- **SEC-AUDIT-004:** aggiungere il check `_ticket_access_flags` nelle 4 API tickets
  (`_api_intervento_update` / `_delete`, `_api_componente_delete`, `api_crea_workorder`).
- **SEC-AUDIT-002:** decidere con il committente la granularità voluta sui download allegati
  (`diario_preposto`, `assets`) e, se per-oggetto, aggiungere il controllo di visibilità.

Inoltre, prima del go-live, separatamente: investigare i 5 test `admin_portale` preesistenti
rotti — non sono security ma vanno chiariti. *(Indirizzato da SEC-PREPROD-03.)*

> Per questa patch — scope limitato, 10 file, modifiche localizzate — non è stato necessario
> un team di agenti: gestita inline.

---

*Fine documento — SEC-PREPROD-01 Evidence Report. Pronto per conversione in PDF di audit.*
