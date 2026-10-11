# Report conformita: dati, fonti e rettifiche

La pagina `/report-conformita/<slug>/dati/` si apre da **Dati e fonti** in ogni report. Mostra la stessa estrazione del report, provenienza di tutte le colonne, note dei criteri, indicatori, collegamenti alle schede o ai registri sorgente e storico paginato. Le sorgenti si correggono nei loro moduli con i permessi e i flussi esistenti (incluse revisioni approvate e integrazioni).

Le rettifiche del solo report richiedono accesso al modulo, all'area e `report_conformita.rettifiche.edit`. Il nuovo grant e' create-only, abilitato per admin per impostazione iniziale; la consultazione non concede scrittura. Il binding della nuova route usa il permesso modulo, con secondo controllo server-side area/scrittura nella view. Nessun permesso sulle sorgenti viene ampliato.

`ReportCorrection` conserva ogni operazione in una nuova revisione, inclusi i ripristini. Identita' stabile modello/PK per righe singole; categoria/ambito per aggregati; etichetta per KPI. La chiave della colonna e' il titolo, non la posizione della riga. Scope normalizzato: periodo + filtri per report temporali; soli filtri per report di situazione. Il valore originale e' confrontato a ogni lettura: una rettifica su un valore cambiato e' sospesa, con avviso, finche' non viene verificata e salvata nuovamente (oppure il valore sorgente torna identico). I record non piu' inclusi non ricevono rettifiche; il loro storico rimane consultabile nello stesso scope.

Le rettifiche sono valori di presentazione, anche per KPI: non scrivono nei modelli sorgente, non ricalcolano formule dipendenti o semafori di riga. I KPI rettificati hanno tono di attenzione e valore originale nella nota. Il report, PDF e XLSX elencano originale, valore rettificato, motivo, autore e data; la vista web marca le celle. Il riesame riporta solo rettifiche degli indicatori, senza reintrodurre le righe nominative attraverso le note.

I POST richiedono CSRF, target appartenente all'estrazione e token firmato con scope, target, valore sorgente e revisione precedente, valido due ore. Il vincolo univoco sulla revisione impedisce sovrascritture concorrenti. Le operazioni sono anche registrate in AuditLog senza duplicare i valori nel payload generale; autore/data/motivazione restano nel registro dedicato. Nessuna cancellazione o modifica dello storico esposta nella UI.

Per aggiungere un report: dichiarare origine/calcolo delle colonne in `sources.COLUMN_SOURCES`, fornire `source=obj` o una `key` stabile per ogni `add_row`, e un collegamento sorgente dove disponibile. La view limita le azioni visibili con `acl_allows_path`; gli endpoint sorgente restano autoritativi. Non accettare nomi modello/campo o URL arbitrari dal client.

## Deploy e controlli

- Applicare `python manage.py migrate report_conformita --settings=config.settings.prod` e riavviare il processo web; il bootstrap ACL v2 registra permesso e binding nuovi.
- Attribuire il permesso di rettifica ai ruoli non admin solo se desiderato tramite ACL canonico.
- Test mirati: `python manage.py test report_conformita --settings=config.settings.test --keepdb`.
- Rilascio documentato in Unreleased: nessun bump globale o modifica ai file di ambiente.
- Collaudare su SQL Server e sui ruoli reali prima del rilascio; nessun dato di produzione usato nei test.
