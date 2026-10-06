# Contatori MFC & SNMP — migliorie proposte

Stato al 2026-10-06, dopo il rilascio «operatività» (fatture da pagina, letture guidate,
Centrale con KPI «da fare», navigazione per sezioni). Ordine = valore per chi usa il
modulo tutti i giorni. Ogni voce indica se richiede una migrazione.

| # | Miglioria | Priorità | Migrazione | Stato |
|---|-----------|----------|------------|-------|
| 1 | Permessi di modifica separati dalla consultazione | Alta | Sì (dati ACL) | Fatto (2026-10-06) |
| 2 | Storico consumabili con avviso e stima giorni residui | Alta | Sì | Fatto (2026-10-06) |
| 3 | Lettura trimestrale proposta dalle letture mensili | Alta | No | Fatto (2026-10-06) |
| 4 | Costi per copia e anagrafica Contratto | Media | Sì | Da fare |
| 5 | Import fattura da PDF/Excel del fornitore | Media | No | Da fare (serve un esempio reale) |
| 6 | Riepilogo «Da fare» settimanale via email/Teams | Media | No | Da fare |
| 7 | Analisi: filtri periodo/reparto, confronto anno su anno, separatore migliaia | Media | No | Da fare |
| 8 | «Leggi MFC ora» in background (django-q) | Tecnico | No | Da fare |
| 9 | Query aggregate in riconciliazione, cali e ultime letture | Tecnico | No | Da fare |
| 10 | Monitor SNMP: grafico per sonda e notifica su soglia | Tecnico | No | Da fare |

## 1. Permessi di modifica separati

**Problema.** Chiunque acceda al modulo può creare, correggere o eliminare fatture e
letture, cambiare anagrafica stampanti, profili e configurazione SNMP. Inoltre molte
route del modulo (monitor, profili, discovery, fatture, letture) non hanno un binding
ACL v2: con `ACL_STRICT_CANONICAL` attivo in produzione vengono negate ai non superuser.

**Soluzione.**
- Permesso canonico `contatori.gestione.manage` per tutte le scritture (letture,
  fatture, lettura SNMP massiva, anagrafica MFC/dispositivi/sonde/profili, discovery,
  configurazione globale), verificato dentro le view; i pulsanti di modifica spariscono
  per chi non lo ha.
- Binding creati **solo se mancanti** per ogni route del modulo: consultazione su
  `contatori.modulo.view`, pagine di modifica su `contatori.gestione.manage`.
- Grant iniziali che **non tolgono accesso a nessuno**: `contatori.modulo.view` a chi
  già vede la Centrale; `contatori.gestione.manage` a chi già poteva modificare le MFC
  (`contatori.macchina.edit`). Dopo il deploy l'amministratore restringe da
  *Accessi* chi deve restare in sola lettura.

## 2. Storico consumabili con avviso

**Problema.** I consumabili si leggono solo in diretta: nessuno storico, nessun avviso,
la Centrale non può mostrarli senza interrogare tutte le stampanti.

**Soluzione.**
- Modello `LetturaConsumabile` (MFC, consumabile, %, rilevata il).
- Task django-q giornaliero che legge e salva i livelli delle MFC attive con IP.
- Stima giorni residui dal consumo medio degli ultimi giorni.
- Voce «Da fare» in Centrale per i consumabili sotto il 15% (dato salvato, nessuna
  interrogazione all'apertura); pagina Consumabili con ultimo valore salvato e stima.

## 3. Lettura trimestrale proposta dalle mensili

**Problema.** Le letture mensili SNMP esistono già ma la lettura trimestrale va inserita
a mano o con «Leggi MFC ora».

**Soluzione.** Per il trimestre senza lettura il portale propone come lettura quella
mensile più vicina alla chiusura del trimestre (fonte SNMP, data reale della rilevazione).
L'operatore conferma con un clic, singolarmente o in blocco dalla Centrale. Nessuna
scrittura automatica: la proposta va sempre confermata.

## 4. Costi per copia e anagrafica Contratto

Prezzi per copia (B/N, colore, A3) e canone per contratto; costo per trimestre e per
reparto in Analisi; eccesso fatturato espresso in euro in riconciliazione. Il contratto
diventa un'anagrafica (fornitore, canone, copie incluse, scadenza) al posto del testo
libero sulla MFC.

## 5. Import fattura da file

Caricamento del PDF/Excel del fornitore con estrazione delle righe per contratto e
precompilazione della pagina fattura. Prerequisito: un esempio reale (anonimizzato)
del formato fattura.

## 6. Riepilogo settimanale

Invio dell'elenco «Da fare» della Centrale al responsabile (email o Teams), solo se
non vuoto, con link diretti.

## 7. Analisi

Filtri per periodo e reparto, confronto con lo stesso trimestre dell'anno precedente,
separatore delle migliaia nei numeri.

## 8–10. Tecnico

- «Leggi MFC ora» come job django-q con avanzamento, per non rischiare timeout con molte
  stampanti spente.
- Riconciliazione, controllo cali e ultime letture con query aggregate invece di una
  query per macchina.
- Monitor SNMP: grafico nel tempo per ogni sonda e notifica al superamento soglia.
