# Piano: supporto SNMPv3 nel modulo contatori

Stato: **da implementare** (piano del 2026-10-05). Nessun codice scritto.

## Contesto

- Oggi il modulo legge solo con SNMPv1/v2c (`puresnmp` 2.0.1, `V1(...)`/`V2C(...)`). La community viaggia in chiaro.
- `puresnmp` 2.0.1 supporta già v3: nessuna nuova dipendenza.
- Motivazione: v3 è autenticato e cifrato, più difendibile in ottica NIS2.
- Il timeout osservato su un iLO in prod era un problema di firewall, non di codice.

## Regole di lavoro

- Worktree dedicato e branch `feature/contatori-snmp-v3` da `origin/main`; poi main, poi `release/prod`.
- Le credenziali v3 sono segreti: mai in log, fixture, esempi o commit. Usare solo dati sintetici.
- Gli apparati v1/v2c esistenti non devono cambiare comportamento: `versione` resta il discriminante.
- Test mirati: `python django_app\manage.py test django_app.contatori --keepdb --settings=config.settings.test`.

## Fasi

1. **Modello e migrazione** (`django_app/contatori/models.py`, `CommunitySNMP`)
   - Aggiungere utente, protocollo e chiave di autenticazione (SHA/MD5), protocollo e chiave di cifratura (AES/DES).
   - Cifrare le chiavi con `credential_crypto`, come oggi `segreto_cifrato`.
   - Aggiungere `v3` alle scelte dei campi `versione` (`CommunitySNMP`, profilo, dispositivo, macchina).
   - Migrazione `contatori/0024_*`.
2. **Costruttore unico di credenziali** (`django_app/contatori/snmp.py`)
   - Una funzione che restituisce `V1`, `V2C` o `V3`.
   - Sostituire le costruzioni dirette in `leggi_oids`, `leggi_colonna` e negli altri punti (`printer_snmp.py`, comando `snmp_discover`, ecc.). Cercare con `grep -rn "V1(\|V2C(" django_app --include=*.py`.
3. **Servizi** (`django_app/contatori/services.py`)
   - `_community_snmp` e `_parametri_snmp` devono fornire le credenziali v3 quando la versione è v3.
   - Verificare budget e timeout (`SPECIFICATION_BUDGET`, `WALK_BUDGET`) con v3.
4. **Form e template**
   - I campi v3 compaiono solo se la versione scelta è v3.
   - Il segreto non si mostra in chiaro e non si scrive nei log.
5. **Test**
   - Credenziali v3 simulate (mock), come negli altri test del modulo.
   - Verificare che v1/v2c non regrediscano.
6. **Documenti**
   - `CHANGELOG.md` in `[Unreleased]` con i file modificati; `README.md` (sezione contatori/SNMP).
7. **Deploy**
   - Pacchetto da `release/prod`, poi `migrate contatori`.
8. **Apparato (iLO 5)**
   - Creare l'utente SNMPv3 (Administration → Management → SNMP Settings), scegliere i protocolli.
   - Impostare le stesse credenziali sulla scheda apparato in HUB.

## Verifica finale

- Lettura v3 riuscita su un apparato reale dopo il deploy.
- Un apparato v1/v2c esistente continua a rispondere.
- Nessuna credenziale compare in log, audit o dump.
