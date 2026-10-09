# `security`

Area **SOC IT - CN** · URL `/soc/` · codice [`django_app/security/`](../../django_app/security/)

[← Catalogo moduli nel README](../../README.md#-catalogo-moduli)

## Sintesi

Security Center (Security Center AI innestato): **Panoramica IT** (`/soc/`: verdetto, «Da guardare adesso» dal più grave, riquadro per area con stato e freschezza dati, **sintesi del giorno con l'AI locale**), **registro incidenti NIS2/GDPR** (`/soc/incidenti/`, vedi sotto), **report periodico** con PDF (`/soc/report/`), **sezione Backup** per PC e per job (`/soc/backup/`), **«Spiega con l'AI»** nel dettaglio alert (Ollama aziendale, contesto minimo, cache, registro `SecurityAiInteractionLog`), **analisi** dell'alert («Cosa sappiamo»: storico VPN, asset, backup, precedenti e scartati) e **pagina Analisi** (`/soc/analisi/`: ricorrenti, falsi positivi, scartati, fermi, proposte dell'AI), **risposta** con procedure standard per tipo di alert, prossimi passi e bozza dell'esito proposti dall'AI nel ticket, **caselle mail** da cui arrivano i report (`/soc/admin/mailbox/`: creazione, anteprima senza importare, lettura manuale, **importazione dello storico** da una data; schedule `security_cycle` ogni 15 min), **Eventi** (`/soc/eventi/`: tutti gli eventi letti dai report, anche quelli giudicati a posto, con filtri, grafico per giorno e **promozione ad alert** di un allarme mancato; la promozione crea una **regola appresa** che fa scattare da solo l'alert sugli eventi simili e alimenta l'apprendimento dell'AI locale, che può proporre «è un allarme?»), **KPI per area con dettaglio** (`/soc/kpis/`, `/soc/kpis/<metrica>/`; stati come «computer senza protezione» mai sommati tra giorni, report doppi o sovrapposti contati una volta), **grafici interattivi** (tooltip al passaggio e clic sul giorno in Panoramica, Eventi, Accessi VPN, KPI), **Stato elaborazione** (`/soc/pipeline/`), **cartelle per casella** e Config modificabile, **storico accessi VPN** (`/soc/vpn/`: ogni accesso consentito/negato dei report Firebox, distinto per tipo VPN/Firewall/Guest, con filtri, segnali «Da controllare» e KPI giornalieri), **dispositivi dei report collegati agli asset HUB** (conferma manuale, scheda «Sicurezza e backup» sull'asset), **parser sui formati reali** (WatchGuard Executive Summary/Dashboard/Interface/SD-WAN/Zero-Day, report e mail EPDR, autenticazioni Firebox; Synology Active Backup in italiano; Veeam Backup & Replication), dashboard con **postura e trend calcolati dai dati reali** (`services/posture.py`: nessun valore fisso, «n.d.» se mancano dati), alert/ticket/KPI (**ticket gestibili** `/soc/tickets/<id>/`: responsabile, stato, attività, note e timeline; **azioni massive** sulla coda alert; **chiusura automatica** degli alert quando il problema rientra, disattivabile con `SECURITY_AUTO_RESOLVE_ENABLED`), pipeline parser+regole+KPI sincrona, Configuration Studio (sorgenti/parser/regole/soppressioni/backup/notifiche/ticketing/audit; la pagina **Parser** mostra lo stato reale di ogni parser, prova a secco una mail o un PDF e rielabora gli elementi non elaborati; testo dei **PDF** allegati estratto con pymupdf), **autoconfigurazione** (`/soc/admin/autoconfig/`), diagnostica; task via django-q2; tool AI aggregati (`soc_summary`); FK SecurityAsset↔Asset HUB (`collega_asset_security`). **Notifiche in uscita** email/Teams su alert e ticket, con audit (`SecurityNotificationLog`), cooldown per dedup e consegna fail-safe (`send_security_test_notification` per provare un canale). **Heartbeat sorgenti**: l'assenza di un report oltre la cadenza attesa (`expected_every_hours`) genera un alert, distinguendo "nessun dato" da "scheduler fermo" (`check_security_source_heartbeat`, da schedulare accanto all'ingestione). Provenienza delle mail stabilita **solo dal mittente** (dominio ancorato) con gate opt-in DKIM/SPF; ingestione Graph **incrementale e paginata** (nessun backlog perso); dedup di alert/ticket garantita da indici unici parziali. UI allineata ai token del tema del portale (light/dark, niente tema dark proprietario). L'accesso alla **configurazione** è governato dall'ACL v2 (permesso canonico `security.config.view`, lo stesso applicato dal middleware alle rotte `/soc/admin/config/`); restano validi per compatibilità `is_staff` e il permesso Django `security.manage_security_configuration`. **Autoconfigurazione in UI** (`/soc/admin/autoconfig/`): mostra il piano di configurazione (mancante / difforme dai default / allineato) e semina la base senza shell, in modo **additivo** (il riallineamento ai default è un'azione separata ed esplicita); espone come pulsante le correzioni che la diagnostica sa risolvere da sola (riattivare sorgenti o parser, creare canale notifiche/ticketing, ticket automatici sulle regole critiche, soppressioni scadute), nessuna delle quali cancella dati. I default vivono in un solo posto (`security/services/autoconfig.py`), di cui `manage.py seed_security_center_config` è il wrapper CLI; ogni scrittura è tracciata nel registro audit con l'utente. **Guida operativa integrata e renderizzata in-app**: 13 documenti Markdown (con la *guida di configurazione* al centro) in `django_app/security/guide/`, resi da un renderer interno zero-dipendenze e consultabili da `/soc/security/admin/docs/` → doc singoli (`/soc/docs/<slug>/`, gated); ogni sezione della Configuration Studio ha un help contestuale con link alla guida e alla diagnostica. API DRF/mailbox-admin/AI provider esclusi in questa fase

## Registro incidenti (NIS2 / GDPR)

`/soc/incidenti/` — livello sopra alert e ticket: l'alert è il segnale, il ticket il lavoro tecnico, l'incidente il fatto da ricostruire e, se grave, notificare.

- Codice `INC-AAAA-NNNN`, categoria, gravità, stato (aperto, contenuto, risolto, chiuso), data di rilevazione (momento di conoscenza), responsabile, ticket e alert collegati.
- Valutazione **significatività NIS2** (D.Lgs. 138/2024 art. 25 c. 3, i due criteri), sospetto atto malevolo, impatto transfrontaliero, **dati personali** (GDPR art. 33).
- Scadenze calcolate dalla rilevazione (non salvate: correggendo la data si spostano): pre-notifica CSIRT 24 h, notifica 72 h, relazione finale un mese dalla notifica, Garante 72 h. Stato per scadenza: inviata in tempo, in ritardo, scaduta, in scadenza (entro 12 h), da inviare.
- «Registra invio» con data e protocollo; traccia append-only di ogni modifica (campo vecchio → nuovo) e note.
- Dal ticket: «Apri incidente» (eredita titolo, gravità, alert, responsabile; un solo incidente per ticket). Incidenti registrabili anche senza ticket (furto portatile, mail al destinatario sbagliato).
- Notifiche scadute o in scadenza in testa a «Da guardare adesso» della Panoramica e nel riquadro del registro.
- PDF della scheda incidente (`/soc/incidenti/<id>/pdf/`) e del registro per anno (`/soc/incidenti/registro.pdf?year=AAAA`).
- Servizio: `security/services/incidents.py`; modelli `SecurityIncident`, `SecurityIncidentLog` (migrazione 0019).

## Report periodico

`/soc/report/` — settimana scorsa, mese scorso, ultimi 30 giorni, mese corrente o intervallo libero (max un anno). Postura attuale, alert per gravità con tempo medio di chiusura e più frequenti, backup con job falliti, CVE critiche/alte aperte, accessi VPN (solo conteggi, nessun nome utente), ticket, incidenti del periodo, report elaborati. Pagina e PDF (`/soc/report/pdf/`) usano lo stesso dizionario (`services/periodic_report.py`, PDF in `services/soc_pdf.py`).

## Backup

`/soc/backup/` — dai `BackupJobRecord` già importati (`services/backup_center.py`, nessuna migrazione).

- **KPI** del periodo (7/30/90 giorni): esecuzioni riuscite, PC e server protetti e quanti senza backup riuscito da oltre 3 giorni, job e job attesi non arrivati (`BackupExpectedJobConfig`), dati trasferiti, durata media.
- **Esecuzioni per giorno** (riusciti/con avvisi/falliti) e **Da controllare**: job attesi mancanti, PC con ultimo backup fallito, PC senza backup riuscito recente.
- **Per PC e server**: ultimo esito, ultimo riuscito, striscia delle ultime 14 esecuzioni, % riuscite, GB, durata media, job. **Per job**: esecuzioni, riuscite, dati e durata medi, dispositivi.
- **Log esecuzioni** `/soc/backup/log/` (filtri esito, job, periodo, PC) e **scheda dispositivo** `/soc/backup/dispositivo/?nome=…` (storico, collegamento all'asset HUB se il nome host coincide con un dispositivo SOC collegato).
- Granularità: **Veeam** dà l'esito di ogni macchina (`payload.objects`); **Synology Active Backup** solo quello del job, che i PC del job ereditano (in pagina «esito del job»).

## Impostazioni e avvisi automatici

`/soc/impostazioni/` (Gestione › Impostazioni, modifica con il permesso di configurazione SOC). Tutto **spento di default**; ogni sezione sceglie i canali tra quelli di Config › Notifiche.

- **Scadenze incidenti**: avviso quando una notifica NIS2/GDPR entra nell'anticipo impostato (ore) e quando scade.
- **Backup PC**: avviso per i PC senza backup riuscito oltre la soglia (giorni; la stessa soglia usata dalla pagina Backup) e, se scelto, per l'ultimo backup fallito. Riparte solo dopo un nuovo backup riuscito.
- **Report periodico**: settimanale (lunedì) o mensile (giorno 1), dalle 7; via mail con il PDF allegato, su Teams riassunto e link.
- Motore: `services/proactive_alerts.py`, passo `avvisi` di `security_cycle`; deduplica per canale e stato con `notifications.deliver_once` sul registro `SecurityNotificationLog`. «Esegui i controlli ora» lancia subito i controlli accesi.

## Il mio lavoro, ricerca, scheda PC

- **Il mio lavoro** `/soc/mio-lavoro/`: incidenti di cui sono responsabile (prossima scadenza in alto), ticket assegnati, alert presi in carico.
- **Ricerca** (casella nella barra del SOC, `/soc/cerca/?q=`): incidenti, ticket, alert, PC e server (dispositivi SOC e PC dei backup), vulnerabilità.
- **Scheda PC** `/soc/pc/?nome=…` (`services/pc_overview.py`): verdetto, backup, alert e vulnerabilità aperti, protezione endpoint, eventi, link all'asset HUB. Il nome host è la chiave comune ai fornitori (confronto senza maiuscole).

## Sala controllo: barra live, anteprime, multiselezione, AI

- **Barra di stato** (`services/live_status.py`, cache 60 s, `/soc/stato/` riletta ogni minuto da `static/security/soc-ui.js`): critici e alti, scadenze NIS2, PC backup ko, sorgenti mute, senza responsabile, miei.
- **Anteprima a pannello** (`/soc/anteprima/<tipo>/<id>/`, `/soc/anteprima/pc/?nome=`): righe con `data-preview`; ← → Esc; i form `data-drawer-form` agiscono senza uscire dalla lista.
- **Multiselezione** (`form[data-bulk]` + `soc-ui.js`): ticket `/soc/tickets/bulk/`, incidenti `/soc/incidenti/bulk/`, eventi `/soc/eventi/bulk/`, PC del Backup `/soc/backup/ticket/`; alert come prima; gravità degli alert a scelta multipla.
- **Controlli AI**: `/soc/incidenti/<id>/ai/` e `/soc/pc/ai/` (`ai_explain.check_incident`, `check_pc`), con cache 30 minuti e registro `SecurityAiInteractionLog`.
- **Sezioni vive** (`data-autorefresh`): Panoramica ogni 2-5 minuti, mai mentre si scrive o con righe selezionate. Suggerimenti in pagina chiudibili (`partials/tip.html`).

## Soppressione appresa

Quando lo stesso alert viene **disattivato** più volte a mano, il sistema impara a non disturbare più (`services/learned_suppression.py`).

- **Impronta** dell'alert: sorgente + tipo di evento + campi che identificano il soggetto, mai timestamp, ID o conteggi. Per tipo: backup → job, dispositivo, NAS; CVE (Defender) → CVE, prodotto, organizzazione; candidati WatchGuard → tipo + utente/IP/computer/firewall; VPN → utente/IP; sorgente silenziosa → codice sorgente e motivo; spoofing → vendor dichiarato e dominio. Senza almeno un campo-soggetto (es. solo il «tipo») l'alert non è apprendibile.
- **Disattivazione** = falso positivo, chiusura «Non rilevante» o «Rischio accettato», **Silenzia**: sempre con motivo. «Risolto» e le chiusure automatiche non contano; un'azione massiva (o la chiusura di un caso) conta una volta.
- Alla **3ª disattivazione** nella finestra (90 giorni), se almeno una è di chi ha il permesso di configurazione del SOC, nasce una regola `owner=system:learned` con ambito esatto, motivo che elenca chi/quando/perché, scadenza 180 giorni; audit in `SecurityConfigurationAuditLog` e avviso ai canali scelti (o, se nessuno, a quelli che ricevono i nuovi alert).
- Dalla 4ª occorrenza: nessun alert, l'evento resta in **Eventi soppressi** (`/soc/eventi/?decision=suppressed`) con la regola nel `decision_trace`; `hit_count`/`last_hit_at` aggiornati.
- **Guardrail** (impostazioni, accesi di default): mai per severità critica (anche CVSS ≥ 9), CVE in CISA KEV o non verificabile (catalogo KEV assente o più vecchio di 48 h), minacce/malware/ransomware/botnet; alert comunque se la severità sale oltre quella delle disattivazioni. Riaprire a mano l'alert, o promuovere un evento soppresso, spegne la regola e azzera il conteggio; anche la revoca azzera.
- Pagina **Soppressioni** (`/soc/soppressioni/`): apprese/manuali, attive/in scadenza/scadute, hit, revoca con motivo (permesso di configurazione), ultime disattivazioni. Nel dettaglio alert il badge «2/3 disattivazioni: la prossima creerà una soppressione automatica».
- Impostazioni in `/soc/impostazioni/` › «Soppressione appresa»: on/off, soglia, finestra, durata, guardrail, tipi esclusi, canali.

## Automatismi di rientro

`/soc/admin/config/automatismi/` (permesso di configurazione). Registro in `services/auto_resolution.py`: per ogni regola condizione, prova richiesta, azione; interruttore `autoresolve.<codice>.attivo`. Prima di accendere una regola va eseguita la **simulazione sugli ultimi 30 giorni** (valida 7 giorni): mostra quali alert avrebbe chiuso, senza chiudere nulla.

| Regola | Default | Prova |
| --- | --- | --- |
| Backup tornato a buon fine | accesa | esecuzione completata dello stesso job/dispositivo dopo il fallimento |
| CVE senza più dispositivi esposti | accesa | report successivo con 0 dispositivi esposti |
| Sorgente di nuovo regolare (heartbeat OK) | accesa | report e lettura casella di nuovo nei tempi |
| VPN tornata nei limiti | spenta | N giorni (default 7) sotto soglia **con dati VPN arrivati ogni giorno** |
| CVE con patch installata (inventario) | spenta | impatti recenti: solo versioni fuori range, nessun host da verificare, inventario che copre almeno i dispositivi esposti; mai KEV o critiche |

Ogni chiusura scrive motivo e prova in `status_reason` e nella timeline (`auto_resolved` con `rule`); il caso si chiude solo senza attività aperte.

## Impatto CVE sugli asset

- **Inventario software** (`/soc/admin/config/inventario/`): CSV o XLSX (max 15 MB, 100.000 righe), validato con `validate_extension_and_mime`, tenuto cifrato nello storage privato solo fino all'import (anteprime abbandonate eliminate dopo 2 giorni). Mappatura colonne (hostname, prodotto, versione obbligatorie; vendor, data rilevamento) salvabile come **preset per fonte** (WatchGuard EPDR/Panda, BusinessLog, altro). Anteprima con righe scartate e motivo. Import idempotente (chiave fonte+host+vendor+prodotto+versione); i software spariti dagli host del file diventano «non più rilevati», mai cancellati. Il formato reale degli export non è cablato: si mappa da UI.
- **Normalizzazione e CPE** (`/soc/admin/config/software/`): alias vendor/prodotto modificabili; mappatura verso CPE (vendor:product) con suggerimenti dalle CVE note e, a richiesta, dal dizionario CPE NVD (in coda); vale solo dopo **conferma** di una persona. API key NVD salvata cifrata.
- **Arricchimento** (job `security_cve_enrichment`, ogni ora, spento finché non si accende «Impatto CVE sugli asset» in Impostazioni): NVD CVE API 2.0 (range `versionStart*/versionEnd*`), CISA KEV, EPSS facoltativo; cache dedicata `SecurityExternalFeedCache` (NVD 7 giorni, KEV/EPSS 24 h), timeout 20 s, 3 tentativi con backoff, rate limit 5 req/30 s senza key e 50 con key, budget 90 s per giro. Il ricalcolo degli impatti gira in un task separato.
- **Esiti** per (CVE, host): **Impatta** (prodotto mappato, versione nel range), **Non impatta** (versione fuori range, o prodotto assente da un inventario recente, con la data), **Da verificare** (versione non confrontabile, CPE non confermato, inventario oltre 30 giorni, CVE valida solo su una piattaforma). Ogni esito ha la spiegazione, es. «7-Zip 23.01 installato su PC-XX; vulnerabile < 24.07; fonte: export WatchGuard del gg/mm/aaaa».
- **Dove si vede**: cruscotto `/soc/vulnerabilita/` (CVE ordinate per KEV, CVSS, EPSS, host; asset più esposti; software senza mappatura), dettaglio `/soc/vulnerabilita/<CVE>/`, sezione «Impatto sugli asset» negli alert e nei ticket CVE (con proposta di chiusura, **mai automatica** se KEV o critica), sezione «Vulnerabilità» sulla pagina asset HUB.

## Note di rilascio

- **Registro incidenti, report periodico, parser transazionali** — deploy: `migrate security` (0019). Nuove rotte sotto `/soc/` (stesso binding ACL). Il motore parser salva ogni elemento in una transazione: un errore a metà non lascia più report parziali che bloccavano la rielaborazione; nel `raw_payload` restano parser, tempo (`parse_ms`) ed esito (`parse_outcome`). Pagine alert, ticket, KPI ed Elaborazione controllano il permesso di lettura SOC anche nella view (`soc_view_required`).
- **Sezione Backup** — nessuna migrazione: legge i job di backup già importati.
- **Avvisi automatici, impostazioni, Il mio lavoro, ricerca, scheda PC** — nessuna migrazione. Dopo il deploy: aprire Impostazioni, scegliere i canali e accendere gli avvisi voluti.
- **Sala controllo (barra live, anteprime, multiselezione, controlli AI)** — nessuna migrazione.
- **Soppressione appresa, automatismi di rientro, impatto CVE** — deploy: `migrate security` (0020), `pip install -r requirements.txt` (nuova dipendenza `packaging`), `setup_q_schedules` (nuovo schedule `security_cve_enrichment`, orario). Nuove rotte sotto `/soc/` e `/soc/admin/config/` (stessi binding ACL a prefisso; le view controllano comunque i permessi). Soppressione appresa accesa di default con guardrail; regole di rientro nuove e arricchimento CVE spenti finché non accesi. Serve accesso Internet dal server verso `services.nvd.nist.gov`, `www.cisa.gov`, `api.first.org`.
