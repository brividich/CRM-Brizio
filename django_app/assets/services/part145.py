"""Attrezzature dei processi qualificati (MOD.128) e PART 145.

Un asset e' attrezzatura di un processo qualificato se:
- e' collegato al processo dal dettaglio MOD.128 (``Asset.processi_qualificati``);
- oppure ha il flag ``part_145`` e il processo e' in regime PART145.

Il flag resta la fonte per «rientra in PART 145»: non si scrive nessuna riga di
collegamento in automatico, l'unione si calcola alla lettura.

Avviso: quando un'attrezzatura qualificata cambia stato (in riparazione, dismessa,
di nuovo in uso...) Qualita' riceve una mail, agli stessi destinatari dei timbri
sospesi MOD.128 (``mpq_msm_reminder_emails``).
"""
from __future__ import annotations

import logging
import threading

from django.db import transaction
from django.db.models import Q
from django.db.models.signals import post_save, pre_save
from django.utils import timezone
from django.utils.html import escape

from automazioni.managed_flows import event_flow

logger = logging.getLogger(__name__)

REGIME_PART145 = "PART145"


def processi_part145():
    from anagrafica.models_mpq import ProcessoQualificato

    return ProcessoQualificato.objects.filter(regime=REGIME_PART145)


def processi_perimetro():
    """Processi del Dossier: regime PART145 + processi speciali «nel perimetro Part 145».

    Il flag ``part_145`` dell'asset vale solo per il regime PART145: i processi speciali
    del perimetro (es. DQP) hanno le attrezzature collegate dal dettaglio MOD.128.
    """
    from anagrafica.models_mpq import ProcessoQualificato

    return ProcessoQualificato.objects.filter(Q(regime=REGIME_PART145) | Q(perimetro_part145=True))


def attrezzature_processo(processo):
    """Asset attrezzatura del processo: collegati + (se regime PART145) quelli col flag."""
    from ..models import Asset

    filtro = Q(processi_qualificati=processo)
    if processo.regime == REGIME_PART145:
        filtro |= Q(part_145=True)
    return Asset.objects.filter(filtro).distinct()


def processi_dell_asset(asset) -> list:
    """Processi qualificati dell'asset (collegati + PART145 se ha il flag), per nome."""
    processi = {p.pk: p for p in asset.processi_qualificati.all()}
    if asset.part_145:
        for p in processi_part145():
            processi.setdefault(p.pk, p)
    return sorted(processi.values(), key=lambda p: (p.nome or "").lower())


def e_qualificata(asset) -> bool:
    return bool(asset.part_145) or asset.processi_qualificati.exists()


# ── Avviso cambio di stato ────────────────────────────────────────────────────

_locale = threading.local()


def _coda() -> list:
    if not hasattr(_locale, "coda"):
        _locale.coda = []
    return _locale.coda


def _ricorda_stato(sender, instance, update_fields=None, raw=False, **kwargs):
    if raw or not instance.pk or (update_fields is not None and "status" not in update_fields):
        return
    instance._part145_stato_prima = (
        sender.objects.filter(pk=instance.pk).values_list("status", flat=True).first()
    )


def _confronta_stato(sender, instance, created=False, raw=False, **kwargs):
    prima = getattr(instance, "_part145_stato_prima", None)
    instance._part145_stato_prima = None
    if raw or created or prima is None or prima == instance.status:
        return
    try:
        if not e_qualificata(instance):
            return
    except Exception:  # un controllo fallito non deve bloccare il salvataggio
        logger.exception("Controllo attrezzatura qualificata fallito per asset %s", instance.pk)
        return
    _coda().append((instance.pk, prima, instance.status))
    # Il primo callback a girare svuota la coda: un import che cambia 20 stati manda
    # una mail sola; gli altri callback trovano la coda vuota.
    transaction.on_commit(_svuota_coda)


def _svuota_coda():
    from ..models import Asset

    cambi = list(_coda())
    _coda().clear()
    if cambi:
        # Un cambio rimasto in coda da una transazione annullata non e' mai avvenuto:
        # si tiene solo se lo stato salvato e' davvero quello nuovo.
        attuali = dict(Asset.objects.filter(pk__in=[c[0] for c in cambi]).values_list("pk", "status"))
        cambi = [c for c in cambi if attuali.get(c[0]) == c[2]]
    if cambi:
        try:
            notifica_cambio_stato(cambi)
        except Exception:
            logger.exception("Avviso PART 145 sui cambi di stato non inviato")


def collega_segnali():
    from ..models import Asset

    pre_save.connect(_ricorda_stato, sender=Asset, dispatch_uid="part145_ricorda_stato")
    post_save.connect(_confronta_stato, sender=Asset, dispatch_uid="part145_confronta_stato")


@event_flow("part145_attrezzatura_stato", skipped_result=0)
def notifica_cambio_stato(cambi, *, override=None, fail_silently: bool = True) -> int:
    """Mail a Qualita': attrezzature PART 145 / processi qualificati che hanno cambiato stato.

    ``cambi``: [(asset_id, stato_prima, stato_dopo)]. Ritorna le mail inviate (0 o 1).
    """
    from anagrafica.services.mpq_timbri import MSM_CONFIG_KEY
    from anagrafica.services.reminders import get_reminder_recipients
    from core.email_utils import send_hub_mail

    from ..models import Asset

    recipients = get_reminder_recipients(MSM_CONFIG_KEY, override=override)
    if not cambi or not recipients:
        return 0
    stati = dict(Asset.STATUS_CHOICES)
    assets = {a.pk: a for a in Asset.objects.filter(pk__in=[c[0] for c in cambi]).prefetch_related("processi_qualificati")}
    righe = []
    for asset_id, prima, dopo in cambi:
        a = assets.get(asset_id)
        if a is None:
            continue
        processi = ", ".join(p.nome for p in processi_dell_asset(a)) or ("PART 145" if a.part_145 else "—")
        cella = "padding:8px 12px;border-top:1px solid #e2e8f0;"
        righe.append(
            f"<tr><td style='{cella}'>{escape(a.asset_tag)} — {escape(a.name)}</td>"
            f"<td style='{cella}'>{escape(a.reparto or '—')}</td>"
            f"<td style='{cella}'>{escape(stati.get(prima, prima))} → <strong>{escape(stati.get(dopo, dopo))}</strong></td>"
            f"<td style='{cella}'>{escape(processi)}</td></tr>"
        )
    if not righe:
        return 0
    intestazione = "text-align:left;padding:9px 12px;color:#64748b;font-size:12px;"
    tabella = (
        "<table role='presentation' width='100%' cellpadding='0' cellspacing='0' "
        "style='width:100%;border-collapse:collapse;background:#f6f9fc;border:1px solid #d8e1ec;'>"
        f"<tr style='background:#eef3f8;'><th style='{intestazione}'>Attrezzatura</th>"
        f"<th style='{intestazione}'>Reparto</th><th style='{intestazione}'>Stato</th>"
        f"<th style='{intestazione}'>Processi qualificati</th></tr>"
        + "".join(righe) + "</table>"
    )
    testo = (
        f"{len(righe)} attrezzature PART 145 o di processi qualificati hanno cambiato stato "
        f"({timezone.localtime():%d-%m-%Y %H:%M}). Verificare l'impatto sui processi."
    )
    return send_hub_mail(
        subject=f"[PART 145] Attrezzature che hanno cambiato stato ({len(righe)})",
        body_text=testo,
        recipients=recipients,
        title="Attrezzature qualificate — cambio di stato",
        email_type="Qualità",
        badge="PART 145",
        section_label="Processi qualificati",
        body_html_fragment=f"<p style='margin:0 0 14px;'>{escape(testo)}</p>{tabella}",
        fail_silently=fail_silently,
    )
