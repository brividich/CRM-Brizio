# Guida all'utilizzo — Gestione Carichi Macchina

Modulo di pianificazione dei carichi sulle macchine utensili: organizza **commesse** e
**lavori** sulle macchine giorno per giorno, stima le **durate** e **suggerisce la
macchina** più adatta a una famiglia di pezzi, sempre con un motore **dati-driven ed
esplicabile** (niente "scatola nera": ogni numero è ricavato dallo storico).

> Le macchine NON sono una nuova anagrafica: il modulo si appoggia agli **asset**
> esistenti (`assets.Asset`) in sola lettura e aggiunge solo gli attributi di
> pianificazione (categoria, turni, ore/giorno, stato).

---

## 1. Le due viste

- **Vista Excel** (`/carichi-macchina/`): griglia macchine × giorni, come il
  foglio di officina. È la vista per **inserire e correggere** i lavori cella per cella.
- **Vista Gantt** (`/carichi-macchina/gantt/`): barre temporali per macchina,
  con filtri (famiglia, cliente), KPI di saturazione e **trascinamento** delle barre
  (snap al giorno, con conferma). La **Cascata** sposta anche i lavori successivi; il
  tratteggio indica una **durata stimata** (non confermata); ⚠ segnala un conflitto.

Si passa da una vista all'altra dal selettore in alto.

---

## 2. Pianificare un lavoro (vista Excel)

1. **Clic su una cella** (macchina + giorno): si apre il form inline.
2. Nel campo testo scrivi il lavoro nel formato dell'officina, es. **`8 gimbal (33h)`**
   (quantità + famiglia + ore). Il campo ha l'**autocompletamento** delle famiglie note.
3. Facoltativi: **qta**, **ore**, **stato** (pianificata / in corso / completata) e
   **lavorazione** (finitura / sgrossatura / assieme / ripristino). Se non compili ore/qta,
   il sistema prova a ricavarle dal testo e dalle stime (vedi §4).
4. **Salva**. Per rimuovere un lavoro: svuota il testo e salva, oppure usa il cestino 🗑.

La **famiglia** del pezzo viene riconosciuta automaticamente dal testo (per nome o alias,
es. *gimbal, sombrero, campane, ragni*). È la chiave che lega lo storico macchina↔pezzo.

Un **doppio salvataggio accidentale** dello stesso lavoro (stessa macchina/turno/giorno e
stesso testo) **non crea un duplicato**. Se inserendo o spostando un lavoro questo **si
sovrappone** a un altro sullo stesso turno, il sistema **chiede conferma** prima di salvare.

---

## 2-bis. Turni e capacità della macchina

Quando aggiungi un lavoro (pulsante **«+ Aggiungi lavoro»** nel Gantt o nell'Excel) scegli
anche il **turno**:

- **1° turno** (6-14), **2° turno** (14-22), **Entrambi** (6-22), **Notturno** (22-6), **H24**.
- «Entrambi» e «H24» fanno entrare **più ore al giorno**, quindi a parità di ore il lavoro
  **occupa meno giorni**.

Le opzioni mostrate dipendono dalla **macchina**: una macchina senza 2° turno non potrà
ricevere lavori di 2° turno/Entrambi/H24, una senza turno notturno non potrà ricevere
notturni/H24 (così non si pianifica per errore su un turno che la macchina non fa).

Questi flag si configurano nella pagina **Impostazioni macchine** (ingranaggio ⚙ in alto
nel Gantt) oppure dai **toggle rapidi** nel pannello laterale che si apre cliccando il nome
di una macchina. La **capacità** (saturazione) di una macchina è **ore/giorno × numero di
turni abilitati** (1° sempre, +2° turno, +notturno).

Nel pannello laterale di un **lavoro** ci sono anche **Duplica** (per ripetere velocemente
una lavorazione) ed **Elimina**.

### Corsie per turno e conflitti

Nel **Gantt** ogni macchina è una riga divisa in **corsie per fascia oraria** (a sinistra i
chip **1° / 2° / Notte**). Un lavoro **Entrambi** o **H24** è una **barra alta** che occupa
più corsie. Due lavori sulla stessa macchina e giorno sono in **conflitto** (bordo rosso ⚠)
se le loro fasce **si sovrappongono**:

- 1° turno **+** 2° turno → **nessun** conflitto (sono sequenziali nella giornata);
- 1° (o 2°) **+** Entrambi → conflitto;
- qualunque turno **+** H24, e Notturno **+** H24 → conflitto.

Quando inserisci un lavoro che si sovrappone, il modale mostra un **avviso** e propone il
**primo slot libero** sulla macchina (un altro turno nello stesso giorno, oppure lo stesso
turno dal primo giorno libero): col bottone **«Usa questo slot»** i campi si compilano da
soli. Lo stesso avviso compare quando **trascini** una barra in una posizione occupata.

### Permessi e registro

Le azioni di **modifica** (aggiungere/spostare/duplicare/eliminare lavori, configurare le
macchine) richiedono il permesso **«Carichi Macchina – Modifica piano»**. Chi ha solo la
**vista** non vede i comandi di modifica (pulsanti «+ Aggiungi», «Impostazioni», toggle nel
pannello, Duplica/Elimina); restano disponibili Gantt, Excel, suggerimenti AI e il Registro.

Il **Registro azioni** (pulsante in alto nel Gantt/Excel, oppure
`/carichi-macchina/registro/`) elenca **chi ha fatto cosa e quando** sul piano
(creazioni, modifiche, spostamenti, eliminazioni, duplicazioni, configurazioni), filtrabile
per azione, macchina o testo.

---

## 3. Il suggerimento macchina (novità)

Mentre digiti un lavoro nel form della cella, se la **famiglia è riconosciuta** compare
sotto i pulsanti un box **«Consigliate · <famiglia>»** con le macchine migliori per quel
pezzo. Aiuta a decidere su quale macchina conviene mettere il lavoro.

Per ogni macchina vedi una riga:

```
● DM3                      78%
[██████████████░░░░]   ← barra
```

Come si legge:

- **La lunghezza della barra = score complessivo** (più lunga = più consigliata).
- **Il colore della barra = carico attuale della macchina**:
  - 🟢 **verde** = macchina **libera** (poca saturazione);
  - 🟠 **ambra** = **mediamente** carica;
  - 🔴 **rosso** = **satura** (occhio: spingerci altro lavoro crea coda).
- **●** davanti al codice = è **la macchina della cella** che stai compilando (così vedi
  subito se stai pianificando su una macchina consigliata o no).
- **Passa il mouse** su una riga per il **perché** (tooltip): peso dello storico, quanto
  è recente quella storia, quanto la macchina è libera, n. di lavori storici e % di
  saturazione.
- Se compare **«Questa macchina non è tra le consigliate»**, lo storico suggerisce altre
  macchine per quella famiglia: valuta se spostare il lavoro.

### Come viene calcolato lo score

Lo score combina tre segnali che provengono **dai dati**, non da un'intelligenza testuale:

| Segnale | Significato | Peso default |
|---|---|---|
| **Storico (affinità)** | quante volte quella famiglia è stata lavorata su quella macchina | 0.50 |
| **Recency** | quanto è **recente** quella storia (decadimento nel tempo) | 0.20 |
| **Carico libero** | quanto la macchina è **libera ora** (1 − saturazione) | 0.30 |

Inoltre le macchine in **guasto** o **manutenzione** sono **escluse** dai suggerimenti
(non possono prendere lavoro adesso).

> **Perché così e non una ricerca testuale (BM25)?** L'affinità commessa↔macchina è un
> problema **numerico/categoriale** (tipo di lavorazione, storico, carico), non di
> ricerca di parole. Per questo si usa uno **scoring pesato** trasparente. Tecniche più
> fini (similarità su feature / nearest-neighbour) diventeranno sensate solo quando il
> pezzo avrà **feature strutturate** (materiale, tolleranze, attrezzaggio): oggi la
> "famiglia" è di fatto un soprannome, quindi lo scoring pesato è il livello corretto.

### Spiegazione in linguaggio naturale (opzionale)

Se l'assistente AI locale è attivo, l'endpoint `api/spiega-macchina/` produce una frase
di sintesi sui suggerimenti. L'AI **spiega soltanto** i numeri già calcolati (non predice
e non inventa); se non è disponibile, restano i suggerimenti deterministici.

---

## 4. Stima delle ore (durata)

Quando le ore di un lavoro non sono indicate, il sistema le **stima** con questa priorità
(dalla più alla meno affidabile):

1. **Tempo di ciclo** dell'operazione × pezzi (alta confidenza);
2. **Media storica** per quella coppia (macchina, famiglia) — confidenza media;
3. **Media storica della famiglia** su qualunque macchina — confidenza bassa.

Le ore stimate alimentano la **saturazione** e il **rischio ritardo** (sotto), così la
pianificazione resta realistica anche prima di confermare i tempi reali.

---

## 5. Saturazione, colli di bottiglia e rischio ritardo

- **Saturazione**: carico (ore pianificate) ÷ capacità (ore/giorno × giorni lavorativi ×
  turni). Una macchina/reparto **oltre il 100%** è un **collo di bottiglia**, evidenziato
  nei KPI.
- **Carico settimanale**: previsione delle prossime settimane per reparto e totale, usando
  ore reali dove ci sono e stimate altrimenti.
- **Rischio ritardo**: dato inizio, ore previste e consegna, stima la data di fine
  (giorni lavorativi) e indica **margine** o **ritardo**.

Usa questi indicatori per ribilanciare: se il box suggerimento mostra una macchina
consigliata ma **rossa** (satura), conviene scegliere la seconda scelta 🟢 libera.

---

## 5-bis. Abilitati assenti (manodopera)

Sul **Gantt**, sotto ogni cella-giorno, può comparire una **sottile striscia colorata**:
segnala che, in quel giorno, **uno o più operatori abilitati** a quella macchina (secondo
la **Skill Matrix MOD.187**) hanno **un'assenza già programmata** (ferie/permesso
confermati). Serve a non pianificare a pieno carico una macchina che resterà **scoperta di
manodopera**.

- Il **colore** indica *quanti* assenti rispetto al pool: **giallo** = pochi, **arancio** =
  circa un terzo, **rosso** = molti (≥3 o ~due terzi del pool).
- Passando il mouse sulla striscia compare un **riepilogo**: «*N di M abilitati assenti il
  gg/mm · Cognome Nome (Ferie), …*».
- È un **avviso non bloccante**: non modifica le barre, non impedisce di pianificare; è solo
  un'informazione in più.

L'indicatore si attiva **solo dopo l'import della baseline Skill Matrix** (chi è abilitato a
ciascuna macchina). Finché la matrice è vuota, il Gantt resta identico a prima.

---

## 6. Importazione dati

Lo storico (affinità macchina↔famiglia, cicli, alias) e il backlog si popolano dal foglio
di officina con il comando di import:

```powershell
python django_app\manage.py import_carichi --help
```

L'import fa dedup dello storico, calcola le **affinità** (occorrenze, ore medie, ultima
data) e rileva i **pool di equivalenza** (macchine intercambiabili sulla stessa famiglia,
da confermare a mano). Più storico = suggerimenti più affidabili.

### Import cumulativo da più edizioni del foglio

Per **imparare anche dalle edizioni più vecchie** del foglio (settimane non più presenti
nel file corrente) si passano **più file** allo stesso comando:

```powershell
python django_app\manage.py import_carichi <recente.xlsx> <vecchia1.xlsx> <vecchia2.xlsx>
```

- L'edizione **più recente** (per data degli snapshot `AGG`) fornisce il **piano vivo**,
  il backlog e i cicli; le altre contribuiscono **solo allo storico** (affinità, recency,
  pool).
- Le settimane **in comune** tra edizioni non vengono ricontate (dedup su
  macchina/data/testo); quelle presenti **solo** nelle edizioni vecchie **aggiungono**
  occorrenze e date → suggerimenti e stime più ricchi.
- L'ordine in cui elenchi i file non conta (decide la data degli snapshot); se i titoli
  `AGG` non contengono date, elenca **per primo** il file più recente.
- Resta tutto **idempotente**: ripetere l'import non crea duplicati.

---

## 7. Limiti e note operative

- La qualità del suggerimento dipende dallo **storico**: una famiglia senza storia non ha
  suggerimenti (e per i pezzi nuovi conviene partire dai pool di equivalenza / cicli).
- La **famiglia** è un'etichetta (soprannome): lavori molto diversi nella stessa famiglia
  ereditano lo stesso suggerimento. La granularità più fine arriverà con le feature di
  pezzo (fase 2).
- Tutto è **read-only verso gli asset** e **deterministico/esplicabile**: nessun dato
  viene inventato, e l'eventuale spiegazione AI è solo descrittiva.

---

## 8. Riferimenti rapidi

| Cosa | Dove |
|---|---|
| Vista griglia | `/carichi-macchina/` |
| Vista Gantt | `/carichi-macchina/gantt/` |
| Suggerimento macchina (JSON) | `/carichi-macchina/api/suggerimento-macchina/?famiglia=<id|nome>` |
| Suggerimento + spiegazione AI | `/carichi-macchina/api/spiega-macchina/?famiglia=<id|nome>` |
| Import storico/backlog | `manage.py import_carichi` |

Codice di riferimento: motore predittivo in `gestione_carichi_macchina/previsioni.py`
(funzioni pure + builder degli indici), saturazione in `saturazione.py`, spiegazione AI
in `spiegazioni.py`.
