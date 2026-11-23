# Ambiente di test con i dati reali

Serve a provare le funzioni nuove sul portale vero, con una copia del database di produzione, senza che partano mail o automazioni. Gira sul server di test, con lo stesso pacchetto della produzione.

## Che cosa lo rende sicuro

Nel `.env` dell'ambiente di test va scritto `HUB_AMBIENTE_TEST=1`. Le impostazioni restano `config.settings.prod`. Con quella variabile:

| Barriera | Effetto |
|---|---|
| Nome del database | Ogni database deve avere `TEST` nel nome, altrimenti il portale non parte. L'ambiente di test non può puntare alla produzione |
| Posta | Le mail diventano file in `logs\mail_test`, uno per messaggio |
| Rete | Le connessioni Python verso l'esterno falliscono: SMTP, Graph, webhook, SNMP, syslog. Restano aperti solo i server del login di dominio (`LDAP_SERVER`, `LDAP_DOMAIN`) |
| Automazioni | `manage.py qcluster` e `manage.py process_automation_queue` si rifiutano di partire |
| Etichetta | Ogni pagina mostra «AMBIENTE DI TEST» in basso |

Per aprire un altro host, per esempio il server dell'AI: `HUB_TEST_HOST_CONSENTITI=nome1,nome2` nel `.env`.

Senza la variabile non cambia nulla: in produzione il blocco è spento.

## Rifarlo da zero

Tutti i passi si fanno sul server di test, da amministratore. Gli script sono in `deployment\scripts`.

1. **Togliere il vecchio ambiente.**
   - Fermare e rimuovere il sito e l'app pool `PortaleNovicrom-TEST` da IIS.
   - Rimuovere le attività pianificate dell'ambiente di test: qcluster, «Portale Hub Polling Mail», raccoglitori, backup, `IISRestart_TEST`.
   - Rinominare `C:\PortaleNovicrom\test` e, a prova riuscita, cancellarla.
   - Eliminare il vecchio database di test.
2. **Copiare il database di produzione.** Prendere l'ultimo backup completo (`*_FULL_*.bak`) e ripristinarlo con un nome che contiene `TEST`, per esempio `PortaleNovicrom_TEST`:

   ```sql
   RESTORE FILELISTONLY FROM DISK = N'<percorso del .bak>';
   RESTORE DATABASE [PortaleNovicrom_TEST] FROM DISK = N'<percorso del .bak>'
     WITH MOVE N'<nome logico dati>' TO N'<cartella dati>\PortaleNovicrom_TEST.mdf',
          MOVE N'<nome logico log>'  TO N'<cartella dati>\PortaleNovicrom_TEST_log.ldf',
          RECOVERY, STATS = 10;
   ALTER DATABASE [PortaleNovicrom_TEST] SET RECOVERY SIMPLE;
   ```

   Cancellare il file `.bak` dal server di test a ripristino finito.
3. **Creare le cartelle:** `.\setup-environment.ps1 -Environment test`.
4. **Scrivere il `.env`** in `C:\PortaleNovicrom\test\config\.env`, partendo da quello di produzione. Righe da cambiare:

   | Variabile | Valore |
   |---|---|
   | `HUB_AMBIENTE_TEST` | `1` |
   | `DB_NAME`, `DB_HOST` | Il database di test e la sua istanza |
   | `REGISTRO_LOG_DB_NAME` | Vuoto, oppure un database con `TEST` nel nome |
   | `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS` | L'indirizzo del sito di test |
   | `DJANGO_LOG_DIR` | `C:\PortaleNovicrom\test\logs` |
   | `DOCUMENT_ENCRYPTION_KEY` | La stessa della produzione: serve a leggere i campi cifrati |

   Poi `.\secure-env-acl.ps1 -Environment test`.
5. **Installare il pacchetto:** `.\deploy-release.ps1 -Environment test -PackagePath "<zip>" -AutoActivate`. Il passo fa anche le migrazioni: è la prova delle migrazioni non ancora in produzione.
6. **Creare il sito:** `.\configure-iis-site.ps1 -Environment test -Hostname "<indirizzo del sito di test>"`.
7. **Non installare** per l'ambiente di test: qcluster, polling della posta, raccoglitori, backup pianificati. Il sito di test non va pubblicato su Entra Application Proxy.

## Controlli dopo l'avvio

| Controllo | Esito atteso |
|---|---|
| Aprire una pagina | Etichetta «AMBIENTE DI TEST» in basso |
| Entrare con il proprio utente di dominio | Si entra |
| Fare un'azione che manda una mail | Nessuna mail arriva; compare un file in `logs\mail_test` |
| `manage.py qcluster --settings=config.settings.prod` dalla cartella della release di test | Errore «le automazioni restano ferme» |

## Aggiornare i dati

Ripetere il passo 2 sopra lo stesso database (`WITH REPLACE`) e reinstallare l'ultimo pacchetto, che riallinea lo schema.

## Limiti

- **Versione di SQL Server.** Un backup si ripristina solo su un'istanza della stessa versione o più recente. La produzione è su SQL Server 2025: se il server di test ha una versione precedente serve un'istanza 2025 (`install-sql2025-instance.ps1`), oppure il database di test resta sull'istanza di produzione con un altro nome.
- **Dati reali.** Il database di test contiene dati personali veri: stessi accessi e stesse cautele della produzione. Chi entra vede ciò che vedrebbe in produzione.
- **Allegati.** I file di `media` non stanno nel database: senza copiarli i link agli allegati sono rotti.
- **Comandi esterni.** Il blocco di rete copre Python, non i comandi lanciati con `subprocess` (PowerShell) né le attività pianificate di Windows.
- **Funzioni che parlano con l'esterno.** SharePoint, calendario Outlook, AI e simili danno errore: è il blocco che lavora.
- **Azioni interne.** Notifiche in pagina, attività e registri si scrivono normalmente nel database di test.
