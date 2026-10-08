# `glossario_tecnico` — glossario tecnico metalmeccanico e SGI

Area **Qualità** · URL `/glossario/` · codice [`django_app/glossario_tecnico/`](../../django_app/glossario_tecnico/)

[← Catalogo moduli nel README](../../README.md#-catalogo-moduli)

## Sintesi

Termini di lavorazione, quotatura, tolleranze dimensionali e geometriche, rugosità, filettature, trattamenti, controllo qualità e sigle del sistema di gestione. Ogni termine ha sinonimi, gergo d'officina, sigle, simboli (es. lamatura = spot face = ⌴) e traduzione inglese. La Qualità valida i termini: solo quelli validati serviranno all'assistente AI (fase B2).

## Dettaglio

- **Modelli**: `Termine` (forma canonica, inglese, categoria, definizione con parole nostre, simbolo, esempio a disegno, solo il *codice* della norma, stato bozza/validato/deprecato, fonte, «usa nell'assistente», note interne mai mostrate all'AI) e `Variante` (sinonimo, gergo, sigla, simbolo, traduzione, grafia errata). La **chiave** della variante (minuscolo, senza accenti, spazi singoli) è univoca: una variante appartiene a un solo termine e i conflitti vengono segnalati, mai risolti in silenzio.
- **Elenco iniziale**: ~85 termini in **bozza** (migrazione 0002): lavorazioni, quotatura, tolleranze ISO, le caratteristiche GD&T con riferimento/MMC/LMC/zona proiettata, rugosità, filettature, trattamenti termici e superficiali, controlli (FAI, ballonatura, CMM, calibri, caratteristiche chiave), sigle SGI. Le sigle aziendali di cui non è documentata l'espansione (MT, MTSI, IDOR, IDPR, CN) sono descritte per funzione, con una nota «da confermare».
- **Elenco**: ricerca su termine, inglese, simbolo e varianti (es. «spot face» o «⌴» trovano la lamatura); filtri per categoria e stato.
- **Scheda termine**: definizione, esempio a disegno, norma, stato e chi l'ha validato; varianti aggiunte e tolte in linea (HTMX).
- **Da rivedere** (`/glossario/revisione/`): bozze da validare (Valida / Correggi / Scarta) e proposte dell'AI (Accetta / Correggi / Scarta). Ogni decisione sulle proposte finisce in `AiProposta`, così le proposte successive tengono conto delle correzioni.
- **Import CSV**: `glossario_import_csv --file X.csv [--dry-run]`, colonne `termine;termine_en;categoria;definizione;simbolo;norma_rif;varianti` con varianti `tipo:testo` separate da `|` (pensato per un export IATE filtrato a mano). Righe importate in bozza; le righe con errori vengono scartate per intero e riportate.
- **Candidati dai documenti SGI**: `glossario_candidati [--limit N] [--min-documenti N] [--ai] [--sincrono]` legge il testo persistito dei documenti SGI (`sgi_estrai_testi`) e propone le espressioni di 1–3 parole presenti in almeno N documenti e non ancora nel glossario. Esclude i nomi degli utenti del portale. Con `--ai` l'LLM on-premise propone termine, categoria, definizione e varianti (un task per gruppo di 5, < 90 s); le proposte restano in attesa finché una persona non le accetta.
- **Permessi (ACL v2)**: `glossario_tecnico.termini.view` (consultazione, tutti i ruoli) e `glossario_tecnico.gestione` (inserire, modificare, validare, decidere le proposte: ruoli admin e qualità). L'Ufficio tecnico si abilita per utente o gruppo in Admin › ACL. Le API (`/glossario/api/`) rispondono sempre JSON, anche 401/403.
- **Menu**: categoria «Qualità» della barra (`riorganizza_topbar`).

## Comandi

```powershell
python django_app\manage.py migrate glossario_tecnico
python django_app\manage.py glossario_import_csv --file termini.csv --dry-run
python django_app\manage.py glossario_candidati --limit 30
python django_app\manage.py glossario_candidati --limit 20 --ai
python django_app\manage.py riorganizza_topbar --apply
```

## Note di rilascio

- **B1 (10/2026)**: app nuova, migrazioni 0001 (schema) e 0002 (elenco iniziale, reversibile). Nessun effetto sull'assistente finché non arriva la fase B2 (`OLLAMA_RAG_GLOSSARIO_ENABLED`).
