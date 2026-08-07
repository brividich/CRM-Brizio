# Sorveglianza sanitaria — acquisizione automatica dei referti scansionati

**Data:** 2026-08-06
**Stato:** ADR proposto — in attesa di approvazione, nessun codice scritto
**Ambito:** `anagrafica` (visite mediche), nuovo sottoinsieme "intake referti"

---

## 1. Contesto e vincolo di partenza

Il medico competente consegna i certificati di idoneità alla mansione (Winasped,
D.Lgs 81/08 art. 41) su carta, **firmati dal lavoratore**. La firma autografa
impone il passaggio da scansione: non esiste una via "PDF nativo" che eviti l'OCR.

L'obiettivo è che una pila di scansioni si trasformi da sola in visite registrate
a scadenzario, con una coda di revisione per i casi incerti.

### 1.1 Cosa è stato verificato prima di scrivere questo documento

L'investigazione ha cambiato l'inquadramento del problema. In sintesi:

| Assunzione iniziale | Realtà verificata |
|---|---|
| Il modulo va modellato da zero | Esiste già ed è completo (§2) |
| La pipeline di acquisizione va progettata | Esiste già per la formazione, in produzione (§2) |
| Serve `pdfplumber` + `pdf2image` + poppler | Bastano PyMuPDF (già in requirements) + Tesseract |
| Serve un gruppo ACL nuovo | Esiste già un singleton di permessi dedicato |
| Le scansioni potrebbero avere un layer testo | **Zero caratteri**: OCR obbligatorio |
| Un certificato = una visita | Un certificato = **N visite** (protocollo sanitario) |

### 1.2 Misure sul campione reale

Un certificato reale, originale non ritoccato (scansione ~150 dpi, immagine pura):

- **~2 secondi per certificato** (rasterizzazione 200 dpi + OCR italiano).
  Cento referti ≈ 3,5 minuti: compatibile con un giro di job.
- **Taratura: 200 dpi, `--psm 6`, `-l ita`.** Misurata su matrice dpi × psm con 9
  ancore di controllo. I default di libreria (300 dpi, psm 3) sono risultati
  **peggiori**: più lenti e con la data del giudizio corrotta (`241-05-2024`).
  Salire di risoluzione non aiuta — la scansione è nativa ~150 dpi, sopra si
  amplifica solo il rumore. `psm 11` distrugge sistematicamente la tabella del
  protocollo.
- **Il nome va letto dal blocco anagrafico, non dalla riga di firma.** La riga
  `Il Lavoratore ...:` è attraversata dalla firma autografa: l'OCR la spezza su
  due righe e storpia il cognome. Il blocco anagrafico esce invece pulito — e vi
  compare il nome *insieme alla data di nascita*, cioè insieme alla propria
  conferma. **Conclusione raggiunta in modo indipendente** dalla misura sul
  campione e dallo script già in uso dalla segreteria, che ha adottato la stessa
  priorità: è il punto più solido dell'intera estrazione.
- **Il pattern di fallback può produrre un nome plausibile ma sbagliato.** In una
  delle configurazioni provate ha restituito `AMMAI NATI ALBERTO`. Un fallimento
  visibile è innocuo; un nome verosimile e falso che guida un abbinamento
  sanitario non lo è (§D5).
- **Estrarre le immagini incorporate nel PDF non funziona** (restituisce testo
  spazzatura). Va rasterizzata la *pagina*.

> **Limite dichiarato:** tutte le misure vengono da **un solo documento, di un solo
> medico**. La taratura è un punto di partenza motivato, non un ottimo dimostrato.
> Il primo lotto reale può spostarla, e il codice deve renderla configurabile.

---

## 2. Cosa esiste già (e non va rifatto)

### 2.1 Modello sorveglianza sanitaria — completo

| Elemento | Dove |
|---|---|
| `TipoVisitaMedica` — catalogo, `durata_mesi`, ruoli operativi | `anagrafica/models.py:2156` |
| `VisitaSessione` — giornata del medico competente | `anagrafica/models.py:2189` |
| `VisitaMedica` — svolgimento, **scadenza calcolata in `save()`**, 7 esiti, referto FK, audit | `anagrafica/models.py:2215` |
| `AnagraficaVisiteMedichePermission` — singleton ACL, default `ADMIN` | `anagrafica/models.py:2311` |
| Dashboard, sessioni, candidati, export, scadenzario unificato | `anagrafica/urls.py:105-120` |
| `DocumentoDipendente.Tipo.VISITA_MEDICA_REFERTO` | `anagrafica/models.py:2046` |
| Storage privato **cifrato**, fuori webroot, download con ACL+audit | `anagrafica/storage.py` |

### 2.2 Pipeline di acquisizione scansioni — esiste per la formazione

`anagrafica/services/intake_scansioni.py` risolve già, in produzione: sorveglianza
di una cartella di rete, attesa che il file sia stabile (la fotocopiatrice scrive
a pezzi), archiviazione *prima* della lettura, spostamento in `elaborati`/`errori`,
isolamento dei guasti, limite per giro, annotazione dell'ultimo passaggio.
Accompagnato da `TrainingScanIntakeConfig` (singleton) e `TrainingScanLog`
(registro letture), UI di impostazioni/log/esito e job django-q2.

---

## 3. Decisioni

### D1 — Riusare il modello esistente, non modellarne uno nuovo

`VisitaMedica` copre già tutto ciò che l'intake deve produrre. **Nessuna modifica
ai modelli sanitari esistenti.** I nuovi modelli riguardano solo l'acquisizione.

*Perché:* il modello è in produzione, ha uno storico e alimenta lo scadenzario
unificato. Un secondo modello parallelo creerebbe due verità sulla stessa scadenza.

### D2 — Intake dedicato ora, estrazione in `core` rimandata

Il modulo di intake referti **duplica il pattern** di `intake_scansioni.py` senza
condividerne il codice.

*Perché (revisione di una valutazione precedente):* a prima vista i due casi
sembravano lo stesso meccanismo con due riconoscitori. Non lo sono. Il foglio
firme si identifica **con certezza** (QR → token → foglio) e produce *una*
proposta su un oggetto già esistente; il referto si identifica in modo
**probabilistico** e *crea* N record nuovi su un dato sanitario. Divergono la
semantica della conferma automatica, il modello del registro e la coda di
revisione. Astrarre su due casi così diversi produrrebbe una generalizzazione
sbagliata, e per farlo bisognerebbe rimettere le mani su codice in produzione.

*Costo accettato:* ~100 righe di meccanica di cartella duplicate (stabilità del
file, spostamento, isolamento errori). È debito reale e va scritto nel changelog.
*Rimedio previsto:* quando arriverà un terzo caso d'uso, estrarre in
`core/intake_cartella.py` il solo ciclo di spazzamento, parametrizzato per
gestore. Non prima.

### D3 — Estrazione: PyMuPDF per rasterizzare, Tesseract per leggere

- **Nessuna nuova dipendenza Python.** PyMuPDF è già in `requirements.txt` e già
  usato da `core/qr.py` esattamente per rasterizzare PDF.
- **Nuova dipendenza di sistema: Tesseract 5.x + pacchetto lingua `ita`.**
  Invocato come eseguibile (`subprocess`), percorso configurabile via
  `TESSERACT_CMD` in `.env`. Non serve `pytesseract`.
- Parametri di default: **200 dpi, `--psm 6`, `-l ita`**, tutti configurabili
  dalle impostazioni (§D9) perché la taratura è provvisoria.
- **Attenzione: i parametri non sono trasferibili fra rasterizzatori.** Lo script
  già in uso dalla segreteria rasterizza con **poppler** (`pdf2image`) a 300 dpi e
  funziona. Le stesse impostazioni applicate a **PyMuPDF** producono, sul medesimo
  file, una data corrotta (`241-05-2024` invece di `21-05-2024`): pixel diversi,
  OCR diverso. Portare la logica nel HUB conservando `dpi=300` e la segmentazione
  di default sarebbe quindi una **regressione silenziosa** rispetto a uno strumento
  che oggi funziona. Con 200 dpi, oppure con `--psm 6`, il campo esce integro con
  entrambi i motori: è il motivo per cui i default sono quelli e non i canonici.
- **Degradazione, mai crash:** sul modello di `core/qr.py:disponibile()`, se
  Tesseract manca il file viene comunque archiviato e la riga finisce in coda con
  motivo esplicito. Un ambiente aggiornato a metà non deve buttare giù nulla.
- **Timeout per file** (default 30s): oltre, la riga va in errore e il giro
  prosegue.

### D4 — Estrazione dei campi: ancore ridondanti, mai una sola

Il documento contiene la stessa informazione più volte. L'estrattore sfrutta la
ridondanza invece di scommettere su un pattern.

| Campo | Ancora primaria | Conferma |
|---|---|---|
| Cognome e nome | blocco anagrafico in testa | riga `Il Lavoratore` (se leggibile) |
| Data di nascita | blocco anagrafico | — (chiave di conferma del match) |
| Data del giudizio | `Espresso il` | `Trasmesso al datore` + `Trasmesso al lavoratore` |
| Esito | riga in maiuscolo dopo il giudizio | — |
| Mansione | `Mansione` (compare due volte) | seconda occorrenza |
| Protocollo | tabella `Esame/prestazione` ↔ `Periodicita'` | — |
| Tipo documento | footer `Winasped` + `CERTIFICATO MEDICO DI IDONEITA'` | — |

**Regola delle date:** si raccolgono *tutte* le occorrenze e si decide per
consenso. Nel campione reale l'OCR ha corrotto una delle tre (`241-05-2024`): le
altre due l'avrebbero salvata. Se le occorrenze non concordano → coda di revisione.

**Non si persiste il testo OCR grezzo** (§D8).

### D5 — Matching: fuzzy sul nome, **conferma sulla data di nascita**

- Libreria: **`difflib.SequenceMatcher`, standard library** — zero dipendenze
  nuove, ed è già il criterio usato in `gestione_specifiche/ai_copilota.py`.
  `rapidfuzz` sarebbe più veloce ma su poche centinaia di dipendenti è irrilevante.
- Normalizzazione: maiuscole, accenti rimossi, spazi compattati, confronto anche
  con ordine invertito (`COGNOME NOME` / `NOME COGNOME`).

**Soglie proposte (da ritarare sul primo lotto reale):**

| Situazione | Esito |
|---|---|
| Similarità ≥ 0,70 **e data di nascita coincidente** | match confermato |
| Similarità ≥ 0,92, candidato unico, DOB assente dal referto | match confermato |
| Data di nascita **discordante** | coda, sempre — qualunque similarità |
| Più candidati sopra soglia | coda, con l'elenco dei candidati |
| Nessun candidato | coda, con i campi letti per la ricerca manuale |
| Candidato trovato ma **cessato** | coda, con avviso — mai automatico |
| Nome letto dal **pattern di fallback** (`Il Lavoratore`) | coda, mai automatico |

*Perché la data di nascita è il perno:* è l'unico campo del certificato che
identifica la persona ed è insieme **immutabile e verificabile** contro
`Dipendente.data_nascita` (`models.py:886`). Il codice fiscale non c'è; il numero
`N.Cartella` è la numerazione del medico e non è (ancora) mappato sui nostri
dipendenti. Con la DOB il fuzzy smette di essere l'ultima parola su un dato
sanitario, ed è esattamente la garanzia che serve.

> **Miglioria a costo zero, fuori software:** sul certificato il campo
> `N.Matricola` è **vuoto**. Se il medico competente lo compila con la nostra
> matricola, ogni referto futuro si abbina in modo deterministico e la coda di
> revisione si svuota. Vale una telefonata prima di tarare qualunque soglia.

### D6 — Un certificato produce **N visite**, con periodicità **dal catalogo**

Il protocollo sanitario elenca più esami, ciascuno con la propria cadenza
(nel campione: Visita Medica *annuale*, Visita Oculistica *biennale*,
Vaccinazione Antitetanica *decennale*). Dal singolo PDF nascono quindi **tre**
`VisitaMedica` con la stessa `data_svolgimento` e tre scadenze diverse.

**Decisione (approvata): la periodicità viene dal catalogo**
`TipoVisitaMedica.durata_mesi`, non dal certificato.

Conseguenze operative:

- La scadenza continua a essere calcolata da `VisitaMedica.save()` come oggi:
  nessuna deroga, nessun percorso alternativo, una sola regola nel sistema.
- **La periodicità letta sul certificato non viene ignorata: viene confrontata.**
  Se diverge dal catalogo, la visita si crea comunque con il valore del catalogo,
  ma la divergenza è registrata e mostrata in coda. Una divergenza significa che
  il medico ha cambiato protocollo, ed è un'informazione che deve arrivare a una
  persona, non essere sovrascritta in silenzio.
- Esame non mappabile su alcun `TipoVisitaMedica` → **coda, senza inventare il
  tipo**. La mappatura nome-esame → tipo a catalogo è una tabella di alias
  configurabile, non una costante nel codice.
- Un unico `DocumentoDipendente` (tipo `VISITA_MEDICA_REFERTO`, storage cifrato)
  viene referenziato da tutte le N visite: il PDF è uno solo.
- Creazione in `transaction.atomic()`: o nascono tutte, o nessuna.

### D7 — Idempotenza e duplicati

- **Stesso file ricaricato:** hash SHA-256 del contenuto registrato sulla riga di
  intake. Se già visto → si salta, con esito esplicito.
- **Duplicato logico** (stesso dipendente + stesso tipo + stessa data, file
  diverso): non si crea nulla, va in coda come "possibile duplicato".
- **Nessun `UniqueConstraint` in questa fase.** Aggiungerlo su dati storici già
  esistenti può fallire in migrazione: prima un comando di report sui duplicati
  presenti, poi eventualmente il vincolo. Il controllo resta applicativo.
- Rilancio sicuro: un file in errore resta in `errori/` e può essere rimesso in
  ingresso senza effetti collaterali.

### D8 — Privacy: cosa si conserva e cosa no

Il giudizio di idoneità è dato che il datore di lavoro **deve** trattare
(art. 41 D.Lgs 81/08). La diagnosi no. L'OCR però legge *tutta* la pagina.

- **Il testo OCR grezzo non viene mai persistito.** Vive in memoria per la durata
  dell'estrazione. Sulla riga di intake finiscono solo i campi riconosciuti.
- Il PDF si archivia sempre — nello storage privato **cifrato**, fuori webroot,
  scaricabile solo da view con ACL e audit (`anagrafica/storage.py`).
- Le fixture di test riproducono il **layout**, mai contenuti reali: nomi, date di
  nascita e giudizi sono inventati.
- Ogni conferma manuale di un match registra **chi** e **quando**.

### D9 — Nuovi modelli (solo intake)

`RefertoIntakeConfig` — singleton, come `TrainingScanIntakeConfig`:
attiva, cartella, `max_file_per_giro`, `sposta_elaborati`, **`dpi`**, **`psm`**,
**soglie di match**, `conferma_automatica`, `ultima_esecuzione`, `ultimo_esito`.

`RefertoIntakeRiga` — una riga per file elaborato:
`nome_file`, `percorso` archiviato, `dimensione`, `sha256`, `origine`
(CARTELLA/WEB), `esito` (OK / DA_RIVEDERE / DUPLICATO / RIFIUTATO / ERRORE),
campi letti (cognome-nome, data di nascita, data del giudizio, esito, mansione,
protocollo come JSON), `legacy_anagrafica_id_proposto`, punteggio del match,
candidati (JSON), divergenze di periodicità, visite create, `confermato_da` +
`confermato_il`, `messaggio`.

I parametri OCR e le soglie stanno in configurazione **proprio perché la taratura
viene da un solo documento**: il primo lotto reale si corregge dall'interfaccia,
senza un rilascio.

### D10 — ACL: riusare il singleton esistente

**Nessun gruppo nuovo.** `AnagraficaVisiteMedichePermission` (default `ADMIN`)
governa già l'accesso ai dati sanitari.

- Caricare e revisionare → stesso permesso che serve per registrare una
  `VisitaMedica`: confermare un match *è* registrare una visita.
- Consultare lo stato delle scadenze → già coperto dallo scadenzario esistente.
- **Le route API/AJAX della coda vanno inserite in `API_ACL_GATE_PATHS`**,
  altrimenti `ACL_STRICT_CANONICAL` le nega con 403 (trappola nota del progetto).
- Gli endpoint protetti rispondono JSON 401/403, mai redirect HTML.

### D11 — UI

Quattro pagine, sui token esistenti (`hub-` / `fmd-`), **senza introdurre un terzo
namespace**:

1. **Upload multiplo** — trascina i PDF, oltre alla cartella di rete sorvegliata.
2. **Coda di revisione** — il cuore: per ogni riga i campi letti, il dipendente
   proposto con punteggio, i candidati alternativi, le divergenze di periodicità,
   l'anteprima del PDF, e tre azioni: conferma / correggi il dipendente / scarta.
3. **Registro letture** — tutte le acquisizioni con esito, come
   `formazione_scansioni_log`.
4. **Impostazioni** — cartella, parametri OCR, soglie, conferma automatica.

**Conferma automatica spenta di default.** Anche accesa, si ferma davanti a DOB
discordante, candidati multipli, dipendente cessato o esame non mappato. La stessa
prudenza già adottata per le presenze ai corsi, qui a maggior ragione.

---

## 4. Edge case

| # | Caso | Comportamento |
|---|---|---|
| 1 | PDF illeggibile né a testo né in OCR | archiviato, `RIFIUTATO`, consultabile dal registro |
| 2 | Tesseract assente o non avviabile | riga in coda con motivo, nessun crash |
| 3 | Dipendente cessato | coda con avviso, mai automatico |
| 4 | Stesso file ricaricato | hash → saltato |
| 5 | Stesso dipendente+tipo+data, file diverso | coda, "possibile duplicato" |
| 6 | Più certificati in un unico PDF | una pagina con blocco anagrafico = un certificato; pagina senza = continuazione |
| 7 | OCR corrompe la data | consenso fra le tre occorrenze |
| 8 | OCR storpia il cognome | blocco anagrafico + conferma su data di nascita |
| 9 | Omonimi | discrimina la data di nascita; se coincide anche quella → coda obbligatoria |
| 10 | Esame fuori catalogo | coda, nessun tipo inventato |
| 11 | Periodicità certificato ≠ catalogo | vince il catalogo, divergenza segnalata |
| 12 | Layout di un medico diverso | non riconosciuto → coda; l'estrattore non indovina |
| 13 | File ancora in scrittura | attesa di stabilità, ripreso al giro dopo |
| 14 | Upload concorrenti sullo stesso file | hash + `transaction.atomic()` |

---

## 5. Piano di test

Sullo standard del modulo (la formazione ha ~275 test specifici). Copertura minima:

**Estrazione** — PDF corrotto; PDF vuoto; PDF senza layer testo *e* senza OCR
disponibile; timeout OCR; multi-pagina; footer Winasped assente (documento
estraneo); tabella protocollo con un solo esame e con cinque.

**Parsing** — date corrotte con consenso 2 su 3; date discordanti 1/1/1;
cognome storpiato; nome invertito; data di nascita assente; esito con
limitazioni e con prescrizioni; periodicità divergente dal catalogo.

**Matching** — match esatto; fuzzy sopra e sotto soglia; omonimi con DOB diversa;
omonimi con DOB identica; dipendente cessato; nessun candidato; due candidati
sopra soglia.

**Creazione** — N visite da un protocollo; referto unico condiviso; rollback
atomico se un tipo non mappa; duplicato logico rifiutato; scadenza calcolata dal
catalogo e non dal certificato.

**ACL** — accesso negato a utente senza permesso su ogni route; API che
rispondono 401/403 JSON e non redirect; route registrate in `API_ACL_GATE_PATHS`.
Attenzione: nei test serve `@override_settings(LEGACY_AUTH_ENABLED=False)`,
altrimenti l'ACL nega tutto ai non-superuser (trappola nota).

**Concorrenza e idempotenza** — stesso file due volte; due giri sovrapposti sulla
stessa cartella; file in scrittura.

> **Nota di costo:** `config.settings.test` usa un DB SQLite per-PID, quindi ogni
> run rimigra da zero (6-8 minuti anche per un solo test). I task del piano di
> implementazione vanno dimensionati di conseguenza, con timeout ≥ 600s.

---

## 6. Fuori ambito

Notifica al dipendente; anagrafica strutturata dei medici competenti; modifiche
al modello `VisitaMedica` esistente; estrazione della meccanica di cartella in
`core`; supporto a layout di software diversi da Winasped.

---

## 7. Rischi aperti

1. **Taratura su un solo documento** (§1.2). Mitigazione: parametri configurabili
   da interfaccia, non costanti nel codice.
2. **Layout di altri medici sconosciuto.** Se in futuro arriveranno certificati non
   Winasped, il riconoscimento del tipo documento li manda in coda invece di
   estrarre male: fallimento visibile, non silenzioso.
3. **Tesseract su produzione** — dipendenza binaria fuori dal venv e fuori
   dall'allowlist del packager. Va documentata nel deploy e verificata da
   `validate_deployment`. È la prima dipendenza di sistema di questo tipo nel
   portale.
4. **`N.Cartella` non mappato.** Se si scoprisse che il numero del medico è stabile
   per dipendente, diventerebbe una chiave deterministica e il fuzzy diventerebbe
   marginale. Da verificare.
5. **Variante di esito mai vista.** L'enum ha 7 valori; il campione ne mostra uno.
   La mappatura testo → enum va confermata su almeno un certificato con
   limitazioni o prescrizioni.

---

## 8. Cosa serve per chiudere i punti aperti

- 2-3 altri esemplari, **soprattutto uno con esito diverso** (rischio 5).
- L'elenco dei `TipoVisitaMedica` configurati in produzione, per la tabella di
  alias degli esami (§D6).
- L'esito della verifica su `N.Cartella` (rischio 4).

Nessuno dei tre blocca l'implementazione: incidono sulla mappatura e sulle soglie,
entrambe configurabili per costruzione.
