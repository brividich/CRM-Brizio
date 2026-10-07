"""Ciclo di vita delle notifiche in-app: lettura, archiviazione, pulizia.

Una notifica **archiviata** esce da campanella, badge, banner e popup ma resta
consultabile dall'utente in «Notifiche → Archiviate». L'archiviazione avviene:

- **automaticamente** (task giornaliero ``core.tasks.run_notifiche_archivio``):
  - non letta da più di ``notif_archivio_non_lette_giorni`` giorni (default 30);
  - letta da più di ``notif_archivio_lette_giorni`` giorni (default 14);
- **a mano**, dall'utente (singola o «Archivia lette») o dall'admin.

Le archiviate più vecchie di ``notif_archivio_elimina_giorni`` (default 365)
vengono eliminate definitivamente. ``0`` su una qualsiasi soglia = mai.

Le soglie stanno in ``SiteConfig`` e si gestiscono da Admin portale →
Gestione notifiche. Le date di riferimento sono:
- non lette → ``created_at``;
- lette → ``letta_il`` (``created_at`` per le righe lette prima di questa
  versione o marcate lette da ``update()`` dei moduli, senza timestamp);
- eliminazione → ``archiviata_il``.

NB: i promemoria dei moduli che deduplicano su «non letta» (ticket SLA,
anomalie da gestire, …) trovano anche le archiviate non lette: un promemoria
archiviato per scadenza non viene ricreato a ogni giro. La fonte di verità
dell'attività resta il modulo, non la campanella.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

logger = logging.getLogger(__name__)

KEY_NON_LETTE = "notif_archivio_non_lette_giorni"
KEY_LETTE = "notif_archivio_lette_giorni"
KEY_ELIMINA = "notif_archivio_elimina_giorni"

DEFAULT_NON_LETTE = 30
DEFAULT_LETTE = 14
DEFAULT_ELIMINA = 365
MAX_GIORNI = 3650

MOTIVO_NON_LETTA = "scadenza_non_letta"
MOTIVO_LETTA = "scadenza_letta"
MOTIVO_UTENTE = "utente"
MOTIVO_ADMIN = "admin"


@dataclass(frozen=True)
class PoliticaArchivio:
    """Soglie in giorni; 0 = disattivata."""

    non_lette: int = DEFAULT_NON_LETTE
    lette: int = DEFAULT_LETTE
    elimina: int = DEFAULT_ELIMINA


def _giorni(raw, default: int) -> int:
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return max(0, min(MAX_GIORNI, value))


def get_politica() -> PoliticaArchivio:
    """Soglie correnti (fail-safe: default se SiteConfig non è leggibile)."""
    try:
        from core.models import SiteConfig

        cfg = SiteConfig.get_many({
            KEY_NON_LETTE: str(DEFAULT_NON_LETTE),
            KEY_LETTE: str(DEFAULT_LETTE),
            KEY_ELIMINA: str(DEFAULT_ELIMINA),
        })
    except Exception:
        logger.exception("Lettura politica archivio notifiche fallita: uso i default")
        return PoliticaArchivio()
    return PoliticaArchivio(
        non_lette=_giorni(cfg.get(KEY_NON_LETTE), DEFAULT_NON_LETTE),
        lette=_giorni(cfg.get(KEY_LETTE), DEFAULT_LETTE),
        elimina=_giorni(cfg.get(KEY_ELIMINA), DEFAULT_ELIMINA),
    )


def set_politica(*, non_lette, lette, elimina) -> PoliticaArchivio:
    """Salva le soglie (valori normalizzati in [0, MAX_GIORNI])."""
    from core.models import SiteConfig

    politica = PoliticaArchivio(
        non_lette=_giorni(non_lette, DEFAULT_NON_LETTE),
        lette=_giorni(lette, DEFAULT_LETTE),
        elimina=_giorni(elimina, DEFAULT_ELIMINA),
    )
    SiteConfig.set(KEY_NON_LETTE, str(politica.non_lette), "Notifiche: giorni prima di archiviare le non lette (0 = mai)")
    SiteConfig.set(KEY_LETTE, str(politica.lette), "Notifiche: giorni prima di archiviare le lette (0 = mai)")
    SiteConfig.set(KEY_ELIMINA, str(politica.elimina), "Notifiche: giorni prima di eliminare le archiviate (0 = mai)")
    return politica


def attive(qs=None):
    """Queryset delle notifiche non archiviate."""
    from core.models import Notifica

    return (qs if qs is not None else Notifica.objects.all()).filter(archiviata=False)


def data_archiviazione(notifica, politica: PoliticaArchivio | None = None):
    """Quando la notifica verrà archiviata in automatico (``None`` = mai / già archiviata)."""
    if getattr(notifica, "archiviata", False):
        return None
    politica = politica or get_politica()
    if notifica.letta:
        if not politica.lette:
            return None
        base = notifica.letta_il or notifica.created_at
        return base + timedelta(days=politica.lette) if base else None
    if not politica.non_lette or not notifica.created_at:
        return None
    return notifica.created_at + timedelta(days=politica.non_lette)


def _filtro_scadute(politica: PoliticaArchivio, now) -> dict[str, Q]:
    filtri: dict[str, Q] = {}
    if politica.non_lette:
        cutoff = now - timedelta(days=politica.non_lette)
        filtri[MOTIVO_NON_LETTA] = Q(letta=False, created_at__lt=cutoff)
    if politica.lette:
        cutoff = now - timedelta(days=politica.lette)
        filtri[MOTIVO_LETTA] = Q(letta=True) & (
            Q(letta_il__lt=cutoff) | Q(letta_il__isnull=True, created_at__lt=cutoff)
        )
    return filtri


def archivia(qs, motivo: str, *, now=None) -> int:
    """Archivia le notifiche del queryset (solo quelle ancora attive)."""
    now = now or timezone.now()
    return qs.filter(archiviata=False).update(
        archiviata=True,
        archiviata_il=now,
        archiviata_motivo=motivo,
        popup_shown=True,
    )


def ripristina(qs) -> int:
    """Riporta tra le attive marcandola letta adesso: la soglia «lette» riparte
    da oggi, così il giro notturno non la riarchivia subito."""
    now = timezone.now()
    return qs.filter(archiviata=True).update(
        archiviata=False,
        archiviata_il=None,
        archiviata_motivo="",
        letta=True,
        letta_il=now,
        popup_shown=True,
    )


def segna_lette(qs, *, now=None) -> int:
    """Marca come lette (con timestamp) le notifiche non lette del queryset."""
    now = now or timezone.now()
    return qs.filter(letta=False).update(letta=True, letta_il=now, popup_shown=True)


def archivia_scadute(*, now=None, dry_run: bool = False, politica: PoliticaArchivio | None = None) -> dict:
    """Archivia le notifiche scadute ed elimina le archiviate oltre la soglia.

    Ritorna i conteggi per motivo: ``{"non_lette": n, "lette": n, "eliminate": n}``.
    Con ``dry_run`` conta soltanto."""
    from core.models import Notifica

    now = now or timezone.now()
    politica = politica or get_politica()
    risultato = {"non_lette": 0, "lette": 0, "eliminate": 0, "dry_run": dry_run}
    chiavi = {MOTIVO_NON_LETTA: "non_lette", MOTIVO_LETTA: "lette"}

    for motivo, filtro in _filtro_scadute(politica, now).items():
        qs = Notifica.objects.filter(archiviata=False).filter(filtro)
        risultato[chiavi[motivo]] = qs.count() if dry_run else archivia(qs, motivo, now=now)

    if politica.elimina:
        cutoff = now - timedelta(days=politica.elimina)
        qs = Notifica.objects.filter(archiviata=True, archiviata_il__lt=cutoff)
        risultato["eliminate"] = qs.count() if dry_run else qs.delete()[0]

    if not dry_run and (risultato["non_lette"] or risultato["lette"] or risultato["eliminate"]):
        logger.info(
            "Archivio notifiche: %s non lette e %s lette archiviate, %s eliminate",
            risultato["non_lette"], risultato["lette"], risultato["eliminate"],
        )
    return risultato


def statistiche() -> dict:
    """Conteggi globali per le pagine admin."""
    from core.models import Notifica

    totale = Notifica.objects.count()
    archiviate = Notifica.objects.filter(archiviata=True).count()
    non_lette = Notifica.objects.filter(archiviata=False, letta=False).count()
    return {
        "totale": totale,
        "archiviate": archiviate,
        "attive": totale - archiviate,
        "non_lette": non_lette,
        "in_scadenza": archivia_scadute(dry_run=True),
    }
