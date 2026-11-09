# Governance dei rilasci NOVICROM HUB (ISO/IEC 27001:2022, A.8.32)

Questa cartella contiene i modelli e i registri che accompagnano ogni rilascio in produzione, secondo la procedura interna MT CN 275 «Gestione dei progetti e dei cambiamenti» e il modulo MOD.172 (Request For Change). I documenti del Sistema di Gestione Integrato restano in Arxivar; qui ci sono solo le evidenze operative che nascono nel repository.

| File | A cosa serve | Quando si compila |
|---|---|---|
| [CATALOGO_CAMBI.md](CATALOGO_CAMBI.md) | Classifica i cambiamenti dell'HUB in standard, normali ed emergenza (MT CN 275 par. 9.1) | Si consulta a ogni RFC; si aggiorna quando nasce un tipo di cambio nuovo |
| [REGISTRO_RFC.md](REGISTRO_RFC.md) | Una riga per ogni RFC: numero, versione, commit, stato, autorizzazione, chiusura | Apertura RFC, autorizzazione, rilascio, chiusura |
| [CHECKLIST_GOLIVE.md](CHECKLIST_GOLIVE.md) | Passi prima, durante e dopo il deploy in PROD con data, esecutore ed esito (A.8.19) | A ogni rilascio in PROD, copiata nella cartella della release |
| [VERBALE_COLLAUDO_TEMPLATE.md](VERBALE_COLLAUDO_TEMPLATE.md) | Protocollo e verbale del collaudo su TEST per modulo (A.8.29) | Prima dell'autorizzazione al go-live |
| [RIESAME_POST_RILASCIO_TEMPLATE.md](RIESAME_POST_RILASCIO_TEMPLATE.md) | Riesame dopo tre giorni lavorativi: anomalie, rollback, lezioni apprese | Alla chiusura della RFC, obbligatorio se il rilascio ha migrazioni o moduli nuovi |
| [AUTORIZZAZIONE_COPIA_PROD_TEST_TEMPLATE.md](AUTORIZZAZIONE_COPIA_PROD_TEST_TEMPLATE.md) | Autorizzazione scritta per copiare dati di produzione in TEST o DEV (A.8.33) | Prima di ogni copia; la copia va anonimizzata con `ripristina-copia-anonima.ps1` |
| [AMBIENTE_TEST.md](AMBIENTE_TEST.md) | Stato e procedura per l'ambiente TEST su NOVISQL (A.8.31) | Quando si crea o si riallinea TEST |

## Flusso di un rilascio ordinario

1. **Apertura**: RFC MOD.172 compilata dal Titolare del progetto con l'elenco dei cambiamenti (CHANGELOG `[Unreleased]` raggruppato per area), rischi P x D, protocollo di test, piano di ripristino. Riga «aperta» nel registro.
2. **Valutazione**: il CISO compila la propria sezione del MOD.172; la Governance autorizza. Riga «autorizzata» nel registro con data e riferimento (mail o firma).
3. **Sviluppo e versione**: bump secondo la checklist di `docs/ai/06`, sezione `## X.Y.Z - data` nel CHANGELOG, merge feature -> main -> release/prod.
4. **Pacchetto**: `deployment\scripts\package-release.ps1` senza `-SourcePath` né `-FromWorkingTree`: il pacchetto nasce dal commit di `release/prod` e `BUILD_INFO.json` lo riporta. Il release guard blocca versioni disallineate, segreti, scoperture ACL e vulnerabilità note nelle dipendenze.
5. **Collaudo**: deploy su TEST, verbale di collaudo firmato dai responsabili di modulo.
6. **Rilascio**: checklist go-live; `deploy-release.ps1` e `activate-release.ps1` (o SetupWizard) fuori orario; tag `prod-vX.Y.Z` sul commit di `current\BUILD_INFO.json`. Riga «rilasciata» nel registro.
7. **Chiusura**: dopo tre giorni lavorativi senza anomalie bloccanti, riesame post-rilascio e riga «chiusa».

## Cambiamenti urgenti

Un hotfix o un rilascio fatto prima dell'autorizzazione formale (par. 9.3.7 di MT CN 275) va registrato **entro un giorno lavorativo**: riga nel registro con categoria «Emergenza» o «Urgente», RFC compilata a posteriori, analisi nel riesame post-rilascio.

## Evidenze conservate

MOD.172 compilato (OneDrive, cartella `Documenti/Portale Novicrom/ISO27001_Change_Management_HUB`), registro RFC, sezione CHANGELOG, `BUILD_INFO.json` della release attiva, log di `package-release.ps1` e del deploy, verbale di collaudo, checklist go-live, tag Git. Nessuno di questi documenti contiene dati personali: si usano ruoli (IT Officer, CISO, Governance, Responsabile di modulo), non nomi.
