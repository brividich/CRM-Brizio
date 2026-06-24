"""F6 — Distribuzione tracciata + regola copie cartacee con deroga.

- Presa visione richiesta secondo `ConfigPresaVisione` (tipo documento × reparto) —
  decisione F0 #3.
- Copie cartacee: **warning + deroga giustificata** (no blocco rigido — decisione
  F0 #4) quando le copie ritirate per la nuova revisione non corrispondono alle
  copie distribuite per la revisione precedente. Con una giustificazione di deroga
  l'operazione procede comunque.
"""
from __future__ import annotations

import logging

from django.db import transaction
from django.utils import timezone

from . import constants as C
from .models import ConfigPresaVisione, Distribuzione, EventoSpecifica

logger = logging.getLogger(__name__)


class DerogaCopieRichiesta(Exception):
    """Sollevata quando le copie non corrispondono e manca la giustificazione."""

    def __init__(self, attese: int, ritirate: int):
        self.attese = attese
        self.ritirate = ritirate
        super().__init__(
            f"Copie non corrispondenti: rev. precedente distribuite={attese}, "
            f"ritirate per la nuova rev={ritirate}. Serve una giustificazione di deroga."
        )


def _log_evento(spec, trigger: str, payload: dict, attore=None) -> None:
    try:
        EventoSpecifica.objects.create(
            specifica=spec, stato_da=spec.stato, stato_a=spec.stato,
            attore=attore, trigger=trigger,
            payload={"snapshot": spec.snapshot_metadati(), **payload},
        )
    except Exception as exc:  # pragma: no cover
        logger.debug("gs log evento distribuzione fallito: %s", exc)


def presa_visione_richiesta(tipo_documento: str, reparti) -> bool:
    """True se per il tipo documento la presa visione è richiesta per almeno un
    reparto destinatario (o per la regola di default reparto=NULL)."""
    reparti = list(reparti or [])

    def _per_reparto(reparto):
        cfg = ConfigPresaVisione.objects.filter(
            tipo_documento=tipo_documento, reparto=reparto
        ).first()
        if cfg is None:
            cfg = ConfigPresaVisione.objects.filter(
                tipo_documento=tipo_documento, reparto__isnull=True
            ).first()
        return bool(cfg.richiesta) if cfg else False

    if not reparti:
        return _per_reparto(None)
    return any(_per_reparto(r) for r in reparti)


def copie_distribuite_rev_precedente(specifica) -> int:
    """Copie cartacee distribuite nell'ultima distribuzione cartacea della rev precedente."""
    prev = specifica.revisione_precedente
    if prev is None:
        return 0
    last = (
        Distribuzione.objects.filter(specifica=prev, cartacea=True)
        .order_by("-created_at").first()
    )
    return int(last.n_copie_distribuite) if last else 0


@transaction.atomic
def crea_distribuzione(
    specifica, *, canale: str, reparti=None, cartacea: bool = False,
    n_copie_distribuite: int = 0, n_copie_ritirate: int = 0,
    presa_visione=None, deroga_giustificazione: str = "", attore=None,
) -> Distribuzione:
    reparti = list(reparti or [])
    if presa_visione is None:
        presa_visione = presa_visione_richiesta(specifica.tipo, reparti)

    deroga_necessaria = False
    attese = 0
    if cartacea:
        attese = copie_distribuite_rev_precedente(specifica)
        if n_copie_ritirate != attese:
            deroga_necessaria = True
            if not (deroga_giustificazione or "").strip():
                raise DerogaCopieRichiesta(attese, n_copie_ritirate)

    dist = Distribuzione.objects.create(
        specifica=specifica, canale=canale, presa_visione_richiesta=presa_visione,
        cartacea=cartacea, n_copie_distribuite=int(n_copie_distribuite or 0),
        n_copie_ritirate=int(n_copie_ritirate or 0),
        deroga_giustificazione=deroga_giustificazione or "",
        data_distribuzione=timezone.now(),
    )
    if reparti:
        dist.destinatari.set(reparti)

    _log_evento(specifica, "distribuzione", {
        "canale": canale, "cartacea": cartacea,
        "n_copie_distribuite": dist.n_copie_distribuite,
        "n_copie_ritirate": dist.n_copie_ritirate,
        "deroga": bool(deroga_necessaria),
        "presa_visione_richiesta": presa_visione,
        "reparti": [r.id for r in reparti],
    }, attore)
    return dist
