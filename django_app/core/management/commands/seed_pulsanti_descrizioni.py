"""
Management command: seed_pulsanti_descrizioni

Popola automaticamente il campo `descrizione` sui Pulsante esistenti
basandosi sul codice. Usa UPDATE (non INSERT) — non crea pulsanti nuovi.
Sovrascrive solo i record che hanno descrizione NULL o vuota, a meno che
non venga passato --force.

Uso:
    python manage.py seed_pulsanti_descrizioni
    python manage.py seed_pulsanti_descrizioni --dry-run
    python manage.py seed_pulsanti_descrizioni --force   # sovrascrive anche esistenti
"""

from django.core.management.base import BaseCommand

from core.legacy_models import Pulsante

# ---------------------------------------------------------------------------
# Dizionario codice → descrizione
# Le descrizioni sono in italiano, concise (1 riga), orientate all'utente admin
# che deve capire cosa fa la pagina senza aprirla.
# ---------------------------------------------------------------------------
_DESCRIZIONI: dict[str, str] = {
    # ── DASHBOARD ────────────────────────────────────────────────────────────
    "dashboard_home": "Home page personale con widget KPI, accessi rapidi ai moduli e ultime attività.",
    "dashboard_richieste": "Alias di compatibilità → reindirizza al modulo Assenze.",
    "dashboard_anomalie_menu": "Menu rapido anomalie integrato nella dashboard.",
    "dashboard_scheda_dipendente": "Scheda riepilogativa del dipendente (dashboard principale con dati personali).",
    "dashboard_api_toggle": "API: attiva/disattiva un widget nella dashboard personale.",
    "dashboard_api_layout": "API: salva il layout dei widget della dashboard personale.",
    "dashboard_api_employee_data": "API: dati del pannello dipendente (presenze, assenze, KPI).",
    "dashboard_scheda_pdf": "Genera il PDF della scheda riepilogativa del dipendente.",
    "dashboard_api_employee_layout": "API: layout del pannello dipendente.",
    "dashboard_api_employee_widget_config": "API: configurazione dei widget del pannello dipendente.",

    # ── ASSENZE ──────────────────────────────────────────────────────────────
    "assenze_lista": "Lista delle proprie richieste di assenza con stato di approvazione.",
    "assenze_nuova": "Inserimento di una nuova richiesta di assenza (ferie, permesso, ecc.).",
    "assenze_gestione": "Pannello gestione assenze: lista tutte le richieste del team con approvazione/rifiuto.",
    "assenze_calendario": "Calendario mensile/settimanale con presenze e assenze del reparto.",
    "assenze_certifica_presenza": "Certifica la propria presenza in ufficio per la giornata corrente.",
    "assenze_admin": "Configurazione globale del modulo assenze (turni, policy, soglie).",
    "assenze_export_csv": "Esporta le assenze in formato CSV per elaborazione esterna.",
    "assenze_api_eventi": "API: recupera eventi (assenze/presenze) per il calendario.",
    "assenze_eventi_colors": "API: schema colori personalizzato per i tipi di assenza nel calendario.",
    "assenze_evento_update": "API: modifica un evento assenza esistente.",
    "assenze_evento_delete": "API: elimina un evento assenza.",
    "assenze_sync_push": "API: sincronizza le assenze verso SharePoint (push).",
    "assenze_sync_pull": "API: importa le assenze da SharePoint (pull).",

    # ── ANOMALIE ─────────────────────────────────────────────────────────────
    "anomalie_gestione": "Lista e gestione di tutte le anomalie produzione segnalate.",
    "anomalie_nuova": "Inserimento di una nuova segnalazione di anomalia produzione.",
    "anomalie_configurazione": "Configurazione categorie, linee e parametri del modulo anomalie.",
    "anomalie_statistiche": "Dashboard KPI anomalie: trend, distribuzione per linea/categoria, tempi di risoluzione.",
    "anomalie_api_ordini": "API: lista ordini di produzione (per collegamento anomalie).",
    "anomalie_api_anomalie": "API: recupero anomalie in formato JSON.",
    "anomalie_api_salva": "API: salvataggio nuova anomalia o modifica esistente.",
    "anomalie_api_sync": "API: sincronizzazione anomalie con sistemi esterni.",
    "anomalie_api_campi": "API: metadati dei campi anomalia (valori validi, configurazione).",
    "anomalie_api_allegati": "API: upload e gestione allegati alle anomalie.",
    "anomalie_api_statistiche": "API: dati statistici aggregati per il dashboard KPI.",
    "anomalie_api_report": "API: generazione report anomalie in PDF/CSV.",
    "anomalie_export_csv": "Esporta il registro anomalie in formato CSV.",

    # ── ASSETS ───────────────────────────────────────────────────────────────
    "assets_list": "Lista completa degli asset aziendali con filtri per categoria e stato.",
    "assets_new": "Registrazione di un nuovo asset (macchinario, attrezzatura, ecc.).",
    "assets_view": "Scheda dettaglio asset: dati tecnici, storico interventi, documenti, KPI ticket.",
    "assets_edit": "Modifica i dati anagrafici e tecnici di un asset esistente.",
    "assets_components": "Lista dei componenti/sottopezzi associati agli asset.",
    "assets_components_new": "Aggiunta di un nuovo componente a un asset.",
    "assets_components_edit": "Modifica di un componente esistente.",
    "assets_deadlines": "Scadenze amministrative degli asset (collaudi, verifiche periodiche, assicurazioni).",
    "assets_deadlines_new": "Inserimento di una nuova scadenza amministrativa.",
    "assets_deadlines_edit": "Modifica di una scadenza amministrativa.",
    "assets_maintenance_templates": "Template di manutenzione programmata (check-list riutilizzabili).",
    "assets_maintenance_templates_new": "Creazione di un nuovo template di manutenzione.",
    "assets_maintenance_templates_edit": "Modifica di un template di manutenzione esistente.",
    "assets_maintenance_rules": "Regole di manutenzione periodica (frequenza, tipo, responsabile).",
    "assets_maintenance_rules_new": "Aggiunta di una nuova regola di manutenzione.",
    "assets_maintenance_rules_edit": "Modifica di una regola di manutenzione.",
    "assets_maintenance_schedule": "Calendario delle prossime manutenzioni programmate.",
    "assets_assistance_contracts": "Gestione contratti di assistenza e manutenzione esterna con fornitori.",
    "assets_asset_maintenance_rules": "Regole di manutenzione specifiche per singolo asset (override delle regole globali).",
    "assets_asset_maintenance_overrides_new": "Aggiunta di un override di regola manutenzione su asset specifico.",
    "assets_asset_maintenance_overrides_edit": "Modifica di un override di regola manutenzione.",
    "assets_asset_maintenance_overrides_reset": "Ripristina le regole di manutenzione di default su un asset.",
    "assets_work_machines": "Lista dei macchinari di produzione con stato e ubicazione.",
    "assets_wm_dashboard": "Dashboard KPI macchinari: OEE, fermi, interventi, disponibilità.",
    "assets_wm_map": "Mappa planimetrica interattiva con posizione dei macchinari.",
    "assets_workorders": "Lista degli ordini di lavoro (work order) aperti e chiusi.",
    "assets_wo_new": "Creazione di un nuovo work order di manutenzione.",
    "assets_verifiche": "Registro verifiche periodiche obbligatorie (conformità normativa).",
    "assets_reports": "Generazione report manutenzione, KPI e storico interventi.",
    "assets_gestione": "Pannello admin assets: gestione categorie, configurazioni, import/export.",
    "assets_labels": "Designer etichette asset (QR code, barcode) per stampa.",
    "assets_bulk_update": "Modifica massiva di più asset contemporaneamente.",
    "assets_wm_map_editor": "Editor planimetria: posizionamento drag-and-drop dei macchinari sulla mappa.",
    "assets_wm_create": "Registrazione di un nuovo macchinario di produzione.",
    "assets_view_layout": "Configurazione delle sezioni visibili nella scheda dettaglio asset per ruolo.",
    "assets_assign": "Assegnazione di un asset a un utente/reparto.",
    "assets_wo_view": "Dettaglio work order con log attività, allegati e timeline.",
    "assets_wo_close": "Chiusura di un work order con inserimento esito e ore lavorate.",
    "assets_reports_manage": "Gestione template report personalizzati per gli asset.",
    "assets_maintenance_month_pdf": "Genera il report PDF delle manutenzioni del mese corrente.",

    # ── AUTOMAZIONI ──────────────────────────────────────────────────────────
    "automazioni_regole": "Lista delle regole di automazione configurate (trigger + azioni).",
    "automazioni_sorgenti": "Configurazione delle sorgenti dati per le regole di automazione.",
    "automazioni_contenuti": "Gestione dei contenuti (template messaggi) usati dalle automazioni.",
    "automazioni_queue": "Coda di esecuzione delle automazioni: eventi in attesa di elaborazione.",
    "automazioni_run_log": "Log delle esecuzioni passate: esito, errori, payload.",
    "automazioni_rule_create": "Designer visuale per creare una nuova regola di automazione.",
    "automazioni_rule_import": "Importazione di un package di regole di automazione da file.",
    "automazioni_rule_import_result": "Risultato dell'ultima importazione di package automazioni.",

    # ── TICKETS ──────────────────────────────────────────────────────────────
    "tickets_dashboard": "Dashboard ticket personale: i miei ticket aperti, in attesa e recenti.",
    "tickets_nuovo": "Apertura di un nuovo ticket di assistenza o segnalazione.",
    "tickets_gestione": "Lista gestione ticket (vista tecnici/admin): tutti i ticket con filtri avanzati.",
    "tickets_impostazioni": "Impostazioni modulo ticket: categorie, SLA, notifiche, SharePoint.",
    "tickets_api_commento": "API: aggiunta o modifica di un commento su un ticket.",
    "tickets_api_allegato": "API: upload di un allegato a un ticket (storage privato).",
    "tickets_api_stato": "API: cambio stato di un ticket (aperto, in carico, risolto, ecc.).",
    "tickets_api_assegna": "API: assegnazione di un ticket a un tecnico.",
    "tickets_api_bulk": "API: operazioni massive su più ticket (chiusura, riassegnazione).",
    "tickets_api_import_csv": "API: importazione massiva ticket da file CSV.",
    "tickets_api_test_sp": "API: test connettività SharePoint per il modulo ticket.",
    "tickets_api_asset": "API: collegamento/scollegamento di un asset a un ticket.",
    "tickets_api_cerca_utenti": "API: ricerca utenti per l'assegnazione del ticket.",
    "tickets_api_assets_autocomplete": "API: autocomplete asset nel form di creazione ticket.",

    # ── NOTIZIE ──────────────────────────────────────────────────────────────
    "notizie_lista": "Bacheca notizie: lista comunicazioni aziendali per l'utente.",
    "notizie_obbligatorie": "Notizie obbligatorie da leggere: richiede conferma di lettura.",
    "notizie_report": "Report HR letture: chi ha letto, chi non ha letto, date.",
    "notizie_dashboard": "Dashboard gestione notizie: lista tutte le notizie pubblicate e in bozza.",
    "notizie_conferma": "API: conferma di lettura di una notizia obbligatoria.",
    "notizie_report_csv": "API: esporta il report letture notizie in CSV.",
    "notizie_gestione": "Pannello admin notizie: crea, modifica, pubblica e archivia comunicazioni.",
    "notizie_dashboard_nuova": "Creazione di una nuova notizia/comunicazione aziendale.",

    # ── TASKS ─────────────────────────────────────────────────────────────────
    "tasks_view": "Lista dei task assegnati all'utente corrente.",
    "tasks_create": "Creazione di un nuovo task con assegnazione, priorità e scadenza.",
    "tasks_edit": "Modifica di un task esistente.",
    "tasks_comment": "API: aggiunta di un commento a un task.",
    "tasks_admin": "Vista admin task: tutti i task di tutti gli utenti e progetti.",
    "tasks_projects": "Lista progetti: task raggruppati per progetto.",

    # ── TIMBRI ───────────────────────────────────────────────────────────────
    "timbri_home": "Elenco operatori con report timbrature lette dal database legacy.",
    "timbri_view": "Scheda operatore: storico timbrature individuali con anomalie rilevate.",
    "timbri_edit": "Modifica manuale di un record di timbratura.",
    "timbri_config": "Configurazione importazione timbrature da SharePoint.",
    "timbri_import": "Import timbrature da file SharePoint.",
    "timbri_export": "Esporta le timbrature in formato CSV.",

    # ── RENTRI ───────────────────────────────────────────────────────────────
    "rentri_menu": "Home modulo RENTRI: riepilogo registro rifiuti e accessi rapidi.",
    "rentri_carico": "Inserimento movimento di carico rifiuti (normativa RENTRI).",
    "rentri_scarico_orig": "Inserimento movimento di scarico originale rifiuti.",
    "rentri_scarico_eff": "Inserimento movimento di scarico effettivo rifiuti.",
    "rentri_rettifica": "Rettifica di uno scarico rifiuti già inserito.",
    "rentri_elenco": "Lista completa dei movimenti del registro rifiuti con filtri.",
    "rentri_import_preview": "Anteprima importazione dati RENTRI prima della conferma.",
    "rentri_import_confirm": "Conferma importazione dati RENTRI nel registro.",
    "rentri_export_pdf": "Genera il PDF del registro rifiuti (formato ufficiale RENTRI).",
    "rentri_sync_pull": "API: sincronizzazione registro rifiuti da sorgente esterna.",

    # ── DIARIO PREPOSTO ──────────────────────────────────────────────────────
    "diario_preposto_lista": "Lista segnalazioni del diario preposto sicurezza.",
    "diario_preposto_nuovo": "Inserimento di una nuova segnalazione nel diario preposto.",
    "diario_preposto_dettaglio": "API: dettaglio di una segnalazione preposto.",
    "diario_preposto_modifica": "API: modifica di una segnalazione preposto.",
    "diario_preposto_elimina": "API: eliminazione di una segnalazione preposto.",
    "diario_preposto_allegato_upload": "API: upload allegato a una segnalazione preposto.",
    "diario_preposto_allegato_delete": "API: eliminazione allegato da una segnalazione preposto.",

    # ── RILEVAZIONE INCIDENTI ────────────────────────────────────────────────
    "rilev_inc_lista": "Lista rilevazioni incidenti/unsafe condition (sorgente: SharePoint).",
    "rilev_inc_nuovo": "Inserimento di una nuova rilevazione incidente o condizione non sicura.",
    "rilev_inc_dettaglio": "Dettaglio di una rilevazione incidente con allegati e dati di indagine.",
    "rilev_inc_modifica": "Modifica di una rilevazione incidente esistente.",
    "rilev_inc_statistiche": "Statistiche incidenti: frequenza, gravità, reparti, trend temporale.",
    "rilev_inc_impostazioni": "Configurazione modulo rilevazione incidenti (admin): categorie, SharePoint.",
    "rilev_inc_export_csv": "Esporta il registro incidenti in formato CSV.",

    # ── DPI ──────────────────────────────────────────────────────────────────
    "dpi_view": "Dashboard DPI personale: i miei DPI assegnati e richieste in corso.",
    "dpi_create": "Inserimento di una nuova richiesta DPI (dispositivi di protezione individuale).",
    "dpi_manage": "Gestione richieste DPI (admin/responsabile): approvazione, consegna, rifiuto.",
    "dpi_impostazioni": "Configurazione modulo DPI: categorie, responsabili, soglie di approvazione.",
    "dpi_storico": "Storico consegne DPI: tutti i DPI consegnati per utente e categoria.",
    "dpi_categoria_create": "Creazione di una nuova categoria DPI con immagine e vita utile.",

    # ── PROCEDURE REFRESH ────────────────────────────────────────────────────
    "pr_view": "Le mie letture: procedure assegnate all'utente con stato di lettura.",
    "pr_assignment_detail": "Dettaglio assegnazione procedura con contenuto del documento.",
    "pr_admin": "Dashboard admin presa visione: KPI campagne, percentuali completamento.",
    "pr_documents": "Gestione documenti procedura: anagrafica, revisioni, sorgente SharePoint/file server.",
    "pr_campaigns": "Gestione campagne di presa visione: crea, pubblica, chiudi campagne.",
    "pr_report_user": "Report per utente: quali procedure ha letto, aperto, confermato.",
    "pr_report_document": "Report per documento: chi ha letto e chi no con date.",
    "pr_report_campaign": "Report campagna: avanzamento complessivo e dettaglio per assegnazione.",
    "pr_export_csv": "Esporta i dati di presa visione in CSV.",

    # ── ANAGRAFICA ───────────────────────────────────────────────────────────
    "anagrafica_index": "Dashboard Anagrafica HR: riepilogo dipendenti, scadenze, cataloghi e KPI del personale.",
    "anagrafica_dipendenti": "Lista dipendenti con filtri, ricerca e link alla scheda individuale.",
    "anagrafica_fornitori": "Voce storica fornitori: usare il modulo separato Anagrafica Fornitori.",
    "anagrafica_fornitore_create": "Voce storica creazione fornitore: usare il modulo separato Anagrafica Fornitori.",
    "anagrafica_ruoli_operativi": "Gestione ruoli operativi (mansioni e assegnazioni).",
    "anagrafica_mansioni": "Catalogo mansioni: definizione dei profili di ruolo operativo.",
    "anagrafica_qualifiche": "Catalogo qualifiche: titoli abilitativi e certificazioni del personale.",
    "anagrafica_widget_layout": "API: configurazione layout widget scheda dipendente.",
    # --- FORNITORI ---
    "fornitori_index": "Dashboard Anagrafica Fornitori: KPI fornitori, ordini, spesa e asset assegnati.",
    "fornitori_list": "Lista fornitori aziendali con filtri, contatti e accesso alla scheda.",
    "fornitori_create": "Registrazione di un nuovo fornitore.",
    "fornitore_detail": "Scheda fornitore con anagrafica, documenti, ordini, valutazioni e asset collegati.",
    "fornitore_edit": "Modifica dati anagrafici e contatti del fornitore.",
    "fornitore_toggle_active": "Attivazione o disattivazione del fornitore.",
    "fornitore_documento_add": "Caricamento di un documento nella scheda fornitore.",
    "fornitore_documento_delete": "Eliminazione di un documento dalla scheda fornitore.",
    "fornitore_ordine_add": "Inserimento di un ordine collegato al fornitore.",
    "fornitore_ordine_stato": "Aggiornamento dello stato di un ordine fornitore.",
    "fornitore_valutazione_add": "Inserimento di una valutazione qualita fornitore.",
    "fornitore_valutazione_delete": "Eliminazione di una valutazione qualita fornitore.",
    "fornitore_asset_add": "Collegamento di un asset al fornitore.",
    "fornitore_asset_remove": "Rimozione del collegamento tra asset e fornitore.",
    "anagrafica_impostazioni_widget": "Gestione permessi di visibilità dei widget nella scheda dipendente per ruolo.",

    # ── ADMIN PORTALE ────────────────────────────────────────────────────────
    "index": "Home pannello di amministrazione del portale.",
    "utenti_list": "Lista utenti del portale con filtri per ruolo, stato e AD.",
    "utente_create": "Creazione di un nuovo utente locale (non AD).",
    "utente_edit": "Scheda utente: dettaglio, permessi effettivi, override navigazione.",
    "permessi": "Gestione permessi dettagliata per ruolo o utente (ACL legacy).",
    "pulsanti": "Gestione pulsanti ACL: registra, modifica e configura le voci del sistema di permessi.",
    "topbar_live": "Anteprima live della barra di navigazione superiore per ruolo.",
    "navigation_builder": "Builder visuale navigazione: drag-and-drop voci di menu tra sezioni (topbar, subnav, admin).",
    "acl_canonico": "Gestione ACL canonico v2: permission definition, route binding, grant ruolo, override utente.",
    "acl_route_coverage": "Report copertura route ACL: stato per ogni URL (bound, fallback, unbound).",
    "schema_dati": "Mappa visuale dello schema dati Django: modelli, campi e relazioni tra app.",
    "acl_diagnostica": "Diagnostica ACL combinata (legacy + canonico): simula la decisione di accesso per un utente su un path.",
    "mappa_permessi_navigazione": "Mappa completa route/menu con sorgente permesso, ruoli abilitati e override.",
    "ldap_diagnostica": "Diagnostica connessione LDAP/Active Directory: cerca utenti, verifica credenziali.",

    "login_config": "Personalizzazione pagina di login: logo, banner, testo di benvenuto.",
    "checklist_index": "Gestione checklist onboarding/configurazione per utente.",
    "audit_log": "Log audit: storico operazioni eseguite dagli utenti (CRUD, export, accessi).",
    "health_check": "Health check del sistema: stato DB, cache, servizi interni.",
    "accessi": "Gestione accessi legacy: assegnazione ruoli e permessi modulo per utente.",
    "gestione_accessi": "Alias → gestione accessi.",
    "accessi_semplice": "Vista semplificata accessi: spunta moduli e pulsanti attivi per ruolo in un'unica schermata.",
    "accessi_avanzati": "Vista avanzata accessi: controllo granulare permessi per modulo, utente e ruolo.",
    "matrice_permessi": "Matrice permessi: tabella incrociata ruoli × pulsanti con stato can_view.",
    "ruoli_list": "Lista ruoli del portale con conteggio utenti assegnati e link a configurazione permessi.",
    "wizard_ruolo": "Wizard configurazione permessi per ruolo: abilita/disabilita l'accesso a ogni funzione.",
    "wizard_pulsante": "Wizard guidato per la creazione di un nuovo pulsante ACL con configurazione permessi.",
    "guestportal_sso": "Configurazione SSO Guest Portal: relay credenziali per portale esterno.",
    "crea_release": "Creazione pacchetto release: genera lo zip del progetto per il deploy.",
}


class Command(BaseCommand):
    help = "Popola il campo 'descrizione' sui Pulsante esistenti in base al loro codice."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Mostra cosa verrebbe aggiornato senza salvare.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Sovrascrive anche i pulsanti che hanno già una descrizione.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        force = options["force"]

        updated = 0
        skipped_has_desc = 0
        skipped_no_match = 0

        for pulsante in Pulsante.objects.all():
            desc = _DESCRIZIONI.get(pulsante.codice)
            if not desc:
                skipped_no_match += 1
                continue
            if pulsante.descrizione and not force:
                skipped_has_desc += 1
                continue
            if dry_run:
                self.stdout.write(
                    f"  [DRY-RUN] {pulsante.codice!r} → {desc[:70]}{'…' if len(desc)>70 else ''}"
                )
            else:
                Pulsante.objects.filter(pk=pulsante.pk).update(descrizione=desc)
            updated += 1

        verb = "Da aggiornare" if dry_run else "Aggiornati"
        self.stdout.write(self.style.SUCCESS(
            f"\n{verb}: {updated} | Già con descrizione (skip): {skipped_has_desc} | Codice non mappato: {skipped_no_match}"
        ))
        if skipped_no_match > 0:
            self.stdout.write(
                "  Hint: riesegui con --verbosity=2 per vedere i codici non mappati."
            )
            if options.get("verbosity", 1) >= 2:
                for p in Pulsante.objects.exclude(codice__in=_DESCRIZIONI):
                    self.stdout.write(f"    - {p.codice!r} (modulo={p.modulo})")
