# Soggetti esterni e nomine (art. 28) — bozza

Checklist GDPR del 21/10/2026, punto F3. Elenco dei soggetti esterni che ricevono o trattano dati personali **attraverso il portale**, ricavato dalle integrazioni reali (`hub_tools/schema_db.py`, `CONNESSIONI_ESTERNE`). Per ognuno: ruolo proposto, cosa serve, stato. **Ruoli e stato vanno confermati dal titolare**: il codice dice quali dati escono, non quali contratti esistono.

| Soggetto | Dati e trattamenti | Ruolo proposto | Cosa serve | Stato |
| --- | --- | --- | --- | --- |
| **Microsoft** (Microsoft 365, Entra ID, SharePoint, Outlook, Teams, Power Automate, Defender, Intune, Power BI) | Liste SharePoint di assenze e incidenti (T03, T07), cedolini (T02), calendari e mail (T13, T15), flussi di approvazione, dati di sicurezza dei PC e degli account (T11), audit sigillato, report Power BI (T06) | Responsabile (art. 28) | Il Data Protection Addendum (DPA) dei prodotti Microsoft vale con il contratto di licenza: archiviarne la versione in vigore; verificare la regione dei dati del tenant (EU Data Boundary) e le garanzie per i trasferimenti (clausole contrattuali tipo, Data Privacy Framework) | *da verificare* |
| **Medico competente** | Riceve i dati del lavoratore per le visite; invia il giudizio e i referti caricati (T04) | Titolare autonomo per la cartella sanitaria; per l'uso del portale, se vi accede o vi carica documenti, valutare la nomina a responsabile per quella parte | Lettera d'incarico con le regole sui referti: nel portale solo il giudizio di idoneità | *da verificare* |
| **Consulente del lavoro / studio paghe** | Produce i cedolini importati nel portale (T02); probabile scambio di anagrafiche (T01) | Responsabile (art. 28) | Contratto o nomina con le istruzioni, le misure di sicurezza e il rientro dei dati a fine incarico | *da confermare che esista e come scambia i dati* |
| **Fornitore del NAS / servizio di backup** (se esterno) | Copie del database e dei documenti (tutti i trattamenti) | Responsabile se gestisce o accede ai backup | Nomina; i backup del database oggi non sono cifrati | *da confermare* |
| **Servizi push dei browser** (Google, Mozilla, Apple, Microsoft) | Solo il segnale «nuova notifica» verso l'iscrizione del browser; il contenuto è cifrato tra portale e browser (T14) | Non tratta il contenuto: nessuna nomina, da citare nell'informativa | Indicare nell'informativa ai dipendenti | *da valutare* |
| **Enti di formazione** | Iscritti, esiti e attestati dei corsi (T05) | Titolari autonomi in genere | Nessuna nomina se titolari autonomi; verificare i casi in cui operano su istruzioni dell'azienda | *da confermare* |
| **Organismi di certificazione, autorità, clienti in audit** | Consultazione di registri qualità, formazione, timbri (T05, T09) | Titolari autonomi / destinatari | Nessuna nomina; accesso solo con accompagnamento o estratti | — |

## Interni con accesso ai dati (art. 29, autorizzati)

Le persone che usano il portale trattano i dati come **autorizzati** del titolare. Servono le istruzioni scritte per ruolo (HR, responsabili, IT, sicurezza, qualità). Il portale applica già i permessi per ruolo (ACL v2); l'elenco dei ruoli e delle persone autorizzate si ricava dalla pagina «Ruoli e permessi».

L'amministratore di sistema del portale e dei server rientra nel provvedimento del Garante sugli amministratori di sistema (27/11/2008): designazione individuale, elenco aggiornato, registrazione degli accessi.

## Nessun trasferimento da strumenti interni

- **Assistente AI**: modello (Ollama) e indice sul server interno; nessun fornitore esterno.
- **Lettura dei referti**: OCR Tesseract sul server.
- **Azioni HTTP delle automazioni**: solo servizi Microsoft o host approvati in configurazione (`automazioni_http_host_report` elenca le regole che chiamano host esterni).
