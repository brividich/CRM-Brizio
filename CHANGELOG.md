# Changelog - NOVICROM HUB

Tutte le modifiche rilevanti al progetto sono documentate qui.
Formato: [Keep a Changelog](https://keepachangelog.com/it/1.0.0/)

Storico archiviato: [dalla 1.4.0 alla 1.6.2 (pre go-live)](docs/changelog/CHANGELOG_1.4.0-1.6.2_pre_golive.md) · [fino alla 1.4.0](docs/changelog/CHANGELOG_fino_1.4.0.md).

---

## [Unreleased]

- **Core — pulizia pre go-live dei log operativi** (`django_app/core/management/commands/pulizia_pre_golive.py` nuovo, test `django_app/core/test_pulizia_pre_golive.py` nuovo, `docs/moduli/core.md`, `docs/RUNBOOK_COMANDI.md`): comando una tantum che svuota i log accumulati in sviluppo e collaudo (run/action log e coda eventi processati delle automazioni, notifiche in-app, log email e notifiche già inviate delle anomalie, conversazioni dell'assistente AI e del Security Center, esecuzioni di lettura casella SOC, esiti task django-q, sessioni scadute). Dry-run di default, `--esegui` cancella a batch e lascia una riga `AuditLog` con i conteggi, `--solo` limita le voci. Audit trail, registri di sicurezza, deduplica approvazioni e dati di dominio non vengono toccati. Nessuna migrazione.

- **Repo — changelog e note ripartiti da zero per il go-live**:
  - `CHANGELOG.md` archiviato in `docs/changelog/CHANGELOG_1.4.0-1.6.2_pre_golive.md` (testo invariato).
  - `django_app/CHANGELOG.md` (note di release mostrate in Admin → Versioning e nel piè di pagina delle dashboard, ferme alla 0.9.18 del 2026-04-16) archiviato in `docs/changelog/CHANGELOG_django_app_fino_0.9.18.md` e riscritto con la sola release 1.6.2.
  - `_AGENT_CONTROL/AGENT_CHANGELOG.md` e `session_checkpoint.md` tolti dal repository e messi in `.gitignore`, come chiesto dall'audit di sicurezza del 2026-10-09 (contenevano diagnosi di produzione e percorsi del `.env`): restano file di lavoro locali della cartella condivisa. Aggiornati `AGENTS.md` e `README.md`.
  - Rimosso `requirements_txt.txt` (alias inutilizzato di `django_app/requirements.txt`).
  - `CLAUDE.md` non entra più nel pacchetto di release (`deployment/scripts/package-release.ps1`).

## 1.6.2 - 2026-10-10

Release di avvio della produzione. Dettaglio completo di questa versione e delle precedenti dalla 1.4.0, comprese le modifiche non ancora numerate fino al 2026-10-12: [docs/changelog/CHANGELOG_1.4.0-1.6.2_pre_golive.md](docs/changelog/CHANGELOG_1.4.0-1.6.2_pre_golive.md).
