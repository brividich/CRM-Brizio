# Design — Report compliance SDS (`schede_sicurezza`, sotto-progetto "Fase 2" #1)

Data: 2026-07-09
Modulo: `schede_sicurezza` (già in produzione locale, Fase 1 completa — vedi `docs/BUILD_SPEC_schede_sicurezza.md` e `docs/RECON_schede_sicurezza.md`)

## Contesto

L'utente ha chiesto genericamente di proseguire con una "Fase 2" del modulo, non definita nello spec originale (che salta da "Fase 1" a un blocco "Fase 3 fuori scope"). La richiesta ("fare le cose fuori spec, migliorare la UI, documentazione, gestione dei report") copre quattro sottoprogetti indipendenti. Decomposti; l'utente ha scelto di partire da **report/compliance**.

## Obiettivo

Un report aziendale che mostri:
1. Quali prodotti chimici attivi **non hanno ancora una scheda di sicurezza corrente** caricata (gap da colmare)
2. Per ogni reparto, la **percentuale di dipendenti attivi che hanno confermato la presa visione** di ciascun prodotto con scheda corrente

## Decisioni chiave (dalle domande di chiarimento)

- **Denominatore compliance** = dipendenti attivi del reparto (da `anagrafica`), non un elenco di assegnazioni esplicite. Nessun nuovo concetto di "assegnazione" introdotto nel modulo.
- **Ambito**: entrambe le sezioni (gap SDS + matrice presa visione) in un'unica pagina.
- **Export CSV**: sì, per entrambe le sezioni.
- **Accesso**: chi ha il permesso esistente `schede_sicurezza.prodotto.gestisci` vede TUTTI i reparti (nessuno scoping per caporeparto in questa iterazione).

## Percorso dati verificato (Reparto → User Django)

Verificato sul codice reale (non supposto):

```
anagrafica.Reparto
  <- anagrafica.AreaAziendale.reparto (FK opzionale)
       <- anagrafica.DipendenteAnagraficaAziendale.area_aziendale (FK opzionale)
            campo legacy_anagrafica_id
              == core.models.Profile.legacy_user_id (stesso spazio ID, pattern
                 già usato in procedure_refresh/views.py:103, dashboard/views.py:1103,
                 anomalie/views.py:238, ecc.)
                   -> Profile.user (Django auth User)
```

"Dipendente attivo" = `data_cessazione__isnull=True` su `DipendenteAnagraficaAziendale` (non esiste un booleano `is_active` dedicato).

**Limite noto**: solo i dipendenti con `area_aziendale` valorizzato entrano nel denominatore. Chi ha solo il vecchio campo testo `area` (CharField legacy) non viene contato. Se per un reparto non si trova nessun dipendente mappato, la percentuale è **"n/d"**, non 0% (per non confondere "nessun dato" con "nessuno ha letto la scheda").

## Componenti

### 1. `schede_sicurezza/reports.py` (nuovo modulo di servizio)

- `prodotti_senza_scheda_corrente() -> QuerySet[ProdottoChimico]`
  `ProdottoChimico.objects.filter(attivo=True).exclude(schede__is_corrente=True).select_related("reparto")`

- `matrice_presa_visione() -> list[dict]`
  Per ogni `Reparto` con almeno un `ProdottoChimico` attivo che ha una scheda corrente:
  - risolve l'elenco `User` attivi del reparto (percorso sopra)
  - per ogni prodotto/scheda corrente del reparto: conta `PresaVisioneScheda` di quegli User su quella scheda
  - struttura risultato: `{reparto, righe: [{prodotto, scheda, totale_dipendenti, confermati, percentuale_o_none}]}`

Entrambe le funzioni sono pure (nessun accesso a `request`), testabili in isolamento.

### 2. View (`schede_sicurezza/views.py::report_compliance`)

- Gating: `_can_gestire` (stesso helper già esistente, permesso `schede_sicurezza.prodotto.gestisci`)
- GET normale → `render(..., "schede_sicurezza/pages/report_compliance.html", {...})`
- GET con `?formato=csv&sezione=gap` → `HttpResponse` CSV colonne: Prodotto, Reparto, Fornitore
- GET con `?formato=csv&sezione=matrice` → `HttpResponse` CSV colonne: Reparto, Prodotto, Versione scheda, Dipendenti totali, Confermati, Percentuale

### 3. URL

`path("report/", views.report_compliance, name="report_compliance")` in `schede_sicurezza/urls.py`.

### 4. ACL (`schede_sicurezza/acl_bootstrap.py`)

Aggiunta a `_ROUTE_BINDINGS`: `"schede_sicurezza:report_compliance": PERM_GESTISCI`. Nessun nuovo permesso: riusa `PERM_GESTISCI` esistente. Bump della `_BOOTSTRAP_CACHE_KEY` (v1 → v2) per forzare la ri-registrazione del binding sugli ambienti dove il modulo è già avviato.

### 5. Template (`pages/report_compliance.html`)

- Estende `core/base.html`, riusa le classi `ss-*` già definite in `prodotto_list.html` (coerenza visiva, nessuna nuova palette)
- Sezione 1 "Prodotti senza scheda corrente": tabella semplice, link al dettaglio prodotto per caricare la SDS
- Sezione 2 "Presa visione per reparto": una tabella per reparto (o tabella unica con colonna reparto), badge percentuale colorato — rosso <50%, arancione 50-99%, verde 100%, grigio "n/d" — con tooltip che spiega il limite "n/d" quando il denominatore è 0
- Due pulsanti export CSV (uno per sezione)
- Link "Report compliance" aggiunto in `prodotto_list.html` (header) e come voce eventualmente nella subnav se il modulo ne avrà una in futuro — per ora solo link diretto, nessuna subnav esiste ancora nel modulo

## Testing

Nuovo file `schede_sicurezza/tests_reports.py`:
- `prodotti_senza_scheda_corrente`: prodotto senza schede → incluso; prodotto con scheda `is_corrente=False` → incluso; prodotto con scheda corrente → escluso; prodotto non attivo → escluso
- `matrice_presa_visione`: reparto con 2 dipendenti mappati (via `AreaAziendale`/`Profile`), 1 conferma presa visione → percentuale 50%; reparto senza dipendenti mappati → "n/d"; dipendente cessato (`data_cessazione` valorizzata) → escluso dal denominatore
- View: CSV export contiene le righe attese (parsing con `csv.reader` sul contenuto della response); ACL nega l'accesso senza permesso `gestisci`

## Fuori scope di questo sotto-progetto

- Scoping caporeparto→solo proprio reparto (rimandato, non richiesto ora)
- Alert automatici/notifiche email sul gap SDS (è un sotto-progetto separato, "alert automatici sulle revisioni")
- Dashboard/widget riassuntivo in home (non richiesto)
