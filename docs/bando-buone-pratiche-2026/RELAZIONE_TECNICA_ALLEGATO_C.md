# Bando Buone Pratiche 2026 — Relazione tecnica (Allegato C)

> **Bozza di lavoro.** Il testo qui sotto è già utilizzabile; i blocchi marcati
> `[DA COMPLETARE]` sono i punti in cui servono fatti che il codice non conosce.
> Ripartire da qui: leggere §1 (coordinate), §2 (cosa manca), poi compilare §4.

Deck di supporto (una slide per criterio, stesso ordine di questo file):
<https://claude.ai/code/artifact/7f4ab726-866e-4c26-887f-d69759592758>

---

## 1. Coordinate del bando

| | |
|---|---|
| Atto | Decreto dirigenziale **n. 13485 del 15-06-2026**, Regione Toscana |
| Nome pubblico | «Premio Impresa più sicura 2026» |
| **Scadenza** | **31 ottobre 2026** (fa fede la ricevuta di consegna PEC) |
| Invio | **solo PEC** a `regionetoscana@postacert.toscana.it`, oggetto **"BANDO BUONE PRATICHE"** |
| Documenti | **All. B** domanda di partecipazione + **All. C** relazione tecnica |
| Struttura All. C | Abstract (3 righe) + tabella con **un riquadro per criterio** |
| Vincoli di forma | niente loghi commerciali, niente carattere pubblicitario, niente opere protette da diritto d'autore |
| Ammissibilità | regolarità contributiva e assicurativa; nessuna condanna in materia di salute e sicurezza negli ultimi 5 anni |

Requisiti che la pratica deve soddisfare (art. 3 del bando): essere stata
**effettivamente realizzata e applicata** previa valutazione dei rischi; apportare
un miglioramento oggettivo; affrontare un **rischio identificato**; determinare un
**beneficio identificabile e permanente**; prevedere un **approccio partecipativo**
fra datore di lavoro e lavoratori, con coinvolgimento **RLS/RLST**.

### Punteggi (totale 100)

| Criterio | Punti |
|---|---:|
| Coerenza con le finalità del bando | 15 |
| Trasferibilità ad altri contesti lavorativi | 15 |
| Efficacia prevenzionale oggettiva (confronto **ante/post**) | 15 |
| Coinvolgimento attivo lavoratori e **RLS/RLST** | 15 |
| Innovazione | 10 |
| Fattibilità tecnica ed economica | 10 |
| Azioni e contenuti formativi/informativi | 10 |
| Investimenti in upgrade tecnologici | 10 |

---

## 2. Stato al 2026-08-25 e cosa manca

**Decisione presa:** si scrive la relazione adesso, ma la **fotografia dei dati si
fa a metà ottobre**, dopo alcune settimane di uso reale. Oggi il modulo è un
archivio popolato, non ancora una pratica applicata: dichiararlo come tale
indebolirebbe proprio i due criteri da 15 punti.

Fotografia di partenza (baseline dell'ante/post):

| | valore |
|---|---:|
| Prodotti chimici attivi censiti | 56 |
| Con scheda di sicurezza corrente | 52 (93%) |
| Senza scheda | 4 |
| Versioni caricate in totale | 61 |
| Reparti coperti | 1 (AGG/MONT) |
| Estrazione automatica riuscita | 38 / 52 |
| **Prese visione registrate** | **0** |
| Aperture da QR | 1 |
| Dipendenti di AGG/MONT nel denominatore | 12 |

### Da fare prima di scrivere la versione definitiva

1. **Stampare e applicare i QR** sui contenitori di AGG/MONT e far partire le
   prese visione. È l'unica azione che trasforma i numeri.
2. **Incontro con l'RLS** per documentare il coinvolgimento (criterio da 15 punti,
   oggi il più scoperto). Vedi le domande in §4.7.
3. **Compilare a mano le 14 schede con estrazione fallita** (PDF probabilmente
   scansionati senza livello di testo): finché sono vuote, la pagina mobile di
   quei prodotti non mostra nulla.
4. **Ricostruire l'"ante"** con il metodo di stima, e dichiararlo come stima.
5. **Contare ore interne e costi materiali** (§4.5).
6. **Decidere sulla condivisione** della pratica con altre imprese (§4.3).

---

## 3. Estrazione dei dati a ottobre

Da lanciare sul DB di produzione, dichiarando nella relazione la data della
fotografia e il periodo di osservazione.

```sql
SELECT
  (SELECT COUNT(*) FROM schede_sicurezza_prodottochimico WHERE attivo = 1)                    AS prodotti_attivi,
  (SELECT COUNT(DISTINCT reparto_id) FROM schede_sicurezza_prodottochimico WHERE attivo = 1)  AS reparti_coinvolti,
  (SELECT COUNT(*) FROM schede_sicurezza_schedasicurezza s
     JOIN schede_sicurezza_prodottochimico p ON p.id = s.prodotto_id
    WHERE s.is_corrente = 1 AND p.attivo = 1)                                                 AS con_scheda_corrente,
  (SELECT COUNT(*) FROM schede_sicurezza_presavisionescheda)                                  AS prese_visione,
  (SELECT COUNT(DISTINCT operatore_id) FROM schede_sicurezza_presavisionescheda)              AS operatori_distinti,
  (SELECT ISNULL(SUM(visite_qr), 0) FROM schede_sicurezza_prodottochimico WHERE attivo = 1)   AS aperture_da_qr,
  (SELECT COUNT(*) FROM core_auditlog
    WHERE modulo = 'schede_sicurezza' AND azione = 'segnalazione_sds_mancante')               AS segnalazioni_sds_mancante;
```

La copertura per reparto è già a video in `/schede-sicurezza/report/`, con export
CSV: quello si allega come evidenza senza rielaborarlo.

> **Nota tecnica.** Il denominatore per reparto passa da
> `anagrafica_dipendenti.utente_id`, non dal confronto diretto fra
> `legacy_anagrafica_id` e `Profile.legacy_user_id` — sono due spazi di ID
> distinti (corretto il 2026-08-25). Un dipendente entra nel conteggio solo se ha
> `area_aziendale` valorizzato **e** un account portale attivo.

---

## 4. I riquadri dell'Allegato C

### Abstract (3 righe)

> Ogni contenitore di prodotto chimico porta un QR: chi lo inquadra vede in dieci
> secondi la scheda di sicurezza della versione oggi in vigore — pittogrammi,
> frasi di pericolo, DPI obbligatori, primo soccorso — senza account e senza
> raggiungere un raccoglitore in ufficio. La consultazione da parte del lavoratore
> identificato viene registrata per singola versione: quando il fornitore
> revisiona la scheda l'obbligo informativo si riapre da solo, e il sistema
> indica reparto per reparto chi manca. L'archivio è versionato e cifrato, e un
> report evidenzia i prodotti privi di scheda aggiornata.

### 4.1 Coerenza con le finalità del bando (15)

Rischio affrontato: **agenti chimici pericolosi**, Titolo IX Capo I del D.Lgs.
81/2008, già valutato nel DVR. L'intervento è realizzato e in uso, non teorico.
Supera lo standard minimo: la norma (art. 227) chiede che i lavoratori
*dispongano* delle schede; qui la scheda è **al punto d'uso**, in forma
comprensibile, e la consultazione lascia una traccia verificabile. Il beneficio è
permanente perché è il modo ordinario in cui una scheda entra in azienda, non una
campagna con una data di fine.

`[DA COMPLETARE]` numero di prodotti censiti, reparti coinvolti e lavoratori
potenzialmente esposti alla data della fotografia.

### 4.2 Innovazione (10)

- Lettura automatica del PDF del fornitore segmentato sulle **16 sezioni** del
  Reg. UE 2020/878: propone pittogrammi, frasi H/P, primo soccorso, DPI,
  incompatibilità. La proposta resta **marcata come tale**: l'RSPP conferma o
  corregge, e la distinzione fra ciò che ha proposto il documento e ciò che ha
  validato una persona non si perde.
- **La sintesi come atto di prevenzione**: dalle dodici pagine della scheda ai
  cinque dati che servono davanti al contenitore; la scheda integrale resta
  scaricabile.
- **Accesso senza identificazione, senza tracciamento**: chi non ha un account
  (manutentore, autista) legge comunque. Nessun cookie, nessun IP registrato: si
  contano le aperture, non le persone. La riservatezza è data dall'indirizzo non
  indovinabile e dal blocco all'indicizzazione.
- Nessun nuovo silo: vive dentro il portale aziendale, accanto all'anagrafica di
  DPI, reparti e lavoratori — ed è questo che rende possibile sapere non solo che
  il rischio è documentato, ma **chi l'ha letto**.

### 4.3 Trasferibilità (15)

Il modello non dipende dal ciclo produttivo, solo dall'esistenza di contenitori e
di persone che li aprono: officine, carrozzerie, tintorie, laboratori, imprese di
pulizia, aziende agricole, scuole, strutture sanitarie. Il formato SDS a 16
sezioni è **obbligatorio per legge in tutta l'UE**, quindi la lettura automatica
funziona sui documenti di qualunque fornitore senza accordi preventivi.

Ingredienti replicabili: elenco prodotti per reparto → etichetta QR sul
contenitore → scheda sintetica → registro presa visione per versione → report dei
prodotti scoperti. Soglia d'ingresso: uno smartphone e una stampante di etichette.

Ciò che **non** è trasferibile, e va detto: l'integrazione con l'anagrafica
interna di DPI e reparti. Il valore trasferibile è il **processo**, non il
programma.

`[DA COMPLETARE]` disponibilità a condividere la descrizione del processo con
altre imprese o con l'associazione di categoria, o a ospitare una visita. Il bando
prevede un archivio regionale consultabile delle pratiche premiate: dichiararlo è
coerente con quella finalità e pesa su questo criterio.

### 4.4 Efficacia prevenzionale — ante/post (15)

| Indicatore | Ante | Post | Fonte |
|---|---|---|---|
| Prodotti con scheda corrente | `[ ]` | `[ ]` | report di conformità |
| Tempo medio di reperimento dal punto d'uso | `[ ]` min | < 1 min | misurazione in reparto |
| Lavoratori con presa visione documentata | 0 | `[ ]` | registro prese visione |
| Copertura media per reparto | n.d. | `[ ]` % | matrice presa visione |
| Consultazioni dal QR | 0 | `[ ]` | contatore aperture |
| Versioni superate in circolazione | `[ ]` | 0 | una sola scheda corrente per prodotto |
| Segnalazioni di scheda mancante chiuse | 0 | `[ ]` | audit trail |
| Infortuni / malattie professionali da agenti chimici | `[ ]` | `[ ]` | registro infortuni, sorveglianza sanitaria |

**Come argomentare senza forzare.** Su una base di pochi eventi la variazione
degli infortuni non è statisticamente significativa, e sostenere il contrario
indebolisce la candidatura. La riduzione del rischio si dimostra con gli
**indicatori di processo**: la scheda giusta raggiunge la persona giusta al
momento giusto, e ora esiste la prova che sia successo. Il dato infortunistico si
dichiara comunque, come contesto.

### 4.5 Fattibilità tecnica ed economica (10)

Nessun canone per utente, nessun nuovo fornitore, nessun hardware dedicato:
sviluppato dentro il portale già in esercizio. L'operatore usa il proprio
telefono, senza installare nulla e senza account. Manutenzione ordinaria: si
carica il PDF quando il fornitore manda una revisione; versione corrente,
storicizzazione, riapertura della presa visione e ricalcolo dei vuoti avvengono da
sé.

`[DA COMPLETARE]` ore interne di progettazione e sviluppo; ore di censimento e
caricamento; costo etichette e supporto resistente ai solventi; date di avvio e di
messa in esercizio. Un totale contenuto e **dettagliato** vale più di un totale
basso e generico.

### 4.6 Azioni e contenuti formativi/informativi (10)

La scheda sintetica **è** informazione ai sensi dell'art. 36: linguaggio
essenziale, simboli normati riconoscibili anche da chi legge poco l'italiano,
primo soccorso in evidenza invece che a pagina quattro. La presa visione è
l'evidenza documentale dell'informazione avvenuta, **riferita alla singola
versione** — non un foglio firme generico a inizio anno. Il report per reparto
rende la formazione mirata invece che generalizzata.

`[DA COMPLETARE]` attività effettivamente svolte, con **data, durata, numero di
partecipanti e conduttore**: incontro di lancio, addestramento all'uso del QR,
informativa agli RLS, aggiornamenti all'arrivo di nuove revisioni, materiale
affisso.

### 4.7 Coinvolgimento lavoratori e RLS/RLST (15)

Ciò che la pratica contiene già:

- **Canale di ritorno permanente**: davanti a un contenitore la cui scheda manca,
  il lavoratore trova un pulsante per segnalarlo; la segnalazione resta registrata
  con autore e data e diventa un'azione da chiudere. La partecipazione è *dentro*
  lo strumento, non solo attorno.
- **Dato oggettivo su cui confrontarsi**: la copertura per reparto è consultabile
  e discutibile in riunione periodica, invece di essere un'impressione.

`[DA COMPLETARE]` — da ricostruire **insieme all'RLS**:

- *Prima*: chi ha segnalato che la scheda non era raggiungibile? La necessità è
  nata da un'osservazione dei lavoratori o da un rilievo interno?
- *Durante*: chi ha scelto quali cinque informazioni mostrare nella scheda
  sintetica? Dove sono stati posizionati i QR, e su indicazione di chi?
- *Prova sul campo*: quanti operatori hanno provato la lettura prima
  dell'estensione, in quale data, con quali correzioni conseguenti?
- *Dopo*: quali osservazioni sono arrivate dai reparti e cosa è cambiato di
  conseguenza? **Anche una sola modifica fatta su richiesta di un operatore è la
  prova più forte di approccio partecipativo.**
- Atti da allegare: verbale della riunione periodica (art. 35) in cui la pratica è
  stata presentata, consultazione RLS (art. 50), eventuale sopralluogo congiunto.

### 4.8 Investimenti in upgrade tecnologici (10)

Etichettatura QR dei contenitori; archivio documentale versionato con **cifratura
a riposo** fuori dall'area pubblica del server e accesso profilato; controllo del
file in ingresso sul contenuto reale e non sull'estensione; estrazione automatica
dai PDF; integrazione con l'anagrafica DPI (la sezione 8 diventa un elenco di DPI
**con immagine**); audit trail e reportistica.

`[DA COMPLETARE]` eventuali investimenti hardware (stampante di etichette,
dispositivo di reparto, punto di consultazione fisso). Se non ce ne sono stati,
dichiararlo: è coerente con la fattibilità a costi contenuti.

---

## 5. Riferimenti normativi citabili

- D.Lgs. 81/2008: Titolo IX Capo I (agenti chimici), art. 36 (informazione),
  art. 227 (informazione dei lavoratori esposti), art. 35 (riunione periodica),
  art. 50 (attribuzioni dell'RLS).
- Reg. CE 1272/2008 (CLP), allegato V — i nove pittogrammi di pericolo.
- Reg. UE 2020/878 — struttura in 16 sezioni della scheda dei dati di sicurezza.

## 6. Limite noto da valutare prima di consegnare

La soglia «da rivedere» delle schede guarda la **data di caricamento** nel
portale, non la **data di revisione del fornitore** (campo presente ma non
valorizzato: la data vive dentro la stringa `versione` come testo libero). Avendo
caricato tutto insieme, nessuna scheda risulterà «da rivedere» per tre anni,
comprese quelle revisionate nel 2019. Correggerlo rafforzerebbe il criterio
«efficacia»: il sistema segnalerebbe l'obsolescenza reale invece di quella
apparente.
