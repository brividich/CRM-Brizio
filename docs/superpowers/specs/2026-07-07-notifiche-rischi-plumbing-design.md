# Notifiche — chiusura dei 4 rischi 🔴 (plumbing)

**Data:** 2026-07-07
**Ambito:** `core` (notifiche in-app + email helper) + settings + `validate_deployment`
**Stato:** approvato (brainstorming) — scope MINIMO deciso dall'utente («solo i 4 rischi»), NIENTE dispatcher

## Contesto

Audit del sistema notifiche (in-app `core.notifiche` + email `core.email_utils.send_hub_mail`)
ha rilevato 10 punti deboli. L'utente ha scelto di chiudere **solo i 4 rischi concreti**
in questa sessione (fix mirati, basso rischio, nessun ridisegno/dispatcher). L'arricchimento
dei template mail va a **un'altra sessione** (brief separato).

Scoperta chiave: il template di `send_hub_mail` (`core/templates/core/email/base_email.html`)
è **già** identico allo stile «anomalie». Il gap dei template è di *contenuto*, non di *look* —
fuori scope qui.

## I 4 fix

### Fix 1 — `DEFAULT_FROM_EMAIL` mai vuoto (+ guard al deploy)
- **Problema:** `config/settings/base.py:135` → `DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "")`.
  Vuoto ⇒ Django ripiega su `webmaster@localhost` (email che non parte). `validate_deployment.check_email`
  NON lo segnala (il controllo placeholder scatta solo su valore non vuoto).
- **Fix:** in `base.py` → `DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "") or EMAIL_HOST_USER`
  (ripiega sulla mailbox SMTP, che è un indirizzo reale). In `validate_deployment.check_email`:
  se backend SMTP e **sia** `DEFAULT_FROM_EMAIL` **sia** `EMAIL_HOST_USER` vuoti → `FAIL` in prod,
  `WARN` fuori prod (via `_severity_for_env`).

### Fix 2 — Dev con console backend
- **Problema:** `config/settings/dev.py` eredita il backend SMTP di base → dallo sviluppo si
  tentano invii reali / errori nascosti.
- **Fix:** in `dev.py` → `EMAIL_BACKEND = env("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")`
  (import esplicito di `env`). Le email di dev si stampano a console; override sempre possibile da `.env`.
  Prod invariato.

### Fix 3 — Niente invii al login legacy
- **Problema:** `core/legacy_anagrafica.py:80-84` `resolve_notification_email` ripiega su `email`
  (che in `anagrafica_dipendenti` è il **login** legacy, non un indirizzo) quando `email_notifica` è vuoto.
- **Fix:** ripiega su `email` **solo se contiene `@`** (euristica «sembra un indirizzo»), altrimenti `""`
  (nessun invio). Nessun impatto quando `email_notifica` è valorizzato.

### Fix 4 — Notifiche non consegnate → visibili nei log
- **Problema:** `core/notifiche.py` `invia_notifica` fa `return` silenzioso se `legacy_user_id` è vuoto;
  `invia_notifica_email` ignora in silenzio le email che non risolvono nessun utente.
- **Fix:** `logger.warning` in entrambi i casi (tipo + destinatario). **Comportamento invariato**,
  solo osservabilità (i «buchi» finiscono nei log/monitoring invece di svanire).

## Non-obiettivi (esplicitamente fuori scope)
- Dispatcher unico `notify()`, registro `tipo`, unificazione delle 3 cascate destinatario,
  log di consegna / retry email. (Valutabili in futuro.)
- Arricchimento template mail GS/anagrafica/monitoring → **altra sessione** (brief dedicato).

## Test (TDD)
- `resolve_notification_email`: scarta un `email` senza `@`, tiene un `email` con `@`, preferisce `email_notifica`.
- `invia_notifica` / `invia_notifica_email`: emettono `WARNING` quando non consegnano (assertLogs).
- `validate_deployment.check_email`: con backend SMTP e from-email+host-user vuoti → FAIL/WARN per ambiente.
- (Fix 2 e la parte settings del Fix 1 sono config a caricamento-processo: verifica per ispezione, non unit test.)

## File toccati
`config/settings/base.py`, `config/settings/dev.py`, `core/legacy_anagrafica.py`, `core/notifiche.py`,
`core/management/commands/validate_deployment.py`, + i relativi test. Nessuna migration.
