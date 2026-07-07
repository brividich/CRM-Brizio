# NOVICROM HUB — Automazioni e Intelligenza Artificiale

## Automazioni

L'obiettivo è **ridurre il lavoro manuale ripetitivo** e rendere i processi affidabili.

- **Designer visuale dei flussi**: i processi si disegnano a blocchi, senza scrivere codice — eventi,
  condizioni, notifiche, approvazioni.
- **Approvazioni portabili e affidabili**: le richieste di approvazione possono arrivare via email o Teams,
  sono **deduplicate** (niente doppioni) e **fail-closed** (in caso di dubbio non approvano da sole).
- **Innesto sui dati esistenti**: i flussi reagiscono ai cambiamenti nel database aziendale e alla
  **casella di posta** (Microsoft Graph), collegando ciò che già succede in azienda.

Valore: meno passaggi manuali, meno errori, processi che "si ricordano" i passi da fare.

---

## Intelligenza Artificiale — privata e on-premise

Il punto distintivo: l'AI di NOVICROM HUB **gira sui server aziendali**, non su servizi cloud di terzi.

### Principi

- **On-premise**: i dati **non escono** dall'azienda; nessun abbonamento a servizi AI esterni.
- **"L'AI propone, l'umano firma"**: l'AI non salva nulla in automatico e non prende decisioni al posto
  delle persone — suggerisce, la persona rivede e conferma.
- **Rispetta gli accessi**: l'AI vede **solo** ciò che l'utente collegato può vedere; ogni utilizzo è
  tracciato a livello di metadati tecnici, **mai** i contenuti delle conversazioni.

### Cosa sa fare (in ottica di valore)

- **Assistente con risposte citate**: risponde a domande su procedure e specifiche indicando la **fonte
  esatta** (es. «MT CN 06 Rev.7, paragrafo 4.2»), invece di inventare. Se non trova la risposta nei
  documenti, lo dichiara.
- **Copiloti per modulo**: propone il triage di un ticket (categoria, priorità), il set di DPI corretto
  a partire dalla mansione, o la bozza di compilazione del MOD.133 — sempre da approvare.
- **Supporto ai carichi macchina**: stima durate e macchina probabile, segnala rischi di ritardo e
  colli di bottiglia, con spiegazione.
- **Domande operative**: "cosa devo fare oggi?", "chi è assente domani?", "chi è abilitato su questa
  macchina?" — con risposte filtrate dai permessi dell'utente.
- **Report PDF** generati su richiesta, ancorati alle sole fonti autorizzate e marcati come bozza.

### Perché è importante per la direzione

- **Riservatezza**: know-how, specifiche e dati HR restano dentro il perimetro aziendale.
- **Affidabilità**: l'AI cita le fonti e ammette quando non sa, riducendo il rischio di risposte inventate.
- **Governance**: esiste una console che regola quali dati ogni funzione AI può usare, con revisione privacy.
