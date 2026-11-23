<!-- Scheda tecnica: tre pagine. Il dettaglio è in 01_asis.md, 02_tobe_flusso_algoritmo.md, 03_ux.md, 04_gap_sgi.md. -->

# Ruoli, mansioni e competenze: scheda tecnica

## La proposta in sei punti

1. **Due atti, due effetti.** La Sessione Formativa (SF) cambia ciò che la persona sa fare; la Richiesta di
   Aggiornamento Mansione (RAM) ciò che è autorizzata a fare. Nessun'altra via scrive livelli o mansioni.
2. **Il livello è un giudizio, la validità è un calcolo.** Il livello lo dà il capo reparto in una SF e non cambia da
   solo. Il portale calcola ogni giorno se è ancora valido e lo segnala; blocca solo sui controlli non distruttivi.
3. **Livelli solo dove servono.** Competenze generiche a «sì o no», livelli sulle specifiche: il carico di
   valutazione resta quello di oggi invece di moltiplicarsi per 2,6.
4. **Un solo motore** dice, per ogni persona, che cosa è richiesto e perché, che cosa possiede, che cosa manca, che
   cosa potrebbe fare in più.
5. **Assegnazione in due passaggi**: avviata (in formazione, non firma), poi effettiva.
6. **Emissione firmata**: ogni sei mesi RDD firma la fotografia della skill matrix, come chiede MT CN 06.

## Che cosa si riusa

| Esiste già | Diventa |
| --- | --- |
| Catalogo mansioni, livelli I/L/U/O, storici | Restano; il livello passa dalla mansione alla competenza |
| Motore unico dei requisiti di sicurezza (`services/requisiti.py`) | Resta; si affianca il motore delle competenze |
| Ricalcolo automatico del livello (`services/competenze_ricalcolo.py`) | Diventa calcolo della validità: non scrive più livelli |
| Pratica di inserimento, cambio mansione | Si agganciano alla RAM |
| Edizioni dei corsi, MOD.040 | L'edizione di un corso «formativo» prepara una SF |
| Registro timbri (`timbri/models.py:84`) | «Può firmare» = timbro attivo e mansione effettiva da livello L |
| Conferma del capo reparto (`services/skillmatrix_refresh.py`) | Dichiara anche il mancato esercizio |

**Dati.** Ciò che oggi è nel portale per skill matrix e mansionario è un caricamento di prova: all'avvio si caricano
la skill matrix firmata (MOD.187) e la bozza della Qualità (253 mansioni, 208 competenze), che sostituisce la tabella
del MOD.053. Il 95% dei livelli firmati si abbina per nome.

## Lo schema

<figure class="diagramma"><img src="svg/d04.svg" alt="La catena dal ruolo alla competenza" style="width:330px"></figure>

**Validità di una competenza.** Valida → da confermare (requisito scaduto da meno di 30 giorni, 9 mesi senza
esercizio, conferma semestrale mancata) → sospesa. Il rientro è automatico quando il requisito torna valido.

<h2 class="np">Tappe e stime</h2>

Giorni lavorativi di sviluppo di una persona, prove comprese. Non comprendono il lavoro di contenuto.

| Tappa | Contenuto | Giorni |
| --- | --- | --- |
| 1. Base | Catalogo dalla bozza della Qualità; calcolo di validità e conformità; sessione formativa; caricamento della skill matrix firmata | 36-53 |
| 2. Mansioni e firme | Richiesta di mansione; permessi per reparto e sostituti; firma e timbri; emissione semestrale firmata; conferma con mancato esercizio | 27-49 |
| 3. Estensioni | Personale non operativo; prove e viste per cliente; turno e copertura; ricetta con versioni; selezione candidati; corso collegato alla sessione; inserimento e cambio mansione | 33-68 |
| 4. Sintesi | Scheda personale generata; cruscotti; indicatori; non conformità e competenze | 18-38 |
| Navigazione | Menu a due livelli, «Da fare», «Il mio reparto», pagine uniche. Indipendente: si può fare per prima | 16-31 |
| **Totale** | | **130-239** |

| Traguardo | Settimane dall'inizio |
| --- | --- |
| Avvio minimo: skill matrix firmata nel modulo che c'è già, firmata da RDD nel portale | 1-2 |
| Tappa 1: livelli con la prova e avvisi, su un reparto | 7-11 |
| Tappe 1 e 2: anche la richiesta di mansione con le firme | 13-20 |
| Tutto | 26-48, cioè 6-11 mesi |

Guide e collaudo con i reparti valgono circa il 15% in più. La voce più incerta è il calcolo di validità e
conformità: tutto il resto ci si appoggia. Ogni tappa ha un interruttore per tornare indietro. Il motore di riferimento `build/motore_rif.py` fa da oracolo per i
test: l'implementazione deve dare gli stessi risultati sugli stessi dati.

<h2 class="np">Rischi e punti aperti</h2>

| Rischio | Come si gestisce |
| --- | --- |
| Il catalogo non viene completato | La bozza della Qualità ha 5 fogli compilati su 27: si carica un reparto alla volta |
| Troppa burocrazia per i capi reparto | Una SF vale per più persone e più competenze; i rinnovi non richiedono una SF |
| Una segnalazione ignorata | Presa in carico con termine, poi sale a RDD; blocco dove la procedura lo impone |
| Le risposte della Qualità cambiano un'ipotesi | Ipotesi isolate: le alternative non cambiano il modello dati |
| Chi non svolge più una mansione | Lo dichiara il capo reparto nella conferma semestrale: il portale non è collegato all'ERP |

**Aperto.** Le nove domande alla Qualità; la revisione di MT CN 06 e dei moduli MOD.053, MOD.040, MOD.187; la soglia
di firma, che la procedura fissa a L e il portale oggi a U; se RDD firma nel portale o su carta.

**Non verificato.** Il MOD.130 (registro timbri) è un'immagine; il MOD.192 non è nella cartella del sistema di
gestione; il legame fra timbro e skill matrix nel portale non è stato controllato nel dettaglio.

**Navigazione.** Il menu di Anagrafica passa da tre livelli a due, da 60 voci a 34: `RMC_Menu_foglio.pdf`.

**Dove sta il dettaglio.** I documenti `01`-`06` nella stessa cartella; i PDF lunghi in `archivio/`; il prototipo in
`prototipo/prototipo_rmc.html`.
