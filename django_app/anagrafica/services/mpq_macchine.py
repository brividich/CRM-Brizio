"""MOD.128 — macchine qualificate: stato, verifiche con misure, sospensioni automatiche.

La qualifica di una macchina su un processo ha una scadenza propria
(``QualificaMacchina``), indipendente da quella del processo e delle persone.

- Verifica (es. MOD.161 per P11TF12, MT CN 69 §9): le misure si confrontano con
  i parametri del processo; conforme → qualificata fino a data + frequenza;
  non conforme → sospesa, con il periodo di parti lavorate da riesaminare.
- Requisiti della macchina (manutenzioni, tarature, controlli): letti dalle
  scadenze del piano di manutenzione sull'asset (nessuna scadenza duplicata).
- Eventi che chiedono una valutazione (MT CN 07 §6, MT CN 69 §9): chiusura di un
  OdL non programmato, asset «in riparazione» → «Da valutare»; asset dismesso →
  «Non più usata nel processo».
"""
from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.utils import timezone
from django.utils.html import escape

from automazioni.managed_flows import event_flow

logger = logging.getLogger(__name__)

SOGLIA_IN_SCADENZA = 30

# Classe del badge per stato visuale (stessi colori delle altre pagine MOD.128).
_CLASSE = {
    "qualificata": "fmd-b-green",
    "in_scadenza": "fmd-b-amber",
    "scaduta": "fmd-b-red",
    "da_qualificare": "fmd-b-gray",
    "da_valutare": "fmd-b-orange",
    "sospesa": "fmd-b-red",
    "declassata": "fmd-b-amber",
    "ritirata": "fmd-b-slate",
    "non_richiesta": "fmd-b-slate",
}


def _log(processo, evento, dettaglio="", *, user=None, sistema=False):
    from ..models_mpq import MpqStorico

    try:
        MpqStorico.objects.create(
            processo=processo, evento=evento[:200], dettaglio=dettaglio,
            origine=MpqStorico.Origine.SISTEMA if sistema else MpqStorico.Origine.MANUALE,
            registrato_da=user if getattr(user, "is_authenticated", False) else None,
        )
    except Exception:  # pragma: no cover - lo storico non blocca l'azione
        logger.exception("MpqStorico non registrato")


# ── Stato ────────────────────────────────────────────────────────────────────

def stato_visuale(qm, oggi=None) -> dict:
    """``{"codice", "label", "classe", "scadenza", "giorni", "operativa"}`` di una qualifica."""
    oggi = oggi or timezone.localdate()
    if qm is None:
        return {"codice": "non_richiesta", "label": "Qualifica non registrata",
                "classe": _CLASSE["non_richiesta"], "scadenza": None, "giorni": None,
                "operativa": False}
    scad = qm.scadenza_effettiva
    giorni = (scad - oggi).days if scad else None
    S = type(qm)
    if qm.stato == S.STATO_QUALIFICATA:
        if scad and scad < oggi:
            codice, label = "scaduta", f"Scaduta il {scad:%d-%m-%Y}"
        elif scad and giorni <= SOGLIA_IN_SCADENZA:
            codice, label = "in_scadenza", f"Qualificata, scade il {scad:%d-%m-%Y}"
        elif scad:
            codice, label = "qualificata", f"Qualificata fino al {scad:%d-%m-%Y}"
        else:
            codice, label = "qualificata", "Qualificata"
    elif qm.stato == S.STATO_DECLASSATA:
        codice, label = ("scaduta", f"Scaduta il {scad:%d-%m-%Y}") if (scad and scad < oggi) \
            else ("declassata", "Declassata")
    else:
        codice = qm.stato.lower()
        label = qm.get_stato_display()
    return {"codice": codice, "label": label, "classe": _CLASSE.get(codice, "fmd-b-gray"),
            "scadenza": scad, "giorni": giorni, "operativa": qm.is_operativa(oggi)}


def stato_requisiti_macchina(processo, asset, *, oggi=None, requisiti=None) -> list[dict]:
    """Stato dei requisiti macchina del processo su un asset, dal motore manutenzioni."""
    from assets.models import MaintenanceOccurrence

    oggi = oggi or timezone.localdate()
    if requisiti is None:
        requisiti = list(processo.requisiti_macchina.filter(attivo=True).select_related("piano"))
    out = []
    for req in requisiti:
        voce = {"req": req, "nome": req.descrizione, "tipo": req.get_tipo_display(),
                "bloccante": req.bloccante, "ultima": None, "prossima": None}
        if not req.piano_id:
            voce.update(stato="na", label="Registrato a bordo macchina")
            out.append(voce)
            continue
        occ = MaintenanceOccurrence.objects.filter(asset=asset, plan_id=req.piano_id)
        aperta = (occ.filter(status=MaintenanceOccurrence.STATUS_OPEN)
                  .order_by("due_date").first())
        fatta = (occ.filter(status=MaintenanceOccurrence.STATUS_DONE)
                 .order_by("-completed_on").first())
        voce["ultima"] = getattr(fatta, "completed_on", None)
        voce["prossima"] = getattr(aperta, "due_date", None)
        if aperta is None and fatta is None:
            voce.update(stato="mancante", label="Piano non applicato alla macchina")
        elif aperta and aperta.due_date < oggi:
            voce.update(stato="scaduto", label=f"Scaduta il {aperta.due_date:%d-%m-%Y}")
        elif aperta and (aperta.due_date - oggi).days <= SOGLIA_IN_SCADENZA:
            voce.update(stato="in_scadenza", label=f"Entro il {aperta.due_date:%d-%m-%Y}")
        else:
            voce.update(stato="ok", label=(f"Fatta il {voce['ultima']:%d-%m-%Y}" if voce["ultima"]
                                           else "In regola"))
        out.append(voce)
    return out


def macchina_operativa(qm, *, oggi=None, requisiti=None) -> bool:
    """Qualifica operativa e nessun requisito bloccante scaduto o mancante."""
    if qm is None or not qm.is_operativa(oggi):
        return False
    voci = stato_requisiti_macchina(qm.processo, qm.asset, oggi=oggi, requisiti=requisiti)
    return not any(v["bloccante"] and v["stato"] in ("scaduto", "mancante") for v in voci)


def righe_macchine(processo, *, oggi=None) -> list[dict]:
    """Macchine del processo con qualifica e requisiti (pagina del processo)."""
    from assets.services.part145 import attrezzature_processo

    oggi = oggi or timezone.localdate()
    qualifiche = {q.asset_id: q for q in processo.qualifiche_macchina.all()}
    collegate = set(processo.attrezzature.values_list("pk", flat=True))
    requisiti = list(processo.requisiti_macchina.filter(attivo=True).select_related("piano"))
    righe = []
    for a in attrezzature_processo(processo).select_related("asset_category").order_by("asset_tag"):
        qm = qualifiche.get(a.pk)
        if qm is not None and qm.stato == qm.STATO_RITIRATA:
            qm = None
        voci = stato_requisiti_macchina(processo, a, oggi=oggi, requisiti=requisiti) if requisiti else []
        stato = stato_visuale(qm, oggi)
        problemi = [v for v in voci if v["bloccante"] and v["stato"] in ("scaduto", "mancante")]
        righe.append({
            "asset": a, "collegata": a.pk in collegate, "da_flag": bool(a.part_145),
            "qualifica": qm, "stato": stato, "requisiti": voci, "problemi": problemi,
            "operativa": stato["operativa"] and not problemi,
        })
    return righe


def qualifiche_dell_asset(asset, *, oggi=None) -> dict[int, dict]:
    """{processo_id: stato_visuale} delle qualifiche (non ritirate) di un asset."""
    oggi = oggi or timezone.localdate()
    out = {}
    for qm in asset.qualifiche_processo.exclude(stato="RITIRATA").select_related("processo"):
        out[qm.processo_id] = {**stato_visuale(qm, oggi), "qualifica": qm}
    return out


# ── Collegamento macchina ↔ processo ─────────────────────────────────────────

def collega(processo, asset, *, user=None):
    """Collega l'asset al processo e apre (o riapre) la sua qualifica «Da qualificare»."""
    from ..models_mpq import QualificaMacchina

    with transaction.atomic():
        if processo.regime != "PART145" or not asset.part_145:
            asset.processi_qualificati.add(processo)
        qm, creata = QualificaMacchina.objects.get_or_create(
            processo=processo, asset=asset,
            defaults={"frequenza_mesi": processo.frequenza_macchine_mesi, "aggiornato_da": user},
        )
        if not creata and qm.stato == QualificaMacchina.STATO_RITIRATA:
            qm.stato = QualificaMacchina.STATO_DA_QUALIFICARE
            qm.motivo_stato = "Di nuovo usata nel processo: registrare la qualifica."
            qm.aggiornato_da = user
            qm.save()
    return qm


def scollega(processo, asset, *, user=None):
    """Toglie l'asset dal processo; la qualifica resta come storico («Non più usata»)."""
    from ..models_mpq import QualificaMacchina

    with transaction.atomic():
        asset.processi_qualificati.remove(processo)
        QualificaMacchina.objects.filter(processo=processo, asset=asset).update(
            stato=QualificaMacchina.STATO_RITIRATA,
            motivo_stato="Scollegata dal processo.", updated_at=timezone.now(),
        )


# ── Verifica con misure ──────────────────────────────────────────────────────

def _dec(valore):
    if valore in (None, ""):
        return None
    try:
        return Decimal(str(valore).replace(",", "."))
    except (InvalidOperation, ValueError):
        return None


def valuta_misura(parametro, *, nominale=None, misurato=None, conforme=None) -> dict:
    """Conformità di una riga di verifica rispetto al parametro del processo."""
    P = type(parametro)
    nominale, misurato = _dec(nominale), _dec(misurato)
    scost = None
    if parametro.tipo == P.TIPO_PROVA:
        nominale = misurato = None
        ok = bool(conforme)
    elif parametro.tipo == P.TIPO_MINIMO:
        nominale = None
        ok = misurato is not None and parametro.valore_minimo is not None \
            and misurato >= parametro.valore_minimo
    else:
        if nominale and misurato is not None:
            scost = ((misurato - nominale) / nominale * 100).quantize(Decimal("0.01"))
            ok = parametro.tolleranza_pct is not None and abs(scost) <= parametro.tolleranza_pct
        else:
            ok = False
    return {"nominale": nominale, "misurato": misurato, "scostamento_pct": scost, "conforme": ok}


def registra_verifica(qm, *, tipo, data, righe, eseguita_da="", note="", documento=None,
                      user=None):
    """Registra una verifica e aggiorna la qualifica.

    ``righe``: ``[(parametro, {"nominale", "misurato", "conforme"}), ...]``.
    Esito conforme se tutte le righe sono conformi (nessuna riga = conforme).
    """
    from ..models_mpq import QualificaMacchina, VerificaMacchina, VerificaMacchinaMisura

    with transaction.atomic():
        ver = VerificaMacchina.objects.create(
            qualifica=qm, tipo=tipo, data=data, eseguita_da=eseguita_da[:150], note=note,
            registrato_da=user if getattr(user, "is_authenticated", False) else None,
        )
        if documento:
            ver.documento = documento
            ver.documento_nome_originale = getattr(documento, "name", "")[:255]
        esito_ok = True
        non_conformi = []
        for par, valori in righe:
            v = valuta_misura(par, **valori)
            VerificaMacchinaMisura.objects.create(
                verifica=ver, parametro=par, nome=par.nome, tipo=par.tipo, unita=par.unita,
                tolleranza_pct=par.tolleranza_pct, valore_minimo=par.valore_minimo, **v,
            )
            if not v["conforme"]:
                esito_ok = False
                non_conformi.append(par.nome)
        ver.esito = VerificaMacchina.ESITO_OK if esito_ok else VerificaMacchina.ESITO_KO
        ver.save()

        precedente_ok = (qm.verifiche.filter(esito=VerificaMacchina.ESITO_OK, data__lt=data)
                         .order_by("-data").values_list("data", flat=True).first())
        if esito_ok:
            qm.stato = QualificaMacchina.STATO_QUALIFICATA
            qm.data_qualifica = data
            qm.data_scadenza = None
            if qm.frequenza_mesi is None:
                qm.frequenza_mesi = qm.processo.frequenza_macchine_mesi
            qm.motivo_stato = ""
        else:
            qm.stato = QualificaMacchina.STATO_SOSPESA
            qm.motivo_stato = (f"Verifica del {data:%d-%m-%Y} non conforme: "
                               + ", ".join(non_conformi))[:255]
        qm.aggiornato_da = user if getattr(user, "is_authenticated", False) else None
        qm.save()
        _log(qm.processo, f"Verifica macchina {qm.asset.asset_tag}: "
             + ("conforme" if esito_ok else "NON conforme"),
             ver.get_tipo_display() + (f" · {', '.join(non_conformi)}" if non_conformi else ""),
             user=user)
    if not esito_ok:
        transaction.on_commit(lambda: _notifica_sicura(
            [(qm.pk, qm.motivo_stato, precedente_ok)]))
    return ver


def periodo_da_riesaminare(verifica):
    """(dal, al) delle parti lavorate da riesaminare dopo una verifica non conforme.

    Dall'ultima verifica conforme precedente (o dalla data di qualifica) alla
    verifica non conforme (MT CN 69 §9: «esaminare tutti i particolari che
    potrebbero essere stati lavorati a velocità eccessive»).
    """
    from ..models_mpq import VerificaMacchina

    if verifica.esito != VerificaMacchina.ESITO_KO:
        return None
    dal = (verifica.qualifica.verifiche
           .filter(esito=VerificaMacchina.ESITO_OK, data__lt=verifica.data)
           .order_by("-data").values_list("data", flat=True).first())
    return (dal, verifica.data)


# ── Cambi di stato manuali e automatici ──────────────────────────────────────

def cambia_stato(qm, nuovo, *, motivo="", user=None, sistema=False, limitazioni=None):
    from ..models_mpq import QualificaMacchina

    prima = qm.get_stato_display()
    qm.stato = nuovo
    qm.motivo_stato = (motivo or "")[:255]
    if limitazioni is not None:
        qm.limitazioni = limitazioni
    qm.aggiornato_da = user if getattr(user, "is_authenticated", False) else None
    qm.save()
    _log(qm.processo, f"Macchina {qm.asset.asset_tag}: {prima} → {qm.get_stato_display()}",
         motivo, user=user, sistema=sistema)
    if sistema and nuovo in (QualificaMacchina.STATO_DA_VALUTARE, QualificaMacchina.STATO_SOSPESA):
        transaction.on_commit(lambda: _notifica_sicura([(qm.pk, qm.motivo_stato, None)]))


def da_valutare_per_asset(asset, motivo):
    """Qualifiche operative dell'asset → «Da valutare» (evento di manutenzione)."""
    from ..models_mpq import QualificaMacchina

    toccate = []
    for qm in (QualificaMacchina.objects.filter(asset=asset,
                                                stato__in=QualificaMacchina.STATI_OPERATIVI)
               .select_related("processo", "asset")):
        cambia_stato(qm, QualificaMacchina.STATO_DA_VALUTARE, motivo=motivo, sistema=True)
        toccate.append(qm)
    return toccate


def applica_cambio_stato_asset(cambi):
    """Riflette i cambi di stato degli asset sulle qualifiche (da ``part145._svuota_coda``)."""
    from assets.models import Asset

    from ..models_mpq import QualificaMacchina

    for asset_id, _prima, dopo in cambi:
        asset = Asset.objects.filter(pk=asset_id).first()
        if asset is None:
            continue
        if dopo == Asset.STATUS_IN_REPAIR:
            da_valutare_per_asset(asset, "Macchina messa «in riparazione»: valutare se serve la riqualifica.")
        elif dopo == Asset.STATUS_RETIRED:
            for qm in (QualificaMacchina.objects.filter(asset=asset)
                       .exclude(stato=QualificaMacchina.STATO_RITIRATA).select_related("processo", "asset")):
                cambia_stato(qm, QualificaMacchina.STATO_RITIRATA,
                             motivo="Macchina dismessa.", sistema=True)


def odl_chiede_valutazione(workorder) -> bool:
    """Un OdL non programmato (correttivo o da ticket, non taratura) chiede la valutazione."""
    from assets.models import WorkOrder

    if workorder.kind == WorkOrder.KIND_CALIBRATION:
        return False
    return workorder.kind == WorkOrder.KIND_CORRECTIVE or workorder.origin == WorkOrder.ORIGIN_TICKET


def qualifiche_toccate_da_odl(workorder) -> list:
    """Qualifiche operative che passeranno a «Da valutare» alla chiusura dell'OdL."""
    from ..models_mpq import QualificaMacchina

    if not workorder.asset_id or not odl_chiede_valutazione(workorder):
        return []
    return list(QualificaMacchina.objects.filter(asset_id=workorder.asset_id,
                                                 stato__in=QualificaMacchina.STATI_OPERATIVI)
                .select_related("processo"))


def su_odl_chiuso(workorder):
    """OdL non programmato chiuso su una macchina qualificata → «Da valutare».

    MT CN 69 §9 / MT CN 07 §6: dopo una manutenzione che può incidere sul
    processo (mandrino, assi, sensori) la macchina va riqualificata; Qualità
    decide con «Non incide» o «Serve la riqualifica».
    """
    if not odl_chiede_valutazione(workorder):
        return []
    quando = timezone.localtime(workorder.closed_at).date() if workorder.closed_at else timezone.localdate()
    return da_valutare_per_asset(
        workorder.asset,
        f"Manutenzione non programmata «{workorder.title}» chiusa il {quando:%d-%m-%Y}: "
        "valutare se serve la riqualifica.",
    )


def _ricorda_stato_odl(sender, instance, update_fields=None, raw=False, **kwargs):
    if raw or not instance.pk:
        return
    instance._mpq_stato_prima = (
        sender.objects.filter(pk=instance.pk).values_list("status", flat=True).first()
    )


def _confronta_stato_odl(sender, instance, created=False, raw=False, **kwargs):
    prima = getattr(instance, "_mpq_stato_prima", None)
    instance._mpq_stato_prima = None
    if raw or instance.status != sender.STATUS_DONE or prima == sender.STATUS_DONE:
        return
    if created or prima is not None:
        pk = instance.pk

        def _dopo():
            odl = sender.objects.select_related("asset").filter(pk=pk).first()
            if odl is not None and odl.status == sender.STATUS_DONE:
                try:
                    su_odl_chiuso(odl)
                except Exception:
                    logger.exception("Qualifiche macchina non aggiornate dopo l'OdL %s", pk)

        transaction.on_commit(_dopo)


def collega_segnali():
    from django.db.models.signals import post_save, pre_save

    from assets.models import WorkOrder

    pre_save.connect(_ricorda_stato_odl, sender=WorkOrder, dispatch_uid="mpq_odl_ricorda_stato")
    post_save.connect(_confronta_stato_odl, sender=WorkOrder, dispatch_uid="mpq_odl_confronta_stato")


# ── Avvisi ───────────────────────────────────────────────────────────────────

def _notifica_sicura(voci):
    try:
        notifica_macchine_da_valutare(voci)
    except Exception:
        logger.exception("Avviso macchine qualificate non inviato")


@event_flow("mpq_macchina_da_valutare", skipped_result=0)
def notifica_macchine_da_valutare(voci, *, override=None, fail_silently: bool = True) -> int:
    """Mail a Qualità: macchine qualificate sospese o da valutare.

    ``voci``: [(qualifica_id, motivo, dal)] dove ``dal`` è l'inizio del periodo di
    parti lavorate da riesaminare (solo dopo una verifica non conforme).
    """
    from django.urls import reverse

    from core.email_utils import send_hub_mail

    from ..models_mpq import QualificaMacchina
    from .mpq_timbri import MSM_CONFIG_KEY
    from .reminders import get_reminder_recipients

    recipients = get_reminder_recipients(MSM_CONFIG_KEY, override=override)
    if not voci or not recipients:
        return 0
    qms = {q.pk: q for q in QualificaMacchina.objects.filter(pk__in=[v[0] for v in voci])
           .select_related("processo", "asset")}
    cella = "padding:8px 12px;border-top:1px solid #e2e8f0;"
    righe = []
    for qid, motivo, dal in voci:
        qm = qms.get(qid)
        if qm is None:
            continue
        url = reverse("anagrafica:mpq_qualifica_macchina", args=[qm.pk])
        riesame = (f"<br><span style='color:#b91c1c;'>Riesaminare le parti lavorate dal "
                   f"{dal:%d-%m-%Y}</span>") if dal else ""
        righe.append(
            f"<tr><td style='{cella}'>{escape(qm.asset.asset_tag)} — {escape(qm.asset.name)}</td>"
            f"<td style='{cella}'>{escape(qm.processo.nome)}</td>"
            f"<td style='{cella}'><strong>{escape(qm.get_stato_display())}</strong><br>"
            f"{escape(motivo or '')}{riesame}</td>"
            f"<td style='{cella}'><a href='{escape(url)}'>Apri</a></td></tr>"
        )
    if not righe:
        return 0
    intest = "text-align:left;padding:9px 12px;color:#64748b;font-size:12px;"
    tabella = (
        "<table role='presentation' width='100%' cellpadding='0' cellspacing='0' "
        "style='width:100%;border-collapse:collapse;background:#f6f9fc;border:1px solid #d8e1ec;'>"
        f"<tr style='background:#eef3f8;'><th style='{intest}'>Macchina</th>"
        f"<th style='{intest}'>Processo</th><th style='{intest}'>Stato</th><th style='{intest}'></th></tr>"
        + "".join(righe) + "</table>"
    )
    testo = (f"{len(righe)} macchine qualificate non possono lavorare il processo finché "
             "Qualità non decide (riqualifica o «Non incide»).")
    return send_hub_mail(
        subject=f"[MOD.128] Macchine qualificate da valutare ({len(righe)})",
        body_text=testo, recipients=recipients,
        title="Macchine qualificate — da valutare", email_type="Qualità", badge="MOD.128",
        section_label="Processi qualificati",
        body_html_fragment=f"<p style='margin:0 0 14px;'>{escape(testo)}</p>{tabella}",
        fail_silently=fail_silently,
    )


def macchine_in_scadenza(*, giorni=60, oggi=None) -> list[dict]:
    """Qualifiche macchina scadute, in scadenza entro ``giorni`` o non operative."""
    from ..models_mpq import ProcessoQualificato, QualificaMacchina

    oggi = oggi or timezone.localdate()
    limite = oggi + timedelta(days=giorni)
    out = []
    for qm in (QualificaMacchina.objects
               .filter(processo__stato=ProcessoQualificato.STATO_ATTIVO)
               .exclude(stato=QualificaMacchina.STATO_RITIRATA)
               .select_related("processo", "asset")):
        st = stato_visuale(qm, oggi)
        scad = st["scadenza"]
        if not st["operativa"] or (scad and scad <= limite):
            out.append({"qualifica": qm, "stato": st})
    return out
