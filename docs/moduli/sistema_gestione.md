# `sistema_gestione` — SoA ISO 27001 e audit interni EN 9100

Area **Qualità** · URL `/sistema-gestione/` · codice [`django_app/sistema_gestione/`](../../django_app/sistema_gestione/)

[← Catalogo moduli nel README](../../README.md#-catalogo-moduli)

## Sintesi

**Sistema di gestione**: SoA ISO/IEC 27001 e threat intelligence; **audit interni EN 9100** con auditor interni/esterni qualificati, programma MOD.034 revisionato e approvato, piano MOD.035A, comunicazione con preavviso, checklist Folder B importata dal MOD.035B, rilievi OFI/NC collegati al MOD.174, rapporto e PDF/copie firmate. In arrivo: audit ISMS (MOD.171/168); **preparazione audit dagli audit precedenti** (NC/OFI, CAR ed efficacia, KPI sotto target) con bozza AI che impara dalle registrazioni

## Dettaglio

Sezione `/sistema-gestione/` (menu **Qualità**) per i documenti di governo del SGI. Comprende SoA/threat intelligence e gli audit interni EN 9100; l'estensione ISMS MOD.171/MOD.168 resta la fase successiva.

- **SoA** = foglio *Control Matrix* del MOD.165 - RAR: catalogo dei 93 controlli ISO/IEC 27002:2022 (titoli brevi in italiano scritti per il portale), per ciascuno livello 0–4 (4 = pienamente applicato, 0 = escluso con giustificazione obbligatoria), vulnerabilità (suggerita dal livello come nel MOD.165), riferimenti, giustificazione, fonte dell'obbligo, azione del piano di trattamento (responsabile, scadenza obbligatoria, livello atteso, voce del Registro OFI).
- **Revisioni**: bozza → proposta alla Direzione → approvata; la precedente approvata diventa superata. Una revisione non in bozza non si modifica; «Apri nuova revisione» la copia. Filtri per tema, applicati in parte, esclusi, con azione aperta, modificati rispetto alla revisione precedente.
- **Firme**: approvazione registrata nel portale (riportata nel PDF) + copia firmata a mano caricabile (PDF validato per estensione e MIME reale, storage privato cifrato con `DOCUMENT_ENCRYPTION_KEY`, download solo dalla view protetta).
- **Evidenza viva** (`evidenze.py`): i controlli con dati nel portale linkano i report di Report conformità (inventario IT, revisione accessi, fornitori, Security Center, licenze, presa visione, competenze, manutenzione, registro NC/OFI) e il registro threat intelligence.
- **Import**: `manage.py importa_soa_mod165 "<percorso PDF MOD.165>" --numero N [--apply]` legge la Control Matrix dal PDF (PyMuPDF, pagine ruotate) e crea la revisione in bozza; dry-run di default. I dati restano nel database, il PDF non entra nel repository.
- **Catalogo processi e audit guidati**: `/sistema-gestione/audit/processi/` contiene schede con codice univoco, responsabile, scopo, ingressi/risultati, rischi, indicatori, documenti e frequenza audit. Ogni modifica produce una revisione con autore/motivo; i processi si archiviano. Programma, piano e agenda selezionano queste schede; l'audit ne conserva una copia storica. Quattro sezioni guidano il piano, con controlli prima dell'approvazione; per firmare il rapporto servono checklist valutata, evidenze (anche per conformita), motivazioni N/A, rilievi collegati e giudizio conclusivo. Persone e attivita si correggono in bozza; modifiche al piano richiedono nuova approvazione Lead e nuova comunicazione. Storico e prossima verifica sono consultabili dal catalogo. I dati preesistenti restano leggibili; per nuovi piani e modifiche alle bozze si scelgono i processi dal catalogo. Al deploy applicare migrazioni SG 0005/0006 e bootstrap ACL esistente. Nessuna nuova dipendenza.
- **Owner e tipo dei processi (struttura della Qualità, 21/10/2026, migration `0016`)**: `Processo.ruolo_owner` (un ruolo dell'Anagrafica, es. CEO/SAM/EM/PM/OPM) e `tipo` (principale/ausiliario), nel form della scheda e modificabili anche da Anagrafica → Struttura organizzativa: stessa riga e stessa revisione (`services/processi.salva_processo`, unico punto che salva la scheda con la sua `ProcessoRevisione`). Le mansioni dell'Anagrafica si collegano al processo (`CompetenzaSkm.processo_sgi`); la scheda processo mostra owner e numero di mansioni. I 9 processi della MEGA SKILL MATRIX v8 nascono con `carica_struttura_v8` (codici `PRC-*`) senza responsabile utente: scheda e catalogo lo reggono (prima andavano in errore).
- **Audit EN 9100**: anagrafica auditor con requisiti MT CN 12 §6, inclusi esterni approvati dalla Direzione; programma annuale MOD.034 a revisioni con griglia PR/RP/ST; piano MOD.035A con persone, agenda, imparzialità e preavviso minimo di 5 giorni lavorativi; esecuzione del Folder B e rapporto MOD.035B con firma auditor, convalida dell'ente e valutazione RDD.
- **Checklist e rilievi**: `manage.py importa_checklist_mod035b "<percorso PDF MOD.035B>" --revisione N [--apply]` importa a runtime sezioni e domande (dry-run di default). OFI/NC generano una sola voce nel Registro OFI MOD.174 con origine generica e riferimenti normativi; le domande possono essere ampliate durante l'audit.
- **Documenti**: PDF MOD.034, MOD.035A e MOD.035B con struttura dei moduli aziendali, approvazioni digitali e copie firmate a mano nello storage privato cifrato. Sede e destinatario MSM sono configurabili con `SISTEMA_GESTIONE_AUDIT_SEDE` e `SISTEMA_GESTIONE_AUDIT_EMAIL_MSM`.
- **ACL**: oltre ai permessi SoA, `.audit.view`, `.audit.edit`, `.audit.esegui`, `.audit.approva`; ogni route ha binding canonico e controllo fail-closed nella view. Default: admin tutto, qualità consultazione; assegnazioni operative da Admin › ACL.
- **Report conformità**: «Dichiarazione di applicabilità» nell'area IT e «Audit interni» nell'area Qualità, entrambi inclusi nel pacchetto del riesame. I controlli SoA 5.35 e 5.36 linkano l'evidenza viva degli audit.

- **Rapporto emesso e integrità:** alla chiusura (valutazione RDD) il MOD.035B è generato una sola volta e archiviato con SHA-256 (versione «Emissione»); i download successivi consegnano quel file. Prima della chiusura il PDF è un'anteprima con filigrana «BOZZA - NON EMESSO». Direzione ≠ Lead per il piano, RDD ≠ auditor per il rapporto. Copie firmate: piano dopo l'approvazione, rapporto dopo la chiusura, sostituzione solo da approvatore.
- **Rilievi:** esiti Conforme, Punto di forza, Osservazione, OFI, NC (maggiore/minore), N/A, con clausola. Una NC entra nel MOD.174 solo con gravità ed evidenza allegata; NC maggiore = priorità Alta. Le evidenze si scaricano con un ruolo sull'audit o con la gestione del programma.
- **CAR e chiusura:** analisi cause 5 perché / Ishikawa 6M / documento esterno (schema delle NC di produzione). L'audit si chiude solo con il piano azioni approvato per ogni NC (`sistema_gestione.audit_chiusura_richiede_car_approvate`, default attivo). Solleciti giornalieri al responsabile ed escalation a RSGI oltre `sistema_gestione.car_escalation_giorni` (default 15) con il job `sistema_gestione_car_solleciti`; destinatari `sistema_gestione.audit_email_rsgi`.

- **Programma basato sul rischio:** cicli triennali con copertura per processo e clausola (`/sistema-gestione/audit/cicli/`); calendario mensile (`/audit/calendario/`); priorità `priorita-v2` con NC, OFI, requisiti cliente ed efficacia; frequenza raccomandata entro i 12 mesi di MT CN 12; rifiuto motivato del programma, proponente ≠ approvatore. Norme: EN 9100, ISO 45001, ISO 14001, ISO/IEC 27001, UNI/PdR 125.
- **Auditor e indipendenza:** qualifica con scadenza e norme abilitate; deroga d'indipendenza solo se ammessa nelle impostazioni (`/audit/impostazioni/`) e approvata da un RDD esterno al team.

- **Esecuzione da tablet:** editor domanda per domanda con navigazione, esiti a pulsanti, foto dalla fotocamera e caricamento senza ricaricare. Le modifiche restano sul dispositivo finché il server non le conferma; i salvataggi si ritentano da soli quando la rete torna.

- **Preparazione e inviti:** domande di follow-up dai rilievi ancora aperti; persone e agenda proposte dalle schede processo; invito Outlook con conferma degli auditati (Graph) oppure email con `.ics`; annullamento motivato che libera la cella del programma; numerazione RAIS/RAI/STR per tipo.

- **Cruscotto e report:** cruscotto annuale (avanzamento, rilievi per processo/clausola/gravità/mese, tempo medio CAR, % efficacia, ricorrenze, copertura clausole per norma); export xlsx dei rilievi; allegato «Rilievi e azioni» nel MOD.035B, sezioni opzionali da Impostazioni.
- **Auditato:** `/sistema-gestione/audit/miei-rilievi/` mostra solo i propri rilievi a rapporto firmato; il responsabile apre la propria CAR. Permesso `sistema_gestione.audit.miei_rilievi`, concesso a tutti i ruoli.

- **Guida d'uso in-app:** `/sistema-gestione/audit/guida/` con parte generale (fasi MT CN 12, ruoli, sigle) e un capitolo per ogni pagina degli audit, della CAR e del Registro OFI; **Scarica PDF** (`?pdf=1`). Ogni pagina ha in alto «Guida di questa pagina» (mappa `PAGE_HELP` in `guida.py`, tag `{% sg_guida_link %}`). Binding `audit.miei_rilievi`, così la legge anche l'auditato. Se cambia un'etichetta o un pulsante, aggiornare `guida.py` nello stesso commit; `tests_guida.py` verifica rotte e ancore.

## Note di rilascio

**Audit Part 145** (ottobre 2026, sistema_gestione 0015): `Audit.part145` (vuoto / SISTEMA / PRODOTTO, «Perimetro Part 145» nel passo 1 del piano). Il Dossier PART 145 del modulo Asset mostra gli audit Part 145 dell'anno, segnala se manca quello di sistema o di prodotto (MT CN 70 §5.3) e le azioni da audit scadute (permesso `sistema_gestione.audit.view`).

**Verifica SGI e guida (Unreleased, 12/10/2026):** rilievi verso il MOD.174 con ISO 14001, PdR 125 e fonte «Audit interno»; guida d'uso in-app generale e per pagina. Deploy: `migrate gestione_specifiche` 0014.

**Audit interni professionali — fasi 6-7 (Unreleased, prompt 08):** cruscotto, export rilievi, allegato Rilievi e azioni, «I miei rilievi». Deploy: `migrate sistema_gestione` 0014.

**Audit interni professionali — fase 5 (Unreleased, prompt 08):** follow-up, piano guidato, invito Outlook con conferma, annullamento, numerazione per tipo. Deploy: `migrate sistema_gestione` 0013; opzionale `sistema_gestione.audit_organizer_email`.

**Audit interni professionali — fase 4 (Unreleased, prompt 08):** esecuzione da tablet, fotocamera, tolleranza alla rete instabile. Deploy: `migrate sistema_gestione` 0012.

**Audit interni professionali — fase 3 (Unreleased, prompt 08):** cicli triennali, ISO 14001, frequenza raccomandata, calendario, rifiuto del programma, qualifica con scadenza, deroga configurabile, pagina Impostazioni. Deploy: `migrate sistema_gestione` 0011.

**Audit interni professionali — fasi 1-2 (Unreleased, prompt 08):** rapporto emesso immutabile con SHA-256, firme separate, rilievi classificati, CAR 5 perché/Ishikawa, chiusura condizionata e solleciti. Piano completo in [gap analysis](../specs/sgi_audit_interni_gap_analysis.md). Deploy: `migrate sistema_gestione` 0009-0010 e `setup_q_schedules`. Configurare `sistema_gestione.audit_email_rsgi` per l'escalation.

**Procedure aziendali (Unreleased):** copertura annuale e preparazione audit MT CN 12, CAR MT CN 11 nel registro trasversale, indicatori MT CN 13 e import controllato dei Turtle. [Checklist e avanzamento](../../docs/ai/CHECKLIST_PROCEDURE_AZIENDALI.md). Richiede migrazione SG 0008 e bootstrap ACL; nessuna nuova dipendenza.

**Audit e catalogo processi (Unreleased):** checklist revisionate, compilazione con autosalvataggio, evidenze e allegati privati, proposta delle priorita e del riepilogo, efficacia e archivio revisioni firmate. [Funzionamento e rilascio](../../docs/ai/CHECKLIST_SISTEMA_GESTIONE_AUDIT.md#automatismi-audit-2026-09-28).

#### Aggiornamento audit interni EN 9100 - fase 2

Il rapporto MOD.035B diventa immutabile dopo la firma dell'auditor; l'auditor assegnato può usare **Riapri il rapporto** solo prima della convalida dell'ente e della valutazione RDD. La convalida è consentita alla Direzione oppure al responsabile di processo identificato dall'email con permesso audit di lettura. Nel report di conformità, il KPI programmato usa soltanto la revisione MOD.034 approvata e i mesi del periodo; gli anni privi di programma approvato sono esplicitati nelle note.

#### Collegamento con la Struttura organizzativa (23/10/2026)

Scheda processo: sezione «Chi possiede e chi esegue il processo» (`processi_views._persone_processo` → `anagrafica.services.struttura_processo.persone_processo`): titolari del ruolo owner, mansioni lavorative con `processo_sgi` = processo, operativi e in lista. Piano di audit (stato Pianificato, permesso di modifica): «Proposte dalla struttura organizzativa» (`audit_views._proposte_auditati`) con owner come «Responsabile del processo» ed esecutori operativi come «Auditato»; «Aggiungi» invia al già esistente `audit_persona_salva`. Nessuna migrazione, nessun URL nuovo.
