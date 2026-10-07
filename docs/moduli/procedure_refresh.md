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
- **Segnalazioni di modifica** (`ProcedureChangeRequest`): il lettore propone modifiche al documento, il gestore le chiude con stati (aperta → in carico → recepita in Rev.X / respinta) — evidenza del ciclo di miglioramento
- **Tracking aperture**: `open_count`, `first_opened_at`, `last_opened_at`, IP, user agent
- **Log eventi**: opened, confirmed, reminder_sent, overdue_marked, reassigned, exported
- **Matrice formazione** in `/procedure-refresh/admin/report/matrice/` con completamento per reparto e export CSV audit ISO
- **Quiz post-lettura** per revisione procedura, mostrato dopo la conferma e tracciato senza bloccare `read_confirmed`
- **ACL v2 canonico**: gate `_can_manage` con permesso canonico (ruolo qualità/RSPP non-admin) e fallback legacy
- **Export CSV** per audit
- **Report** copertura per reparto/procedura
