# Changelog - NOVICROM HUB

Tutte le modifiche rilevanti al progetto sono documentate qui.
Formato: [Keep a Changelog](https://keepachangelog.com/it/1.0.0/)

Storico archiviato: [dalla 1.4.0 alla 1.6.2 (pre go-live)](docs/changelog/CHANGELOG_1.4.0-1.6.2_pre_golive.md) · [fino alla 1.4.0](docs/changelog/CHANGELOG_fino_1.4.0.md).

---

## [Unreleased]

- **Contatori — import fattura Copylab e riconciliazione per contratto** (`django_app/contatori/fattura_import.py`, `contatori/models.py`, `contatori/migrations/0031_fattura_dettaglio.py` nuovo, `contatori/migrations/0032_acl_riconciliazione_guida.py` nuovo, `contatori/services.py`, `contatori/views.py`, `contatori/urls.py`, `contatori/forms.py`, `contatori/guida.py` nuovo, `contatori/templates/contatori/riconciliazione.html`, `contatori/templates/contatori/guida.html` nuovo, `contatori/templates/contatori/fattura_form.html`, `contatori/templates/contatori/_fattura_riga.html`, `contatori/static/contatori/contatori.css`, test `contatori/tests_fattura_import.py`, `contatori/tests_fatture.py`, `contatori/tests_permessi.py`, `docs/moduli/contatori.md`).
  - La fattura Copylab non veniva letta: il parser riconosceva solo il tracciato BASE («N. Contratto:»). Ora legge anche i blocchi «Matricola:… Contratto:…» con le righe «COPIE EFFETTUATE B/N / COLORE» (lettura di chiusura, apertura, differenza), la testata «TD01 (Fattura) nr. … del …» e, dall'XML, le `AltriDatiGestionali/RiferimentoTesto`. Il contratto della riga si prende dall'anagrafica stampanti tramite matricola; più macchine sullo stesso contratto si sommano (pool). Il periodo del canone non sposta la chiusura delle letture.
  - Nuovo campo fattura «Letture in fattura» (A4/A3 B/N e colore · Solo totali B/N e colore). Con «Solo totali» la riconciliazione confronta «BN totale» e «COL totale» con A4 + A3 interni; il form nasconde le colonne A3.
  - Riconciliazione ridisegnata: schede KPI (contratti, allineati, da controllare, letture mancanti), filtro «Tutti / Da verificare», una scheda per contratto con fattura, MFC del pool, data della lettura interna e giorni dalla chiusura del fornitore, parte di ogni MFC sotto il totale interno. Nuova guida in-app «? Guida» (`/contatori/riconciliazione/guida/`).
  - Deploy: `migrate contatori` (0031 campo, 0032 binding ACL della guida).
  - Barra del modulo senza barra di scorrimento: i gruppi vanno a capo e i tre wizard («+ MFC», «+ Dispositivo SNMP», «+ Profilo SNMP») stanno nel menu «+ Nuovo» (`templates/contatori/_modulo_nav.html`).
  - Centrale compatta in una schermata (`templates/contatori/dashboard.html`): intestazione ridotta, una riga di indicatori (letture, copie, riconciliazione, stato flotta SNMP, consumabili, letture da confermare, fatture da riconciliare) e tre colonne a scorrimento interno (Da fare con i cali di lettura, Parco MFC con il totale e il dettaglio A4/A3 al passaggio del mouse, SNMP con ultimi errori e dispositivi).

- **SOC — Software e CPE: lavoro ridotto a «Da decidere», azioni in blocco, regole «non applicabile»** (`django_app/security/views_vuln.py`, `security/templates/security/vuln_software.html`, `security/services/cpe_rules.py` nuovo, `security/models.py`, `security/migrations/0022_regole_non_applicabile.py` nuova, `security/guide/12_AUTOMATISMI_E_VULNERABILITA.md`, test `security/tests/test_cve_impact.py`, `docs/moduli/security.md`).
  - Il filtro «Da mappare» elencava tutto ciò che non era deciso (centinaia di righe: driver, runtime, language pack). I CPE candidati sono solo quelli delle CVE già nel sistema, quindi un software senza CVE dal nome simile non ha nulla da decidere. Ora i filtri sono **Da decidere** (con proposta), **Senza CVE note** (nessuna azione richiesta; passano da soli in «Da decidere» quando arriva una CVE simile), Collegati in automatico, **Non applicabili**. `?stato=da_mappare` apre «Da decidere».
  - Azioni in blocco: casella «seleziona tutti» della pagina, **N/A selezionati**, **Conferma tutte le proposte a candidato unico** (su tutte le pagine della vista) e **N/A tutti i risultati di «ricerca»** (ricerca ≥ 3 caratteri). Conferma prima di procedere, audit per ogni software.
  - **Regole «non applicabile»** (`SoftwareNaRule`): «il prodotto contiene X» (opzionalmente solo un produttore), applicate subito e dopo ogni import; non toccano decisioni già prese né software con una CVE dal nome simile; un software escluso che più avanti riceve una proposta torna in «Da decidere». Eliminare la regola riapre i software esclusi (`SoftwareCpeMapping.origin="regola"` + `na_rule`).
  - Deploy: `migrate security` (0022).

- **Monitoring — pagina Schedule allineata** (`django_app/monitoring/templates/monitoring/pages/schedules.html`): la tabella veniva presa dal potenziamento automatico delle tabelle, che metteva la barra di ricerca in cima alla pagina fuori dal contenitore; esclusa con `data-fm-table-skip`.

- **Core — pulizia pre go-live dei log operativi** (`django_app/core/management/commands/pulizia_pre_golive.py` nuovo, test `django_app/core/test_pulizia_pre_golive.py` nuovo, `docs/moduli/core.md`, `docs/RUNBOOK_COMANDI.md`): comando una tantum che svuota i log accumulati in sviluppo e collaudo (run/action log e coda eventi processati delle automazioni, notifiche in-app, log email e notifiche già inviate delle anomalie, conversazioni dell'assistente AI e del Security Center, esecuzioni di lettura casella SOC, esiti task django-q, sessioni scadute). Dry-run di default, `--esegui` cancella a batch e lascia una riga `AuditLog` con i conteggi, `--solo` limita le voci. Audit trail, registri di sicurezza, deduplica approvazioni e dati di dominio non vengono toccati. Nessuna migrazione.

- **Repo — changelog e note ripartiti da zero per il go-live**:
  - `CHANGELOG.md` archiviato in `docs/changelog/CHANGELOG_1.4.0-1.6.2_pre_golive.md` (testo invariato).
  - `django_app/CHANGELOG.md` (note di release mostrate in Admin → Versioning e nel piè di pagina delle dashboard, ferme alla 0.9.18 del 2026-04-16) archiviato in `docs/changelog/CHANGELOG_django_app_fino_0.9.18.md` e riscritto con la sola release 1.6.2.
  - `_AGENT_CONTROL/AGENT_CHANGELOG.md` e `session_checkpoint.md` tolti dal repository e messi in `.gitignore`, come chiesto dall'audit di sicurezza del 2026-10-09 (contenevano diagnosi di produzione e percorsi del `.env`): restano file di lavoro locali della cartella condivisa. Aggiornati `AGENTS.md` e `README.md`.
  - Rimosso `requirements_txt.txt` (alias inutilizzato di `django_app/requirements.txt`).
  - `CLAUDE.md` non entra più nel pacchetto di release (`deployment/scripts/package-release.ps1`).

## 1.6.2 - 2026-10-10

Release di avvio della produzione. Dettaglio completo di questa versione e delle precedenti dalla 1.4.0, comprese le modifiche non ancora numerate fino al 2026-10-12: [docs/changelog/CHANGELOG_1.4.0-1.6.2_pre_golive.md](docs/changelog/CHANGELOG_1.4.0-1.6.2_pre_golive.md).
