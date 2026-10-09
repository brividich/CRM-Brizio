# `procedure_refresh` — presa visione procedure

Area **Sicurezza** · URL `/procedure-refresh/` · codice [`django_app/procedure_refresh/`](../../django_app/procedure_refresh/)

[← Catalogo moduli nel README](../../README.md#-catalogo-moduli)

## Sintesi

Presa visione procedure MT/MTSI (lista unica), campagne, motore scadenze/solleciti, sync SGI con log e segnalazione nuove revisioni, segnalazioni di modifica, consultazione in Bacheca, matrice formazione ISO

## Dettaglio

Campagne di aggiornamento procedure MT/MTSI con tracking letture obbligatorio (ciclo ISO 9001/EN 9100).

- **10 modelli**: ProcedureDocument, ProcedureRevision, ProcedureCampaign, ProcedureCampaignDocument, ProcedureAssignment, ProcedureReadEvent, ProcedureQuiz, ProcedureQuizAttempt, ProcedureChangeRequest, SgiSyncLog
- **Anagrafica procedure** con codice univoco, tipo MT/MTSI/ALTRO; **lista unica** con badge indipendenti (Presa visione / AI / Sensibile·no AI), filtro-chip e ricerca — indicizzazione AI (`escludi_dal_rag`) e presa visione (`requires_acknowledgement`) sono ortogonali, non tab esclusivi
- **Revisioni** con sorgente SharePoint o file server, validazione URL/path
- **Campagne** con stati draft → published → closed → archived; picker su **tutte** le revisioni correnti dei documenti attivi (ricerca client-side), helper «Copia elenco destinatari». Il flag presa-visione è un marcatore, la scelta si fa in campagna
- **Consultazione in Bacheca**: categoria virtuale «Procedure SGI» nella Bacheca (home + `/bacheca/`), esclusi i sensibili; apertura via `document_open` (SharePoint → URL, file server → stream PDF whitelistato)
- **Assegnazioni** per utente Django con stati assigned → opened → read_confirmed (o overdue/cancelled). L'assegnazione dalla sessione copre **tutti i documenti** della sessione (niente più scelta della singola revisione): gli utenti selezionati sono assegnati a ogni documento in un colpo (idempotente), con una notifica in-app generica sulla sessione
- **Motore scadenze** (`run_assignment_lifecycle`, CRON 06:45): marca sempre le scadute `OVERDUE`; con `pr_reminder_attivo` invia promemoria pre-scadenza, solleciti post-scadenza e digest inadempienti ai gestori (SiteConfig `pr_reminder_*`, email su `email_notifica`). Notifica in-app all'assegnazione
- **Sync SGI automatica** (`run_sgi_auto_sync`, CRON 03:00, flag `pr_sgi_auto_sync_attivo`) a perimetro sicuro + pulsante «Sincronizza ora»; **aggiorna anche la revisione dei documenti in presa visione** se più recente sulla share (senza toccare le assegnazioni) e la **segnala** (badge «⟳ nuova Rev.X»); ogni cambiamento in **`SgiSyncLog`** (append-only, pagina admin «Log sync»); watchdog rileva anche i documenti spariti dalla share
- **Inventario SGI** (`sgi_inventario [--root] [--json] [--sample N] [--senza-tabelle] [--output FILE]`): fotografia in **sola lettura** della share (nessuna scrittura DB né sulla share, nessuna AI). Conta i file per formato (pdf/docx/doc/xlsx/xls/pptx/altro) e per area (cartella di primo livello), esclusi `SUPERAT*` e i lock `~$`; per i PDF pagine, testo nativo vs scansione (< 50 caratteri/pagina), pagine con tabelle, copertura heading `§`; nomi non riconosciuti, codici presenti sia in PDF sia in editabile, revisioni correnti vs `OLLAMA_RAG_SGI_MAX_PROCS`. Riusa scansione e parser di `import_sgi_da_share`; il report contiene solo numeri e codici, `--output` rifiuta percorsi sotto la root. Fase F0 del progetto database SGI
- **Testo SGI persistito** (`SgiTestoEstratto`, migrazione 0008): testo dei PDF correnti estratto in ordine di lettura, con le tabelle in pipe-table e le intestazioni ripetute tenute una volta sola; vale finché l'hash del file coincide. Comando `sgi_estrai_testi [--solo CODICE] [--forza] [--limit N] [--dry-run]` (idempotente, esclude i documenti fuori dal RAG); task a catena `run_sgi_estrazione_un_documento` accodato dalla sync notturna. Admin in sola lettura (testo visibile solo ai superuser). L'assistente lo usa solo con `SGI_ESTRAZIONE_PERSISTITA_ENABLED` (**spento**: con il corpus attuale la misura `ai_eval --rag-sgi` peggiora). Con `OLLAMA_RAG_SGI_CHUNK_TITLE` i frammenti indicizzati portano anche il titolo del documento (risposte dell'assistente più precise sui documenti cercati per argomento). Estensioni scandite da `PROCEDURE_REFRESH_SGI_EXTENSIONS` (default `.pdf`); a parità di codice e revisione vince il PDF (`PROCEDURE_REFRESH_SGI_PREFER_PDF`)
- **Riferimenti tra documenti SGI** (`SgiRiferimento`, migrazione 0009): per ogni revisione con testo estratto, i codici di altri documenti SGI citati (es. «vedi MOD.093», «IDOR CN 01 Allegato A»), con sezione e occorrenze, collegati al documento del catalogo, alla **famiglia** di documenti quando il codice non ha un documento proprio ma esistono i `<codice>_n` (es. «MT CN 125»), oppure segnati come «non risolto» (documento mancante o refuso). Il campo «tipo di risoluzione» dice come è stato collegato. Deterministico, nessuna AI: stessa regola di riconoscimento dei codici dell'import dalla share, esclusi l'autocitazione e il cartiglio ripetuto; le norme esterne (ISO, EN, UNI, AS, ASTM) non sono riferimenti SGI. Ricostruiti a ogni nuova estrazione; comando `sgi_riferimenti [--dry-run] [--da-file] [--json FILE]` per il primo popolamento e il report (quota risolta, codici inesistenti, documenti più citati, norme esterne). Comando `sgi_collega_processi --dry-run | --apply`: dai codici citati nei campi «procedure» e «fonte documentale» dei processi del Sistema di gestione propone i collegamenti `SgiDocumentoProcesso` (non confermati, da confermare in admin); il testo dei processi non viene mai toccato.
- **Segnalazioni di modifica** (`ProcedureChangeRequest`): il lettore propone modifiche al documento, il gestore le chiude con stati (aperta → in carico → recepita in Rev.X / respinta) — evidenza del ciclo di miglioramento
- **Tracking aperture**: `open_count`, `first_opened_at`, `last_opened_at`, IP, user agent
- **Log eventi**: opened, confirmed, reminder_sent, overdue_marked, reassigned, exported
- **Matrice formazione** in `/procedure-refresh/admin/report/matrice/` con completamento per reparto e export CSV audit ISO
- **Quiz post-lettura** per revisione procedura, mostrato dopo la conferma e tracciato senza bloccare `read_confirmed`
- **ACL v2 canonico**: gate `_can_manage` con permesso canonico (ruolo qualità/RSPP non-admin) e fallback legacy
- **Export CSV** per audit
- **Report** copertura per reparto/procedura
- **Import SGI e permessi (10/2026)**: `import_sgi_da_share` mostra l'utente di processo che scandisce la share e quanti file vede; avvisa se il numero è diverso dall'ultima esecuzione con `--apply` (con l'enumerazione per permessi, utenti diversi vedono documenti diversi).
