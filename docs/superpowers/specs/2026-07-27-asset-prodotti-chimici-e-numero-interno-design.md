# Design — Numero interno opt-in + Asset "Prodotto chimico" collegato alle SDS

Data: 2026-07-27
Branch: `feature/assets-prodotti-chimici`
Stato: design approvato (in attesa di review dello spec prima del piano di implementazione)

## Contesto

Due interventi indipendenti nel modulo `assets`, richiesti insieme:

- **A) Numero interno opt-in.** Oggi `Asset.save()` assegna d'ufficio un progressivo a
  `internal_number` quando il campo è lasciato vuoto alla creazione
  (`assets/models.py:166-179`, feature "3.3"). Il committente vuole che il numero
  interno diventi **davvero opzionale**: vuoto = nessun numero; il progressivo si
  "prende" solo su richiesta esplicita.
- **B) Sezione "Prodotti chimici" negli asset.** Un prodotto chimico deve poter
  esistere come **asset di prima classe** (asset_tag, QR, inventario, export, filtro),
  con una **schermata dedicata** diversa da quella di un asset IT/macchina, e
  **collegato** all'anagrafica chimica già esistente.

### Vincolo architetturale preesistente

Esiste già il modulo `schede_sicurezza`, committato e cablato su `/schede-sicurezza/`,
con:

- `ProdottoChimico` (nome, fornitore, produttore, reparto, famiglia/sottocategoria,
  `numero_interno`, codice prodotto, ubicazione, quantità, `dpi_obbligatori`,
  riferimenti legacy `tag_id`/`asset_id_legacy`/`new_asset_id_legacy`);
- `SchedaSicurezza` versionata (PDF su storage privato cifrato, pittogrammi, frasi
  H/P, classificazione CLP, primo soccorso, incompatibilità, estrazione PDF,
  `is_corrente`, scadenza a ~36 mesi);
- `PresaVisioneScheda`, report compliance, QR, ingestion PDF.

Il modello `ProdottoChimico` documenta una scelta deliberata: *"nessuna FK ad
`assets.Asset`: quel modello copre IT/macchinari, non contenitori chimici"*.

Questo design **rivede** quella scelta introducendo un collegamento 1:1, mantenendo
`schede_sicurezza` come **fonte unica** dei dati chimici/SDS.

## Decisioni approvate

1. **Approccio**: nuovo tipo asset "Prodotto chimico" + link al `ProdottoChimico`
   condiviso; schermata e form dedicati sul modello del pattern per-tipo già esistente
   (`WORK_MACHINE`/`CNC`).
2. **Relazione**: `OneToOne` — un prodotto chimico ↔ un solo asset-contenitore.
3. **Doppio ingresso**: si crea/aggancia sia da `assets` sia da `schede_sicurezza`,
   condividendo lo **stesso** record `ProdottoChimico`.
4. **Creazione inline libera**: chi può creare asset può anche creare al volo un nuovo
   `ProdottoChimico` collegato (nessun gating aggiuntivo sul permesso SDS).
5. **Numero interno opt-in**: campo vuoto di default + bottone "Assegna progressivo".

## A) Numero interno opt-in

### Modello
- `assets/models.py`: rimuovere il blocco di auto-assegnazione in `Asset.save()`
  (`self._state.adding and not internal_number` → `next_numeric(...)`). Il campo resta
  `CharField(blank=True, default="")`; vuoto salva vuoto.
- `core/numbering.py` invariato (`next_numeric` resta la logica del prossimo numero).
  Nota: `next_numeric` è usato anche da `anagrafica` (codice corso) — **non toccarlo**.

### Endpoint "prossimo progressivo"
- Nuova view GET (es. `assets:internal_number_next`) che ritorna JSON
  `{"next": <int>}` calcolato con `next_numeric(Asset.objects.values_list(
  "internal_number", flat=True))`.
- Protetta dalla **stessa ACL** del create asset. Endpoint API/AJAX → risponde
  `401/403` in JSON, non redirect HTML (regola di progetto).

### Form/UI
- Nel form asset (`AssetForm` e `WorkMachineAssetForm`) accanto a `internal_number`:
  bottone **"Assegna progressivo"** che chiama l'endpoint e riempie il campo (poi
  editabile a mano). Piccolo JS inline / HTMX; nessun submit implicito.
- Nessun placeholder che "assegna" da solo: il default è **vuoto**.

### Test
- Aggiornare `assets/tests_numbering_p3.py`:
  `test_internal_number_progressivo_alla_creazione` cambia semantica → la creazione con
  campo vuoto **non** assegna più (resta vuoto). Mantenere il test "esplicito non
  sovrascritto".
- Nuovo test per l'endpoint (valore corretto + 403 senza permesso).

## B) Asset "Prodotto chimico"

### Modello (`assets/models.py`)
- Nuova costante/scelta: `TYPE_CHEMICAL = "PRODOTTO_CHIMICO"`, etichetta "Prodotto
  chimico", aggiunta a `TYPE_CHOICES`.
- Nuovo campo:
  ```python
  prodotto_chimico = models.OneToOneField(
      "schede_sicurezza.ProdottoChimico",
      on_delete=models.SET_NULL,
      null=True, blank=True,
      related_name="asset_container",
  )
  ```
  String-ref → nessun ciclo di import (`schede_sicurezza` non importa `assets`).
- Migration: aggiunta campo + scelta. Nessun backfill.
- `internal_number` non è usato per gli asset chimici: in schermata si mostra il
  `numero_interno` del prodotto (fonte unica). Il bottone "Assegna progressivo" non
  compare nel form chimico.

### Fonte unica dei dati
I dati chimici/SDS **restano** in `schede_sicurezza`. L'`Asset` porta solo l'identità
asset (asset_tag, stato, reparto, note, QR) + il link. Il PDF SDS **non** viene copiato:
resta su `PrivateSchedaSicurezzaStorage`, l'asset lo linka.

### Schermata dedicata (dettaglio + form)
Ramo per-tipo nel dettaglio/form come per `WORK_MACHINE`/`CNC`.

**Mostra** (dal `ProdottoChimico` collegato + `scheda_corrente()`):
- **Pittogrammi CLP in evidenza** (icone) + stato scheda (corrente / scaduta);
- pericolosità: frasi H, frasi P, classificazione CLP;
- sicurezza operativa: DPI obbligatori (chip), primo soccorso (sez. 4),
  incompatibilità (sez. 10);
- logistica: ubicazione, quantità presente, codice prodotto, fornitore/produttore,
  famiglia/sottocategoria, **numero interno del prodotto**;
- SDS: anteprima/link PDF corrente, versione, data revisione fornitore, stato presa
  visione operatori.

**Nasconde** per i chimici (rispetto agli altri asset):
- produttore/modello/seriale IT (sostituiti da fornitore/produttore del prodotto);
- flag PART 145 + blocchi/tab specifici macchina di lavoro / CNC;
- sezione manutenzioni / collaudi (scadenzario, work order, costi manutenzione);
- cartelle SharePoint IT + assegnatario/responsabile (si usano reparto/ubicazione);
- **assistenza / copertura amministrativa**: status band "copertura + scadenze",
  contratti di assistenza, scadenze amministrative e relativi costi.

Riferimenti concreti da nascondere nel template `asset_detail.html`: lo status band
"copertura + scadenze" (~riga 287/620), il blocco "Scadenze amministrative eseguite"
(~riga 818), i costi manutenzione/scadenze (~riga 898-906), e i rami
`asset_type == "WORK_MACHINE"/"CNC"` (~riga 453/1456/1717). La schermata chimica è un
ramo `asset_type == "PRODOTTO_CHIMICO"` che rende solo i blocchi pertinenti.

### Doppio ingresso & creazione
- **Da assets**: form chimico dedicato (`ChemicalAssetForm`, sul modello di
  `WorkMachineAssetForm`, con vista create/edit dedicata) con:
  - select-ricerca sui `ProdottoChimico` esistenti **+ "Crea nuovo" inline** (nome,
    fornitore, produttore, reparto, ubicazione, quantità, codice, famiglia/
    sottocategoria; PDF SDS caricabile subito o dopo in schede_sicurezza);
  - salvataggio: crea/aggancia il `ProdottoChimico` e crea l'`Asset` collegato.
- **Da schede_sicurezza**: toggle opzionale *"Crea anche l'asset in inventario"* sul
  form `ProdottoChimico` → crea l'`Asset` di tipo chimico collegato. Questa parte fa
  sì che `schede_sicurezza` importi `assets` in una view/service (dipendenza soft, a
  senso unico, nessun ciclo a livello di modelli).
- **Anti-doppione**: la relazione `OneToOne` impedisce due asset sullo stesso prodotto;
  validazione nel form con messaggio chiaro.

### ACL, errori, privacy
- **ACL**: gli asset chimici stanno sotto i permessi `assets` esistenti; i dati SDS
  restano sotto ACL `schede_sicurezza`. Creazione inline del prodotto: libera per chi
  gestisce asset (decisione 4).
- **Errori**: prodotto senza scheda corrente → la schermata mostra "SDS non
  disponibile" senza rompere; asset chimico con link nullo (prodotto cancellato,
  `SET_NULL`) → banner "prodotto non collegato".
- **Privacy**: nessuna copia del PDF; solo link allo storage privato cifrato esistente.

## Testing

- `assets`: creazione asset chimico (aggancio esistente + crea-nuovo inline);
  rendering schermata (`assertContains` pittogrammi/DPI/CLP/ubicazione,
  `assertNotContains` campi nascosti: PART145, manutenzioni, copertura amministrativa);
  numero interno opt-in (vuoto resta vuoto) + endpoint prossimo progressivo.
- `schede_sicurezza`: toggle "crea asset" crea l'`Asset` collegato; `OneToOne` blocca
  i doppioni.
- ACL: 403 JSON su endpoint protetto senza permesso.
- Usare `@override_settings(LEGACY_AUTH_ENABLED=False)` nelle view test (altrimenti
  l'ACL nega tutto ai non-superuser → 403 dal middleware, non dal gate testato).
- Eseguire solo i test degli app toccati:
  `python django_app\manage.py test django_app.assets django_app.schede_sicurezza --keepdb --settings=config.settings.test`.

## Documentazione (obbligatoria a fine lavoro)

- `CHANGELOG.md`: voce sotto `[Unreleased]` con tutti i file modificati.
- `README.md`: catalogo moduli e/o sezione assets (nuovo tipo asset + link SDS).
- Se cambia comportamento visibile: seguire la checklist di version-bump.

## Fuori scope (YAGNI)

- Nessuna migrazione automatica dei `ProdottoChimico` esistenti verso asset (l'aggancio
  è manuale/opzionale).
- Nessuna modifica alla logica di estrazione SDS o ai report compliance.
- Nessun cambiamento a `core/numbering.py` oltre all'uso già presente.
- Nessuna gestione "multi-contenitore" per prodotto (relazione 1:1 approvata).
