# Revisione UX modulo Manutenzione — stato e cose da fare

Documento di ripresa. Scritto per essere il **primo file da aprire** in una sessione
nuova: dice dove siamo, cosa è già fatto, cosa resta e quali trappole sono già state
pagate.

Ultimo aggiornamento: **2026-09-08** (seconda sessione: P2 chiusa, Fase 11 fatta).

---

## 1. Stato delle linee git

| Ramo | Commit | Contiene |
|---|---|---|
| `origin/fix/assets-manutenzione-p0` | `33168148` | **tutto il lavoro P0+P1+P2+Fase 11**, non mergiato |
| `main` = `origin/main` | `2aa349c3` | coda condivisa, sidebar categorie, P0 |
| `release/prod` = `origin/release/prod` | `9eea3864` | indietro di 4 commit rispetto a `main` |
| **produzione (PCLOGSYS)** | `acf1813` | **non ha nulla di questa revisione** |

Commit sul branch non ancora in `main`, dal più recente:

```
33168148  P2 conclusa (scheda fornitore) e Fase 11 (Sintesi direzione)
514af5c1  docs - stato e cose da fare della revisione UX manutenzione
4dd8bf51  P2 - Storico onesto sui dati e Piani con copertura reale
2d8f7fcc  P1.4/P1.5 - Interventi coerenti e Cruscotto senza blocchi vuoti
87ffe4d9  "Attivita'" e "Parametri" erano la stessa pagina
64f3b046  P1.3 - carico manutentori nel Cruscotto
86942148  P1.2 - "Da fare" risponde a "cosa devo fare adesso"
1a3ae8aa  P1.1 - il menu manutenzione si divide in due rami
```

> **Il checkout condiviso `C:\Dev\Portale Novicrom` è sporco (21 file).** Non è WIP da
> salvare: sono copie del branch, messe lì per poter guardare le pagine sul server di
> sviluppo. Prima di qualunque merge, verificare che siano identiche al branch e
> scartarle — la procedura è al §6.

**Migrazioni introdotte** (tutte sui pulsanti di menu, nessun cambio di schema, tutte
reversibili):

| # | Cosa fa | Applicata su |
|---|---|---|
| `0101_sidebar_sezione_categorie` | le categorie asset escono da «Navigazione» | dev, test |
| `0102_sidebar_manutenzione_configurazione` | il ramo Manutenzione si divide in due | dev, test |
| `0103_sidebar_attivita_voce_unica` | rettifica: «Attività» e «Parametri» erano la stessa pagina | dev, test |

**In produzione non è applicata nessuna delle tre.**

---

## 2. Fatto — checklist

### P0 (in `main`)

- [x] Testo di debug visibile negli Interventi — commenti `{# #}` su due righe
- [x] «0 ODL aperti» sopra a 4 da gestire → **«Ordini di lavoro attivi»** = tutti gli aperti
- [x] «in ritardo» → **«Aperti da oltre N giorni»** (`due_at` non è valorizzato: è anzianità)
- [x] Finestre Scadenze: limite inferiore + solo aperte, filtro avanzato «Includi concluse»
- [x] Stato **operativo** e **documentale** separati (Eseguita + Rapporto mancante)

### P1 (sul branch)

- [x] Menu in due rami: Manutenzione / Configurazione
- [x] «Quadro» → **Cruscotto**, «Impostazioni» → **Attività** (URL invariati)
- [x] «Da fare»: KPI Scadute / Oggi / Prossimi 7 giorni / Assegnate a me
- [x] Filtri: 4 a vista + «Filtri avanzati» collassabili (nessun filtro perso, c'è un test)
- [x] Raggruppamento chiuso di default
- [x] Interventi: azione unica per riga, «Chiudi» anche sui non assegnati
- [x] Etichette assegnazione: «Assegnato a te» / «Di nessuno» / «Interventi di nessuno»
- [x] Cruscotto: sezioni vuote compresse a «nessuna criticità»
- [x] **Carico manutentori** con riga «Non assegnate» in evidenza

### P2 (sul branch, chiusa)

- [x] Storico: KPI onesti sulla copertura del dato
- [x] Piani: colonna **Copertura** `32/33` + %, colonna **Ultima esecuzione**
- [x] Piani: `prefetch_related` mancante — da 141 a 84 query
- [x] **Scheda fornitore** `/assets/manutenzione/fornitori/<id>/`: contratti, manutenzioni
      affidate, verifiche periodiche, interventi aperti e conclusi, asset coperti. La spesa
      **non viene stampata**: il riquadro «Quanto è documentato il lavoro svolto» dichiara la
      copertura di durata, fermo macchina e costo. L'anagrafica resta in `/fornitori/`
- [x] Helper di copertura condiviso `_copertura_dato` (era interno allo Storico)

### Fase 11 — Sintesi direzione (sul branch, fatta)

- [x] Toggle `[ Operativo ] [ Sintesi ]` nel Cruscotto, stesso URL (`?vista=`)
- [x] KPI su dati reali: nei tempi 12 mesi, scadute + anzianità della più vecchia,
      interventi aperti oltre soglia, copertura documentale, parco con un piano, conflitti
- [x] Grafico a barre 12 mesi (HTML+CSS, nessuna libreria) diviso puntuali / in ritardo
- [x] Riquadro **«Cosa il portale non può ancora misurare»**: copertura reale di durata,
      fermo macchina e costi, più MTTR/MTBF/disponibilità dichiarati non calcolabili
- [x] Default dai permessi esistenti (`can_execute_maintenance`), scelta esplicita vince

---

## 3. Da fare — in ordine

### Prossimo passo: il rilascio

P2 e Fase 11 sono chiuse. Quello che resta non è codice: è portare in produzione un
lavoro che oggi vive solo su un branch, e farlo guardare da una persona (§4.2).

### P3, solo dove i dati lo permettono

- [ ] Costi, downtime, MTTR/MTBF — **oggi non calcolabili**, vedi §5

### Rilascio

- [ ] Merge `fix/assets-manutenzione-p0` → `main`
- [ ] Merge `main` → `release/prod`
- [ ] `package-release.ps1` + promote
- [ ] **`migrate` applica 0101, 0102, 0103**
- [ ] Dopo il promote: **«📅 Registra schedule»** in Centrale di comando
- [ ] Dopo il promote: **riavviare il cluster django-q** (il promote ricicla solo l'App Pool IIS)

---

## 4. Decisioni aperte — servono risposte

1. **`get_portal_branding()` non ha cache** (`core/branding.py:143`). Su Piani viene
   chiamata **46 volte**, una query ciascuna. Non è codice manutenzione: è del guscio,
   quindi pesa su **ogni pagina del portale**. Una cache per richiesta lo risolve in
   poche righe ma tocca `core`. **Farla? Quando?**

2. **Verifica visiva a video mai eseguita.** La cattura schermo va in timeout su questo
   ambiente (JS e query passano, lo screenshot no). Tutte le verifiche sono su HTML
   renderizzato, contesto delle view e database. **Le pagine vanno guardate da una
   persona** prima del rilascio — in particolare la Sintesi, il cui grafico a barre è
   l'unico pezzo di layout non coperto dai test.

> **Chiusa:** il dettaglio fornitore si è fatto, con il criterio del §8 — i due riquadri
> che sarebbero nati vuoti (costi, tempi) sono diventati un riquadro solo che *dichiara*
> quanto quei campi sono compilati. Un riquadro vuoto non informa; la sua copertura sì.

---

## 5. Copertura reale dei dati — misurata, non stimata

Sui 339 ordini di lavoro chiusi in sviluppo:

| Campo | Valorizzato `> 0` |
|---|---|
| durata intervento | **3** (0,9%) |
| fermo macchina | **1** (0,3%) |
| costo manodopera / materiali / totale | **0** |
| eseguito da | 2 (0,6%) |

> **Trappola:** questi campi hanno **default `0`, non `NULL`**. `exclude(campo=None)`
> restituisce il 100%. La copertura vera si misura con `filter(campo__gt=0)`.

Conseguenza: ogni KPI su tempi e costi va trattato come in §2 (Storico), e i grafici
di Fase 11 su costi e fermo macchina **non si fanno finché il dato non viene compilato**.

Occorrenze in sviluppo: **2 aperte, entrambe scadute**. In produzione **533 aperte**.
Le pagine operative in dev sembrano vuote: non è un errore, è il dataset.

---

## 6. Procedura di merge

Il checkout condiviso contiene copie del branch. Verificare che siano identiche prima
di scartarle:

```powershell
cd "C:\Dev\Portale Novicrom"
git fetch --all
# per ogni file modificato: deve dire IDENTICO
foreach ($f in (git status --porcelain | ForEach-Object { ($_ -split '\s+',3)[2] })) {
    git diff --quiet origin/fix/assets-manutenzione-p0 -- $f
    if ($?) { "IDENTICO  $f" } else { "DIVERSO   $f" }
}
```

Se tutti identici:

```powershell
git checkout -- .
git status --porcelain          # deve essere VUOTO

# merge in main da worktree dedicato, MAI dal checkout condiviso
cd C:\Dev\pn-merge
git checkout main ; git pull --ff-only
git merge --no-ff origin/fix/assets-manutenzione-p0 -m "Merge branch 'fix/assets-manutenzione-p0'"
git log -1 --format="%h parents=%p"     # devono essere DUE genitori
git push origin main

# poi release/prod, dal checkout condiviso (e' li' che vive il branch)
cd "C:\Dev\Portale Novicrom"
git merge --no-ff main -m "merge: allinea release/prod a main (revisione UX manutenzione)"
git push origin release/prod
```

Conflitti attesi su `CHANGELOG.md`: si risolvono **tenendo entrambe le voci**, mai
scegliendone una.

---

## 7. Trappole già pagate — non ripagarle

- **Django `{# … #}` commenta UNA riga sola.** Un commento su due righe lascia la
  seconda visibile in pagina. Usare `{% comment %}`.
- **SQL Server errore 8127**: `Meta.ordering` insieme a `values()`+`annotate()`.
  Serve `order_by()` esplicito su ogni aggregazione.
- **La sidebar vive a database**: cambiare il codice non tocca le installazioni
  esistenti. Serve una migration, e va allineato anche `_default_sidebar_seed_rows`
  in `views.py`, altrimenti un'installazione nuova nasce diversa.
- **Il guscio `base_shell.html` rende DUE livelli** (`group.items` → `item.children`).
  Un terzo livello sparisce senza errori.
- **`workorder_close.html` stampa i campi uno per uno**: un campo aggiunto al form e
  non dichiarato nel template viene salvato ma mai mostrato.
- **`/assets/manutenzione/templates/` è un redirect permanente** a
  `/assets/manutenzione/impostazioni/?tab=catalogo`, che ha una scheda sola.
- **Il server di sviluppo è lentissimo al primo caricamento** (SQL Server reale, non
  SQLite): attendere prima di concludere che una pagina sia rotta.
- **La copertura di un campo non si misura con `exclude(campo=None)`**: durata, fermo
  macchina e costi hanno **default `0`, non `NULL`**, quindi risulterebbe sempre il 100%.
  Si conta con `filter(campo__gt=0)`; l'helper condiviso è `views._copertura_dato`.
- **Test**: `manage.py test assets --settings=config.settings.test --keepdb`.
  Baseline attuale **538 verdi**.

---

## 8. Contesto di merito — le tre correzioni che valgono più delle altre

1. **Scadenze mostrava lo storico.** Il filtro era `due_date <= oggi+N` senza limite
   inferiore né stato: «30 giorni» significava «tutto ciò che scade da qui a 30
   giorni», quindi anche il 2021. In dev: 189 righe di cui **187 già concluse**.

2. **«0 ODL aperti» sopra a 4 da gestire.** Non un errore di conteggio: due
   popolazioni con etichette che sembravano annidate. «Aperti» contava solo gli OdL
   nati da un piano, «in ritardo» tutti.

3. **«Completata» accanto ad «Allega rapporto».** Il modello distingueva già
   `report_missing` / `executed` / `completed`: era la UI ad appiattirli.

Il criterio applicato ovunque: **l'interfaccia non deve promettere più di quanto i
dati mantengano.** Vale per i KPI dello Storico, per «in ritardo» che era solo
anzianità, e per i grafici di Fase 11 che non vanno disegnati a zero.
