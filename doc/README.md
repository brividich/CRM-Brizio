# Documentazione Tecnica - NOVICROM HUB

> Versione documentazione: **1.1.0**
> Aggiornata: **2026-05-27**

La cartella `doc/` raccoglie la documentazione Markdown canonica del repository. I nomi storici come `Portale Novicrom` restano presenti solo come esempio di istanza, cartella o percorso di deploy.

## Parti da qui

- [`START_HERE.md`](START_HERE.md) - landing page per persona: sviluppatore, admin funzionale, deployer, tester/UAT

## Fonti canoniche

Questi file costituiscono il set di riferimento che deve restare coerente con `VERSION`:

- [`../README.md`](../README.md) - overview repo, quick start e documentazione collegata
- [`../CLAUDE.md`](../CLAUDE.md) - contesto tecnico, pattern e regole operative
- [`../CHANGELOG.md`](../CHANGELOG.md) - storico modifiche della versione corrente
- [`START_HERE.md`](START_HERE.md) - punto di ingresso per persona
- [`TESTING.md`](TESTING.md) - test, smoke e UAT allineati al repo reale
- [`ARCHITETTURA_TARGET_E_DISMISSIONE_LEGACY.md`](ARCHITETTURA_TARGET_E_DISMISSIONE_LEGACY.md) - target ACL e piano di uscita dal legacy
- [`STRUTTURA_ATTUALE_PORTALE.md`](STRUTTURA_ATTUALE_PORTALE.md) - snapshot architetturale corrente
- [`../deployment/README_DEPLOY_IIS_WINDOWS.md`](../deployment/README_DEPLOY_IIS_WINDOWS.md) - deploy reale su Windows Server + IIS
- [`../tools/MANUALE_ADMIN_NAVIGAZIONE_PERMESSI.md`](../tools/MANUALE_ADMIN_NAVIGAZIONE_PERMESSI.md) - manuale admin funzionale

## Documenti di riferimento in `doc/`

- [`STRUTTURA_ATTUALE_PORTALE.md`](STRUTTURA_ATTUALE_PORTALE.md) - app attive, routing, layer dati, sicurezza e integrazioni
- [`TESTING.md`](TESTING.md) - test locali, smoke ACL, seed UAT e raccolta evidenze
- [`ARCHITETTURA_TARGET_E_DISMISSIONE_LEGACY.md`](ARCHITETTURA_TARGET_E_DISMISSIONE_LEGACY.md) - convivenza canonico/legacy e criteri di promozione
- [`ACL_V2_PERMISSION_GUIDE.md`](ACL_V2_PERMISSION_GUIDE.md) - guida tecnica e operativa ACL v2
- [`ACL_V2_ADMIN_QUICK_GUIDE.md`](ACL_V2_ADMIN_QUICK_GUIDE.md) - guida rapida per admin ACL
- [`ACL_V2_UAT_CHECKLIST.md`](ACL_V2_UAT_CHECKLIST.md) - checklist di collaudo UAT

## Artefatti derivati

- I file `.html` e `.pdf` presenti in `doc/`, `tools/` e `deployment/` sono artefatti consultabili ma non sono la fonte primaria di governance.
- Se un artefatto derivato diverge dal Markdown canonico, fa fede il Markdown.
- I file di configurazione reali non sono inclusi nel repository; valori e host presenti nei documenti sono esempi o placeholder.
