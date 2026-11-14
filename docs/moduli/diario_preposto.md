# `diario_preposto` — diario sicurezza

Area **Sicurezza** · URL `/diario-preposto/` · codice [`django_app/diario_preposto/`](../../django_app/diario_preposto/)

[← Catalogo moduli nel README](../../README.md#-catalogo-moduli)

## Sintesi

Diario preposto sicurezza con segnalazioni, allegati privati e ispezioni periodiche

## Dettaglio

Registro delle segnalazioni di sicurezza del preposto (D.Lgs. 81/2008 art. 19) e delle ispezioni periodiche.

- **3 modelli**: SegnalazionePreposto, SegnalazioneAllegato, DiarioPrepostoImpostazioni
- **Segnalazioni**: data, titolo, descrizione; preposto e «chi segnala» presi dall'utente collegato; codice `DP-anno-NNNN` mai riusato
- **Allegati multipli** (PDF, immagini, Office, testo, CSV) con upload hardening e **storage privato** cifrato (`DIARIO_PREPOSTO_PRIVATE_ROOT`) servito solo via download autenticato `/diario-preposto/allegato/<id>/download/`
- **Ispezioni periodiche** in `/diario-preposto/ispezioni/` con template `ChecklistVoce`, registrazioni `ChecklistEsecuzione`/`ChecklistRisposta`, area/macchina e frequenza (1-365 giorni) nelle impostazioni
- **Autorizzazioni scrittura** in `/diario-preposto/impostazioni/` (admin o permesso `diario_preposto.impostazioni.manage`): widget di ricerca dipendenti, match su username/`aliasusername`/email aziendale. Elenco vuoto = aperto a tutti gli autenticati
- **Export Excel** con i filtri correnti e **PDF** della singola segnalazione (con l'impronta degli allegati)
- **Guida in-app** `/diario-preposto/guida/` (pagina e PDF), link «? Guida» su elenco, scheda, modulo e ispezioni
- **ACL bootstrap automatico** all'avvio app

## Infografica della singola segnalazione (08/11/2026)

- `diario_preposto/scheda.py` + `partials/_infografica.html`, in cima alla scheda a tutta larghezza. Parte dalla storyline, quindi non ricalcola nulla da fonti diverse.
- **Percorso**: Fatto → Registrata (avviso oltre `GIORNI_RITARDO_REGISTRAZIONE`) → Documentata (primo allegato attivo) → Notificata (prima mail inviata; critico se una è in errore) → Oggi, oppure Eliminata con il motivo. Ogni tappa riporta i giorni dal fatto.
- **Controlli** (ok / avviso / critico / non applicabile), con esito complessivo «N controlli superati su M»: registrata in tempo, allegati, impronta SHA-256, download bloccati per integrità, notifiche, dati completi, presenza nel registro.
- **Il preposto**: le segnalazioni dello stesso preposto sul queryset visibile all'utente (`_base_registro`). Mostra totale, ultimi 12 mesi, stesso mese, posizione, il grafico mensile con il mese della segnalazione segnato da ▲ e i link a precedente e successiva.

## Cruscotto e storia della segnalazione (08/11/2026)

- **Cruscotto dell'elenco** (`diario_preposto/cruscotto.py`, `partials/_cruscotto.html`): sullo stesso queryset della tabella (ruoli + ricerca + preposto) conta totale, ultimi 7/30 giorni con confronto sui 30 precedenti, mese corrente, senza allegati, registrate oltre `GIORNI_RITARDO_REGISTRAZIONE` (2) giorni dopo il fatto; andamento 12 mesi, giorno della settimana, primi 6 preposti; stato ispezioni (`stato_ispezioni`, usato anche dalla pagina Ispezioni); attività recenti dall'audit delle sole segnalazioni visibili; per chi gestisce il modulo le mail del diario in errore negli ultimi 30 giorni (`EmailInviata`, `sorgente="diario_preposto"`). Non compare nella vista «Eliminate».
- **Storia della segnalazione** (`diario_preposto/storyline.py`, `partials/_storyline.html`): fatto, registrazione (con ritardo), allegati aggiunti/rimossi, modifiche campo per campo, eliminazione con motivo e ripristino, download (anche bloccati per impronta), mail partite e non partite. Riquadri di sintesi in cima alla scheda. I download ora vengono agganciati alla segnalazione nell'audit.
- Grafici a una serie in CSS, colore validato (`#0d9488` chiaro, `#0fa596` scuro), valori al passaggio/focus e in «Vedi i numeri»; stati con icona e testo.

## Integrità (08/11/2026)

- **Eliminare = archiviare con motivo**: `eliminata_il`, `eliminata_da`, `motivo_eliminazione` (minimo 5 caratteri). Record e allegati restano; la segnalazione esce da elenco, export, dashboard, conteggi in anagrafica e assistente AI (`SegnalazionePreposto.objects.attive()`). Chi gestisce il modulo la vede con il filtro «Eliminate» e la riporta con «Ripristina» (`POST /diario-preposto/<id>/ripristina/`). Per gli altri dettaglio, modifica, PDF e download rispondono 404.
- **Allegati con impronta**: al caricamento `sha256`, `dimensione`, `caricato_da`; il download ricalcola l'impronta e, se il file sul disco non corrisponde, risponde 409 e scrive `download_allegato` con esito `integrita_ko` nell'audit. Gli allegati precedenti (impronta vuota) non vengono controllati.
- **Rimozione allegato = archiviazione** (`rimosso_il`, `rimosso_da`): il file resta sul disco; lo scarica solo chi gestisce il modulo.
- **Tutto o niente**: in inserimento e modifica, se un allegato non è valido non si salva nulla.
- **Modifiche concorrenti**: la modifica porta la versione letta (`updated_at`) e la ricontrolla sotto `select_for_update`; se nel frattempo un altro ha salvato, il salvataggio è rifiutato.
- **Data non nel futuro** (tolleranza 10 minuti); titolo e descrizione non possono essere solo spazi.
- **Storico sulla scheda**: insert/update dall'audit automatico più `allegato_aggiunto` / `allegato_rimosso` espliciti; le impostazioni registrano i valori prima/dopo.
- **Ispezioni**: `legacy_user_id` è sempre l'id legacy (`utenti.id`), mai l'id Django; senza utente legacy collegato vale 0.

Migrazione `diario_preposto 0007_integrita_eliminazione_impronta_allegati` (solo colonne nuove, nullable o con default).

## Scheda per mail (14/11/2026)

`python manage.py invia_mail_preposto <codice|id…> --to … [--cc …] [--allegati] [--dry-run]` manda la scheda completa della segnalazione (`diario_preposto/mail_scheda.py`, layout `send_hub_mail`, riga in «Mail inviate»). Gli allegati sono sempre elencati; con `--allegati` vanno in allegato fino a 15 MB in tutto. La stessa scheda parte da sola a ogni nuova segnalazione (flusso evento `diario_preposto_scheda`, destinatari SiteConfig `diario_preposto_scheda_emails`, di base rspp@, modificabili e disattivabili da Automazioni).

## Ruoli del portale

Con il sistema dei ruoli attivo ([PERMESSI_RUOLI.md](../ai/PERMESSI_RUOLI.md)) le segnalazioni sono filtrate per autore (`creato_da`): il preposto vede e modifica le proprie, il responsabile vede quelle del suo team d'organigramma, la Sicurezza tutte. Dettaglio, modifica, eliminazione, export Excel/PDF, allegati e ispezioni applicano la stessa regola; la lista «acl_scrittura» delle impostazioni vale solo a sistema spento.
