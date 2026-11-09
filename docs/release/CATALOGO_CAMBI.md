# Catalogo dei cambiamenti dell'HUB (MT CN 275 par. 9.1)

Ogni intervento sull'HUB rientra in una delle tre categorie. La categoria decide chi autorizza, quali evidenze servono e quanto tempo c'è per registrarle.

## Standard: pre-autorizzati, registrati

Interventi ripetitivi, a rischio noto e basso, con procedura scritta. Non serve una RFC dedicata: basta la riga nel registro RFC, o la voce nel CHANGELOG, con data ed esecutore.

| Cambio | Procedura | Evidenza |
|---|---|---|
| Testi, etichette, guide in-app, Centro guide, documentazione | Commit su feature -> main; entra nel rilascio ordinario successivo | CHANGELOG |
| Correzione di template o CSS senza nuove rotte né permessi | Idem; `collectstatic` al deploy | CHANGELOG |
| Patch di versione (`1.N.k`) con sole correzioni e nessuna migrazione | Rilascio ordinario con RFC «di patch» ridotta (sezione rischi riusata dall'ultima minor) | Registro RFC, tag |
| Aggiornamento di dipendenze Python entro la stessa major, pip-audit pulito | `pip-compile`, test dell'app toccata, release guard | CHANGELOG, log del guard |
| Riavvio di app pool, qcluster, task pianificati | `restart-iis-env.ps1`, `qcluster-console.ps1` | Registro log del server |
| Modifica di permessi ACL dalla matrice (senza codice) | Interfaccia Amministrazione; audit trail del modulo | Audit ACL |
| Rigenerazione di `SetupWizard.exe` dal `setup_wizard.py` committato | Automatica in `package-release.ps1` | Log del pacchetto |

## Normali: RFC MOD.172, valutazione CISO, autorizzazione Governance

Tutto ciò che cambia funzioni visibili, dati, permessi o infrastruttura in modo pianificabile.

| Cambio | Perché è «normale» | Note di valutazione |
|---|---|---|
| Nuova app Django, nuovo modulo o nuova pagina con rotte e permessi | Nuova superficie, nuovi dati | Requisiti di sicurezza: ACL v2, API JSON 401/403, nessuna esenzione da login se non in `MIDDLEWARE_EXEMPT_PREFIXES` e `PUBLIC_VIEWS` |
| Migrazioni di schema su SQL Server | Irreversibilità, tempi di deploy | Prova su copia anonimizzata, backup pre-deploy, piano di rollback |
| Minor (`1.N.0`) | Raggruppa i due casi sopra | Collaudo su TEST con verbale |
| Integrazioni esterne (Graph, LDAP, SMTP, Entra proxy, API di fornitori) | Credenziali, dati in uscita | Segreti solo in `config\<env>\.env`; registro trattamenti se cambiano i dati |
| Modifiche a `.env` di PROD, `web.config`, IIS, Task Scheduler | Configurazione d'esercizio | Account admin, copia di sicurezza del file, annotazione nel registro |
| Cambio di versione di Python, SQL Server, Waitress | Piattaforma | Finestra concordata, prova su TEST |
| Copia di dati di produzione in TEST o DEV | Dati personali | Autorizzazione scritta e anonimizzazione (A.8.33) |

## Emergenza: prima si interviene, entro un giorno lavorativo si registra

| Situazione | Intervento | Evidenza richiesta |
|---|---|---|
| Portale bloccato o flusso critico fermo (approvazioni, assenze, mail, timbrature) | `hotfix-create` / `hotfix-apply` oppure `rollback-release.ps1` | Riga «Emergenza» nel registro, RFC a posteriori, riesame post-rilascio |
| Falla di sicurezza o esposizione di dati | Blocco della superficie (ACL, exempt, proxy), poi correzione | Come sopra, più segnalazione al CISO secondo MT CN 275 |
| Vulnerabilità critica in una dipendenza (pip-audit, CVE) | Aggiornamento mirato e pacchetto di patch | Come sopra |
| Rilascio eseguito prima dell'autorizzazione formale | Nessun intervento tecnico aggiuntivo | Registrazione come «Urgente» entro un giorno lavorativo, autorizzazione a sanatoria |

## Regole comuni

- Un cambio «standard» che tocca permessi, migrazioni o superfici pubbliche diventa «normale».
- Il pacchetto nasce sempre da un commit di `release/prod` (`package-release.ps1` senza `-SourcePath`): un pacchetto da cartella è ammesso solo in emergenza, con `-Force`, e non riceve il tag `prod-vX.Y.Z`.
- Una vulnerabilità nota nelle dipendenze blocca il pacchetto; `-AllowVulnerabilities` va motivato nella RFC.
