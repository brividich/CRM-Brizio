# Piano vivo — Workflow PDF & MOD.133 (Gestione Specifiche)

> **Documento vivo**: memoria, stato avanzamenti e "chi fa cosa" dell'iniziativa che
> automatizza nel portale la gestione documentale delle specifiche (cover, MOD.133,
> protezione, ciclo di vita sulla share). **Aggiornare ad ogni step** (vedi §9 Registro).
>
> Ultimo aggiornamento: **2026-07-01**. Owner: DM + team dev. Piattaforma: **il portale**
> (ARXivar scartato; eventuali plugin in futuro).

---

## 0. Scopo (una frase)
Far fare al **portale**, in automatico e tracciato, ciò che oggi il **DM fa a mano in
Adobe/ARXivar**: caricare una nuova revisione, mettere la cover "in attesa MOD.133",
compilare il MOD.133 (assistito dall'AI), sostituire la cover col MOD.133 compilato,
applicare filigrana + password-permessi, e gestire nuove/superate **direttamente sul
percorso UNC** (`\\novisrv\Area Produzione\SPECIFICHE`) che è il riferimento aziendale.

## 1. Stato a colpo d'occhio
| Blocco | Stato |
|---|---|
| Intake specifiche (metadati) da export gestionale | ✅ in prod (2515 SPTE + 786 Cliente) |
| Collegamento PDF sulla share (`percorso_esterno`) | ✅ 771 collegati (path esatto) · 🔜 `--fallback-nome` da lanciare dopo redeploy |
| F0 — visione PDF dalla scheda | ✅ codice pronto · ⏳ da deployare + LETTURA app-pool |
| F1 — Detector/inventario MOD.133 vs cover | ✅ costruito+integrato (test verdi) · ⏳ da lanciare in prod |
| F2 — Ingestion + gestione file sulla share | ✅ service+comando costruiti+testati (dry-run/rollback/audit) · ⏳ dry-run reale su share da fare |
| F3 — Toolkit PDF (componi + proteggi) | ✅ costruito+integrato (test verdi) |
| F4 — Renderer MOD.133 | ✅ costruito+integrato (test verdi) |
| F5 — AI diff rev↔rev → pre-compila MOD.133 | ✅ copilota+endpoint costruiti+testati (offline) |
| F6a — Composito ufficiale (offline: render+componi+proteggi) | ✅ costruito+testato |
| F6b — Aggancio FSM + deposito share + flag protezione UI | ⏳ da fare (con revisione utente sulle scritture) |
| F7 — Conformità alla Matrice ARXivar | ✅ checklist prodotta (portale già ampiamente conforme + backlog gap) |
| UI — pulsante diff copilota + info cartella share | ✅ fatto (stile gs-*) |

## 2. Decisioni prese (LOCKED — non ri-discutere senza motivo)
- **Piattaforma = portale**; ARXivar scartato. La `Matrice_Workflow_ARXivar.xlsx` è ora la
  **specifica di conformità** (checklist), non una seconda implementazione.
- **La share è il riferimento unico** per tutti → il PDF resta sul master; il portale
  **collega** (`percorso_esterno`), non copia (salvo modalità copia alternativa).
- **Il portale SCRIVE sulla share** (automatico): deposita la nuova revisione, sposta la
  superata in `_SUPERATO`, aggiorna il collegamento. Regola d'oro: **move, mai delete** +
  **audit + rollback** di ogni operazione.
- **Ingresso file = dal portale** (il DM carica nel portale, che orchestra tutto).
- **AI = diff semantica** rev. precedente ↔ nuova → **pre-compila la griglia MOD.133**
  (paragrafi modificati / impatto documenti / impatto operativo); l'AI propone, il DM firma.
- **Composito = prodotto e salvato al milestone** (il MOD.133, una volta approvato, è
  congelato → il composito diventa il file "ufficiale" sulla share).
- **Protezione**: default **no-stampa + no-modifica**, **owner-password in `.env`** (unica per
  tutti i documenti), **filigrana** "DOCUMENTO SOLO PER CONSULTAZIONE"; flag **configurabili**
  (pulsanti no stampa / no modifica / …).
- **OCR**: quasi tutti i PDF sono digitali → estrazione testo primaria + **fallback OCR
  leggero** per i pochi scansione-immagine.
- **Storico esistente**: per ora **lasciato com'è**; il nuovo flusso vale dalle nuove
  revisioni in avanti (normalizzazione del pregresso: da valutare).

## 3. Architettura (che nasce dalle decisioni)
1. DM **carica il PDF nel portale** (punto d'ingresso unico).
2. Portale **deposita sulla share** il file ufficiale = **[cover "in attesa"] + [originale]**,
   con **filigrana + password-permessi + flag**; sposta la revisione **superata in
   `_SUPERATO`**; aggiorna `percorso_esterno`.
3. **AI confronta** rev. precedente e nuova → **pre-compila la griglia MOD.133**; DM firma.
4. All'**approvazione MOD.133** → il portale **rigenera e salva** il file sulla share =
   **[pagina MOD.133 compilata dai dati portale] + [originale]** (la cover sparisce),
   ri-protetto → è il **composito ufficiale** a cui punta il collegamento.
- Il **PDF originale non viene mai modificato**; il portale produce **compositi derivati**.
- La **sicurezza serve/scrittura** passa da `share_link` (allowlist + anti-traversal, già
  hardened: canonicalizzazione + `realpath` + `commonpath`).

## 4. Convenzione share (derivata dai path reali, 2477 campioni)
- Struttura: `\\novisrv\Area Produzione\SPECIFICHE\<Cliente|Categoria>\<file>.pdf`
  (a volte `…\<Cliente>\<sottocartella>\<file>.pdf`).
- **48 cartelle di 1° livello**: clienti (LEONARDO ELICOTTERI 703, FERRARI 359, GE AVIO 207,
  LEONARDO OTO MELARA, SALVER, PIAGGIO, MAGNAGHI, KOPTER, APRILIA, RHEINMETALL, SPIRIT…) +
  categorie con prefisso `_` (`_SPECIFICHE GENERICHE`, `UNI-ISO`, `WORK INSTRUCTION`,
  `_SUPERATO`…).
- **Naming file**: dominante **`<CODICE> REV.<rev>.pdf`** (78%); varianti `.REV.`/`_REV.`/
  ` ESP.`/`ED`. Il 92% dei nomi inizia col codice.
- → **Schema canonico F2**: `<Cliente>\<codice> REV.<rev>.pdf`, superate → `_SUPERATO\…`.
  Da **confermare contro la share live** (da prod) prima di scrivere.

## 5. Piano a fasi (ognuna dry-run/testabile)
- **F0 — Visione PDF** ✅: link download in scheda anche per specifiche solo "collegate"
  (`percorso_esterno`). *Deploy + LETTURA app-pool per l'effetto in prod.*
- **F1 — Detector/inventario** 🔜: comando `analizza_pdf_specifiche` (read-only, in prod):
  apre i PDF, estrae testo, classifica **ha MOD.133 / cover "in attesa" / senza / incerto** →
  report CSV. Marcatori: cover = "SPECIFICA IN ATTESA DI COMPILAZIONE MOD.133"; MOD.133 =
  header/tabella del modulo.
- **F2 — Ingestion + share writes** ✅ (service+comando): `share_write.py` +
  `deposita_revisione_share`. Deriva il path canonico (naming §4), **archivia la revisione
  precedente** collegata alla specifica in `_SUPERATO` (move mai delete), aggiorna
  `percorso_esterno` (`.update()`); **dry-run default / `--apply`**, **rollback** su errore,
  **audit** `EventoSpecifica`. Cartella scelta tra quelle **reali** (`elenca_cartelle_consentite`
  / `--lista-cartelle`), nessuna cartella inventata. Collisione: identico→no-op, diverso→rifiuto
  salvo `--forza`. **Da fare**: dry-run REALE contro la share live (da prod) prima del primo
  `--apply`; la supersessione della revisione *precedente come altra Specifica* (+ FSM `supera()`)
  è demandata a **F6**.
- **F3 — Toolkit PDF** (`pdf_compose.py`, isolato/plugin-ready): `componi(cover|mod133 +
  originale)` + `proteggi(filigrana + owner-pw + flag)` con pymupdf.
- **F4 — Renderer MOD.133**: dalla `MOD133` del portale → pagina PDF (reportlab, replica il
  layout del `.docx`: header + griglia 7 colonne + note + compilato/approvato-da).
- **F5 — AI diff rev↔rev** ✅ (copilota + endpoint): `ai_copilota.proponi_righe_da_diff` +
  endpoint `ai_diff_mod133` (ACL `PERM_COMPILA`). Estrae testo delle due revisioni (allegato o
  share) → **diff deterministico a paragrafi** (`difflib`) → LLM interpreta i soli cambiamenti in
  **righe MOD.133** (Copilota; umano firma). Fail-safe, nessuna scrittura, ritorna anche i
  `cambiamenti` per la UI. **Da fare**: bottone/UI nella scheda (F6/UI) e OCR per scansioni.
- **F6a — Composito ufficiale** ✅ (offline): `composito.py` orchestra F4 (render MOD.133) →
  F3 (`anteponi_pagine` + `applica_protezione`) → byte del composito `[MOD.133]+[originale]`
  protetto; `dati_mod133_da_spec` mappa `MOD133`/`RigaMOD133`; originale letto in sola lettura
  (allegato o share). Nessuna scrittura.
- **F6b — Aggancio workflow**: all'approvazione MOD.133 → rigenera+**deposita** il composito sulla
  share (F2); **flag protezione** nella UI; download serve il composito quando c'è MOD.133. **Da
  fare** con revisione utente sulle scritture.
- **F7 — Conformità Matrice**: escalation 14gg, algoritmo copie cartacee, griglie condizionali,
  mappa ruoli→gruppi (dalla `Matrice_Workflow_ARXivar.xlsx`).

## 6. Domande aperte / da confermare
- [ ] Valore **owner-password** da mettere in `.env` come `GESTIONE_SPECIFICHE_PDF_OWNER_PASSWORD`
      (chiave già cablata in `settings.GESTIONE_SPECIFICHE['PDF_OWNER_PASSWORD']`); default flag già
      no-stampa/no-modifica in `pdf_compose.applica_protezione`.
- [ ] La **filigrana** va SEMPRE applicata all'output? (assunto: sì, configurabile).
- [ ] **OCR**: quale motore leggero (es. Tesseract) per i pochi scansione-immagine?
- [ ] **Normalizzazione del pregresso** (i file già sulla share): sì/no/graduale.
- [ ] Conferma **schema naming** contro la share live prima delle scritture F2.
- [ ] La password è **cambiabile** dal portale o resta solo in `.env`?

## 7. Prerequisiti operativi
- **Deploy del branch** aggiornato + `python manage.py migrate gestione_specifiche` (campo
  `percorso_esterno`, mig 0003). Il deploy porta anche: fix mojibake (output ASCII),
  `--fallback-nome`, F0, controllo share robusto nello script.
- **App-pool IIS**: **LETTURA** sulla share (per il download); **SCRITTURA** per F2 in avanti.
- **`.env`**: `GESTIONE_SPECIFICHE_SHARE_ROOTS`, `GESTIONE_SPECIFICHE_SHARE_EXCLUDE`
  (default `_SUPERATO`), e la **owner-password** (F3).
- Setting Python **UTF-8** (già `PYTHONUTF8=1` nello script; oppure output ASCII dopo redeploy).

## 8. Come lo costruiamo — team di agenti (valutazione)
I moduli **F1, F3, F4, F5 sono indipendenti** (nuovi file, poche intersezioni) → ottimi per un
**team di agenti in parallelo** (un agente per modulo, ognuno con codice + test), in
**worktree isolate** per evitare conflitti sui file condivisi (models/urls/settings vanno
gestiti con "proprietà" chiara o integrati da un unico passo). **F2 e F6 sono integrazione**
(scrivono sulla share / cablano il workflow) → **sequenziali**, guidati a mano, con **review
avversariale** sui punti sensibili (scritture share, protezione PDF). **F7** è analisi/review →
un agente. Modello consigliato: *fan-out sui moduli → integrazione sequenziale → verify
avversariale*. Da lanciare quando il DM dà l'ok a una fase (non a rischio di scritture non
volute). Nota: partire sempre in **dry-run**; nessun `--apply` in prod senza conferma.

## 9. Registro avanzamenti (log)
- **2026-06-30/07-01** — Intake: `converti_export_gestionale` (SPTE/Cliente → CSV F8),
  `import_specifiche_storico` in prod (2515 + 786, 0 scarti). Fix mojibake cp1252 (output ASCII).
- **2026-07-01** — Collegamento: campo `percorso_esterno` (mig 0003), `collega_pdf_da_share`
  (+ `--fallback-nome`), `share_link` (allowlist hardened dopo review: 5 bypass chiusi),
  download view serve dalla share. In prod: **771 collegati** (path esatto), 1643 file_mancante
  (path datati; recupero per-nome pronto), 63 fuori-allowlist. Emerso: cartella `_SUPERATO` sulla
  share; `fvali` del gestionale ≠ organizzazione share (riconciliazione da valutare).
- **2026-07-01** — **F0** visione PDF sbloccata (link in scheda per `percorso_esterno`).
  Convenzione naming share derivata (§4). Creato questo piano vivo.
- **2026-07-01** — **F1/F3/F4 costruiti a team di agenti** (recon → build parallelo → verify
  avversariale; un agente si era impiantato → ripreso da cache). File nuovi:
  `management/commands/analizza_pdf_specifiche.py` (F1, detector read-only), `pdf_compose.py`
  (F3, componi+proteggi), `mod133_render.py` (F4, renderer) + rispettivi test. Integrati dopo fix
  delle 3 issue *med* (F4 rete anti-`LayoutError`, F3 validazione PDF vuoto, F1 marker multi-riga)
  e delle low economiche; setting `PDF_OWNER_PASSWORD` cablato. **Suite `gestione_specifiche` verde
  (171 test)**. Issue *low* residue accettate: F4 font WinAnsi (drop non-latino, modulo IT) e
  fedeltà sotto-colonna «Impatto documenti»; F1 cap 12 pagine (mitigato con coda 2 pagine).
  **Prossimo: F2 (ingestion + scritture share) e F6 (aggancio workflow), integrazione sequenziale.**
- **2026-07-01** — **F2 costruito+testato** (io, non fan-out, come da natura sensibile):
  `share_write.py` + comando `deposita_revisione_share` (dry-run/rollback/audit, cartelle reali,
  collisione idempotente/forza). 12 test verdi. **Nessuna scrittura sul master reale**: l'utente
  vuole vedere un dry-run PRIMA del primo `--apply`. Scoping v1: archivia il file collegato a
  QUESTA specifica; supersessione della revisione precedente (altra Specifica + FSM) → F6.
- **2026-07-01** — Fetta gestione_specifiche (F0+intake+F1-F4+F2) **committata+pushata**
  (`0b25997` su `feature/skill-matrix-mod187`, 24 file, nessun file dati; suite 183 verde).
  `--lista-cartelle` provato dal dev contro la share LIVE: **87 cartelle reali**, `_SUPERATO`
  escluso (read-only, ok). **Prossimo "A"**: dry-run per singola specifica **in prod** (dove
  stanno i 3301 import) dopo `git pull` + `migrate gestione_specifiche`.
- **2026-07-01** — 1° dry-run reale (spec 123 `109040245101_LIN01` → FINCANTIERI): scoperto che
  **la cartella share è il cliente/categoria reale**, non il codice gestionale. Fix naming F2
  (`51c6e9d`) + comando read-only `mappa_cartelle_specifiche` (`c5aa9e1`) per la futura
  **assegnazione** (in attesa del run in prod).
- **2026-07-01** — **F5 costruito+testato offline** (utente da remoto, prod in pausa):
  `proponi_righe_da_diff` + endpoint `ai_diff_mod133` (diff `difflib` rev precedente↔nuova → LLM →
  righe MOD.133; fail-safe, nessuna scrittura). **Prossimo: F6** (aggancio workflow + composito
  protetto + supersessione FSM) e la **UI** (bottoni copilota diff + flag protezione), oltre a
  **assegnazione cartelle** e **F7** conformità.
- **2026-07-01** — **F6a costruito+testato offline**: `composito.py`
  (`componi_composito_ufficiale`/`_da_spec`, `dati_mod133_da_spec`) — [MOD.133]+[originale]
  protetto, lettura originale read-only da allegato/share, owner-password dai settings. 7 test.
  **Resta F6b** (aggancio FSM approvazione → deposito share via F2 + flag protezione UI), da fare
  con l'utente sulle scritture; poi UI copiloti e **F7**.
- **2026-07-01** — **F7 + UI** (utente da remoto). F7: analizzati i 2 Excel reali (Matrice ex
  ARXivar + FLUSSO) → doc `CONFORMITA_MATRICE_ARXIVAR.md`: il portale è **già ampiamente conforme**
  (S1-S9, transizioni H1-H4/T1-T6/R1, motivi obbligatori, pausa timer, 7/14gg + 6 mesi,
  distribuzione+copie+presa visione); backlog gap (griglie condizionali, Ruolo→ACL, algoritmo
  copie cartacee, campi obbligatori duplicato/errore, reminder S1). **UI**: pulsante «Confronta con
  revisione precedente» (F5 diff) nel copilota MOD.133 + chip **cartella share** (cliente reale) in
  scheda. **Resta**: F6b, assegnazione cartelle e i gap del backlog F7, tutti da fare in prod/con
  l'utente.
