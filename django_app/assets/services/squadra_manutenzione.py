"""Squadra manutenzione interna: chi puo' ricevere un intervento eseguito «Interno».

Due impostazioni (SiteConfig, da Assets > Impostazioni > Configurazione):

- ``assets_squadra_manutenzione_gruppo``: codice del ruolo del portale
  (``AccessGroup``) che raccoglie i manutentori. I membri sono quelli messi a
  mano nel ruolo piu' quelli che lo ricevono dall'organigramma.
- ``assets_straordinaria_assegnatario``: username del manutentore proposto
  come «Assegnato a» quando l'intervento e' interno.

Finche' l'impostazione non e' salvata vale il ruolo ``manutenzione``.
Senza gruppo (scelto «Nessuno», ruolo inesistente o vuoto) l'elenco resta quello di
sempre: tutti gli utenti attivi. Nessun nome di persona sta nel codice.
"""
from __future__ import annotations

import logging

from django.contrib.auth import get_user_model
from django.db import DatabaseError
from django.db.models import Q, QuerySet
from django.utils import timezone

logger = logging.getLogger(__name__)

CHIAVE_GRUPPO = "assets_squadra_manutenzione_gruppo"
CHIAVE_ASSEGNATARIO = "assets_straordinaria_assegnatario"
# Ruolo usato finche' nessuno sceglie altro (il ruolo «Manutenzione» del portale).
# Scegliere «Nessuno» nelle impostazioni salva il valore vuoto e lo disattiva.
GRUPPO_PREDEFINITO = "manutenzione"
DESCRIZIONE_GRUPPO = "Ruolo del portale con i manutentori interni (interventi «Interno»)"
DESCRIZIONE_ASSEGNATARIO = "Username del manutentore proposto negli interventi interni"


def impostazioni() -> dict[str, str]:
    from core.models import SiteConfig

    valori = SiteConfig.get_many({CHIAVE_GRUPPO: GRUPPO_PREDEFINITO, CHIAVE_ASSEGNATARIO: ""})
    return {
        "gruppo": (valori.get(CHIAVE_GRUPPO) or "").strip().lower(),
        "assegnatario": (valori.get(CHIAVE_ASSEGNATARIO) or "").strip(),
    }


def salva_impostazioni(*, gruppo: str, assegnatario: str) -> None:
    from core.models import SiteConfig

    SiteConfig.set(CHIAVE_GRUPPO, (gruppo or "").strip().lower(), DESCRIZIONE_GRUPPO)
    SiteConfig.set(CHIAVE_ASSEGNATARIO, (assegnatario or "").strip(), DESCRIZIONE_ASSEGNATARIO)


def gruppo_configurato():
    """Il ruolo della squadra, se configurato e attivo."""
    from core.models import AccessGroup

    codice = impostazioni()["gruppo"]
    if not codice:
        return None
    try:
        return AccessGroup.objects.filter(code=codice, is_active=True).first()
    except DatabaseError:
        return None


def _legacy_ids_del_gruppo(gruppo) -> set[int]:
    from core.models import AccessGroupMembership

    oggi = timezone.localdate()
    ids: set[int] = set()
    try:
        ids |= set(
            AccessGroupMembership.objects.filter(group=gruppo)
            .filter(Q(scade_il__isnull=True) | Q(scade_il__gte=oggi))
            .values_list("legacy_user_id", flat=True)
        )
    except DatabaseError:
        logger.warning("Squadra manutenzione: appartenenze non leggibili", exc_info=True)
    try:
        from core.permessi.organigramma import utenti_del_gruppo

        ids |= utenti_del_gruppo(gruppo.id)
    except Exception:
        logger.warning("Squadra manutenzione: ruoli da organigramma non leggibili", exc_info=True)
    return {int(i) for i in ids if i}


def membri_squadra() -> QuerySet | None:
    """Utenti Django attivi della squadra; ``None`` = nessuna squadra (vale chiunque)."""
    gruppo = gruppo_configurato()
    if gruppo is None:
        return None
    legacy_ids = _legacy_ids_del_gruppo(gruppo)
    if not legacy_ids:
        return None
    from core.models import Profile

    user_ids = set(Profile.objects.filter(legacy_user_id__in=legacy_ids).values_list("user_id", flat=True))
    if not user_ids:
        return None
    return get_user_model().objects.filter(pk__in=user_ids, is_active=True)


def assegnatario_predefinito():
    """Il manutentore proposto negli interventi interni (utente attivo), se configurato."""
    username = impostazioni()["assegnatario"]
    if not username:
        return None
    User = get_user_model()
    return User.objects.filter(is_active=True).filter(
        Q(username__iexact=username) | Q(email__iexact=username)
    ).first()


def ruoli_disponibili() -> list:
    from core.models import AccessGroup

    try:
        return list(AccessGroup.objects.filter(is_active=True, amministratore=False).order_by("label", "id"))
    except DatabaseError:
        return []
