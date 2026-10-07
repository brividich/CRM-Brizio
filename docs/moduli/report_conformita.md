# `report_conformita` — report per audit ISO 9001 / EN 9100 / ISO 45001 / ISO 27001

Area **Qualità** · URL `/report-conformita/` · codice [`django_app/report_conformita/`](../../django_app/report_conformita/)

[← Catalogo moduli nel README](../../README.md#-catalogo-moduli)

## Sintesi

**Report conformità** per audit **ISO 9001, EN 9100, ISO 45001, ISO 27001**: 16 report di sola lettura, incluso «Audit interni» (programma, rilievi, tempi di chiusura e qualifica auditor), consultabili a video e scaricabili in **PDF ed Excel** con riferimenti normativi, periodo e indicatori; **pacchetto riesame della direzione** (PDF unico con gli indicatori). ACL per area, download tracciati in audit

## Dettaglio

Sezione trasversale (`/report-conformita/`, menu **Qualità**) che raccoglie le evidenze documentali chieste agli audit, calcolate dai dati già presenti nei moduli. Nessun modello e nessuna migration: ogni report è una funzione di sola lettura registrata in `report_conformita/reports/` (`registry.register(ReportDef(...))`), che restituisce indicatori + tabella + note; lo stesso risultato alimenta la pagina web, il **PDF** (template HUB, orizzontale, righe critiche evidenziate) e l'**Excel** (foglio «Indicatori» con riferimenti normativi e foglio «Dati»), così i numeri non divergono fra schermo e file.

| Area (permesso) | Report | Riferimenti principali |
|---|---|---|
| Qualità e processi (`report_conformita.qualita.view`) | Non conformità e azioni di miglioramento · Albo fornitori · Strumenti e verifiche periodiche · Presa visione procedure · Manutenzione · Audit interni | 9001 §9.2/§10.2, §8.4.1, §7.1.5, §7.3/7.5.3, §7.1.3 · 9100 §9.2.2, §8.4.1, §7.1.5.2, §8.1.2 |
| Competenze e qualifiche (`report_conformita.persone.view`) | Formazione obbligatoria e qualifiche · Processi speciali e personale abilitato · Efficacia della formazione | §7.2 di tutte le norme · 9100 §8.5.1.2 |
| Salute e sicurezza (`report_conformita.sicurezza.view`) | Infortuni, quasi infortuni e situazioni pericolose · DPI · Scadenziario degli obblighi di legge | 45001 §9.1.1, §10.2, §8.1.2, §6.1.3, §9.1.2 |
| Sicurezza delle informazioni (`report_conformita.it.view`) | Inventario asset IT · Licenze software · Revisione degli accessi · Backup, vulnerabilità e rimedi | 27001 A.5.9, A.5.32, A.5.15–5.18, A.6.5, A.8.5, A.8.8, A.8.13 |

- **Riesame della direzione** (`/report-conformita/riesame/`): gli indicatori di tutti i report delle aree consentite, sul periodo scelto, in pagina e in un unico PDF (dati di ingresso §9.3). Solo indicatori: il dettaglio nominativo resta nei singoli report.
- **ACL**: `report_conformita.modulo.view` per l'accesso (binding sulle 3 route) + un permesso per area verificato nella view, fail-closed. Default: admin tutte le aree; qualità: qualità, competenze, sicurezza; amministrazione: qualità; HR: competenze. L'area IT va assegnata a mano.
- **Calcolo condiviso con la reportistica di anagrafica**: «Formazione obbligatoria e qualifiche» e la riga formazione dello scadenziario legale usano `anagrafica/reportistica/calcoli.py` (requisiti da mansione, area, ruoli, regole in vigore, processi; stato alla data, non la cache `TrainingDeadline`); qualifiche correnti per persona e tipo anche sulle anagrafiche doppie; visite dello scadenziario solo del personale in forza. `people.cessati_ids` usa la stessa regola di «in forza» della reportistica (spenti nel legacy, riassunti, id dei doppioni).
- **Privacy**: lo scadenziario legale mostra solo conteggi (visite mediche comprese, mai esiti); gli eventi di sicurezza non riportano il segnalante; i report nominativi usano solo nominativo e reparto, dipendenti cessati esclusi dove non rilevanti.
- **Audit**: ogni download PDF/Excel registra `report_conformita_download` con report, formato e periodo.
- **Filtri**: periodo (default ultimi 12 mesi) per i report di flusso; i report «situazione» sono alla data odierna. Parametri non ammessi vengono ignorati.
- **Limiti noti** (dati non ancora presenti nel portale): audit interni, consegne puntuali (OTD) per EN 9100, indici infortunistici (servono ore lavorate e giorni di prognosi), FAI / contraffazione / FOD. La dichiarazione di applicabilità ISO 27001 è ora nel modulo `sistema_gestione` (report «Dichiarazione di applicabilità»).
