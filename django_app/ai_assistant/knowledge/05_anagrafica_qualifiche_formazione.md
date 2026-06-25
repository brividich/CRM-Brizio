# Anagrafica HR, qualifiche e formazione

## Cosa contiene il modulo Anagrafica HR?

Il modulo **Anagrafica HR** raccoglie i dati dei dipendenti: scheda anagrafica e
aziendale (reparto, mansione, area, ruolo, stato attivo o cessato), qualifiche e
abilitazioni, formazione, documenti e i ratei di ferie, permessi e ROL. L'accesso
ai dati riservati è regolato da permessi granulari: un utente standard vede le
proprie informazioni, mentre i dati di altri dipendenti sono visibili solo a chi
ha un ruolo HR o amministrativo adeguato.

## Quali dati l'assistente AI non mostra mai?

Per tutela della privacy l'assistente non riporta dati personali riservati anche
a chi è autorizzato a vedere l'elenco: codice fiscale, IBAN e banca, indirizzi e
contatti privati, categorie protette o disabilità, visite mediche, retribuzioni e
dettagli del cedolino, documenti e allegati. Riporta solo campi minimi e generali
(nome, reparto, mansione, area, ruolo aziendale, stato) e, per chi ha i permessi,
i ratei come ore e periodo.

## Cosa sono le qualifiche e le abilitazioni?

Le **qualifiche** (o abilitazioni) sono le competenze certificate di un dipendente,
spesso con una **scadenza** e un'evidenza documentale (l'attestato). Il modulo
tiene un cruscotto e uno scadenzario dedicato per vedere quali qualifiche stanno
per scadere e quali vanno rinnovate. Al rinnovo viene storicizzata anche l'evidenza
documentale, così resta lo storico append-only dei rinnovi.

## Come funziona la formazione e l'e-learning?

L'area formazione tiene traccia dei corsi e dei **micro-corsi e-learning**
assegnati ai dipendenti. Al completamento di un micro-corso l'attestato viene
archiviato automaticamente tra i documenti del dipendente. Le campagne di lettura
e i quiz di presa visione sono invece gestiti dal modulo Procedure (refresh).

## Dove trovo i documenti dei dipendenti?

I documenti HR sono organizzati in cartelle, anche per reparto o ruolo, con
cartelle riservate visibili solo agli amministratori e una retention configurabile
per cartella secondo le regole GDPR. I file con dati personali sono conservati
fuori dalla webroot e protetti da permessi: l'assistente AI non espone mai
contenuti, percorsi o allegati dei documenti.
