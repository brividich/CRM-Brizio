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
        "destinatari": "SiteConfig cambio_mansione_emails (Task pianificati → cambio_mansione_digest → Configura mail)",
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
        "destinatari": "SiteConfig dpi_amm_emails / dpi_car_emails + capireparto",
        "source": "anagrafica/services/onboarding.py",
        "func": "notifica_assegnazione_mansione_rischio",
    },
    {
        "code": "dpi_richiesta_da_approvare",
        "label": "Richiesta DPI - da approvare",
        "module": "DPI",
        "trigger": "Un dipendente (o il suo responsabile per suo conto) invia una richiesta DPI.",
        "destinatari": "Responsabile effettivo del dipendente (area/reparto), co-responsabili e preposto; ripiego SiteConfig dpi_car_emails",
        "source": "dpi/flusso.py",
        "func": "notifica_nuova_richiesta",
    },
    {
        "code": "dpi_avviso_consegna",
        "label": "Richiesta DPI approvata - avviso di consegna",
        "module": "DPI",
        "trigger": "Il responsabile/preposto approva una richiesta DPI.",
        "destinatari": "Impostazioni DPI: email Magazzino + Amministrazione",
        "source": "dpi/flusso.py",
        "func": "notifica_approvata",
    },
    {
        "code": "dpi_report_consegna",
        "label": "DPI consegnato - report di consegna",
        "module": "DPI",
        "trigger": "Il magazzino registra la consegna di un DPI approvato.",
        "destinatari": "Impostazioni DPI: email Amministrazione (con il modulo di consegna PDF in allegato)",
        "source": "dpi/flusso.py",
        "func": "notifica_consegnata",
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
        "code": "suggestion_corner_nuova_segnalazione",
        "label": "Suggestion Corner — nuova segnalazione",
        "module": "Suggestion Corner",
        "trigger": "Creazione di una nuova segnalazione da un reparto.",
        "destinatari": "Team Suggestion Corner",
        "source": "suggestion_corner/notifications.py",
        "func": "notifica_team_nuova_segnalazione",
    },
]


def get_event_notifications() -> list[dict[str, str]]:
    """Copia difensiva del catalogo, per uso nelle view."""
    from .models import ManagedFlow
    bindings = {b.code: b for b in ManagedFlow.objects.select_related("rule").filter(kind="event")}
    return [{**item, "rule_id": bindings[item["code"]].rule_id if item["code"] in bindings else None,
             "enabled": (bindings[item["code"]].rule.is_active and not bindings[item["code"]].rule.is_draft) if item["code"] in bindings else None}
            for item in EVENT_NOTIFICATIONS]
