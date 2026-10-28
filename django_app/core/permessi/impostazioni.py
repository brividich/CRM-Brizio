"""Impostazioni dei moduli: un'azione propria nella matrice dei ruoli.

Regola: «impostazioni» apre SOLO la pagina Impostazioni del modulo e le sue
sotto-pagine (stesso percorso, es. ``/dpi/impostazioni/...``). Le altre pagine
amministrative (area HR, certificazioni, gestione admin, cataloghi fuori dalle
impostazioni, code operative) restano alle azioni standard.

Le pagine di impostazioni (configurazione, cataloghi, branding del modulo)
prima le apriva «Chiudere / gestire» insieme a tutta la gestione: non si poteva
dare la gestione senza dare anche le impostazioni. Qui ogni modulo dichiara i
permessi di pagina delle sue impostazioni; la registrazione nel registro
(``registra_modulo``) aggiunge da sola l'azione «impostazioni» con quelle pagine,
che le azioni standard non accendono piu'.

- ``codici``: permessi di pagina accesi solo da «impostazioni». Il primo e' quello
  a cui sono legate le ``rotte``.
- ``rotte``: nomi rotta da legare al primo codice (binding per nome rotta),
  quando oggi hanno un permesso condiviso con pagine che non sono impostazioni.
- ``nuovo``: etichetta del primo codice se il codice nasce qui.

La migrazione ``core 0097`` applica la tabella al database (permessi, binding,
celle della matrice); i bootstrap delle app che rilegano le rotte all'avvio
leggono il codice da ``codice_impostazioni``.
"""
from __future__ import annotations

from dataclasses import dataclass

AZIONE_IMPOSTAZIONI = "impostazioni"
ETICHETTA_IMPOSTAZIONI = "Impostazioni del modulo"


@dataclass(frozen=True)
class PagineImpostazioni:
    codici: tuple[str, ...]
    rotte: tuple[str, ...] = ()
    nuovo: str = ""
    modulo_acl: str = ""
    etichetta: str = ETICHETTA_IMPOSTAZIONI


IMPOSTAZIONI: dict[str, PagineImpostazioni] = {
    "assenze": PagineImpostazioni(
        codici=("assenze.impostazioni.manage",),
        rotte=("assenze_impostazioni",),
        nuovo="Assenze · impostazioni",
        modulo_acl="assenze",
    ),
    "anomalie": PagineImpostazioni(
        codici=("anomalie.configurazione.manage",),
        rotte=("anomalie_configurazione_page",),
        modulo_acl="anomalie",
    ),
    "ticket_manutenzione": PagineImpostazioni(
        codici=("tickets.impostazioni.view", "tickets.impostazioni.manage"),
        rotte=("tickets:impostazioni", "tickets:api_impostazioni"),
        modulo_acl="tickets",
        etichetta="Impostazioni dei ticket (IT e manutenzione)",
    ),
    "diario_preposto": PagineImpostazioni(
        codici=("diario_preposto.impostazioni.view", "diario_preposto.impostazioni.manage"),
        rotte=("diario_preposto:impostazioni",),
        modulo_acl="diario_preposto",
    ),
    "rilevazione_incidenti": PagineImpostazioni(
        codici=("rilevazione_incidenti.impostazioni.view", "rilevazione_incidenti.impostazioni.manage"),
        rotte=("rilevazione_incidenti:impostazioni",),
        modulo_acl="rilevazione_incidenti",
    ),
    "automazioni": PagineImpostazioni(
        codici=("automazioni.automazioni_settings.view",),
    ),
    "timbri": PagineImpostazioni(
        codici=("timbri.configurazione.view",),
        rotte=("timbri:configurazione",),
        modulo_acl="timbri",
    ),
    "dpi": PagineImpostazioni(
        codici=(
            "dpi.impostazioni.view", "dpi.categoria_nuova.view",
            "dpi.categoria_modifica.view", "dpi.categoria_elimina.view",
        ),
        rotte=(
            "dpi:impostazioni", "dpi:tipo_nuovo", "dpi:tipo_modifica", "dpi:modello_nuovo",
            "dpi:modello_modifica", "dpi:taglia_nuova", "dpi:taglia_modifica",
        ),
        modulo_acl="dpi",
        etichetta="Impostazioni e catalogo DPI",
    ),
    "assets": PagineImpostazioni(
        codici=("assets.gestione_admin.view",),
        rotte=(
            "assets:reporting_settings", "assets:reporting_edit", "assets:reporting_run",
            "assets:reporting_retry", "assets:maintenance_impostazioni",
        ),
        modulo_acl="assets",
    ),
    "kickoff": PagineImpostazioni(
        codici=("tasks.impostazioni.manage",),
        rotte=("tasks:impostazioni", "tasks:impostazioni_kickoff_delete", "tasks:impostazioni_task_delete"),
        nuovo="Kickoff · impostazioni",
        modulo_acl="tasks",
    ),
    "rentri": PagineImpostazioni(
        codici=("rentri.impostazioni.manage",),
        rotte=("rentri_impostazioni",),
        nuovo="RENTRI · impostazioni",
        modulo_acl="rentri",
    ),
    "carichi_macchina": PagineImpostazioni(
        codici=("gestione_carichi_macchina.impostazioni.manage",),
        rotte=("gestione_carichi_macchina:impostazioni",),
        nuovo="Carichi macchina · impostazioni macchine",
        modulo_acl="gestione_carichi_macchina",
    ),
    "notizie": PagineImpostazioni(
        codici=("notizie.impostazioni.manage",),
        rotte=("notizie_gestione_admin",),
        nuovo="Notizie · impostazioni e gestione interna",
        modulo_acl="notizie",
    ),
    "anagrafica": PagineImpostazioni(
        codici=("anagrafica.impostazioni.manage",),
        rotte=(
            "anagrafica:impostazioni", "anagrafica:impostazioni_permessi_save",
            "anagrafica:impostazioni_acl_role_grants_save", "anagrafica:impostazioni_acl_user_override_save",
            "anagrafica:avviso_it_save", "anagrafica:workflow_campo_create",
            "anagrafica:workflow_campo_update", "anagrafica:workflow_campo_delete",
            "anagrafica:retention",
            "anagrafica:viste_elenco", "anagrafica:vista_elenco_nuova", "anagrafica:vista_elenco_modifica",
            "anagrafica:vista_elenco_azione", "anagrafica:vista_elenco_anteprima",
        ),
        nuovo="Anagrafica · impostazioni",
        modulo_acl="anagrafica",
    ),
    "formazione": PagineImpostazioni(
        codici=("formazione.impostazioni.manage",),
        rotte=(
            "anagrafica:attestato_impostazioni", "anagrafica:formazione_elearning_settings",
            "anagrafica:formazione_scansioni_impostazioni",
        ),
        nuovo="Formazione · impostazioni (attestati, e-learning, scansioni)",
        modulo_acl="anagrafica",
    ),
    "visite_mediche": PagineImpostazioni(
        codici=("visite_mediche.impostazioni.manage",),
        rotte=("anagrafica:referti_impostazioni",),
        nuovo="Visite mediche · impostazioni referti",
        modulo_acl="anagrafica",
    ),
    "schede_sicurezza": PagineImpostazioni(
        codici=("schede_sicurezza.impostazioni.manage",),
        rotte=("schede_sicurezza:etichetta_impostazioni",),
        nuovo="Schede di sicurezza · impostazioni etichetta",
        modulo_acl="schede_sicurezza",
    ),
    "sistema_gestione": PagineImpostazioni(
        codici=("sistema_gestione.impostazioni.manage",),
        rotte=("sistema_gestione:audit_impostazioni",),
        nuovo="Sistema di gestione · impostazioni audit",
        modulo_acl="sistema_gestione",
    ),
    "contatori": PagineImpostazioni(
        codici=("contatori.impostazioni.manage",),
        rotte=("contatori:impostazioni",),
        nuovo="Contatori · impostazioni",
        modulo_acl="contatori",
    ),
    "checklist_operativa": PagineImpostazioni(
        codici=("checklist_operativa.impostazioni.manage",),
        rotte=(
            "checklist_operativa:configurazione", "checklist_operativa:task_nuovo",
            "checklist_operativa:task_modifica", "checklist_operativa:task_toggle",
        ),
        nuovo="Checklist operativa · configurazione dei task",
        modulo_acl="checklist_operativa",
    ),
}


def pagine_impostazioni(chiave_modulo: str) -> PagineImpostazioni | None:
    return IMPOSTAZIONI.get(str(chiave_modulo or "").strip().lower())


def codice_impostazioni(chiave_modulo: str) -> str:
    """Il permesso a cui sono legate le rotte delle impostazioni del modulo."""
    pagine = pagine_impostazioni(chiave_modulo)
    return pagine.codici[0] if pagine else ""


def assicura_permesso_impostazioni(chiave_modulo: str) -> str:
    """Crea il permesso delle impostazioni se manca (per i bootstrap delle app)."""
    from core.models import PermissionDefinition

    pagine = pagine_impostazioni(chiave_modulo)
    if pagine is None:
        return ""
    code = pagine.codici[0]
    PermissionDefinition.objects.get_or_create(code=code, defaults={
        "label": pagine.nuovo or code, "module": pagine.modulo_acl or chiave_modulo,
        "description": "Pagine di impostazioni del modulo: le apre l'azione «impostazioni» della matrice.",
        "is_active": True,
    })
    return code


def impostazioni_consentite(request, chiave_modulo: str) -> bool | None:
    """Con il sistema dei ruoli acceso: la persona apre le impostazioni del modulo?

    ``None`` a sistema spento (o modulo senza impostazioni dichiarate): decide il
    controllo storico della view. Acceso, vale il permesso di pagina delle
    impostazioni, lo stesso che il middleware controlla sulla rotta (superuser e
    amministratori compresi).
    """
    from core.permessi.motore import sistema_ruoli_attivo

    pagine = pagine_impostazioni(chiave_modulo)
    if pagine is None or not sistema_ruoli_attivo():
        return None
    from core.acl_v2 import request_has_permission_code

    return any(request_has_permission_code(request, code) for code in pagine.codici)


def impostazioni_o(request, chiave_modulo: str, controllo_storico) -> bool:
    """Gate delle view di impostazioni: la matrice a sistema acceso, il controllo storico se spento."""
    esito = impostazioni_consentite(request, chiave_modulo)
    return bool(controllo_storico(request)) if esito is None else esito
