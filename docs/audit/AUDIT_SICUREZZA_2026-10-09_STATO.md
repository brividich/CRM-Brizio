# Audit sicurezza 09/10/2026 — stato delle correzioni

Branch `feature/security-audit-fase0` (worktree dedicato). Le Fasi 0–3 della roadmap e i finding medi/bassi rimasti fuori sono implementati nel codice; qui sotto c'è cosa resta da fare a mano e cosa non è stato toccato.

## Prima del deploy in produzione

1. `pip install -r django_app/requirements.txt` (cryptography 50, Django 5.2.17, msal 1.39, pyOpenSSL 26.4 e gli altri pacchetti aggiornati).
2. `.env` di produzione:
   - `AUTOMATION_HTTP_ALLOWED_HOSTS`: host interni chiamati dalle regole `http_request` esistenti. Senza, le chiamate verso IP privati falliscono.
   - `LDAP_GROUP_ALLOWLIST`: se valorizzata ora filtra anche il login e l'SSO. Verificare che contenga i gruppi di **tutti** gli utenti del portale, oppure `LDAP_GROUP_ALLOWLIST_ON_LOGIN=0`.
   - `LDAP_SERVER=ldaps://…` (+ `LDAP_CA_CERT_FILE` se il certificato del DC non è nello store di Windows). `validate_deployment` segnala `ldap://`.
   - `TWOFA_EXTERNAL_PROXY_IPS`: IP del connettore Entra Application Proxy, se la policy 2FA è «solo da rete esterna».
   - `TRUSTED_PROXY_IPS`: solo se IIS imposta davvero `X-Forwarded-For` (verificare); altrimenti lasciarlo vuoto, perché un header inviato dal client verrebbe accettato.
   - `BACKUP_ENV_DIR`: cartella separata dai backup per la copia del `.env`.
   - opzionale `Q_CLUSTER_WORKERS` (default ora 3).
3. `web.config` di produzione (non viene rideployato): aggiungere su `<location path="media">` l'header `Content-Security-Policy: script-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'` come nei template in `deployment/config/`.
4. Dopo il deploy: `python manage.py setup_q_schedules` e riavvio del qcluster (timeout dedicato dell'indicizzazione AI, worker).
5. Dopo il deploy: `python manage.py apply_sql_triggers` per riapplicare i trigger della coda con la gestione degli errori (S3). Prima in TEST.
6. Con la policy 2FA attiva, i superuser dovranno configurare il TOTP al primo accesso.
7. Utenti legacy: nuove password di almeno 12 caratteri; chi ha «deve cambiare password» non usa il portale finché non la cambia.
8. Flussi Power Automate delle approvazioni su Teams: se usano il campo `token`, impostare `APPROVAL_TEAMS_INCLUDE_TOKEN=1` (ora arriva vuoto).
9. Le FAQ salvate dalla chat AI nascono disattivate: rivederle in «FAQ & Knowledge AI».

## Azioni fuori dal codice (R1)

- Rendere privato il repository GitHub e ruotare la password UAT che era nel seed e la community SNMP di default (`contatori/models.py`). La history conserva i valori vecchi.
- Togliere dal repository `session_checkpoint.md` e `_AGENT_CONTROL/` (diagnosi di produzione e percorsi del `.env`) o spostarli in `.gitignore`: non rimossi qui perché sono file di lavoro di altre sessioni.
- Verificare nelle impostazioni dell'app GitHub l'accesso in scrittura concesso durante l'analisi.
- Rendere `Security Gate` un *required check* su `main` (impostazione del repository).
- Penetration test esterno sulla superficie App Proxy (`/approval-actions/`).

## Finding

| ID | Stato |
| --- | --- |
| C1, A1, A2, A3, A7, A8 | Corretti (Fase 0) |
| A4, A5, A6, A10, M6, M7, M8, S1, S2, S7 | Corretti (Fase 1); A4/A5 da verificare sul server (IP reale dietro IIS e App Proxy) |
| A9, M1, M2, M4, M10, M12, S4, S5, S6 | Corretti (Fase 2); A9 richiede l'header sul `web.config` di produzione |
| CSP | Tolti gli host CDN. **Non fatto:** nonce senza `'unsafe-inline'` (~290 script inline e ~1000 handler `on*=` da spostare in file `.js` prima) |
| M3 | Corretto (Fase 0) |
| M11 | Corretto (Fase 3) |
| M5, M9, M13, B1–B8, S3, S8, S9 | Corretti (fuori roadmap); S3 richiede `apply_sql_triggers` |
| S10 | Parziale: corretti i KPI della dashboard assets; gli altri ~260 `except Exception: pass` restano, la CI li vieta nel codice nuovo |
| Fase 3 — `views.py` > 8.000 righe in package | **Non fatto:** refactor strutturale, da pianificare a parte |
| Fase 3 — test `fornitori`, `planimetria` | **Non fatto** (aggiunti invece i test su `twofa`) |
