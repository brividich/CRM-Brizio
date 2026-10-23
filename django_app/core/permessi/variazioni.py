"""Registro delle variazioni di accesso che arrivano dall'organigramma.

Assegnare o chiudere un ruolo d'organigramma, disattivarlo o cambiare i ruoli del
portale che concede cambia gli accessi delle persone senza che nessuno tocchi la
pagina «Ruoli e permessi». Qui ogni cambio diventa una voce di registro per
persona (``AuditLog``, ``oggetto_tipo="dipendente"``): cosa ha ricevuto, cosa ha
perso, perché e chi ha fatto la modifica. Serve al riesame degli accessi
(ISO/IEC 27001 A.5.18) e risponde a «da quando ha accesso a…».

Fotografia prima del salvataggio, confronto dopo: si registra solo una differenza
reale (un ruolo del portale già dato da un altro ruolo non conta). Un errore qui
non blocca mai il salvataggio.
"""
from __future__ import annotations

import logging

from django.db.models.signals import m2m_changed, post_delete, post_save, pre_delete, pre_save

logger = logging.getLogger(__name__)

AZIONE = "accessi_da_organigramma"
MODULO = "permessi"
OGGETTO_TIPO = "dipendente"


def gruppi_per_anagrafica(anagrafica_ids) -> dict[int, set[int]]:
    """{id anagrafica: {AccessGroup}} che la persona riceve oggi dall'organigramma."""
    from core.permessi.organigramma import _profili_per_ruolo
    from core.permessi.team import _assegnazioni_attive

    ids = sorted({int(a) for a in anagrafica_ids or [] if a})
    if not ids:
        return {}
    assegnazioni = list(_assegnazioni_attive().filter(legacy_anagrafica_id__in=ids)
                        .values_list("legacy_anagrafica_id", "ruolo_id"))
    profili = _profili_per_ruolo({r for _a, r in assegnazioni})
    out: dict[int, set[int]] = {i: set() for i in ids}
    for aid, ruolo_id in assegnazioni:
        out[int(aid)] |= profili.get(int(ruolo_id), set())
    return out


def persone_del_ruolo(ruolo_ids) -> set[int]:
    """Chi ha un'assegnazione in corso sui ruoli, anche se il ruolo è appena stato disattivato."""
    from django.db.models import Q
    from django.utils import timezone

    from anagrafica.models import DipendenteRuoloOperativo

    ids = [int(r) for r in ruolo_ids or [] if r]
    if not ids:
        return set()
    oggi = timezone.localdate()
    return set(DipendenteRuoloOperativo.objects.filter(Q(data_fine__isnull=True) | Q(data_fine__gte=oggi),
                                                       ruolo_id__in=ids)
               .values_list("legacy_anagrafica_id", flat=True))


def registra(prima: dict[int, set[int]], causa: str) -> int:
    """Confronta con lo stato attuale e scrive una voce per ogni persona cambiata. Ritorna quante."""
    if not prima:
        return 0
    dopo = gruppi_per_anagrafica(prima)
    cambi = {aid: (dopo.get(aid, set()) - vecchi, vecchi - dopo.get(aid, set())) for aid, vecchi in prima.items()}
    cambi = {aid: c for aid, c in cambi.items() if c[0] or c[1]}
    if not cambi:
        return 0
    from core.audit import log_action
    from core.audit_middleware import get_current_request
    from core.models import AccessGroup, AuditLog

    etichette = dict(AccessGroup.objects.filter(
        id__in={g for r, t in cambi.values() for g in r | t}).values_list("id", "label"))
    request = get_current_request()
    for aid, (ricevuti, tolti) in cambi.items():
        dettaglio = {
            "causa": causa,
            "ricevuti": sorted(etichette.get(g, f"#{g}") for g in ricevuti),
            "tolti": sorted(etichette.get(g, f"#{g}") for g in tolti),
        }
        if request is not None:
            log_action(request, AZIONE, MODULO, dettaglio, oggetto_tipo=OGGETTO_TIPO, oggetto_id=str(aid))
        else:
            AuditLog.objects.create(utente_display="Organigramma (automatico)", azione=AZIONE, modulo=MODULO,
                                    dettaglio=dettaglio, oggetto_tipo=OGGETTO_TIPO, oggetto_id=str(aid))
    return len(cambi)


def ultime_variazioni(anagrafica_id: int, limit: int = 10) -> list:
    from core.models import AuditLog

    return list(AuditLog.objects.filter(azione=AZIONE, oggetto_tipo=OGGETTO_TIPO, oggetto_id=str(anagrafica_id))
                .order_by("-created_at")[:limit])


# ── Segnali ─────────────────────────────────────────────────────────────────
def _sicuro(funzione):
    def wrapper(*args, **kwargs):
        if kwargs.get("raw"):
            return
        try:
            funzione(*args, **kwargs)
        except Exception:
            logger.exception("permessi.variazioni: registro non aggiornato")
    return wrapper


@_sicuro
def _assegnazione_prima(sender, instance, **kwargs):
    aids = {instance.legacy_anagrafica_id}
    if instance.pk:
        vecchio = sender.objects.filter(pk=instance.pk).values_list("legacy_anagrafica_id", flat=True).first()
        if vecchio:
            aids.add(vecchio)
    instance._accessi_prima = gruppi_per_anagrafica(aids)


@_sicuro
def _assegnazione_dopo(sender, instance, created=False, **kwargs):
    prima = getattr(instance, "_accessi_prima", None)
    if prima is None:
        return
    ruolo = f"«{instance.ruolo.nome}»" if instance.ruolo_id else "«?»"
    if instance.tipologia and instance.tipologia != "PRINCIPALE":
        ruolo += f" ({instance.get_tipologia_display().lower()})"
    if kwargs.get("signal") is post_delete:
        causa = f"Ruolo {ruolo} tolto"
    elif created:
        causa = f"Ruolo {ruolo} assegnato"
    elif instance.data_fine:
        causa = f"Ruolo {ruolo} chiuso il {instance.data_fine:%d/%m/%Y}"
    else:
        causa = f"Ruolo {ruolo} modificato"
    registra(prima, causa)
    instance._accessi_prima = None


@_sicuro
def _ruolo_prima(sender, instance, **kwargs):
    if not instance.pk:
        return
    instance._accessi_prima = gruppi_per_anagrafica(persone_del_ruolo([instance.pk]))


@_sicuro
def _ruolo_dopo(sender, instance, **kwargs):
    prima = getattr(instance, "_accessi_prima", None)
    if prima:
        stato = "riattivato" if instance.is_active else "disattivato"
        registra(prima, f"Ruolo «{instance.nome}» {stato}")
    instance._accessi_prima = None


@_sicuro
def _profili_cambiati(sender, instance, action, reverse, pk_set, **kwargs):
    from anagrafica.models import RuoloOperativo

    if action not in {"pre_add", "pre_remove", "pre_clear", "post_add", "post_remove", "post_clear"}:
        return
    if action.startswith("pre_"):
        if reverse:  # dal ruolo del portale: i ruoli d'organigramma toccati
            ruoli = list(pk_set or []) if action != "pre_clear" else list(
                instance.ruoli_organigramma.values_list("id", flat=True))
        else:
            ruoli = [instance.pk]
        instance._accessi_prima = gruppi_per_anagrafica(persone_del_ruolo(ruoli))
        instance._accessi_ruoli = ruoli
        return
    prima = getattr(instance, "_accessi_prima", None)
    if not prima:
        return
    if reverse:
        nomi = ", ".join(RuoloOperativo.objects.filter(pk__in=instance._accessi_ruoli)
                         .order_by("nome").values_list("nome", flat=True))
        causa = f"Ruolo del portale «{instance.label}» collegato o scollegato da: {nomi}"
    else:
        causa = f"Ruoli del portale concessi da «{instance.nome}» cambiati"
    registra(prima, causa)
    instance._accessi_prima = None


def collega_segnali() -> None:
    from anagrafica.models import DipendenteRuoloOperativo, RuoloOperativo

    uid = "permessi_variazioni_"
    pre_save.connect(_assegnazione_prima, sender=DipendenteRuoloOperativo, dispatch_uid=uid + "ass_pre_save")
    post_save.connect(_assegnazione_dopo, sender=DipendenteRuoloOperativo, dispatch_uid=uid + "ass_post_save")
    pre_delete.connect(_assegnazione_prima, sender=DipendenteRuoloOperativo, dispatch_uid=uid + "ass_pre_delete")
    post_delete.connect(_assegnazione_dopo, sender=DipendenteRuoloOperativo, dispatch_uid=uid + "ass_post_delete")
    pre_save.connect(_ruolo_prima, sender=RuoloOperativo, dispatch_uid=uid + "ruolo_pre_save")
    post_save.connect(_ruolo_dopo, sender=RuoloOperativo, dispatch_uid=uid + "ruolo_post_save")
    m2m_changed.connect(_profili_cambiati, sender=RuoloOperativo.profili_permessi.through,
                        dispatch_uid=uid + "profili")
