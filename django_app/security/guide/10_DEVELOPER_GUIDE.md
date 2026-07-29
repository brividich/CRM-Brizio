# Guida sviluppo

Note per chi estende il Security Center: aggiungere un parser, una regola o un modulo, e mantenere i test verdi.

## Purezza dei parser

Un parser deve essere una **funzione pura**: prende in input il contenuto di un report e restituisce metriche e finding strutturati, **senza effetti collaterali** (niente scritture su DB, niente invio di notifiche, niente chiamate esterne). La persistenza e le decisioni (alert, ticket) spettano al motore a valle. Questo rende i parser testabili in isolamento e ri-eseguibili senza rischi.

## Struttura dell'output

Un parser produce:

- **Metriche**: coppie nome/valore (con unità ed etichette opzionali) su cui le regole ragionano.
- **Finding**: elementi qualitativi (es. una CVE) con i loro attributi.

Nomi delle metriche coerenti sono fondamentali: le regole alert fanno match sul **nome metrica**. Un nome che cambia rompe silenziosamente le regole.

## Aggiungere una regola o un seed

- Le regole si configurano da UI (Regole alert) oppure via seed.
- I default del seed vivono in **un solo posto**: `security/services/autoconfig.py` (costanti `GENERAL_SETTINGS`, `SOURCES`, `ALERT_RULES`, …). Il comando `seed_security_center_config` e la pagina `/soc/admin/autoconfig/` sono due facce dello stesso servizio: aggiungere un default lì li aggiorna entrambi.
- Il seed è **idempotente**: scrivilo in modo che rilanciarlo non crei duplicati.
- Una correzione automatica si aggiunge nella lista `FIXES` dello stesso modulo, agganciata al `check_code` della diagnostica che deve chiudere. Regola: nessun fix cancella dati.

## Dove aggiungere i test

I test del modulo vivono in `django_app/security/tests/`. Convenzioni utili in questo progetto:

- Importa i moduli app come `from security... import ...` (il package top-level è `security`, non `django_app.security`).
- Esegui gli scoped test: `python manage.py test security.tests.<modulo> --settings=config.settings.test --keepdb`.
- Per i test di view usa un superuser con `force_login` e `@override_settings(LEGACY_AUTH_ENABLED=False)`, altrimenti l'ACL middleware nega l'accesso.

## Visibilità in dashboard

La visibilità in navigazione **non** è un confine di sicurezza: l'autorizzazione autorevole è sempre lato server (ACL/middleware). Non basare controlli di sicurezza sul fatto che una voce di menu sia nascosta.

## Vincolo di pacchettizzazione (importante)

La documentazione della guida vive in **`django_app/security/guide/`**, non in `docs/`. Il packager di produzione (`package-release.ps1`) esclude via robocopy qualunque cartella chiamata `doc` o `docs` a qualsiasi livello, e la cartella `docs/` di root non è nell'allowlist. Una cartella chiamata `docs` **non arriverebbe in produzione**: la guida sarebbe visibile in sviluppo e assente sul server. Per questo il nome è `guide` (non escluso) e i file `.md` (non esclusi). Il loader risolve il percorso da `Path(__file__).resolve().parent / "guide"`, identico in dev e in prod.

## Comandi utili

```
python manage.py run_security_parsers
python manage.py evaluate_security_rules
python manage.py security_center_diagnostics
python manage.py security_db_check
python manage.py security_uat_smoke_check
```
