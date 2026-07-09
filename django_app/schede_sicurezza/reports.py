"""Query di sola lettura per il report di compliance SDS (nessun modello nuovo).

Funzioni pure: non toccano `request`, non hanno side effect. Consumate dalla
view `schede_sicurezza.views.report_compliance` sia per il rendering HTML sia
per l'export CSV.
"""
from __future__ import annotations

from dataclasses import dataclass


def prodotti_senza_scheda_corrente():
    """QuerySet dei ProdottoChimico attivi senza nessuna SchedaSicurezza corrente."""
    from .models import ProdottoChimico

    return (
        ProdottoChimico.objects.filter(attivo=True)
        .exclude(schede__is_corrente=True)
        .select_related("reparto")
        .order_by("reparto__nome", "nome")
    )


@dataclass
class RigaMatricePresaVisione:
    prodotto_id: int
    prodotto_nome: str
    scheda_id: int
    scheda_versione: str
    totale_dipendenti: int
    confermati: int
    percentuale: int | None


@dataclass
class RepartoMatricePresaVisione:
    reparto_id: int
    reparto_nome: str
    righe: list[RigaMatricePresaVisione]


def _user_ids_attivi_per_reparto(reparto_id: int) -> set[int]:
    """Django User attivi collegati (via Profile) a dipendenti in forza del reparto.

    Percorso verificato: Reparto <- AreaAziendale.reparto <- DipendenteAnagraficaAziendale
    (legacy_anagrafica_id == Profile.legacy_user_id, stesso spazio ID) -> User.
    Limite noto: cattura solo i dipendenti con `area_aziendale` valorizzato, non
    quelli ancora sul solo campo testo legacy `area`.
    """
    from anagrafica.models import DipendenteAnagraficaAziendale
    from core.models import Profile

    legacy_ids = list(
        DipendenteAnagraficaAziendale.objects.filter(
            area_aziendale__reparto_id=reparto_id,
            data_cessazione__isnull=True,
        ).values_list("legacy_anagrafica_id", flat=True)
    )
    if not legacy_ids:
        return set()
    return set(
        Profile.objects.filter(legacy_user_id__in=legacy_ids, user__is_active=True)
        .values_list("user_id", flat=True)
    )


def matrice_presa_visione() -> list[RepartoMatricePresaVisione]:
    """Un elemento per ogni Reparto con almeno un prodotto attivo con scheda corrente."""
    from anagrafica.models import Reparto

    from .models import PresaVisioneScheda, ProdottoChimico

    risultato: list[RepartoMatricePresaVisione] = []
    reparti = (
        Reparto.objects.filter(
            prodotti_chimici__attivo=True,
            prodotti_chimici__schede__is_corrente=True,
        )
        .distinct()
        .order_by("nome")
    )
    for reparto in reparti:
        user_ids = _user_ids_attivi_per_reparto(reparto.id)
        prodotti = (
            ProdottoChimico.objects.filter(reparto=reparto, attivo=True, schede__is_corrente=True)
            .distinct()
            .order_by("nome")
        )
        righe: list[RigaMatricePresaVisione] = []
        for prodotto in prodotti:
            scheda = prodotto.scheda_corrente()
            if scheda is None:
                continue
            totale = len(user_ids)
            if totale == 0:
                confermati = 0
                percentuale = None
            else:
                confermati = PresaVisioneScheda.objects.filter(
                    scheda=scheda, operatore_id__in=user_ids
                ).count()
                percentuale = round((confermati / totale) * 100)
            righe.append(RigaMatricePresaVisione(
                prodotto_id=prodotto.id,
                prodotto_nome=prodotto.nome,
                scheda_id=scheda.id,
                scheda_versione=scheda.versione,
                totale_dipendenti=totale,
                confermati=confermati,
                percentuale=percentuale,
            ))
        if righe:
            risultato.append(RepartoMatricePresaVisione(
                reparto_id=reparto.id, reparto_nome=reparto.nome, righe=righe,
            ))
    return risultato
