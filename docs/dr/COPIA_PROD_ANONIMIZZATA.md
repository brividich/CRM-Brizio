# Copia di produzione anonimizzata per le prove

Serve a provare il portale su volumi e collegamenti reali dalla macchina di sviluppo, senza dati di persone e senza mail verso l'esterno.

## Come si crea

1. Prendere dal server l'ultimo FULL di produzione (`*_FULL_*.bak`) e copiarlo in una cartella locale, per esempio `C:\Temp\pnbak`. Lo script dà al servizio SQL locale il permesso di leggere il file.
2. Dalla radice di un checkout aggiornato:

   ```powershell
   .\deployment\scripts\ripristina-copia-anonima.ps1 -BakPath "<percorso del .bak>" -Migra
   ```

   Aggiungere `-Sostituisci` per rifare una copia già presente. `-Migra` porta la copia allo schema del checkout: è anche la prova delle migrazioni non ancora deployate.
3. Cancellare il file `.bak` dalla macchina di sviluppo.
4. Avviare il portale:

   ```powershell
   python django_app\manage.py runserver --noreload --settings=config.settings.copia_anonima
   ```

Per entrare si usa l'utente `collaudo`, superutente: la password viene stampata una sola volta durante la creazione. Le altre persone si provano con l'impersonazione.

Se l'anonimizzazione non riesce, lo script elimina la copia.

## Barriere contro le mail e gli invii

Il profilo `config.settings.copia_anonima` vale qualunque cosa ci sia nel `.env`.

| Barriera | Effetto |
|---|---|
| Backend mail fissato su console | Le mail vengono solo stampate |
| `config/rete_guard.py` | Le connessioni Python verso host non locali falliscono: SMTP, Graph, webhook, SNMP, syslog |
| `qcluster` rifiutato e schedule svuotate | Nessuna automazione parte da sola |
| Indirizzi sostituiti con `@example.invalid` | Nessun destinatario reale resta nel database |
| Login solo locale | LDAP tolto dalla cascata di login |

La barriera di rete non copre i comandi esterni lanciati con `subprocess`, come PowerShell.

## Cosa cambia nei dati

Le regole sono in `core/copia_anonima/regole.py`. Una colonna di testo non riconosciuta viene sostituita.

| Dato | Trattamento |
|---|---|
| Sessioni, audit, log, code, conversazioni AI, token | Tabella svuotata |
| Nomi, utenti, mail, contatti, codici fiscali, IBAN | Valori finti |
| Password e segreti | Sostituiti. 2FA spento |
| Testo libero e campi cifrati | `Testo <impronta>`. I JSON diventano vuoti |
| Allegati e altri contenuti binari nel database | Rimossi |
| Date di nascita e importi retributivi | Date casuali, importi alterati |
| Cataloghi, permessi, menu, stati, codici | Restano |
| Nomi e descrizioni di asset, macchine e software | Restano |

Lo stesso valore diventa sempre lo stesso valore finto, quindi filtri e collegamenti tra tabelle continuano a funzionare. La chiave casuale non viene salvata: non si torna indietro.

## Controllo finale

Prima di sostituire, il comando raccoglie in memoria i nomi e gli identificativi noti. Alla fine rilegge tutte le colonne di testo.

- **Residuo forte** (nome e cognome, codice fiscale, IBAN, mail, telefono, ragione sociale): nelle colonne tenute la colonna viene sostituita. Se resta un residuo, l'anonimizzazione fallisce.
- **Solo cognome**: elencato come `DA GUARDARE`, perché spesso è una parola comune.

Il riepilogo mostra tabella, colonna e conteggio, mai i valori.

## Limiti

- **È una pseudonimizzazione, non un'anonimizzazione piena.** Restano date, durate, quantità, reparti, mansioni e tipi di assenza. Una persona può essere riconoscibile dalla combinazione, quindi la copia va trattata come riservata e tenuta solo su questa macchina.
- **Il controllo cerca solo nomi noti.** Un nome che non compare nelle anagrafiche, dentro una colonna tenuta, può sfuggire.
- **I nomi non sono coerenti tra colonne.** Una persona ha un nome finto in anagrafica e un altro nei campi `nominativo`. Lo stesso valore resta però uguale ovunque.
- **Gli allegati non ci sono.** I file di `media` non stanno nel database, quindi i link agli allegati sono rotti. Le pagine che leggono un file per costruire la schermata vanno in errore 500, come le planimetrie di `assets/manutenzione/verifiche-impianti/`.
- **Il comando rifiuta** ogni database che non finisca con `_ANON` o che non sia su questa macchina.
