"""Promemoria «manca lo scarico effettivo»: avviso in-app prima della scadenza.

Uno scarico originale (O) senza scarico effettivo (M o R collegato) da più di
``rentri_promemoria_m_giorni`` giorni (SiteConfig, di serie 60: la quarta copia
del FIR va annotata entro 90) genera una notifica a chi l'ha inserito e ai
referenti delle Impostazioni RENTRI. La notifica apre lo Scarico effettivo già
compilato. Si ripete al massimo una volta a settimana per scarico.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from .catena import split_rif_op
from .giacenze import _cfg_int
from .models import RegistroRifiuti, RentriImpostazioni
from .verifica import GIORNI_QUARTA_COPIA

logger = logging.getLogger(__name__)

DEFAULT_GIORNI = 60
RIPETI_OGNI_GIORNI = 7


def soglia_giorni() -> int:
    giorni = _cfg_int("rentri_promemoria_m_giorni", DEFAULT_GIORNI)
    return max(1, min(giorni, GIORNI_QUARTA_COPIA))


def scarichi_senza_effettivo(oggi: date, giorni: int) -> list[RegistroRifiuti]:
    """Scarichi originali attivi più vecchi di ``giorni`` senza M/R collegato (stessa regola della Verifica)."""
    attivi = list(RegistroRifiuti.objects.attivi().filter(tipo__in=["O", "M", "R"]))
    citati: set[str] = set()
    rif: set[str] = set()
    for r in attivi:
        if r.tipo in ("M", "R"):
            citati.update(split_rif_op(r.rif_op))
            rif.add(", ".join(split_rif_op(r.rif_op)))
    limite = oggi - timedelta(days=giorni)
    return [
        r for r in attivi
        if r.tipo == "O" and r.data and r.data <= limite
        and r.id_registrazione not in citati
        and ", ".join(split_rif_op(r.rif_op)) not in rif
    ]


def _referenti_legacy_ids() -> list[int]:
    from core.notifiche import legacy_user_ids_for_email

    cfg = RentriImpostazioni.get_singleton()
    email = [str(p.get("email") or "").strip() for p in (cfg.responsabili or []) if isinstance(p, dict)]
    email.append((cfg.responsabile_email or "").strip())
    ids: set[int] = set()
    for e in dict.fromkeys(e for e in email if e):
        ids.update(legacy_user_ids_for_email(e))
    return sorted(ids)


def invia_promemoria(oggi: date | None = None, *, dry_run: bool = False) -> dict:
    from django.urls import reverse
    from django.utils import timezone

    from core.notifiche import invia_notifica

    oggi = oggi or timezone.localdate()
    giorni = soglia_giorni()
    referenti = _referenti_legacy_ids()
    da_avvisare = [
        r for r in scarichi_senza_effettivo(oggi, giorni)
        if not r.promemoria_m_il or (oggi - r.promemoria_m_il).days >= RIPETI_OGNI_GIORNI
    ]
    notifiche = 0
    for r in da_avvisare:
        mancano = GIORNI_QUARTA_COPIA - (oggi - r.data).days
        scadenza = f"scade fra {mancano} giorni" if mancano > 0 else "è scaduta"
        messaggio = (
            f"RENTRI: lo scarico {r.id_registrazione} ({r.codice}) del {r.data:%d/%m/%Y} non ha ancora lo scarico "
            f"effettivo; la quarta copia del FIR {scadenza}. Registra il peso a destino."
        )
        url = reverse("rentri_scarico_effettivo") + f"?da={r.pk}"
        destinatari = set(referenti)
        if r.inserito_da_legacy_id:
            destinatari.add(r.inserito_da_legacy_id)
        if dry_run:
            notifiche += len(destinatari)
            continue
        for uid in sorted(destinatari):
            invia_notifica(uid, "generico", messaggio, url)
            notifiche += 1
        RegistroRifiuti.objects.filter(pk=r.pk).update(promemoria_m_il=oggi)
    if da_avvisare and not referenti and not any(r.inserito_da_legacy_id for r in da_avvisare):
        logger.warning("Promemoria RENTRI: %s scarichi senza effettivo ma nessun destinatario (referenti senza utente)", len(da_avvisare))
    return {"scarichi": len(da_avvisare), "notifiche": notifiche, "soglia_giorni": giorni}
