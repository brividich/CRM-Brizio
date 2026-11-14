"""Catalogo degli eventi applicativi gestiti dal designer tramite managed_flows."""
from __future__ import annotations

EVENT_NOTIFICATIONS: list[dict[str, str]] = [
    {
        "code": "idoneita_gap_mansione",
        "label": "Idoneità alla mansione — requisiti non soddisfatti",
        "module": "Anagrafica HR",
        "trigger": (
            "Uno spostamento organizzativo (reparto/mansione) viene registrato e "
            "la nuova mansione ha requisiti (visita, formazione, DPI) non soddisfatti."
        ),
        "destinatari": "SiteConfig idoneita_reminder_emails + capireparto del reparto",
        "source": "anagrafica/views.py",
        "func": "_notifica_gap_idoneita",
    },
    {
        "code": "cambio_mansione_piano",
        "label": "Cambio mansione — adempimenti da completare",
        "module": "Anagrafica HR",
        "trigger": (
            "Il piano di adeguamento di uno spostamento (o il riallineamento per un override "
            "o per una modifica delle mansioni di rischio) crea nuovi adempimenti: visita, "
            "formazione, DPI, schede di sicurezza. Parte dopo il commit; nessun dato clinico."
        ),
        "destinatari": "SiteConfig cambio_mansione_emails (Task pianificati → cambio_mansione_digest → Modifica)",
        "source": "anagrafica/services/notifiche_cambio_mansione.py",
        "func": "notifica_piano_cambio_mansione",
    },
    {
        "code": "onboarding_dpi_rischio",
        "label": "Onboarding — DPI da distribuire / controllo uso",
        "module": "Anagrafica HR",
        "trigger": (
            "Avvio onboarding con assegnazione a una mansione classificata a rischio "
            "(richiede DPI)."
        ),
        "destinatari": "«Da distribuire»: Impostazioni DPI email Magazzino + SiteConfig dpi_amm_emails; «Controllo uso»: CAR/preposto che approva i DPI del dipendente, ripiego caporeparto del reparto e SiteConfig dpi_car_emails",
        "source": "anagrafica/services/onboarding.py",
        "func": "notifica_assegnazione_mansione_rischio",
    },
    {
        "code": "dpi_richiesta_da_approvare",
        "label": "Richiesta DPI - da approvare",
        "module": "DPI",
        "trigger": "Un dipendente (o il suo responsabile per suo conto) invia una richiesta DPI.",
        "destinatari": "Responsabile effettivo del dipendente (area/reparto), co-responsabili e preposto; ripiego SiteConfig dpi_car_emails; + referenti DPI se è spuntato «Email ai referenti per ogni nuova richiesta»",
        "source": "dpi/flusso.py",
        "func": "notifica_nuova_richiesta",
    },
    {
        "code": "dpi_avviso_consegna",
        "label": "Richiesta DPI approvata - avviso di consegna",
        "module": "DPI",
        "trigger": "Il responsabile/preposto approva una richiesta DPI, o la richiesta di un CAR/preposto si approva da sola.",
        "destinatari": "Impostazioni DPI: email Magazzino; per le categorie senza «La consegna la fa il magazzino» i referenti DPI; per le scarpe al negozio l'operatore incaricato",
        "source": "dpi/flusso.py",
        "func": "notifica_approvata",
    },
    {
        "code": "dpi_ordine_negozio",
        "label": "DPI scarpe - ordine in convenzione al negozio",
        "module": "DPI",
        "trigger": "L'operatore incaricato preme «Invia l'ordine» nella pagina DPI > Scarpe.",
        "destinatari": "Impostazioni DPI: mail del negozio, in copia l'operatore incaricato",
        "source": "dpi/flusso.py",
        "func": "invia_ordine_negozio",
    },
    {
        "code": "dpi_promemoria_ordine_scarpe",
        "label": "DPI scarpe - promemoria del riepilogo al negozio",
        "module": "DPI",
        "trigger": "Ci sono scarpe in convenzione da ordinare e sono passati i giorni del riepilogo (task dpi_expiry_reminders); si ripete ogni 3 giorni finché l'ordine non parte.",
        "destinatari": "Impostazioni DPI: operatore incaricato degli ordini di scarpe (vuoto: referenti DPI)",
        "source": "dpi/flusso.py",
        "func": "notifica_promemoria_ordine",
    },
    {
        "code": "dpi_pronta_ritiro",
        "label": "DPI pronto - avviso di ritiro al dipendente",
        "module": "DPI",
        "trigger": "Il magazzino preme «Pronto per il ritiro» (o subito all'approvazione, se scelto nelle Impostazioni DPI).",
        "destinatari": "Il dipendente che ha richiesto il DPI (email di notifica); in più la notifica nel portale",
        "source": "dpi/flusso.py",
        "func": "notifica_pronta_ritiro",
    },
    {
        "code": "dpi_report_consegna",
        "label": "DPI consegnato - report di consegna",
        "module": "DPI",
        "trigger": "Il magazzino registra la consegna di un DPI approvato.",
        "destinatari": "Responsabile/preposto del dipendente + Impostazioni DPI: email Amministrazione solo per le categorie con «avvisa l'Amministrazione» (PDF del modulo di consegna in allegato)",
        "source": "dpi/flusso.py",
        "func": "notifica_consegnata",
    },
    {
        "code": "dpi_consegna_annullata",
        "label": "Richiesta DPI rifiutata dopo approvazione - consegna annullata",
        "module": "DPI",
        "trigger": "Il responsabile/preposto rifiuta una richiesta DPI già approvata (avviso di consegna già partito).",
        "destinatari": "Impostazioni DPI: email Magazzino; per le categorie senza «La consegna la fa il magazzino» (es. scarpe) i referenti DPI",
        "source": "dpi/flusso.py",
        "func": "notifica_rifiutata_dopo_approvazione",
    },
    {
        "code": "dpi_conferma_ricevuta",
        "label": "DPI consegnato - conferma della ricevuta via mail",
        "module": "DPI",
        "trigger": (
            "Il magazzino registra una consegna senza firma né ricevuta su carta (Banco consegne o scheda richiesta); "
            "promemoria unico dopo 3 giorni senza risposta (task dpi_expiry_reminders)."
        ),
        "destinatari": (
            "Il dipendente se la sua email di notifica è aziendale (Impostazioni DPI: domini della mail aziendale), "
            "altrimenti il suo caporeparto/responsabile/preposto; in mancanza i referenti DPI. Link personale monouso."
        ),
        "source": "dpi/conferme.py",
        "func": "_invia",
    },
    {
        "code": "dpi_consegna_contestata",
        "label": "DPI - consegna contestata («Non li ho ricevuti»)",
        "module": "DPI",
        "trigger": "Chi riceve la mail di conferma della ricevuta risponde «Non li ho ricevuti».",
        "destinatari": "Impostazioni DPI: email Magazzino (referenti DPI per le categorie che il magazzino non consegna)",
        "source": "dpi/conferme.py",
        "func": "_avvisa_contestazione",
    },
    {
        "code": "mpq_timbri_sospesi",
        "label": "Timbri MOD.128 sospesi automaticamente",
        "module": "Anagrafica HR",
        "trigger": (
            "Comando manuale mpq_propaga_timbri: un'abilitazione MOD.128 collegata a "
            "un timbro non è più operativa."
        ),
        "destinatari": "Destinatari MOD.128 configurati nel servizio",
        "source": "anagrafica/services/mpq_timbri.py",
        "func": "notifica_msm_sospensioni (via propaga_sospensioni)",
    },
    {
        "code": "mpq_macchina_da_valutare",
        "label": "Macchine qualificate MOD.128 da valutare o sospese",
        "module": "Anagrafica HR",
        "trigger": (
            "Una macchina qualificata passa a «Da valutare» (OdL non programmato chiuso, asset messo in "
            "riparazione) o viene sospesa da una verifica non conforme."
        ),
        "destinatari": "Destinatari MOD.128 configurati nel servizio (gli stessi dei timbri sospesi)",
        "source": "anagrafica/services/mpq_macchine.py",
        "func": "notifica_macchine_da_valutare",
    },
    {
        "code": "mpq_qualifiche_scadenze",
        "label": "Persone e macchine qualificate MOD.128 da sistemare",
        "module": "Anagrafica HR",
        "trigger": (
            "Ogni lunedì (task mpq_qualifiche_scadenze): persone dei processi attivi non qualificate o in "
            "scadenza entro 60 giorni, macchine sospese, da valutare o in scadenza. Nessuna voce = nessuna mail."
        ),
        "destinatari": "Destinatari MOD.128 configurati nel servizio (gli stessi dei timbri sospesi)",
        "source": "anagrafica/services/mpq_scadenze.py",
        "func": "notifica_scadenze",
    },
    {
        "code": "part145_attrezzatura_stato",
        "label": "Attrezzature PART 145 che cambiano stato",
        "module": "Asset",
        "trigger": (
            "Un'attrezzatura PART 145 o collegata a un processo qualificato MOD.128 cambia stato "
            "(in riparazione, dismessa, di nuovo in uso...): una mail per salvataggio o import."
        ),
        "destinatari": "Destinatari MOD.128 configurati nel servizio (gli stessi dei timbri sospesi)",
        "source": "assets/services/part145.py",
        "func": "notifica_cambio_stato",
    },
    {
        "code": "part145_scadenze",
        "label": "Scadenze PART 145 entro 90 giorni",
        "module": "Asset",
        "trigger": (
            "Ogni lunedì (task part145_scadenze): contratto e requisiti dei processi, processi, tarature e "
            "manutenzioni delle attrezzature, certificazioni del personale in scadenza entro 90 giorni o scaduti. "
            "Nessuna scadenza = nessuna mail."
        ),
        "destinatari": "Destinatari MOD.128 configurati nel servizio (gli stessi dei timbri sospesi)",
        "source": "assets/services/part145_dossier.py",
        "func": "notifica_scadenze",
    },
    {
        "code": "skillmatrix_refresh_car",
        "label": "Refresh abilitazioni macchina — notifica CAR",
        "module": "Anagrafica HR",
        "trigger": "Un CAR applica le decisioni del refresh semestrale abilitazioni macchina di un reparto.",
        "destinatari": "Email del CAR del reparto",
        "source": "anagrafica/services/skillmatrix_refresh.py",
        "func": "_notifica_car",
    },
    {
        "code": "gs_nuova_specifica",
        "label": "Gestione Specifiche — nuova specifica da prendere in carico",
        "module": "Gestione Specifiche",
        "trigger": "Creazione di una nuova specifica (con o senza incaricato indicato).",
        "destinatari": "Incaricato scelto, o pool utenti del modulo",
        "source": "gestione_specifiche/notifiche_gs.py",
        "func": "notifica_nuova_specifica",
    },
    {
        "code": "gs_ofi_reminder",
        "label": "Gestione Specifiche — reminder OFI (MOD.174)",
        "module": "Gestione Specifiche",
        "trigger": "Comando manuale send_ofi_reminders: voci OFI in scadenza o scadute.",
        "destinatari": "Destinatari reminder OFI configurati nel servizio",
        "source": "gestione_specifiche/registro_ofi.py",
        "func": "invia_reminder_ofi",
    },
    {
        "code": "security_lettura_ai_pronta",
        "label": "Security Center — letture proposte dall’AI da controllare",
        "module": "Security Center",
        "trigger": (
            "Il flusso security_ai_lettura ha fatto leggere all'AI locale mail o file che i parser "
            "leggono solo in parte o non riconoscono. Solo proposte: nessun alert creato o chiuso."
        ),
        "destinatari": "Canali scelti in /soc/impostazioni/ › Lettura assistita dall'AI (facoltativi)",
        "source": "security/services/ai_lettura.py",
        "func": "notifica_letture_ai",
    },
    {
        "code": "suggestion_corner_nuova_segnalazione",
        "label": "Suggestion Corner — nuova segnalazione",
        "module": "Suggestion Corner",
        "trigger": "Creazione di una nuova segnalazione da un reparto.",
        "destinatari": "Team Suggestion Corner",
        "source": "suggestion_corner/notifications.py",
        "func": "notifica_team_nuova_segnalazione",
    },
    {
        "code": "kickoff_avviso_cambiamenti",
        "label": "KICK-OFF — mail quando cambia un incarico",
        "module": "KICK-OFF",
        "trigger": (
            "Cambiano date, priorità, stato, titolo o responsabile di un'attività, oppure arriva o si decide "
            "una richiesta di spostamento. La campanella del portale parte sempre."
        ),
        "destinatari": "Impostazioni KICK-OFF → Poteri e avvisi (incaricato, capocommessa, PM, chi ha creato); chi modifica escluso",
        "source": "tasks/services/avvisi.py",
        "func": "mail_cambiamento",
    },
    # Flussi nuovi spenti finché qualcuno non li accende dal designer.
    {
        "code": "kickoff_promemoria_scadenza",
        "label": "KICK-OFF — promemoria prima della scadenza delle tappe",
        "module": "KICK-OFF",
        "trigger": (
            "Una tappa del «Percorso del kickoff» o una riga di «Programmi e FAI» diventa un'attività "
            "con data «Entro il»: prepara il promemoria nel portale con i giorni di preavviso delle "
            "Impostazioni KICK-OFF."
        ),
        "destinatari": "Responsabile dell'attività (campanella del portale)",
        "source": "tasks/services/tappe.py",
        "func": "promemoria_scadenza",
        "attivo_di_default": False,
    },
    {
        "code": "kickoff_evento_outlook",
        "label": "KICK-OFF — evento nel calendario Outlook del responsabile",
        "module": "KICK-OFF",
        "trigger": "Una tappa del «Percorso del kickoff» viene assegnata con data «Entro il» e la spunta «Anche in Outlook».",
        "destinatari": "Calendario Outlook del responsabile (email di notifica dell'anagrafica), via Microsoft Graph",
        "source": "tasks/services/tappe.py",
        "func": "evento_outlook",
        "attivo_di_default": False,
    },
    {
        "code": "assenze_esito_dipendente",
        "label": "Assenze - esito della richiesta al dipendente",
        "module": "Assenze",
        "trigger": "Il capo (o chi approva) approva o rifiuta una richiesta di assenza.",
        "destinatari": "Il dipendente della richiesta (email di notifica)",
        "source": "assenze/mail_esito_service.py",
        "func": "send_esito_dipendente",
    },
    {
        "code": "assenze_richiesta_modificata",
        "label": "Assenze - richiesta modificata",
        "module": "Assenze",
        "trigger": "Una richiesta di assenza già inserita viene modificata (date, tipo, note).",
        "destinatari": "Casella assenze, il dipendente e il suo capo",
        "source": "assenze/mail_modifica_service.py",
        "func": "send_assenza_modificata_notification",
    },
    {
        "code": "assenze_richiesta_eliminata",
        "label": "Assenze - richiesta eliminata",
        "module": "Assenze",
        "trigger": "Una richiesta di assenza viene eliminata.",
        "destinatari": "Casella HR, il dipendente e il suo capo",
        "source": "assenze/mail_delete_service.py",
        "func": "send_assenza_deleted_notification",
    },
    {
        "code": "assenze_certificazione_presenza",
        "label": "Assenze - certificazione di presenza confermata",
        "module": "Assenze",
        "trigger": "Viene registrata una certificazione di presenza dalla pagina Assenze.",
        "destinatari": "Il dipendente, chi l'ha inserita e la casella assenze",
        "source": "assenze/mail_certificazione_presenza.py",
        "func": "send_certificazione_confermata",
    },
    {
        "code": "assenze_sollecito_manuale",
        "label": "Assenze - sollecito al capo dal dipendente",
        "module": "Assenze",
        "trigger": "Il dipendente preme «Sollecita» su una sua richiesta in attesa (rispettando l'intervallo tra due solleciti).",
        "destinatari": "Il capo scelto per la richiesta, altrimenti il capo del dipendente",
        "source": "assenze/solleciti.py",
        "func": "_manda_sollecito_manuale",
    },
    {
        "code": "sicurezza_scheda_segnalazione",
        "label": "Segnalazione di sicurezza - scheda completa",
        "module": "Rilevazione incidenti",
        "trigger": "Una nuova segnalazione di sicurezza viene salvata dal portale (dati nel database del portale): la scheda con tutti i campi, i 5 perché, le note e il link. Si aggiunge all informativa e alle approvazioni della regola AU3.",
        "destinatari": "Destinatari della scheda (Modifica → Impostazioni del modulo), di base rspp@",
        "source": "rilevazione_incidenti/mail_scheda.py",
        "func": "invia_alla_creazione",
    },
    {
        "code": "diario_preposto_scheda",
        "label": "Diario del preposto - scheda completa",
        "module": "Diario preposto",
        "trigger": "Una nuova segnalazione del preposto viene salvata: la scheda con codice, titolo, data, preposto, descrizione, elenco allegati e link. Si aggiunge alla regola AU57.",
        "destinatari": "Destinatari della scheda (Modifica → Impostazioni del modulo), di base rspp@",
        "source": "diario_preposto/mail_scheda.py",
        "func": "invia_alla_creazione",
    },
    {
        "code": "reception_invito",
        "label": "Reception - invito con il codice di accesso",
        "module": "Reception",
        "trigger": "Una visita viene annunciata (o una richiesta accettata): all'ospite codice, QR e invito in calendario; al referente l'avviso della visita.",
        "destinatari": "L'ospite (email della visita) e il referente che lo aspetta",
        "source": "reception/mail.py",
        "func": "invia_invito",
    },
    {
        "code": "reception_conferma_richiesta",
        "label": "Reception - conferma della richiesta di visita",
        "module": "Reception",
        "trigger": "Un esterno compila il modulo pubblico «Richiesta di visita»: riceve il link per confermare l'indirizzo.",
        "destinatari": "L'esterno che ha fatto la richiesta",
        "source": "reception/mail.py",
        "func": "invia_conferma_richiesta",
    },
    {
        "code": "reception_nuova_richiesta",
        "label": "Reception - richiesta di visita al referente",
        "module": "Reception",
        "trigger": "L'esterno conferma la richiesta di visita: il referente riceve la mail per approvarla o rifiutarla (la notifica nell'HUB a chi gestisce la reception parte comunque).",
        "destinatari": "Il referente indicato nella richiesta",
        "source": "reception/mail.py",
        "func": "_mail_nuova_richiesta",
    },
    {
        "code": "reception_rifiuto",
        "label": "Reception - richiesta di visita non accolta",
        "module": "Reception",
        "trigger": "Il referente o la reception rifiuta una richiesta di visita.",
        "destinatari": "L'esterno che ha fatto la richiesta",
        "source": "reception/mail.py",
        "func": "invia_rifiuto",
    },
    {
        "code": "sgi_audit_comunicazione",
        "label": "Sistema di gestione - piano di audit (o annullamento)",
        "module": "Sistema di gestione",
        "trigger": "Si comunica il piano di un audit per email o invito in calendario, o lo si annulla.",
        "destinatari": "Le persone scelte nella comunicazione del piano",
        "source": "sistema_gestione/services/audit.py",
        "func": "invia_email_comunicazione",
    },
    {
        "code": "sgi_audit_rapporto",
        "label": "Sistema di gestione - rapporto di audit chiuso",
        "module": "Sistema di gestione",
        "trigger": "Il rapporto di un audit interno viene chiuso e valutato.",
        "destinatari": "Responsabili di processo e auditati dell'audit + casella MSM (SISTEMA_GESTIONE_AUDIT_EMAIL_MSM)",
        "source": "sistema_gestione/services/audit.py",
        "func": "distribuisci_rapporto",
    },
    {
        "code": "kickoff_assegnazione_attivita",
        "label": "KICK-OFF - nuova attività assegnata",
        "module": "KICK-OFF",
        "trigger": "Un'attività viene assegnata a una persona (la campanella del portale parte comunque).",
        "destinatari": "Il responsabile dell'attività (email di notifica dell'anagrafica)",
        "source": "tasks/services/meeting_tasks.py",
        "func": "_mail_assegnazione",
    },
    {
        "code": "kickoff_convocazione",
        "label": "KICK-OFF - convocazione incontro",
        "module": "KICK-OFF",
        "trigger": "Si preme «Invia convocazione» (o la manda una regola): ordine del giorno ai partecipanti.",
        "destinatari": "Partecipanti dell'incontro, in copia PM e capocommessa",
        "source": "tasks/minute_email.py",
        "func": "send_meeting_invite",
    },
    {
        "code": "kickoff_minuta",
        "label": "KICK-OFF - minuta incontro",
        "module": "KICK-OFF",
        "trigger": "Si preme «Invia minuta» (o la manda una regola): minuta con PDF ai partecipanti.",
        "destinatari": "Presenti all'incontro, in copia assenti, PM e capocommessa",
        "source": "tasks/minute_email.py",
        "func": "send_meeting_minute",
    },
    {
        "code": "kickoff_annullamento",
        "label": "KICK-OFF - incontro annullato",
        "module": "KICK-OFF",
        "trigger": "Un incontro già convocato viene annullato.",
        "destinatari": "Partecipanti dell'incontro, in copia PM e capocommessa",
        "source": "tasks/minute_email.py",
        "func": "send_meeting_cancellation",
    },
    {
        "code": "anagrafica_avviso_it_ingresso",
        "label": "Anagrafica - avviso IT per un nuovo ingresso",
        "module": "Anagrafica HR",
        "trigger": "Viene inserito un nuovo dipendente con l'avviso all'IT attivo.",
        "destinatari": "Indirizzi dell'avviso IT (Anagrafica → Impostazioni → Avviso IT nuovi ingressi)",
        "source": "anagrafica/services/avviso_it_ingresso.py",
        "func": "_invia_email",
    },
    {
        "code": "suggestion_corner_comunicazione_cliente",
        "label": "Suggestion Corner - comunicazione al cliente (SMS)",
        "module": "Suggestion Corner",
        "trigger": "Il team invia al cliente la comunicazione di una segnalazione classificata SMS Sì.",
        "destinatari": "L'email del cliente indicata nella segnalazione",
        "source": "suggestion_corner/notifications.py",
        "func": "notifica_cliente_sms",
    },
]


def get_event_notifications() -> list[dict[str, str]]:
    """Copia difensiva del catalogo, per uso nelle view."""
    from .models import ManagedFlow
    bindings = {b.code: b for b in ManagedFlow.objects.select_related("rule").filter(kind="event")}
    return [{**item, "rule_id": bindings[item["code"]].rule_id if item["code"] in bindings else None,
             "enabled": (bindings[item["code"]].rule.is_active and not bindings[item["code"]].rule.is_draft) if item["code"] in bindings else None}
            for item in EVENT_NOTIFICATIONS]
