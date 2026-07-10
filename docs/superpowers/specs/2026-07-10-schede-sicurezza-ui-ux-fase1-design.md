# Design — UI/UX Fase 1 (`schede_sicurezza`, sotto-progetto "Fase 2" #2)

Data: 2026-07-10
Modulo: `schede_sicurezza` (Fase 1 + Report compliance già completi, non pushati)

## Contesto

Secondo sotto-progetto della "Fase 2" richiesta dall'utente (dopo Report compliance, vedi `docs/superpowers/specs/2026-07-09-schede-sicurezza-report-compliance-design.md`). Rifinisce la UI esistente di Fase 1 con quattro migliorie scelte dall'utente tra le opzioni proposte in brainstorming.

## Obiettivo

1. **Filtri lista prodotti**: reparto, famiglia, stato scheda (con/senza/da rivedere)
2. **Badge scadenze SDS**: segnalazione visiva quando una scheda non viene aggiornata da troppo tempo
3. **Editing manuale campi estratti**: correggere a mano pittogrammi/frasi H-P/classificazione CLP/DPI testo/primo soccorso/incompatibilità quando l'estrazione automatica è parziale o sbagliata
4. **CTA reparto mancante**: aiuto quando la select reparto nel form prodotto è vuota

## Decisioni chiave (dalle domande di chiarimento)

- **Soglia scadenza**: 36 mesi da `SchedaSicurezza.data_caricamento` (non da `data_revisione_fornitore`, campo opzionale e spesso vuoto). Costante `SCADENZA_SDS_GIORNI = 1095` (~36 mesi, calcolo a giorni per semplicità — nessuna dipendenza da `dateutil`).
- **Editing campi estratti**: sezione inline nella pagina dettaglio prodotto esistente (`/schede-sicurezza/<pk>/`), non una pagina separata. Editabile solo la **scheda corrente** (se non esiste, nessuna sezione da mostrare).
- **Gestione reparto mancante**: **nessuna nuova UI di creazione reparto**. Esiste già `anagrafica:aree_list` (tab "+ Reparto", gated `is_admin` lato anagrafica — verificato sul codice reale, `anagrafica/views.py` righe ~5472+, `anagrafica/urls.py:150,156-158`). `schede_sicurezza` si limita a **linkare** quella pagina quando la select reparto è vuota, senza duplicare la logica `is_admin` (permesso diverso da `PERM_GESTISCI` di questo modulo — un caporeparto può gestire prodotti chimici ma non necessariamente creare reparti). La pagina di destinazione gestisce da sola la propria autorizzazione.
- **Filtri "stato scheda"**: `da_rivedere` riusa la stessa soglia di 36 mesi del badge (stessa fonte di verità, nessuna logica duplicata). `senza_scheda` riusa `schede_sicurezza.reports.prodotti_senza_scheda_corrente()` già esistente (Report compliance) invece di reimplementare il filtro.

## Componenti

### 1. Modello — `SchedaSicurezza.scaduta` (property)

In `schede_sicurezza/models.py`, vicino alla classe `SchedaSicurezza`:

```python
SCADENZA_SDS_GIORNI = 1095  # ~36 mesi
```

Property sul modello:

```python
@property
def scaduta(self) -> bool:
    from datetime import timedelta
    from django.utils import timezone
    if not self.data_caricamento:
        return False
    soglia = timezone.now().date() - timedelta(days=SCADENZA_SDS_GIORNI)
    return self.data_caricamento.date() < soglia
```

Nessuna migrazione (property Python, non un campo DB).

### 2. Filtri lista prodotti (`prodotto_list` view + template)

View: aggiunge lettura di 3 nuovi GET param (`reparto`, `famiglia`, `stato`) e applica filtri incrementali sul queryset esistente:
- `reparto=<id>` → `.filter(reparto_id=reparto_id)`
- `famiglia=<valore>` → `.filter(famiglia=valore)`
- `stato=senza_scheda` → intersezione con `prodotti_senza_scheda_corrente()` (via `.filter(pk__in=prodotti_senza_scheda_corrente())`, riusando la funzione già esistente come unica fonte di verità per questa condizione)
- `stato=con_scheda` → `.filter(schede__is_corrente=True).distinct()`
- `stato=da_rivedere` → prodotti con scheda corrente E quella scheda scaduta, filtrato sulla soglia direttamente in query (non sulla property Python, che serve solo per i template): `.filter(schede__is_corrente=True, schede__data_caricamento__lt=soglia).distinct()`

Template: 3 `<select>` (reparto, famiglia, stato) nel form di ricerca esistente, preservano i valori in querystring insieme a `q`. Dropdown `reparto` da `Reparto.objects.filter(is_active=True).order_by("nome")`; dropdown `famiglia` da valori distinti non vuoti (`ProdottoChimico.objects.exclude(famiglia="").values_list("famiglia", flat=True).distinct().order_by("famiglia")`).

Badge scadenza per riga: se `prodotto.scheda_corrente` esiste ed è `.scaduta`, badge "Da rivedere" accanto al badge versione già esistente in `prodotto_list.html`.

### 3. Editing campi estratti (`prodotto_detail` view + template)

View: la POST esistente su `prodotto_detail` gestisce solo l'upload nuova SDS (branch su `request.FILES.get("pdf")`). Si aggiunge un secondo branch, distinto da un campo hidden `form_type`:

```python
if request.method == "POST":
    if request.POST.get("form_type") == "modifica_campi_estratti":
        # ... aggiorna scheda corrente, redirect
    else:
        # ... branch esistente upload PDF (invariato)
```

Il branch di modifica: richiede `_can_gestire` (già garantito, l'intera vista lo richiede su GET), richiede che esista una `scheda_corrente()`, aggiorna i campi:
- `pittogrammi`, `frasi_h`, `frasi_p`: input testo comma-separated → `[s.strip() for s in valore.split(",") if s.strip()]`
- `classificazione_clp`, `dpi_testo`, `primo_soccorso`, `incompatibilita`: textarea diretta

Template: nuova sezione "Modifica campi estratti" nel dettaglio prodotto, visibile solo se `scheda_corrente` esiste e `can_gestire`. Pre-compilata coi valori correnti (liste unite con `", "` per i campi JSON).

### 4. CTA reparto mancante (`prodotto_form.html`)

Nel template, se `reparti` (queryset passato dal contesto) è vuoto: messaggio con link a `{% url 'anagrafica:aree_list' %}` invece della sola select vuota. Nessuna modifica alla view (il queryset `reparti` è già nel context).

## Testing

- `SchedaSicurezza.scaduta`: scheda con `data_caricamento` recente → `False`; scheda con `data_caricamento` > 1095gg fa (creata con `data_caricamento` forzata via `update()` post-creazione, dato `auto_now_add`) → `True`; nessuna eccezione se `data_caricamento` è None (caso teorico, il campo è sempre auto-popolato ma il property resta difensivo)
- Filtri lista: per ciascun valore di `stato` (`con_scheda`/`senza_scheda`/`da_rivedere`) verificare che il queryset risultante sia quello atteso con fixture miste; filtro `reparto`/`famiglia` con prodotti di reparti/famiglie diverse
- Editing campi: POST con `form_type=modifica_campi_estratti` aggiorna la scheda corrente; POST senza `scheda_corrente` non fa nulla di distruttivo (redirect con messaggio errore); parsing comma-separated con spazi/virgole doppie non produce elementi vuoti
- CTA reparto: template test — nessun reparto in DB → link presente; almeno un reparto → link assente (select normale)

## Fuori scope di questo sotto-progetto

- Creazione/gestione reparti dentro `schede_sicurezza` (si linka `anagrafica`, non si duplica)
- Notifiche/alert automatici sulle schede scadute (prossimo sotto-progetto "alert revisioni")
- Editing bulk/multi-scheda, storico modifiche ai campi curati (nessun audit trail sulle correzioni manuali in questa fase)
