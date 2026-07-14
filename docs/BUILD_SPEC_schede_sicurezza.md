# BUILD_SPEC — App `schede_sicurezza` (Fase 1)
### NOVICROM HUB · Sezione Schede di Sicurezza Prodotti Chimici · Bando Buone Pratiche 2026

> Feed questo file a Claude Code come specifica di implementazione autonoma.
> Obiettivo: portare a "realizzato e in uso" il nucleo del modulo entro fine luglio.
> **AI copilot, alert versioni e verifica consegne DPI sono FUORI SCOPE (Fase 3).**

---

## 0. Vincoli operativi (non negoziabili)

- **Rispetta `CLAUDE.md`**: subagent **sequenziali**, mai paralleli (saturazione RAM). Un solo lead; eventuali subagent uno alla volta.
- **Read-before-write**: nessuna riga di codice prima di aver completato la Fase A (ricognizione).
- **Additivo, non distruttivo**: **non modificare** i modelli/migrazioni esistenti di `dpi` e `procedure_refresh`. Ci si collega, non li si tocca.
- Compatibilità **SQL Server (prod) + SQLite (dev)**: usa solo campi/costrutti supportati da `mssql-django`. Verifica `JSONField` su SQL Server prima di adottarlo; in alternativa TextField con serializzazione.
- **Test `pytest` verdi** come condizione di completamento. Nessun task chiuso con test rossi o migrazioni pendenti.
- Segui le **convenzioni delle app esistenti** (struttura cartelle, naming italiano dei modelli come `ProdottoChimico`, ACL v2, navigation registry, HTMX). Non introdurre pattern nuovi se ne esiste già uno nel repo.
- `/compact` prima di sessioni a contesto pesante; aggiungi i PDF SDS di esempio a `.claudeignore`.

---

## 1. Obiettivo di Fase 1

Creare l'app Django `schede_sicurezza` che gestisce l'archivio delle SDS con:
1. Modelli prodotto chimico + scheda versionata, ancorati all'unità organizzativa (reparto) esistente.
2. Ingestion PDF con **PyMuPDF** → estrazione section-aware → pre-compilazione di campi **curabili** (non ci si affida al 100% all'automatismo).
3. Collegamento **M2M ai DPI** obbligatori (`dpi.DPICategoria` — nome reale da confermare in Fase A).
4. **QR code** per prodotto/contenitore → **vista mobile** della scheda sintetica.
5. **Presa visione tracciata**, riusando il meccanismo di `procedure_refresh`.

**Fuori scope Fase 1 (NON implementare):** assistente AI/RAG, alert automatici sulle revisioni, verifica della consegna DPI per operatore, integrazione DVR.

---

## 2. Fase A — Ricognizione obbligatoria (prima di scrivere)

Leggi e produci una nota `RECON.md` (breve) che riporti i **nomi e le firme reali** trovati, NON supposti:

- `dpi/models.py` (intero): nome esatto del modello categoria DPI e del suo campo immagine; modello richiesta e ciclo richiesta→approvazione→consegna; come si costruisce l'URL di avvio richiesta.
- `procedure_refresh/models.py` e relative view/service: come è modellata la **presa visione tracciata** (modello, campi utente/data/documento, unicità). Decidi se **estendere** quel meccanismo o **specchiarne il pattern** in un modello locale `PresaVisioneScheda`. Motiva in `RECON.md`.
- Modello dell'**unità organizzativa/reparto** già esistente (in `assets`, `anagrafica` o core). Il prodotto chimico si aggancia a QUELLO via FK; non creare un nuovo concetto di reparto se esiste.
- Chiave dipendente/operatore in uso nel portale (es. `legacy_anagrafica_id`): usala per collegare la presa visione all'operatore, coerentemente con le altre app.
- **ACL v2**: come si registra un permesso e come si gating-a una view; **navigation registry**: come si registra una voce di menu; **context processor** e layout base dei template.
- Un'app di riferimento con **lista + dettaglio HTMX** da imitare per struttura view/template/URL.
- `config/settings/base.py`: storage privato per file caricati (pattern già usato es. in `timbri`), validazione upload esistente (MIME/magic bytes se presente), dipendenze (`PyMuPDF`/`fitz`, `qrcode`, `python-magic` — verifica presenza in `requirements`/`pip-tools`).

Chiudi la Fase A elencando le eventuali **discrepanze** tra questo spec e la realtà del codice, e adatta lo spec a valle (i nomi reali vincono).

---

## 3. Modelli (`schede_sicurezza/models.py`)

Design intenzionale; adatta i target FK ai nomi reali della Fase A.

### `ProdottoChimico`
- `nome` (CharField), `fornitore` (CharField), `produttore` (CharField, opz.)
- `reparto` → **FK all'unità organizzativa esistente** (es. `assets.Asset` o modello reparto reale)
- `uuid` (UUIDField, `default=uuid4`, `unique`, `editable=False`) → **usato negli URL pubblici del QR** (mai la PK, per evitare enumerazione/IDOR)
- `attivo` (BooleanField)
- timestamps (created/updated) coerenti con le altre app
- M2M `dpi_obbligatori` → **modello categoria DPI reale** (`related_name` sensato, `blank=True`)

### `SchedaSicurezza` (versionata)
- FK `prodotto` → `ProdottoChimico` (`related_name="schede"`)
- `pdf` (FileField su **storage privato**, NON webroot; upload servito da view autenticata)
- `versione` (CharField), `data_revisione_fornitore` (DateField, null=True)
- `data_caricamento` (auto), `caricata_da` (FK utente)
- `is_corrente` (BooleanField) — una sola scheda corrente per prodotto (garanzia a livello di service/save)
- Campi **curati** pre-compilati dall'estrazione ma **editabili** da RSPP/sicurezza:
  - `pittogrammi` (lista — JSONField se supportato, altrimenti TextField)
  - `frasi_h` (lista/TextField), `frasi_p` (lista/TextField)
  - `dpi_testo` (TextField — sezione 8 grezza, per riferimento)
  - `primo_soccorso` (TextField — sezione 4)
  - `incompatibilita` (TextField — sezione 10)
  - `estratto_grezzo` (JSON/Text: mappa sezione→testo, per tracciabilità dell'estrazione)
  - `estrazione_stato` (choices: `non_eseguita` / `ok` / `parziale` / `fallita`)

### `PresaVisioneScheda` (o estensione di `procedure_refresh` — decisione in Fase A)
- riferimento a `SchedaSicurezza` (così la presa visione è legata alla **versione** vista)
- operatore (coerente con la chiave dipendente reale), `data`, eventuale `note`
- unicità (operatore, scheda) per evitare doppioni; storicizzazione sulle nuove versioni

Registra i modelli in `admin.py` con list_display/filtri utili.

---

## 4. Ingestion PDF (PyMuPDF, section-aware)

`schede_sicurezza/services/ingestion.py`:

- Estrai il testo con PyMuPDF (`fitz`) e segmenta secondo la **struttura standard SDS a 16 sezioni** (Reg. UE 2020/878). Individua gli header di sezione in modo robusto (numero + titolo, tollerante a maiuscole/spazi/lingua IT).
- Mappa: **sez. 2** → pittogrammi + frasi H/P; **sez. 4** → primo soccorso; **sez. 8** → DPI/controllo esposizione; **sez. 10** → incompatibilità/reattività. Salva anche l'estratto grezzo per sezione.
- **Robustezza**: l'estrazione è best-effort. Se una sezione non è individuabile, imposta `estrazione_stato=parziale/fallita` e lascia i campi vuoti — **la scheda deve funzionare comunque** con inserimento manuale. L'estrazione **pre-compila**, non è un requisito bloccante.
- Nessuna dipendenza da servizi esterni/AI in questa fase.
- Fornisci un management command `estrai_sds <scheda_id>` per rilanciare l'estrazione su una scheda esistente.

**Sicurezza upload**: valida il PDF con **magic bytes** (`python-magic`), non solo estensione (rif. finding A6 del portale). Rifiuta se il MIME reale non è `application/pdf`.

---

## 5. QR code + vista mobile

- `services/qr.py`: genera il QR (lib `qrcode`) che punta all'URL pubblico basato su `ProdottoChimico.uuid` (es. `/schede-sicurezza/s/<uuid>/`). QR scaricabile/stampabile dal dettaglio prodotto (PNG/SVG).
- **Vista mobile** (`templates/schede_sicurezza/scheda_mobile.html`): rendering della **scheda sintetica** della versione corrente — pittogrammi, frasi H/P, **DPI obbligatori con immagine** (da `DPICategoria`), primo soccorso in evidenza, incompatibilità. Layout mobile-first, coerente con lo stile del portale.
- **Accesso (decisione da confermare, default sicuro):** la vista è **gated dietro login** con permesso ACL `schede_sicurezza.view_scheda`. Predisponi il codice così che un'eventuale variante a **token pubblico non indicizzabile** (per scansione da dispositivo non loggato in reparto) sia attivabile in seguito senza rifattorizzare gli URL. Non aprire nulla di pubblico ora.
- Il download del PDF passa **sempre** da una view autenticata che legge dallo storage privato (mai link diretto a file su disco/webroot).

---

## 6. Presa visione

- Azione **HTMX** dalla vista scheda: l'operatore autenticato attesta la presa visione della **versione corrente** → crea/aggiorna `PresaVisioneScheda` (o record `procedure_refresh`), con data e utente. Idempotente per (operatore, versione).
- Alla pubblicazione di una **nuova versione** della scheda, la presa visione precedente non copre la nuova (storicizzazione): lo stato "da rivedere" deve essere derivabile per reporting futuro.
- Vista elenco prese visione per scheda (base, per audit trail) accessibile a ruoli sicurezza.

---

## 7. Integrazione portale

- **ACL v2**: registra i permessi (`view_scheda`, gestione prodotti/schede per ruoli sicurezza) secondo il pattern reale. Nessuna view senza gating.
- **Navigation registry**: voce di menu nell'area Sicurezza/Compliance, coerente con `dpi`, `procedure_refresh`, `rilevazione_incidenti`.
- **URL/urls.py**: lista prodotti, dettaglio prodotto (con QR + upload nuova versione), vista mobile per uuid, download PDF autenticato, azione presa visione, elenco prese visione.
- **Views**: lista + dettaglio con HTMX come nelle app esistenti; form upload SDS con validazione MIME.

---

## 8. Migrazioni & dipendenze

- Genera le migrazioni e verificane l'applicabilità **su SQLite (dev)**; annota in `RECON.md` eventuali rischi lato SQL Server (in particolare `JSONField`).
- Aggiungi a `pip-tools`/`requirements` solo ciò che manca (`PyMuPDF`, `qrcode[pil]`, `python-magic`), poi ricompila i lock come da prassi del repo.

---

## 9. Test (`pytest`) — obbligatori e verdi

Copertura minima:
- Modelli: creazione prodotto/scheda, vincolo "una sola scheda corrente", storicizzazione versioni.
- Ingestion: su **1 PDF SDS di esempio** (fixture, in `.claudeignore` se pesante) → verifica che i campi curati vengano popolati e che un PDF malformato porti a `estrazione_stato=fallita` senza eccezioni non gestite.
- Upload: rifiuto di file con estensione `.pdf` ma MIME non-PDF (magic bytes).
- QR: generazione e URL basato su `uuid` (non PK).
- Presa visione: creazione, idempotenza, storicizzazione su nuova versione.
- ACL: la vista scheda è negata all'utente senza permesso; il download PDF non è raggiungibile senza auth.

---

## 10. Definition of Done

- [ ] `RECON.md` prodotto, discrepanze risolte, nomi FK reali adottati.
- [ ] App `schede_sicurezza` con modelli, migrazioni applicate su dev, admin registrato.
- [ ] Ingestion PyMuPDF section-aware + command `estrai_sds`, robusta ai fallimenti.
- [ ] Collegamento M2M ai DPI reali con immagini in vista mobile.
- [ ] QR + vista mobile scheda sintetica, gating ACL, download PDF autenticato da storage privato.
- [ ] Presa visione tracciata (riuso `procedure_refresh` o modello locale motivato).
- [ ] Voce menu + permessi ACL registrati.
- [ ] Suite `pytest` **verde**, nessuna migrazione pendente.
- [ ] Nessuna modifica distruttiva a `dpi` / `procedure_refresh`.

Al termine, produci un **report sintetico**: cosa fatto, decisioni prese in Fase A, file toccati, come testare a mano il flusso (carica SDS → estrai → genera QR → apri mobile → presa visione), e cosa resta esplicitamente per la Fase 3.
