# NOVICROM HUB — Sicurezza, governance e compliance

Uno dei valori centrali del portale è la **protezione dei dati** e la **tracciabilità**: pensato per
un'azienda di meccanica di precisione soggetta ad audit (ISO 9001 / EN 9100) e a obblighi di sicurezza.

## Governance degli accessi (ACL v2)

- Le autorizzazioni sono gestite **come dati**, per singola funzione del portale ("chi può fare cosa").
- La **navigazione mostra solo ciò che l'utente può fare**, ma la decisione di sicurezza vera è **sempre
  lato server**: nascondere un pulsante non è la barriera, la barriera è il controllo applicativo.
- Il sistema evolve da un modello legacy verso quello canonico v2, mantenendo la compatibilità durante
  la migrazione (nessuna interruzione).

## Doppio fattore di autenticazione (2FA)

- Supporto a **app authenticator (TOTP)** o **codice via email**.
- **Policy configurabili** per ruolo e per rete (es. richiesto fuori dalla rete interna).
- Attivazione **self-service** con QR code; reset e gestione dal pannello admin.

## Audit trail immutabile

- Ogni operazione rilevante viene **registrata**: chi, cosa, quando.
- Lo storico è **consultabile e ricostruibile "punto-nel-tempo"**, utile in sede di audit.
- Sui moduli critici (es. gestione specifiche) l'audit conserva **snapshot immutabili**: i timestamp reali
  restano intatti anche quando la vista utente presenta i dati in forma semplificata.

## Privacy e GDPR

- **Minimizzazione dei dati** HR: all'AI e alle viste passano solo i campi strettamente necessari.
- **Documenti fuori dall'area pubblica** del web e **cifrati** a riposo.
- **Export protetti** e **consenso privacy** tracciato.
- Dati sanitari, retributivi e identificativi sensibili **non** vengono esposti ai moduli che non ne hanno diritto.

## Sicurezza & compliance operativa (Security Center)

Il portale digitalizza gli adempimenti di sicurezza e ambiente rendendoli **auditabili in ogni momento**:

- **DPI**: conformità alla mansione, consegne firmate, scadenze.
- **Diario preposto** e **ispezioni** periodiche.
- **Incidenti / near-miss** con KPI e heatmap.
- **Procedure** con presa visione tracciata e formazione.
- **Rifiuti (RENTRI)** con registro e giacenze per CER.
- **Azioni correttive/preventive (CAPA)** collegate agli eventi, con chiusura ed efficacia separate
  (principio dei "quattro occhi").

## Sintesi per la direzione

- Il rischio di accessi non autorizzati è **ridotto e governato** (ACL v2 + 2FA).
- In caso di audit o contestazione, esiste una **traccia completa e non alterabile**.
- I **dati restano in azienda**: nessun dato sensibile è delegato a servizi esterni.
