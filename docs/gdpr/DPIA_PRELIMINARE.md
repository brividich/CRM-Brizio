# Valutazione d'impatto (art. 35) — analisi preliminare (bozza)

Checklist GDPR del 21/10/2026, punto F2. Per ogni trattamento del [registro](REGISTRO_TRATTAMENTI.md) che può richiedere una valutazione d'impatto (DPIA), questo documento dà la verifica di necessità e l'impianto: descrizione, rischi, misure già nel portale, rischi residui. **Non è la DPIA**: la valutazione e la decisione finale restano al titolare, sentito il DPO (art. 35.2).

## Verifica di necessità

Criteri delle Linee guida WP248 rev.01 (fatte proprie dall'EDPB). Con due o più criteri la DPIA è di regola necessaria. Si tiene conto anche dell'elenco del Garante (provv. n. 467 dell'11/10/2018), che include i trattamenti nel rapporto di lavoro con sistemi tecnologici da cui può derivare un controllo a distanza dei dipendenti.

| Criterio WP248 | T04 Sorveglianza sanitaria | T10–T11 Accessi e SOC | T12 Assistente AI |
| --- | --- | --- | --- |
| Valutazione o punteggio | sì (idoneità alla mansione) | — | — |
| Decisione automatizzata con effetti | no (decide il medico) | no | no |
| Monitoraggio sistematico | — | **sì** (accessi, dispositivi, alert sui PC) | — |
| Dati sensibili o molto personali | **sì** (salute) | — | possibile (testo libero) |
| Larga scala | no | no | no |
| Incrocio di dataset | — | sì (Entra, Intune, Defender, portale) | sì (documenti e dati del portale) |
| Interessati vulnerabili (dipendenti) | **sì** | **sì** | sì |
| Uso innovativo di tecnologia | sì (lettura automatica dei referti) | — | **sì** (modello linguistico) |
| Ostacolo all'esercizio di un diritto | — | — | — |
| **Esito** | **DPIA necessaria** | **DPIA necessaria** (anche per l'elenco del Garante) | **DPIA consigliata** |

Gli altri trattamenti del registro non raggiungono due criteri in modo chiaro. Il titolare lo conferma e lo annota nel registro.

## D1 — Sorveglianza sanitaria (T04)

**Descrizione.** HR programma le visite e riceve dal medico competente l'esito. I referti caricati in una cartella vengono letti sul server (OCR Tesseract): il portale ne ricava il giudizio e lo propone su una riga da confermare. Prescrizioni e limitazioni servono a capi e preposti per assegnare il lavoro.

**Rischi per gli interessati**
- Conoscenza di dati sanitari da parte di chi non ne ha bisogno (colleghi, capi oltre la limitazione operativa).
- Referti che contengono più del giudizio (diagnosi, esami).
- Lettura automatica sbagliata del giudizio, con un'idoneità errata.
- Uscita dei dati tramite export, backup o log.

**Misure già nel portale**
- Permessi dedicati per le pagine delle visite (ACL v2): chi non ha il permesso non le apre.
- Prescrizioni, note e giudizio letto cifrati nel database; referti cifrati nell'archivio privato.
- Il giudizio letto dal referto è sempre da confermare da una persona.
- Audit sulle consultazioni delle visite; nel registro, solo i nomi dei campi cambiati.
- Export «I miei dati» senza prescrizioni né note; codici fiscali mascherati nei log.

**Rischi residui e azioni proposte**
1. Accordo con il medico competente: nei referti caricati solo il giudizio di idoneità.
2. Termine di conservazione delle visite, da definire con il medico competente.
3. Backup non cifrati (SQL Server Express): decisione IT aperta.
4. Rivedere chi ha il permesso di vedere le visite (elenco dei ruoli) prima del go-live.

## D2 — Accessi, audit e Security Center (T10, T11)

**Descrizione.** Il portale registra accessi, dispositivi, operazioni e consultazioni delle schede più delicate. Il Security Center legge da Microsoft (Defender, Intune, Entra) alert, PC, software e account, e le mail dei report di sicurezza.

**Rischi per gli interessati**
- Uso dei dati per controllare la prestazione lavorativa, fuori dalla finalità di sicurezza.
- Profilazione delle abitudini (orari, dispositivi, siti negli alert).
- Conservazione oltre il necessario.

**Misure già nel portale**
- Finalità limitata a sicurezza e audit; accesso al SOC solo per il personale IT.
- Termini automatici: tentativi di accesso 90 giorni, mail SOC svuotate dopo 12 mesi, chat AI del SOC 12 mesi.
- Avviso alla persona per un accesso da dispositivo nuovo, con «Non ero io»: la persona vede i propri accessi.
- Audit sigillato ogni mese: il registro non si può modificare senza che si veda.

**Rischi residui e azioni proposte**
1. Informativa ai dipendenti sugli strumenti e sui controlli (art. 4 c. 3 L. 300/1970, art. 13 GDPR). Senza informativa i dati non sono utilizzabili.
2. Regolamento interno sull'uso degli strumenti informatici, che dica chi consulta i log e per cosa.
3. Verificare con il consulente del lavoro se servono accordo sindacale o autorizzazione (art. 4 c. 1) per gli strumenti che non sono «strumenti di lavoro».

## D3 — Assistente AI (T12)

**Descrizione.** L'assistente risponde usando i documenti del sistema di gestione, le guide e strumenti che leggono i dati del portale con i permessi dell'utente. Il modello gira su un server interno: nessun dato va a fornitori esterni.

**Rischi per gli interessati**
- Risposte con dati di persone che l'utente non dovrebbe vedere.
- Dati personali scritti nelle domande e conservati.
- Risposte inventate su persone (es. competenze, idoneità).

**Misure già nel portale**
- Strumenti con i permessi dell'utente e revisione privacy per strumento (`AiToolPrivacyReview`).
- Modello e indice su server interno; nessun trasferimento.
- Conversazioni e feedback cancellati dopo 90 giorni; nel registro audit solo i metadati dei messaggi.
- Controlli contro le risposte inventate sulla skill matrix.

**Rischi residui e azioni proposte**
1. Verificare per ogni strumento attivo la revisione privacy e il suo termine di conservazione.
2. Avviso nell'interfaccia: non inserire dati sanitari o di terzi nelle domande.
3. Le risposte su persone non sostituiscono la verifica nella scheda (indicarlo nell'informativa).

## Prossimi passi

1. Il titolare conferma l'esito della verifica di necessità.
2. Per D1 e D2: DPIA completa (metodo a scelta del titolare, ad esempio lo strumento PIA del CNIL citato dal Garante), con il parere del DPO.
3. Riesame a ogni modifica rilevante del trattamento e comunque una volta l'anno.
