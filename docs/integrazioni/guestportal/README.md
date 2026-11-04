# GuestPortal ↔ NOVICROM HUB

Il **GuestPortal** (chiosco visitatori in reception, PHP + MySQL su IIS) resta un'applicazione separata. L'HUB:

1. **legge** le visite dal database MySQL `GuestManagement` in sola lettura (pagina Fornitori → Accessi esterni);
2. **apre** il pannello admin del GuestPortal già autenticato (voce «Accessi azienda» / «Apri GuestPortal»).

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

## Utente MySQL in sola lettura per l'HUB

Da eseguire sul MySQL del GuestPortal con un account amministrativo (scegliere la password e l'host da cui si collega il server HUB):

```sql
CREATE USER 'hub_readonly'@'<IP server HUB>' IDENTIFIED BY '<password robusta>';
GRANT SELECT ON GuestManagement.Visits    TO 'hub_readonly'@'<IP server HUB>';
GRANT SELECT ON GuestManagement.Guests    TO 'hub_readonly'@'<IP server HUB>';
GRANT SELECT ON GuestManagement.Suppliers TO 'hub_readonly'@'<IP server HUB>';
```

Poi nel `.env` persistente dell'HUB: `GUESTPORTAL_DB_HOST`, `GUESTPORTAL_DB_PORT` (3306), `GUESTPORTAL_DB_NAME` (`GuestManagement`), `GUESTPORTAL_DB_USER`, `GUESTPORTAL_DB_PASSWORD`. Dal server HUB deve essere aperta la porta 3306 verso il MySQL.

L'HUB non copia i dati delle visite per la pagina Accessi esterni: legge a ogni apertura.

Eccezione voluta (decisione 04/11/2026): quando un ingresso viene **collegato a un ticket o a un OdL** l'HUB salva `VisitID`, giorno, entrata, uscita, nominativo del tecnico, azienda e badge (`fornitori_ingressointervento`), come prova dell'intervento e per il confronto con le ore fatturate. Questi dati seguono la conservazione del ticket/OdL, non la pulizia del GuestPortal.
