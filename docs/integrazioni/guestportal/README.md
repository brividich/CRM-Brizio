# GuestPortal ↔ NOVICROM HUB

Il **GuestPortal** (chiosco visitatori in reception, PHP + MySQL su IIS) resta un'applicazione separata. L'HUB:

1. **legge** le visite dal database MySQL `GuestManagement` in sola lettura (pagina Fornitori → Accessi esterni);
2. **apre** il pannello admin del GuestPortal già autenticato (voce «Accessi azienda» / «Apri GuestPortal»).

3. **mostra il chiosco** in `/chiosco/` senza login, solo dalle postazioni in `CHIOSCO_ALLOWED_IPS`, chiamando lato server le API `public/api/*.php`.

Codice HUB: [`django_app/fornitori/guestportal.py`](../../../django_app/fornitori/guestportal.py). Scheda modulo: [docs/moduli/fornitori.md](../../moduli/fornitori.md).

## Lato GuestPortal (installato il 04/11/2026)

Nessun file esistente del GuestPortal è stato modificato. Aggiunti:

| File | Contenuto |
|---|---|
| `public/admin/sso.php` | verifica del token (copia versionata: [sso.php](sso.php)) |
| `config/sso.php` | `GP_SSO_SECRET` (segreto condiviso, **mai nel repo**) e `GP_SSO_MAX_SKEW` (30 s) |

Per disattivare l'accesso automatico basta rinominare `public/admin/sso.php`: il pannello funziona come prima.

### Token

`base64url(payload JSON) . "." . base64url(HMAC-SHA256(payload, segreto))`, payload `{u, iat, exp, n, iss:"novicrom-hub"}`:

- `u` = nome utente di dominio minuscolo (come `AdminUsers.Username`);
- validità 60 s (tolleranza orologi 30 s);
- `n` (nonce) usabile una volta: `sso.php` lo registra in `AuditLog` (`TableName='SSO'`, `Action='SSO_LOGIN'`, `PerformedBy='<utente> (HUB)'`) prima di aprire la sessione;
- autorizzazione: utente presente e attivo in `AdminUsers`, stessa regola del login LDAP; l'account master non entra mai da SSO;
- qualsiasi errore → redirect a `index.php` (login normale), motivo in `C:\Windows\Temp\guestportal.log` come `[SSO] accesso rifiutato: …`.

### Segreto

Il segreto è stato generato a caso e scritto solo in `config/sso.php` sul server GuestPortal. Va copiato **a mano** nel `.env` persistente dell'HUB (`GUESTPORTAL_SSO_SECRET`), senza passare da chat, mail o ticket. Per ruotarlo: nuovo valore in entrambi i posti, poi riavvio dell'HUB.

## Passaggio dei dati su SQL Server (app `reception`)

1. Permesso di lettura per l'importazione (un utente dedicato, da togliere a passaggio finito):

```sql
GRANT SELECT ON GuestManagement.* TO 'hub_readonly'@'<IP server HUB>';
```

2. `manage.py importa_guestportal`: prova, stampa solo i conteggi.
3. A chiosco fermo: `manage.py importa_guestportal --apply`, confronta i conteggi.
4. `RECEPTION_NATIVA=1` nel `.env`, `setup_q_schedules`, riavvio di HUB e qcluster.
5. Spegni il sito PHP e le sue attività pianificate; MySQL resta in sola lettura come riserva. Di ritorno: `RECEPTION_NATIVA=0`.

Attenzione: la prima notte con `RECEPTION_NATIVA=1` si cancellano le visite concluse più vecchie di `RECEPTION_CONSERVAZIONE_MESI` (12).

## Utente MySQL in sola lettura per l'HUB

Da eseguire sul MySQL del GuestPortal con un account amministrativo (scegliere la password e l'host da cui si collega il server HUB):

```sql
CREATE USER 'hub_readonly'@'<IP server HUB>' IDENTIFIED BY '<password robusta>';
GRANT SELECT ON GuestManagement.Visits    TO 'hub_readonly'@'<IP server HUB>';
GRANT SELECT ON GuestManagement.Guests    TO 'hub_readonly'@'<IP server HUB>';
GRANT SELECT ON GuestManagement.Suppliers TO 'hub_readonly'@'<IP server HUB>';
```

Poi nel `.env` persistente dell'HUB: `GUESTPORTAL_DB_HOST`, `GUESTPORTAL_DB_PORT` (3306), `GUESTPORTAL_DB_NAME` (`GuestManagement`), `GUESTPORTAL_DB_USER`, `GUESTPORTAL_DB_PASSWORD`. Dal server HUB deve essere aperta la porta 3306 verso il MySQL.

L'HUB non copia i dati delle visite per le pagine Accessi esterni e scheda fornitore → Tecnici: legge a ogni apertura.

Seconda eccezione voluta (decisione 05/11/2026): il **nominativo** di chi entra per una ditta riconosciuta viene registrato sul fornitore (`fornitori_tecnicofornitore`) con la sola origine, senza orari né visite. Resta anche dopo la pulizia del GuestPortal, finché non viene eliminato dalla scheda fornitore (Tecnici → Modifica → «Elimina dal registro»).

Eccezione voluta (decisione 04/11/2026): quando un ingresso viene **collegato a un ticket o a un OdL** l'HUB salva `VisitID`, giorno, entrata, uscita, nominativo del tecnico, azienda e badge (`fornitori_ingressointervento`), come prova dell'intervento e per il confronto con le ore fatturate. Questi dati seguono la conservazione del ticket/OdL, non la pulizia del GuestPortal.

## Messa in sicurezza (04/11/2026)

Fatto sul server; copia dei file originali in `C:\inetpub\guestportal_backup_20261104\`, fuori dalla webroot:

- `web.config` di root ([copia](web.config)): `hiddenSegments` per `scripts`, `sql`, `config`, `logs`, `storage`, `src` e blocco delle estensioni `.sql .py .ps1 .env .log .bak .lock`. Prima `scripts/config.json` (segreto Azure, password DB e SMTP) era scaricabile senza login.
- Spostati in backup (`copie_rimosse_dalla_webroot\`): `public/admin/dashboard - Copia.php`, `public/kiosk/No Responsive/`, `public/kiosk/Tema Scuro/`, `scripts/prereg_worker - Copia.py`, `Thumbs.db` e i doppioni rotti e senza login `public/api/admin/prereg_lookup.php` / `prereg_checkin.php` (puntavano a un bootstrap inesistente e nessuno li chiamava: il chiosco usa `public/api/prereg_*`).
- `public/api/admin/gdpr_purge.php`: «Reset completo» solo per l'account master (`AdminAuth::requireMaster()`); al browser un errore generico, il dettaglio resta in `C:\Windows\Temp\guestportal.log`.

Verificato dopo le modifiche: chiosco (index, checkin, checkout, prereg), API pubbliche, immagini, login admin, SSO dall'HUB, dashboard e logout come prima; cartelle riservate, copie e doppioni rispondono 404.

Ripristino: ricopiare i file da `C:\inetpub\guestportal_backup_20261104\` nella stessa posizione.

### Da fare (competenza IT)

1. Ruotare i segreti già esposti: client secret dell'app Entra, password dell'utente MySQL dell'app, password della casella SMTP.
2. Cambiare la password di root MySQL e togliere la riga con la password da `sql/01_schema_mysql.sql`.
3. HTTPS con certificato della CA interna e redirect da HTTP (oggi le credenziali AD del login admin viaggiano in chiaro); poi `https://` in `GUESTPORTAL_ADMIN_URL` e `GUESTPORTAL_SSO_URL` dell'HUB.
4. LDAP: `ldaps://` (porta 636) al posto di `ldap://` in `src/AdminAuth.php`.
5. `php.ini`: `session.cookie_httponly = 1`, `session.cookie_samesite = Lax`, `session.use_strict_mode = 1`; `session.cookie_secure = 1` dopo l'HTTPS.
6. IIS «Restrizioni IP e dominio» su `public/api/` e `public/kiosk/` per i soli IP dei chioschi (gli endpoint del chiosco non hanno login per scelta).
7. Limite ai tentativi di login falliti nel pannello admin.
8. Rotazione di `scripts/prereg_worker.log` (55 MB).
