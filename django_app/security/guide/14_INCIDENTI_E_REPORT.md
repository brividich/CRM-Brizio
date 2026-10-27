# Incidenti e report

Il registro incidenti serve a ricostruire i fatti gravi e a rispettare le scadenze di notifica NIS2 e GDPR. Il report periodico riassume l'andamento per la direzione e per gli audit.

## Alert, ticket, incidente: la differenza

| | Cos'è | Esempio |
| --- | --- | --- |
| **Alert** | Il segnale che qualcosa non va | 12 accessi VPN negati dallo stesso IP |
| **Ticket** | Il lavoro tecnico per sistemarlo | Bloccare l'IP, controllare l'utente |
| **Incidente** | Il fatto che ha avuto, o poteva avere, un impatto reale e va documentato | Accesso riuscito con credenziali rubate |

Non ogni ticket diventa un incidente. Un incidente si può registrare anche senza alert né ticket: un portatile rubato, una mail con dati personali mandata al destinatario sbagliato.

## Registrare un incidente

- **Dal ticket**: **Apri incidente**. L'incidente eredita titolo, gravità, alert collegati e responsabile. Un ticket può avere un solo incidente.
- **Da zero**: **Incidenti › Registra incidente**.

Nel modulo compili tre parti:

1. **Cosa è successo**: titolo, categoria, gravità, descrizione, la **data di rilevazione** (il momento in cui l'azienda ne è venuta a conoscenza) e, se nota, la data in cui è avvenuto.
2. **Valutazione NIS2 e GDPR**: se è **significativo** ai fini NIS2 (D.Lgs. 138/2024: basta uno dei due criteri), se si sospetta un atto malevolo, se ha impatto transfrontaliero, se coinvolge **dati personali**.
3. **Impatto e gestione**: servizi e utenti coinvolti, impatto, causa, misure adottate, lezioni apprese. Si può completare dopo.

Nel dubbio conviene valutarlo **significativo**: la pre-notifica entro 24 ore si può ritirare, il ritardo no.

## Le scadenze

Le scadenze partono dalla **data di rilevazione**. Se correggi la data, le scadenze si spostano.

| Notifica | A chi | Entro | Quando serve |
| --- | --- | --- | --- |
| Pre-notifica | CSIRT Italia | 24 ore dalla rilevazione | Incidente significativo NIS2 |
| Notifica | CSIRT Italia | 72 ore dalla rilevazione | Incidente significativo NIS2 |
| Relazione finale | CSIRT Italia | 1 mese dalla notifica | Incidente significativo NIS2 |
| Notifica violazione | Garante privacy | 72 ore dalla rilevazione | Dati personali coinvolti |

Ogni scadenza ha uno stato: **da inviare**, **in scadenza** (entro 12 ore), **scaduta**, **inviata in tempo** o **in ritardo**. Le notifiche scadute o in scadenza compaiono:

- in testa a **Da guardare adesso** nella Panoramica;
- nella barra di stato (scadenze NIS2);
- nel riquadro **Notifiche da inviare** in cima al registro;
- come avviso su mail o Teams, se acceso in [Impostazioni](/soc/docs/16-impostazioni-e-ai/#avvisi-automatici).

Quando hai inviato una notifica, nella scheda dell'incidente premi **Registra l'invio**, indica data e **protocollo** e conferma. Se hai sbagliato, **Annulla data di invio**.

## Seguire l'incidente

- **Stato**: aperto, contenuto, risolto, chiuso.
- **Ticket e alert collegati**: **Collega ticket** aggiunge altri ticket.
- **Traccia**: ogni modifica (campo, valore vecchio, valore nuovo, chi e quando) e ogni nota restano registrate e non si cancellano. È la prova per gli audit.
- **Controlla l'incidente**: l'AI aziendale verifica cosa manca per notifiche e audit, lo stato delle scadenze e propone i prossimi passi.
- **Scarica scheda PDF**: la scheda completa da allegare o archiviare.

Nel registro si filtra per stato, ambito (significativi NIS2, con dati personali) e anno. **Scarica registro PDF** produce il registro dell'anno scelto. Con la selezione multipla si può diventare responsabili o cambiare stato a più incidenti insieme.

## Lezioni apprese e azioni correttive

Quando un incidente è **risolto** o **chiuso**, nella scheda va compilato il riquadro **Lezioni apprese**: la **causa** (obbligatoria), cosa ha funzionato, cosa migliorare. È il riesame che la norma ISO/IEC 27001 chiede dopo ogni incidente (controllo 5.27: imparare dagli incidenti). La chiusura non viene bloccata: finché il riesame manca, l'incidente mostra **Riesame mancante** (nel registro e nella scheda) e, dopo i giorni impostati (7 di default), parte un promemoria sui canali scelti in [Impostazioni](/soc/docs/16-impostazioni-e-ai/#avvisi-automatici). Il riesame finisce anche nel campo «Lezioni apprese» e nella scheda PDF.

Le **azioni correttive** (es. «MFA su tutti gli account VPN») hanno un responsabile e una scadenza: **Segna fatta** quando è conclusa. Un'azione scaduta e non fatta è **In ritardo** e riceve un promemoria (uno nei 3 giorni prima della scadenza, uno quando è scaduta). Tutto resta nella traccia dell'incidente.

## Ruoli e contatti per gli incidenti

La scheda dell'incidente e il PDF riportano **chi fa cosa** quando succede un incidente (ISO 27001 5.24: prepararsi prima): responsabile degli incidenti, sostituto, contatto CSIRT Italia / ACN per le notifiche NIS2, fornitore IT di supporto. Si scrivono una volta in **Impostazioni › Gestione degli incidenti**; se mancano, la scheda mostra **Da completare**.

## Tempi di presa in carico degli alert

Ogni alert va **preso in carico** da una persona entro un tempo che dipende dalla gravità (ISO 27001 5.25 e 5.26): critica **1 ora**, alta **4 ore**, media e attenzione **24 ore**, bassa e info **72 ore**; la chiusura è attesa entro **30 giorni**. I tempi si cambiano in Impostazioni. Conta la prima azione di una persona nella timeline dell'alert (presa in carico, chiusura, rinvio, silenzio, falso positivo): le azioni automatiche del sistema non contano.

- Un alert mai preso in carico oltre il tempo mostra **oltre il tempo di presa in carico** nell'elenco e nella scheda; con gli avvisi accesi parte **un** avviso per alert (si ferma da solo quando qualcuno lo prende in carico).
- La scheda dell'alert riporta quando è stato preso in carico, in quante ore rispetto all'obiettivo, e il tempo di risoluzione quando è chiuso.

## Integrità delle evidenze

Ogni contenitore di evidenze di un alert viene **sigillato** alla nascita con un'impronta SHA-256 del contenuto (ISO 27001 5.28: le prove devono restare quelle). Nella scheda dell'alert, tabella **Evidenze correlate**: **Verifica integrità** ricalcola l'impronta e dice **Integra** o **Alterata**; **Esporta** scarica il contenitore in JSON con impronta e **catena di custodia** (chi l'ha creato, sigillato, guardato, esportato, verificato). Ogni verifica ed esportazione resta anche nel registro audit del portale. I contenitori nati prima di questa funzione vengono sigillati dal ciclo automatico.

## Report periodico

**Report** mostra l'andamento di un periodo: settimana scorsa, mese scorso, ultimi 30 giorni, mese corrente o un intervallo libero fino a un anno.

Contiene:

- alert creati, ancora aperti e **tempo medio di chiusura**;
- **backup** riusciti, con avvisi e falliti, con l'elenco dei job falliti;
- **CVE critiche e alte** aperte con dispositivi esposti;
- **postura attuale** per area, con indice e giudizio (passa sopra una riga per vedere la formula);
- alert per gravità e i più frequenti;
- accessi VPN consentiti e negati (solo numeri, **nessun nome utente**), ticket aperti e chiusi, report elaborati;
- incidenti del periodo con le scadenze mancate.

**Scarica PDF** produce lo stesso contenuto della pagina, pensato per la direzione e per gli audit: niente nomi utente, niente contenuto delle mail. Il report può partire da solo ogni settimana o ogni mese: vedi [Impostazioni](/soc/docs/16-impostazioni-e-ai/#avvisi-automatici).
