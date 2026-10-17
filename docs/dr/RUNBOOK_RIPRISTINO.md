# Runbook di ripristino — NOVICROM HUB

Versione 1 · 17/10/2026 · da tenere **stampato** in Direzione e in PDF sul NAS (`deployment\RUNBOOK_RIPRISTINO.pdf`). Il server del portale potrebbe essere proprio quello che non c'è più.

Obiettivi concordati:

- **RTO** (tempo per tornare operativi): mezza giornata; tollerati 1–2 giorni.
- **RPO** (dati che si possono perdere): 1 ora, dalle 07 alle 21, con i backup orari del log attivi; altrimenti fino a 24 ore.

## 1. Prima di tutto: cosa serve e dove si trova

| Cosa | Dove |
|---|---|
| Backup verificati (database, file, fotografia della macchina, zip della release) | share del NAS `BACKUP_TARGET` (es. `\\nas\hub-backup\prod`). Copie fuori sede: Synology C2 (cifrato) e secondo NAS in altra sede, tramite Hyper Backup |
| Recovery Kit (`.hubkit`: `.env` + certificato HTTPS) | share dei segreti, Vaultwarden, C2 cifrato. Vedi [RECOVERY_KIT.md](RECOVERY_KIT.md) |
| **Passphrase** del Recovery Kit | busta sigillata in Direzione (cassaforte). La conosce anche Brizio |
| Installer dei prerequisiti (verificati) | `\\nas\hub-backup\_prereqs`, preparati con `restore-host.ps1 -CachePrereqsOnly` |
| Tool di ripristino | `SetupWizard.exe` → «♻ Ripristina da backup», oppure `deployment\scripts\restore-host.ps1` da una release qualsiasi |
| Ultimo esito dei backup | `\\nas\hub-backup\prod\status.json` (leggibile anche con il portale spento) |

## 2. Contatti

| Ruolo | Quando chiamarlo |
|---|---|
| Responsabile del portale (Brizio) | sempre, per primo |
| Direzione | per aprire la busta della passphrase e per autorizzare un ripristino che sovrascrive dati |
| Fornitore dell'infrastruttura (rete, NAS, ESXi) | NAS o rete non raggiungibili, VM da creare |
| Amministratore del tenant Microsoft 365 / Entra | registrazione del connector Application Proxy, controllo dell'app pubblicata |

I nominativi e i numeri si tengono nella copia stampata, non in questo file.

## 3. Scenari

### A. Il PC/server del portale è guasto (disco, scheda madre, Windows che non parte)

1. Preparare la macchina nuova (oggi il PC; in futuro la VM su ESXi): Windows 11 Pro o Windows Server, nel dominio, nome a piacere. Serve **internet**.
2. Copiare `SetupWizard.exe` dal NAS e avviarlo come amministratore → «♻ Ripristina da backup».
3. Pagina 1: cartella dei backup `\\nas\hub-backup`, ambiente PROD, «Il più recente» → «Leggi i backup e calcola il piano». Controllare data e ora del punto di ripristino.
4. Pagina 2: file del kit + passphrase (busta), `hub.costruzioninovicrom.it`, nome alternativo `hub.cnovicrom.local`, identità del pool. Sul PC resta `ApplicationPoolIdentity`, sulla VM il gMSA (sezione 6). Inserire l'account dei task.
5. Lasciare spuntato «Solo simulazione» e avviare. Leggere il log: ogni fase dice cosa farebbe.
6. «Esegui il ripristino reale». Se si ferma: leggere l'errore, correggere, «Riprendi dal punto interrotto».
7. Eseguire le azioni manuali elencate nella pagina finale (DNS, SPN, permessi share, connector group): vedi la checklist alla sezione 5.

Tempo atteso: 2–4 ore. Il database dopo la pulizia dell'audit richiede pochi minuti; installazioni e IIS sono la parte lunga.

### B. Ransomware o compromissione

1. **Isolare**: scollegare il server dalla rete, non spegnerlo se servono analisi; avvisare Direzione e fornitore.
2. Non ripristinare sulla macchina compromessa: usare una macchina nuova o una VM pulita.
3. Scegliere un punto **precedente all'infezione**: pagina 1 del wizard con data e ora. Il piano mostra quale backup completo e quali log usa.
4. Verificare che i backup non siano stati toccati: i set hanno un manifest con le impronte, e la verifica lo controlla in fase di ripristino. In caso di dubbio usare la copia fuori sede (C2 / secondo NAS).
5. Procedere come nello scenario A. Prima di riaprire il portale, cambiare le password di servizio (DB, Graph, LDAP, SMTP) e rigenerare il Recovery Kit.

### C. Dati cancellati o modificati per errore (il server funziona)

Non si ripristina tutto il portale: si recuperano solo i dati.

1. Individuare l'ora dell'errore (es. 14:35).
2. Sul server: `python manage.py hub_restore_drill --stopat "2026-10-16 14:30" --keep`. Crea la copia `PortaleNovicrom_PROD_drill` allo stato delle 14:30, accanto al DB vero, senza toccarlo.
3. Con SQL Server Management Studio confrontare e copiare solo le righe perse dalla copia `_drill` al DB vero. Va fatto da chi conosce le tabelle e solo con l'accordo della Direzione.
4. Eliminare la copia: `ALTER DATABASE [PortaleNovicrom_PROD_drill] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; DROP DATABASE [PortaleNovicrom_PROD_drill]`. La prova automatica della domenica la eliminerebbe comunque: finire il recupero prima.

### D. Il NAS dei backup è perso

1. Il portale continua a funzionare: non è un'emergenza immediata, ma da quel momento **non ci sono backup**.
2. Ripristinare il NAS (o un sostituto) dalla copia fuori sede di Hyper Backup (C2 o secondo NAS).
3. Se serve subito un backup: puntare `BACKUP_TARGET` a una share temporanea e lanciare `hub_backup --type all`.
4. Verificare con `hub_backup_doctor` e dalla pagina «Backup e ripristino».

## 4. Sequenza e tempi attesi (scenario A)

| Fase | Cosa | Tempo indicativo |
|---|---|---|
| 0 | Preflight e conferma | 5 min |
| 1 | IIS, Python, ODBC, VC++, HttpPlatformHandler, venv | 30–60 min |
| 2 | SQL Server (installazione se manca) e restore dei DB | 20–40 min |
| 3 | Recovery Kit | 2 min |
| 4 | File (media e documenti privati) | 10–60 min (dipende dai GB) |
| 5 | Release esatta | 10–20 min |
| 6 | IIS, certificato, binding | 5 min |
| 7 | Task pianificati, qcluster | 5 min |
| 8 | Connector Entra | 10–20 min (accesso interattivo) |
| 9 | SPN, DNS, share, firewall | 5 min + azioni manuali |
| 10 | Verifiche e primo backup | 10–20 min |
| 11 | Report con RTO | — |

Il report finale (`C:\PortaleNovicrom\shared\recovery\recovery-report-*.html`) riporta i tempi reali. Si archivia come evidenza.

## 5. Checklist dopo il ripristino

- [ ] Il portale si apre su `https://hub.costruzioninovicrom.it` e su `https://hub.cnovicrom.local`.
- [ ] Accesso con un utente tecnico e, dalla rete interna, con Windows SSO (SPN `HTTP/` presenti per entrambi i nomi).
- [ ] Un allegato privato (referto, documento HR) si apre da una scheda.
- [ ] I record DNS **interni di entrambi i nomi** puntano alla nuova macchina.
- [ ] Il connector Entra è nel connector group giusto; il link di approvazione da una mail (`/approval-actions/…`) funziona da fuori.
- [ ] Le share usate dal portale (SGI, documenti) sono raggiungibili dall'identità del pool e dall'account dei task.
- [ ] Monitoring → Centrale di comando: nessun servizio critico; qcluster attivo; schedule registrati.
- [ ] Monitoring → «Backup e ripristino»: primo backup completo OK, task presenti, Recovery Kit allineato (rigenerarlo se i segreti sono cambiati).
- [ ] Verificati i dati dell'ultima ora prima del guasto: se il punto di ripristino è precedente, avvisare chi deve reinserire i dati.
- [ ] Report del ripristino archiviato; vecchia macchina spenta e scollegata (scenario B: conservata per le analisi).

## 6. Futura VM con gMSA (decisione del 16/10/2026)

Sul PC attuale l'identità del pool resta invariata. Sulla VM Windows Server si usa un **gMSA**:

1. Sul controller di dominio, una volta per tutto il dominio: `Add-KdsRootKey -EffectiveImmediately` (in produzione attendere la replica di 10 ore).
2. `New-ADServiceAccount -Name gmsa-hub -DNSHostName gmsa-hub.cnovicrom.local -PrincipalsAllowedToRetrieveManagedPassword <gruppo con l'account computer della VM>`.
3. Sulla VM: `Install-ADServiceAccount gmsa-hub`, poi `Test-ADServiceAccount gmsa-hub` deve dare `True`.
4. SPN sul gMSA: `setspn -S HTTP/hub.costruzioninovicrom.it CNOVICROM\gmsa-hub$` e `setspn -S HTTP/hub.cnovicrom.local CNOVICROM\gmsa-hub$`.
5. Permessi: login SQL (`CREATE LOGIN [CNOVICROM\gmsa-hub$] FROM WINDOWS`, fatto da `restore-host.ps1`), lettura/scrittura sulle share dei backup e dei documenti.
6. Nel wizard o in `restore-host.ps1`: identità del pool e account dei task = `CNOVICROM\gmsa-hub$`, senza password.

## 7. Calendario delle prove

| Prova | Quando | Come | Evidenza |
|---|---|---|---|
| Prova di ripristino automatica | ogni domenica alle 04:00 | task DRILL (`hub_restore_drill`): ripristina su `_drill`, controlla integrità, migrazioni, righe, documenti cifrati | Monitoring → «Backup e ripristino», tabella «Prove di ripristino» (RTO del DB) |
| Verifica del Recovery Kit | ogni mese e dopo ogni modifica del `.env` | `hub_recovery_kit verify <file>` con la passphrase della busta | annotazione nel registro IT |
| **Ripristino completo su VM isolata** | **ogni trimestre** | VM senza accesso alla rete di produzione; wizard «Ripristina da backup» con il kit e la passphrase **custoditi** (non una copia nuova) | `recovery-report-*.html` archiviato con data e RTO misurato |
| Verifica della copia fuori sede | ogni trimestre | ripristino di prova di una cartella da Hyper Backup (C2 e secondo NAS) | annotazione nel registro IT |

## 8. Riferimenti

- Motore di backup, monitoraggio, prova di ripristino: [BACKUP_MOTORE.md](BACKUP_MOTORE.md)
- Tool di reinstallazione: [RIPRISTINO_HOST.md](RIPRISTINO_HOST.md)
- Recovery Kit: [RECOVERY_KIT.md](RECOVERY_KIT.md)
- Migrazione a SQL Server 2025: [SQL2025_MIGRAZIONE.md](SQL2025_MIGRAZIONE.md)
- Politica dell'audit: [AUDIT_POLICY.md](AUDIT_POLICY.md)
- Piano DR (obiettivi, componenti, dipendenze): [DR_PLAN.md](DR_PLAN.md)
