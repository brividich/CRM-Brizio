# Attuazione procedure aziendali — checklist e avanzamento

Aggiornamento: 2026-09-29. Branch: `feature/audit-procedure-aziendali`.
Fonti consultate in sola lettura: `X:\9100_Qualità`. Nessun PDF aziendale o dato personale viene copiato nel repository.

## Regole e verifiche

| Stato | Fonte | Attuazione | Verifica prevista |
|---|---|---|---|
| [x] | MT CN 12 Rev.1 §5.1–5.2 | Copertura annuale processi attivi, pianificata ed eseguita; blocco programmi incompleti | Processo senza mese, annullamento, audit di altro anno |
| [x] | MT CN 12 §5.3, §6 | Gruppo interno con almeno un altro auditor; indipendenza e qualifiche prima dell'approvazione | Responsabile nel team, team singolo, esterno approvato |
| [x] | MT CN 12 §5.5 | Preparazione tracciata: precedenti audit, CAR cliente, documenti/registrazioni, obiettivi e carenze | Avvio bloccato senza riesame preparatorio |
| [x] | MT CN 11 §5.3–5.4 | CAR: causa/contenimento, un mese analisi, tre mesi chiusura, proroga approvata e verifica indipendente | Fine mese, scadenze, permessi, chiusura incompleta |
| [x] | MT CN 13 Rev.4 §7, §10–12 | KPI con periodo, numeratore/denominatore, formula, fonte/filtri, target, confronto e commento | Zero denominatore, confrontabilità, calcolo deterministico |
| [x] | MT CN 13 §8.4 | Vendor Rating 30/70, classificazione, nessuna CAR automatica | Soglie e dati OTD mancanti |
| [x] | Turtle e manuale §4.3–4.4 | Acquisizione controllata delle schede processo da documenti, provenienza e revisione; nessun owner inventato | Import ripetuto, conservazione schede già curate |
| [x] | Documentazione incrociata | Registro delle discrepanze e dei riferimenti da validare | Nessuna revisione dichiarata vigente automaticamente |
| [x] | Tutte | Test mirati, migrazioni/check, documentazione e commit | Esito e limiti riportati a chiusura |

## Discrepanze da risolvere con il responsabile documentale

- MOD.035B cita MOD.034 Rev.19; disponibile Rev.18.
- MOD.035B cita MT CN 04 Rev.1; disponibile Rev.0.
- MT CN 12 cita MOD.077; chiarire adozione e ambito di MOD.035A/B.
- MOD.141 Turtle approvvigionamento riporta Mod.094 nel piè di pagina.
- Riferimenti MTSI non presenti nel perimetro consultato: 03/04/05/06/09/10/15/18.
- Riconciliare indicatori dei Turtle e Master List MT CN 13 Rev.4.
- Preavviso: MT CN 12 indica almeno una settimana, MOD.035A cinque giorni lavorativi; applicare entrambe le verifiche finché il testo non viene riallineato.

## Distinzione tra software e attuazione aziendale

Le funzionalità possono essere implementate e testate; approvazione delle revisioni, assegnazione dei responsabili, import definitivo e compilazione delle registrazioni reali richiedono dati aziendali validati. Non si generano esiti conformi, firme, qualifiche o consuntivi mancanti.

## Avanzamento

- Ricognizione completata: 172 PDF, 1.534 pagine; 63 pagine con testo scarso/assente richiedono revisione visiva/OCR.
- Implementati i controlli procedurali e i registri collegati. Nuova migration SG 0008.
- 171 test mirati verdi su SG, report_conformita e registro OFI; Django check e migration drift verdi. Rendering e percorso HTTP di registrazione KPI verificati con dati sintetici.
- Estrattore eseguito in sola lettura sui cinque Turtle reali: cinque codici/nominativi riconosciuti con input, output, funzioni, metodi e indicatori. Nessuna importazione nel DB aziendale.

## Uso e rilascio

1. Codice integrato nella release il 2026-09-29; il deploy resta separato. Applicare `migrate sistema_gestione`, bootstrap ACL canonico e riavviare web. Collaudare SQL Server e ruoli reali.
2. Anteprima: `python manage.py importa_turtle_processi "X:\9100_Qualità\Turtle Diagram" --settings=<ambiente>`; aggiungere `--apply` solo nell'ambiente autorizzato per creare le proposte inattive. Il comando non sovrascrive codici esistenti. Dal catalogo mostrare tutti i processi, verificare le fonti, completare owner/scopo/rischi/punti norma e attivare le schede corrette.
3. Nel programma annuale completare mesi e riferimenti del catalogo. Il confronto riconosce voci separate da virgola, punto e virgola o ritorno a capo; non deduce equivalenze fra intervalli o requisiti non censiti. La copertura resta dipendente dalla completezza del catalogo e va validata dal responsabile del sistema.
4. Preparazione accessibile dalla scheda audit: esaminare precedenti, CAR cliente e registrazioni, definire obiettivi/carenze; riconfermare dopo l'approvazione del piano. Comunicare prima di avviare. Il PDF rapporto conserva la preparazione. Le note storiche non superano indipendenza o preavviso.
5. Dal dettaglio Registro OFI aprire esplicitamente la CAR quando richiesta: non ogni NC genera automaticamente una CAR. Il responsabile compila; approvatore RSGQ/Direzione approva analisi/azione e proroghe. La chiusura richiede verificatore distinto, approvazione e prove; sincronizza registro ed efficacia dell'audit collegato. Modifiche a causa/azione/responsabile invalidano l'approvazione. Il form generico OFI non puo cambiare scadenza o chiusura di una CAR gestita.
6. Da Audit aprire Indicatori: registrare periodo, formula, dati, fonte/filtri, target e commento con riferimento al VRS. Le registrazioni sono conservate; rettifiche con nuova rilevazione motivata. Target/risultati non vengono approvati automaticamente dal software. Per VR utilizzare rapporti in scala 0-1; nessuna CAR o sospensione fornitore automatica.

## Validazioni aziendali ancora aperte

- [ ] Risolvere le discrepanze di revisione sopra elencate con il responsabile documentale.
- [ ] Validare e attivare le schede importate, distinguendo funzioni coinvolte e process owner.
- [ ] Reperire programmi/rapporti firmati, VRS e cruscotti consuntivi: i modelli vuoti non sono prove dell'esecuzione.
- [ ] Collaudare database SQL Server, grant e ruoli reali prima del deploy.
- [ ] Verificare visivamente/OCR le 63 pagine con testo insufficiente, fuori dall'import automatico Turtle.

## Limiti espliciti

Nessun connettore BMS/Qlik nuovo: i valori KPI sono registrazioni con fonte dichiarata, non estrazioni certificate dal gestionale. Un denominatore nullo o OTD indisponibile non produce un Vendor Rating inventato: occorre chiarire la regola applicabile prima di registrare un VR completo. Le classi usano le soglie 0,80 e 0,70, senza arrotondare prima della classificazione. Nessuna modifica agli originali aziendali, firma automatica o import di nominativi. Nessun nuovo job/email. Le fonti importate sono proposte da validare, non revisioni automaticamente dichiarate vigenti.

- Collaudo finale 2026-09-29: protezione da versioni CAR obsolete anche per approvazioni/proroghe/chiusure, 171 test verdi; layout in tre sezioni verificato su mobile scuro, registrazione KPI via HTTP verificata; server QA arrestato.
