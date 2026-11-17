"""«Le tue visite»: il referente collega la visita a un ticket IT/MAN o a un ordine di lavoro.

Il collegamento è quello di Fornitori («Presenze in azienda della ditta», ``fornitori.ingressi``):
un ``IngressoIntervento`` con la fotografia dell'ingresso, che resta nel ticket/OdL anche dopo la
cancellazione della visita, conta nelle ore in azienda e nel rapportino. Qui c'è solo il punto di
partenza del referente.

- Collegabile: motivo con «Collegabile a ticket e OdL» (Reception → Impostazioni), visita di una ditta
  accreditata, o visita già collegata.
- Collega solo il referente della visita. Ticket: chi lo gestisce (regola del riquadro di Fornitori)
  oppure chi l'ha aperto, IT o manutenzione. OdL: chi esegue le manutenzioni (stessa regola di Fornitori).
- Toglie un collegamento chi l'ha fatto, finché il ticket/OdL non è annullato.
"""
from __future__ import annotations

import logging

from django.db.models import Q

from .models import CategoriaVisita, Visita

logger = logging.getLogger(__name__)

MAX_PROPOSTE = 30
TICKET_CHIUSI = ("CHIUSO", "ANNULLATO")


def motivi_di_lavoro() -> set[str]:
    return {n.strip().lower() for n in CategoriaVisita.objects.filter(collega_interventi=True).values_list("nome", flat=True)}


def collegabile(riga, motivi: set[str] | None = None, *, collegata: bool = False) -> bool:
    """Per una ``Visita`` o una ``Preregistrazione``."""
    if collegata or getattr(riga, "ticket_id", None) or getattr(riga, "ordine_lavoro_id", None):
        return True
    if getattr(riga, "tipo", "") == Visita.FORNITORE:
        return True
    motivi = motivi_di_lavoro() if motivi is None else motivi
    return (riga.motivo or "").strip().lower() in motivi


def e_il_referente(user, riga) -> bool:
    email = (getattr(user, "email", "") or "").strip().lower()
    return "@" in email and (riga.referente_email or "").strip().lower() == email


# --- Chi collega cosa --------------------------------------------------------------------------


def puo_collegare_ticket(request, ticket) -> bool:
    """Chi gestisce il ticket o chi l'ha aperto (anche per conto d'altri)."""
    from tickets.views import _ticket_access_flags

    try:
        accesso = _ticket_access_flags(request, ticket)
    except Exception:  # noqa: BLE001 - nel dubbio non si collega
        logger.exception("reception: verifica accesso al ticket %s", ticket.pk)
        return False
    aperto_da_me = bool(ticket.aperto_da_user_id and ticket.aperto_da_user_id == request.user.id)
    return bool(accesso["is_gestore"] or accesso["is_admin"] or accesso["is_richiedente"] or aperto_da_me)


def gestisce_ticket(request, ticket) -> bool:
    from tickets.services.accesso import utente_puo_gestire_ticket

    return utente_puo_gestire_ticket(request, ticket)


def puo_collegare_odl(request) -> bool:
    from fornitori import ingressi

    return ingressi.puo_collegare_odl(request)


# --- Proposte ----------------------------------------------------------------------------------


def accesso_della_visita(visita: Visita):
    from .letture import _accesso

    return _accesso(visita)


def fornitore_della_visita(visita: Visita):
    """Stessa regola di Fornitori: abbinamento della ditta («Ditte GuestPortal») o nome uguale."""
    from fornitori import ingressi

    try:
        return ingressi.fornitore_da_accesso(accesso_della_visita(visita))
    except Exception:  # noqa: BLE001 - senza ditta riconosciuta si propongono solo i propri
        logger.exception("reception: ditta della visita %s", visita.pk)
        return None


def _ticket_miei(user) -> Q:
    email = (user.email or "").strip()
    filtro = Q(richiedente_user=user) | Q(aperto_da_user=user)
    if "@" in email:
        filtro |= Q(richiedente_email__iexact=email) | Q(assegnato_email__iexact=email)
    return filtro


def proposte(request, fornitore=None) -> dict:
    """``{"ticket": [...], "odl": [...]}`` aperti: i propri e quelli della ditta, solo se collegabili."""
    from assets.models import WorkOrder
    from tickets.models import Ticket

    filtro = _ticket_miei(request.user)
    if fornitore is not None:
        filtro |= Q(delegato_fornitore=fornitore)
    righe = Ticket.objects.filter(filtro).exclude(stato__in=TICKET_CHIUSI).order_by("-created_at")[:MAX_PROPOSTE * 2]
    ticket = [t for t in righe if puo_collegare_ticket(request, t)][:MAX_PROPOSTE]
    odl = []
    if puo_collegare_odl(request):
        filtro = Q(assigned_to=request.user) | Q(ticket__in=[t.pk for t in ticket])
        if fornitore is not None:
            filtro |= Q(supplier=fornitore)
        odl = list(WorkOrder.objects.select_related("asset").filter(filtro, status=WorkOrder.STATUS_OPEN)
                   .order_by("-opened_at")[:MAX_PROPOSTE])
    return {"ticket": ticket, "odl": odl}


def scelta(request, dati) -> tuple[object | None, object | None]:
    """(ticket, OdL) scelto: ``intervento`` = ``t:<id>``/``o:<id>`` dall'elenco o ``numero`` scritto a mano
    (``MAN-2026-0012``, ``IT-2026-0003``, ``342``). ``None`` dove non c'è o non si può collegare."""
    from assets.models import WorkOrder
    from tickets.models import Ticket

    valore, numero = (dati.get("intervento") or "").strip(), (dati.get("numero") or "").strip()
    ticket = odl = None
    if valore.startswith("t:") and valore[2:].isdigit():
        ticket = Ticket.objects.filter(pk=int(valore[2:])).first()
    elif valore.startswith("o:") and valore[2:].isdigit():
        odl = WorkOrder.objects.filter(pk=int(valore[2:])).first()
    elif numero:
        ticket = Ticket.objects.filter(numero_ticket__iexact=numero).first()
        cifre = numero.lstrip("#").split("-")[0].strip()
        if ticket is None and cifre.isdigit():
            odl = WorkOrder.objects.filter(pk=int(cifre)).first()
    if ticket is not None and not puo_collegare_ticket(request, ticket):
        ticket = None
    if odl is not None and not puo_collegare_odl(request):
        odl = None
    return ticket, odl


# --- Collegamenti ------------------------------------------------------------------------------


def collegamenti(visita_ids: list[int]) -> dict[int, list]:
    """visita → collegamenti (``IngressoIntervento``) con ``etichetta`` e ``url``."""
    from fornitori.models import IngressoIntervento
    from fornitori import ingressi

    esito: dict[int, list] = {}
    if not visita_ids:
        return esito
    righe = IngressoIntervento.objects.filter(visita_gp_id__in=visita_ids).select_related(
        "ticket", "work_order", "work_order__asset", "sessione_formazione", "sessione_formazione__corso", "occorrenza",
        "occorrenza__plan", "occorrenza__asset", "scadenza_asset", "scadenza_asset__asset", "scadenza", "scadenza__categoria",
        "verifica", "verifica__check_type", "verifica__check_type__system",
    ).order_by("pk")
    for link in righe:
        iv = ingressi.intervento_del_link(link)
        if link.ticket_id:
            link.etichetta = link.ticket.numero_ticket
        elif link.work_order_id:
            link.etichetta = f"OdL #{link.work_order_id}"
        else:
            link.etichetta = iv.etichetta
        link.url, link.titolo, link.chiuso = iv.url, iv.titolo, iv.chiuso
        esito.setdefault(link.visita_gp_id, []).append(link)
    return esito


def collega(visita_id: int, *, ticket=None, odl=None, utente=None, autore=None, ditta_ticket: bool = False) -> list[str]:
    """Collega la visita a ticket e/o OdL (``fornitori.ingressi.collega``). Ritorna gli errori, in chiaro.

    Come in Fornitori, un ticket/OdL senza ditta prende quella dell'ingresso; sul ticket solo con
    ``ditta_ticket`` (chi lo gestisce): chi l'ha solo aperto non lo delega a una ditta."""
    from fornitori import guestportal as gp
    from fornitori import ingressi
    from fornitori.models import IngressoIntervento

    errori = []
    for tipo, oggetto in ((ingressi.TIPO_TICKET, ticket), (ingressi.TIPO_ODL, odl)):
        if oggetto is None:
            continue
        iv = ingressi.intervento(tipo, oggetto.pk)
        try:
            ingressi.collega(iv, visita_id, utente=utente, modo=IngressoIntervento.MODO_MANUALE, autore=autore,
                             imposta_ditta=ditta_ticket or tipo == ingressi.TIPO_ODL)
        except ingressi.CollegamentoNonValido as exc:
            errori.append(f"{iv.etichetta}: {exc}")
        except (gp.GuestPortalNonConfigurato, gp.GuestPortalNonRaggiungibile):
            errori.append(f"{iv.etichetta}: dati della reception non raggiungibili, riprova tra poco.")
    return errori


def collega_da_invito(pre, visita: Visita) -> None:
    """All'ingresso con il codice: il ticket/OdL scelto annunciando l'ospite diventa un collegamento.
    Il permesso si è controllato all'annuncio; un errore qui non ferma l'ingresso."""
    if not (pre.ticket_id or pre.ordine_lavoro_id):
        return
    from django.contrib.auth import get_user_model

    utente = get_user_model().objects.filter(email__iexact=pre.referente_email, is_active=True).first() if pre.referente_email else None
    try:
        errori = collega(visita.pk, ticket=pre.ticket, odl=pre.ordine_lavoro, utente=utente)
    except Exception:  # noqa: BLE001
        logger.exception("reception: collegamento dall'invito %s", pre.pk)
        return
    for errore in errori:
        logger.warning("reception: collegamento dall'invito %s non fatto: %s", pre.pk, errore)
