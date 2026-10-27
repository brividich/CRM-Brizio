# Conformità ISO 27001

Il SOC verifica da solo i controlli dell'Annex A della **ISO/IEC 27001:2022** che copre con i suoi dati e, ogni mese, archivia un **pacchetto di evidenze** in PDF per il riesame. Niente da compilare: le pagine del SOC restano quelle di sempre, questa le legge.

Si apre dal menu del SOC: **Report › Conformità ISO 27001**.

## La pagina

In alto il **periodo** (mese corrente, mese scorso, ultimi 3 mesi, ultimi 12 mesi, intervallo libero fino a un anno) e il riepilogo: quanti controlli sono **non conformi**, **da guardare**, **conformi**, con **dato non disponibile**.

Sotto, **Da sistemare** elenca i controlli che non sono conformi, dal più grave. Poi un **riquadro per controllo**, raggruppati per area (Minacce e vulnerabilità, Incidenti, Continuità, Log e monitoraggio, Riesame):

- **Cosa si aspetta l'audit**: la frase che un auditor chiederebbe di dimostrare.
- **L'esito** calcolato e la frase che lo spiega.
- **I numeri** su cui si basa, con le tabelle di dettaglio apribili.
- **Cosa fare**: le azioni concrete quando qualcosa manca.
- **Evidenze**: i collegamenti alle pagine del SOC dove un auditor vede i dati (Letture automatiche, Vulnerabilità, Backup, Archivio e integrità…).

Gli esiti sono **prudenti**: un dato che manca non vale mai come conforme. «Dato non disponibile» vuol dire che il SOC non ha la fonte (lettura spenta, servizio non installato, nessun dispositivo visto), non che il controllo è a posto.

## I controlli e come si verificano

| Controllo | Cosa guarda | Conforme quando | Non conforme quando |
| --- | --- | --- | --- |
| **5.7** Threat intelligence | Lettura «CVE: NVD, CISA KEV, EPSS» | Accesa, ultimo giro riuscito da meno di 24 ore, tutti i giri del periodo riusciti | Lettura spenta o mai riuscita |
| **8.8** Vulnerabilità tecniche | Tempi di correzione per classe (servizio `cve_sla`), correzioni e giorni medi (pagina Vulnerabilità) | Almeno il 90% delle CVE corrette nei tempi e nessuna esposizione oltre il termine | Esposizioni scadute senza accettazione del rischio, o meno del 70% nei tempi |
| **8.7** Protezione da malware | Dispositivi visti dal SOC con WatchGuard o Defender; stato della protezione WatchGuard | 100% dei dispositivi coperti, protezione attiva su tutti | Sotto il 90% di copertura |
| **6.8** Segnalazione degli eventi | Canale di segnalazione scritto in Impostazioni › Avvisi e automatismi › «Conformità ISO 27001» | Canale definito | — (vuoto = «da definire», da guardare) |
| **5.24** Pianificazione incidenti | Ruoli della gestione incidenti (servizio `iso_incidenti`) | Tutti i ruoli assegnati | Ruoli senza persona |
| **5.25** Valutazione e decisione | Presa in carico delle segnalazioni entro il tempo scelto | Tutte in tempo | Segnalazioni mai prese in carico |
| **5.26** Risposta | Azioni di risposta degli incidenti | Nessuna azione scaduta | Azioni oltre la scadenza |
| **5.27** Imparare dagli incidenti | «Lezioni apprese» negli incidenti chiusi | Tutti i chiusi con riesame | Incidenti chiusi senza lezioni apprese |
| **5.28** Raccolta delle evidenze | Evidenze degli incidenti con impronta | Tutte verificate | Evidenze alterate |
| **8.13** Backup | Esiti dei job nel periodo e dispositivi mai visti in un backup | Nessun job fallito, tutti i dispositivi con backup | Più del 10% di job falliti |
| **5.30** Prontezza per la continuità | Test di ripristino registrati | Ultimo test riuscito e non in ritardo | Nessun test o ultimo test fallito |
| **8.15** Logging | Registro accessi: giorni sigillati, verifiche d'integrità, interruzioni | Tutti i giorni sigillati e integri, interruzioni giustificate | Raccolta spenta o sigilli non integri |
| **8.16** Monitoraggio | Battito del SOC e giri riusciti sui giri attesi (dagli schedule) | Almeno il 95% dei giri attesi e nessun componente da sistemare | Coda dei lavori ferma o meno dell'80% dei giri |
| **8.17** Orologi | Scarto tra l'ora dei messaggi syslog e quella di ricezione (Registro accessi › Fonti) | Scarto massimo entro 60 s | Oltre 300 s |
| **9.1** Misurazione | Pacchetti mensili archiviati | Gli ultimi 3 mesi hanno il pacchetto | — (mancanti = da guardare) |

Le soglie sono quelle scritte nel codice (`security/services/iso27001.py`): se cambiano, cambia anche questa tabella.

## Il pacchetto mensile di evidenze

Il **giorno 1 di ogni mese alle 06:30** il SOC genera da solo il PDF **«Evidenze SOC – ISO/IEC 27001 – <mese>»** del mese prima (lettura «Pacchetto evidenze ISO 27001» in Letture automatiche e nel Battito del SOC). Chi ha il permesso di configurazione del SOC può generarlo anche a mano con **Genera ora**, per il periodo scelto in alto.

Il PDF contiene:

1. **Copertina** con periodo, data di generazione e conteggi per stato.
2. **Sintesi per controllo** (tabella).
3. **Un capitolo per controllo** con esito, numeri, tabelle e azioni aperte.
4. **Allegato A**: le vulnerabilità corrette nel periodo, un PC per riga (CVE, PC, programma, versione prima e dopo, evidenza, esposto dal, corretto il, giorni).
5. **Allegato B**: le esposizioni oltre il termine, con rischio accettato o no.
6. **Allegato C**: gli incidenti rilevati o chiusi nel periodo, con lo stato delle lezioni apprese.

Ogni pacchetto resta nell'**archivio privato** del portale con la sua **impronta SHA-256**, scritta anche nell'audit del portale (`pacchetto_iso_generato`): chi conserva una copia può verificare che sia quella generata. Ogni download è registrato (`pacchetto_iso_scaricato`). L'elenco dei pacchetti è in fondo alla pagina, con il periodo, chi l'ha generato (o «automatico»), i conteggi e il pulsante **Scarica PDF**. Un pacchetto già presente non viene sovrascritto.

Con **Copia il pacchetto mensile nella cartella SharePoint dell'audit** acceso (Impostazioni › Avvisi e automatismi › «Conformità ISO 27001») il PDF va anche nella cartella SharePoint delle esportazioni dell'audit (Centrale di comando › Audit), sottocartella `soc-iso27001/<anno>`. Spento di serie.

## Cosa resta da fare a mano

Il SOC verifica quello che vede. Per l'audit servono anche cose che nessun automatismo può fare:

- **Scrivere il canale di segnalazione** (6.8) e comunicarlo al personale, conservando la comunicazione.
- **Assegnare i ruoli** della gestione incidenti (5.24) e tenerli aggiornati quando cambiano le persone.
- **Fare i test di ripristino** (5.30) e registrarli: il SOC vede solo quelli registrati.
- **Accettare formalmente il rischio** delle vulnerabilità che non si possono correggere (8.8), con motivo e scadenza.
- **Giustificare le interruzioni** della raccolta dei log (8.15) in Archivio e integrità.
- **Documentare la sincronizzazione dell'ora dei server Windows** (8.17): il SOC misura lo scarto solo sulle fonti syslog.
- **Il riesame della direzione** (9.3): il pacchetto mensile è l'input, il verbale lo scrive la direzione.
- **Lo Statement of Applicability** e la valutazione dei rischi restano nel modulo Sistema di gestione.
