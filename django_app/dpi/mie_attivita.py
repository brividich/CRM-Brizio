"""Voci DPI di «Le mie attività»: quello che l'utente deve fare, non solo ciò che ha chiesto.

Tre ruoli, ognuno con le stesse persone che ricevono la mail del passo (``flusso``):

- chi approva: il preposto scelto nella richiesta, altrimenti responsabile/preposto del dipendente;
- l'operatore incaricato delle scarpe (``destinatari_operatore_negozio``): scarpe da ordinare,
  arrivate da far ritirare, fuori convenzione da chiudere con la fattura;
- chi consegna (``destinatari_consegna``): Magazzino, o i referenti DPI per le categorie
  che il magazzino non distribuisce.

Le pagine di lavoro (Scarpe, Banco consegne) restano protette dal permesso «Gestire» del
modulo: a chi è incaricato ma non lo ha la voce lo dice, invece di portarlo a un rifiuto.
"""
from __future__ import annotations

import logging

from django.urls import reverse

from . import flusso, negozio
from .models import ModalitaNegozio, RichiestaDPI, StatoRichiesta

logger = logging.getLogger(__name__)

MAX_VOCI = 30
SENZA_PERMESSO = "Ti manca il permesso «Gestire» del modulo DPI: chiedilo a chi amministra i permessi"


def email_utente(request) -> set[str]:
    """Indirizzi con cui l'utente può comparire negli elenchi delle Impostazioni DPI."""
    from .views import _legacy_id

    emails = {str(getattr(request.user, "email", "") or "")}
    legacy_user = getattr(request, "legacy_user", None)
    emails.add(str(getattr(legacy_user, "email", "") or ""))
    try:
        legacy_id = _legacy_id(request)
        if legacy_id:
            emails.add(flusso._email_persona(legacy_id) or "")
    except Exception:
        logger.warning("Le mie attività DPI: email di notifica non letta", exc_info=True)
    return {e.strip().lower() for e in emails if e and e.strip()}


def _tra(destinatari, mie: set[str]) -> bool:
    return bool(mie & {str(e).strip().lower() for e in destinatari})


def incaricato_scarpe(request) -> bool:
    return _tra(flusso.destinatari_operatore_negozio(), email_utente(request))


def puo_scarpe(request) -> bool:
    """Chi apre la pagina «Scarpe»: chi gestisce il modulo e l'operatore incaricato in
    Impostazioni (lo stesso che riceve la mail), anche senza il permesso «Gestire»."""
    from .views import _is_gestore

    return _is_gestore(request) or incaricato_scarpe(request)


def scarpe_queryset(request):
    """Richieste approvate su cui lavora la pagina «Scarpe». Chi gestisce resta nel suo
    perimetro; l'operatore incaricato senza «Gestire» vede solo quelle che passano dal negozio."""
    from .views import _approvate_queryset, _is_gestore

    if _is_gestore(request):
        return _approvate_queryset(request)
    return (
        RichiestaDPI.objects.filter(stato=StatoRichiesta.APPROVATA).exclude(modalita_negozio="")
        .select_related("categoria", "tipo_dpi", "modello_dpi", "taglia_dpi")
    )


def _voce(r: RichiestaDPI, stato: str, url: str, *, permesso: bool = True) -> dict:
    return {
        "code": r.numero,
        "title": f"{flusso._riga_dpi(r)} · {r.richiedente_nome}",
        "meta": f"chiesta il {r.created_at:%d/%m/%Y}" + ("" if permesso else f" · {SENZA_PERMESSO}"),
        "status": stato,
        "due": None,
        "url": url if permesso else reverse("dpi:dashboard"),
    }


def _select(qs):
    return qs.select_related("categoria", "tipo_dpi", "modello_dpi", "taglia_dpi").order_by("created_at")


def da_approvare(request) -> list[dict]:
    """Richieste «Inviate» che aspettano l'utente: quelle in cui è il preposto scelto, e quelle
    senza preposto scelto delle persone di cui è responsabile/preposto."""
    from django.db.models import Q

    from .views import _legacy_id, _scope_approvatore

    me = _legacy_id(request)
    scope = _scope_approvatore(request)
    q = Q(pk__in=[])
    if me:
        q |= Q(preposto_legacy_id=me)
    if scope:
        q |= Q(preposto_legacy_id__isnull=True, richiedente_legacy_id__in=list(scope))
    qs = RichiestaDPI.objects.filter(stato=StatoRichiesta.INVIATA).filter(q)
    if me:
        qs = qs.exclude(richiedente_legacy_id=me)  # la propria richiesta non si approva
    return [
        _voce(r, "Da approvare", reverse("dpi:gestione_detail", args=[r.pk]))
        for r in _select(qs)[:MAX_VOCI]
    ]


def scarpe(request) -> list[dict]:
    """Scarpe che aspettano l'operatore incaricato (gli stessi destinatari della mail)."""
    if not incaricato_scarpe(request):
        return []
    permesso = True  # l'incaricato apre la pagina «Scarpe» anche senza «Gestire»
    base = _select(scarpe_queryset(request))
    url = reverse("dpi:negozio")
    voci = [_voce(r, "Scarpe da ordinare", url + "#da-ordinare", permesso=permesso) for r in negozio.da_ordinare(base)]
    voci += [
        _voce(r, "Scarpe ordinate: avvisa del ritiro quando arrivano", url + "#ordinate", permesso=permesso)
        for r in negozio.ordinate(base) if r.pronta_ritiro_il is None
    ]
    voci += [
        _voce(
            r,
            "Fuori convenzione: avvisa il negozio" if r.pronta_ritiro_il is None else "Fuori convenzione: carica la fattura",
            url + "#fuori", permesso=permesso,
        )
        for r in negozio.fuori_convenzione(base)
    ]
    return voci[:MAX_VOCI]


def da_consegnare(request) -> list[dict]:
    """Richieste approvate da preparare e consegnare, per chi riceve l'avviso di consegna."""
    from .views import _banco_queryset, _chiave_persona, _is_gestore

    mie = email_utente(request)
    del_magazzino = _tra(flusso.destinatari_magazzino(), mie)
    dei_referenti = _tra(flusso.destinatari_referenti(), mie)
    if not (del_magazzino or dei_referenti):
        return []
    # Le scarpe ordinate al negozio le segue l'operatore incaricato (sopra).
    qs = _banco_queryset(request).filter(modalita_negozio="")
    if not del_magazzino:
        qs = qs.filter(categoria__consegna_magazzino=False)
    elif not dei_referenti:
        qs = qs.filter(categoria__consegna_magazzino=True)
    permesso = _is_gestore(request)
    banco = reverse("dpi:banco")
    voci = []
    for r in _select(qs)[:MAX_VOCI]:
        tutte = "" if r.categoria.consegna_magazzino else "?tutte=1"
        stato = "Pronto: da consegnare" if r.pronta_ritiro_il else "Da preparare e consegnare"
        voci.append(_voce(r, stato, f"{banco}{tutte}#apri-{_chiave_persona(r)}", permesso=permesso))
    return voci


def voci_da_fare(request) -> list[dict]:
    """Tutte le voci DPI che aspettano l'utente; ogni parte è isolata."""
    voci: list[dict] = []
    for nome, fonte in (("approvazioni", da_approvare), ("scarpe", scarpe), ("consegne", da_consegnare)):
        try:
            voci += fonte(request)
        except Exception:
            logger.exception("Le mie attività: DPI «%s» non calcolabile", nome)
    return voci


def incaricati_senza_utente() -> list[dict]:
    """Per le Impostazioni: indirizzi degli elenchi «chi deve agire» che non corrispondono a
    nessun utente attivo del portale (ricevono la mail ma non vedono nulla in «Le mie attività»)."""
    from django.contrib.auth import get_user_model

    from .models import DPIImpostazioni

    impost = DPIImpostazioni.get_singleton()
    elenchi = (
        ("Magazzino", flusso._split_emails(impost.magazzino_emails)),
        ("Scarpe: operatore incaricato", flusso._split_emails(impost.negozio_operatore_emails)),
    )
    tutte = {e.lower() for _, lista in elenchi for e in lista}
    if not tutte:
        return []
    User = get_user_model()
    note = {
        (u or "").strip().lower()
        for u in User.objects.filter(is_active=True).exclude(email="").values_list("email", flat=True)
    }
    return [
        {"elenco": nome, "email": e}
        for nome, lista in elenchi for e in lista if e.lower() not in note
    ]
