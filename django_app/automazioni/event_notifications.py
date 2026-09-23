"""Catalogo (sola lettura) delle notifiche email "nascoste": invii scatenati da
un evento applicativo (una view, un comando manuale) chiamati direttamente nel
codice, SENZA passare né dal motore regole (``AutomationRule``) né dai task
pianificati django-q (``automazioni.schedules``).

Perché esistono qui e non altrove
---------------------------------
Il motore regole valuta condizioni dichiarative (uguale/contiene/giorni-da-oggi/
campo-cambiato) su eventi INSERT/UPDATE alimentati da trigger SQL Server per
tabella (vedi ``source_registry.py`` + ``migrations/trg_*.sql``). I flussi
elencati qui non ci rientrano perché:

- la tabella di origine non ha ancora una sorgente/trigger SQL registrato
  (specifiche, OFI, timbri MOD.128, abilitazioni macchina); oppure
- la condizione dipende da logica di business incrociata (requisiti mansione,
  catalogo DPI, abilitazioni) che gli operatori dichiarativi del motore non
  possono esprimere; oppure
- il flusso è una soglia temporale periodica (MOD.128, OFI) e non un evento di
  riga, quindi richiederebbe un tipo di trigger "a tempo" che il motore non ha.

Convertirli in vere ``AutomationRule`` richiede quindi, caso per caso: creare e
applicare (`apply_sql_triggers`) un nuovo trigger SQL su dev/test/**prod**, e/o
estendere il motore condiviso — non è un'operazione da fare alla cieca su più
moduli contemporaneamente. Questo catalogo li rende almeno **visibili** senza
toccare la logica di invio esistente.

Per aggiungere una voce: cercare le altre chiamate dirette a ``send_hub_mail``
fuori da ``automazioni/`` e da ``schedules.py`` e aggiungerle qui.
"""
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
        "func": "applica_refresh",
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
    return [dict(item) for item in EVENT_NOTIFICATIONS]
