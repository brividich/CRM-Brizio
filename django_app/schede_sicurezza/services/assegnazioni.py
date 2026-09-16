"""Assegnazione dinamica delle SDS in base alla mansione corrente.

La fonte di verita' resta la relazione prodotto->mansioni e la mansione viva
del dipendente. Un cambio mansione rende quindi immediatamente dovute le SDS
nuove; la presa visione conserva lo storico della specifica versione letta.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ProfiloSDSUtente:
    collegato: bool
    mansione_nome: str
    mansione_id: int | None
    schede: list
    schede_lette_ids: set[int]

    @property
    def da_leggere(self) -> list:
        return [scheda for scheda in self.schede if scheda.pk not in self.schede_lette_ids]

    @property
    def completate(self) -> list:
        return [scheda for scheda in self.schede if scheda.pk in self.schede_lette_ids]


def _mansione_per_nome(nome: str):
    from anagrafica.models import Mansione

    nome = (nome or "").strip()
    if not nome:
        return None
    return Mansione.objects.filter(nome__iexact=nome).order_by("-is_active", "pk").first()


def _riga_anagrafica_per_legacy_user_id(legacy_user_id: int | None):
    if not legacy_user_id:
        return None
    try:
        from core.legacy_models import AnagraficaDipendente
        from core.legacy_utils import legacy_table_has_column

        if not legacy_table_has_column("anagrafica_dipendenti", "utente_id"):
            return None
        return (
            AnagraficaDipendente.objects
            .filter(utente_id=legacy_user_id)
            .values("id", "utente_id", "mansione")
            .first()
        )
    except Exception:
        logger.warning("Risoluzione dipendente per SDS fallita", exc_info=True)
        return None


def profilo_sds_utente(user) -> ProfiloSDSUtente:
    """SDS correnti dovute all'utente in base alla mansione viva in anagrafica."""
    vuoto = ProfiloSDSUtente(False, "", None, [], set())
    if not getattr(user, "is_authenticated", False):
        return vuoto

    try:
        from core.models import Profile
        from ..models import PresaVisioneScheda, SchedaSicurezza

        legacy_user_id = (
            Profile.objects.filter(user=user).values_list("legacy_user_id", flat=True).first()
        )
        dipendente = _riga_anagrafica_per_legacy_user_id(legacy_user_id)
        if not dipendente:
            return vuoto
        mansione_nome = (dipendente.get("mansione") or "").strip()
        mansione = _mansione_per_nome(mansione_nome)
        if mansione is None:
            return ProfiloSDSUtente(True, mansione_nome, None, [], set())

        schede = list(
            SchedaSicurezza.objects.filter(
                is_corrente=True,
                prodotto__attivo=True,
                prodotto__mansioni=mansione,
            )
            .select_related("prodotto")
            .prefetch_related("prodotto__mansioni", "prodotto__dpi_obbligatori")
            .order_by("prodotto__nome")
        )
        lette = set(
            PresaVisioneScheda.objects.filter(
                operatore=user, scheda_id__in=[scheda.pk for scheda in schede]
            ).values_list("scheda_id", flat=True)
        )
        return ProfiloSDSUtente(True, mansione.nome, mansione.pk, schede, lette)
    except Exception:
        logger.warning(
            "Calcolo SDS dovute all'utente %s fallito",
            getattr(user, "pk", None),
            exc_info=True,
        )
        return vuoto


def _utenti_legacy_per_mansioni(nomi_mansioni: list[str]) -> dict[int, str]:
    """Mappa legacy_user_id -> mansione per dipendenti attivi delle mansioni date."""
    nomi = [nome.strip() for nome in nomi_mansioni if (nome or "").strip()]
    if not nomi:
        return {}
    try:
        from django.db.models import Q
        from anagrafica.models import DipendenteAnagraficaAziendale
        from core.legacy_models import AnagraficaDipendente
        from core.legacy_utils import legacy_table_has_column

        if not legacy_table_has_column("anagrafica_dipendenti", "utente_id"):
            return {}
        filtro = Q()
        for nome in nomi:
            filtro |= Q(mansione__iexact=nome)
        cessati_ids = DipendenteAnagraficaAziendale.objects.filter(
            data_cessazione__isnull=False
        ).values_list("legacy_anagrafica_id", flat=True)
        rows = (
            AnagraficaDipendente.objects.filter(
                filtro, utente_id__isnull=False
            ).exclude(id__in=cessati_ids).values_list("utente_id", "mansione")
        )
        return {int(uid): (mansione or "") for uid, mansione in rows if uid}
    except Exception:
        logger.warning("Risoluzione destinatari SDS per mansione fallita", exc_info=True)
        return {}


def _django_user_ids_per_legacy(legacy_ids: set[int]) -> dict[int, int]:
    if not legacy_ids:
        return {}
    try:
        from core.models import Profile

        return {
            int(legacy_id): int(user_id)
            for legacy_id, user_id in Profile.objects.filter(
                legacy_user_id__in=legacy_ids, user__is_active=True
            ).values_list("legacy_user_id", "user_id")
            if legacy_id and user_id
        }
    except Exception:
        logger.warning("Risoluzione account Django per destinatari SDS fallita", exc_info=True)
        return {}


def _notifica_destinatari_scheda(scheda, nomi_mansioni: list[str], *, motivo: str) -> int:
    from core.notifiche import invia_notifica
    from ..models import PresaVisioneScheda

    destinatari = _utenti_legacy_per_mansioni(nomi_mansioni)
    django_ids = _django_user_ids_per_legacy(set(destinatari))
    gia_letta = set(
        PresaVisioneScheda.objects.filter(
            scheda=scheda, operatore_id__in=django_ids.values()
        ).values_list("operatore_id", flat=True)
    )
    inviate = 0
    for legacy_user_id, mansione in destinatari.items():
        if django_ids.get(legacy_user_id) in gia_letta:
            continue
        invia_notifica(
            legacy_user_id,
            "presa_visione",
            (
                f"SDS '{scheda.prodotto.nome}' versione {scheda.versione or '-'} "
                f"da prendere in visione per la mansione '{mansione}' ({motivo})."
            ),
            url_azione="/schede-sicurezza/da-leggere/",
        )
        inviate += 1
    return inviate


def notifica_nuova_versione(scheda) -> int:
    """Avvisa i dipendenti interessati quando diventa corrente una nuova SDS."""
    nomi = list(scheda.prodotto.mansioni.values_list("nome", flat=True))
    return _notifica_destinatari_scheda(scheda, nomi, motivo="nuova versione")


def notifica_mansioni_aggiunte(prodotto, mansione_ids: set[int]) -> int:
    """Avvisa i nuovi destinatari quando una SDS corrente viene legata a una mansione."""
    scheda = prodotto.scheda_corrente()
    if scheda is None or not mansione_ids:
        return 0
    nomi = list(
        prodotto.mansioni.filter(pk__in=mansione_ids).values_list("nome", flat=True)
    )
    return _notifica_destinatari_scheda(scheda, nomi, motivo="nuova assegnazione")


def notifica_cambio_mansione(
    legacy_anagrafica_id: int,
    mansione_nuova: str,
    mansione_precedente: str = "",
) -> int:
    """Avvisa il dipendente delle SDS ancora da leggere dopo il cambio mansione."""
    if (mansione_nuova or "").strip().casefold() == (mansione_precedente or "").strip().casefold():
        return 0
    mansione = _mansione_per_nome(mansione_nuova)
    if mansione is None:
        return 0
    try:
        from core.legacy_models import AnagraficaDipendente
        from core.models import Profile
        from core.notifiche import invia_notifica
        from ..models import PresaVisioneScheda, SchedaSicurezza

        legacy_user_id = (
            AnagraficaDipendente.objects.filter(pk=legacy_anagrafica_id)
            .values_list("utente_id", flat=True)
            .first()
        )
        if not legacy_user_id:
            return 0
        schede_ids = set(
            SchedaSicurezza.objects.filter(
                is_corrente=True, prodotto__attivo=True, prodotto__mansioni=mansione
            ).values_list("pk", flat=True)
        )
        if not schede_ids:
            return 0
        django_user_id = (
            Profile.objects.filter(legacy_user_id=legacy_user_id, user__is_active=True)
            .values_list("user_id", flat=True)
            .first()
        )
        lette = set()
        if django_user_id:
            lette = set(
                PresaVisioneScheda.objects.filter(
                    operatore_id=django_user_id, scheda_id__in=schede_ids
                ).values_list("scheda_id", flat=True)
            )
        mancanti = len(schede_ids - lette)
        if not mancanti:
            return 0
        invia_notifica(
            int(legacy_user_id),
            "presa_visione",
            (
                f"Nuova mansione '{mansione.nome}': hai {mancanti} "
                f"{'schede' if mancanti != 1 else 'scheda'} di sicurezza da prendere in visione."
            ),
            url_azione="/schede-sicurezza/da-leggere/",
        )
        return mancanti
    except Exception:
        logger.warning(
            "Notifica SDS per cambio mansione fallita (dipendente=%s, mansione=%s)",
            legacy_anagrafica_id,
            mansione_nuova,
            exc_info=True,
        )
        return 0
