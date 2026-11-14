"""MOD.128 — utensili critici, Technical Plan e MOD.176 RUC (MT CN 69 §8, P11TF12).

- Technical Plan: uno per P/N e tipologia di foro, con revisioni; vale in produzione
  solo la revisione approvata dal Certify Agent del cliente, la precedente diventa
  «Superata». Una nuova revisione parte dai passi di quella valida.
- Utensili critici: anagrafica per processo (commerciali o speciali, riaffilatura).
- MOD.176: per ogni utensile/kit montato si registrano le parti lavorate; al TCP
  del passo il registro passa a «TCP raggiunto» e va chiuso e consegnato a IN1.
"""
from __future__ import annotations

from django.db import transaction
from django.db.models import Max, Sum
from django.utils import timezone


def nuova_revisione(plan, *, modifiche: str, data=None):
    """Nuova revisione in attesa di approvazione, con i passi copiati da quella valida (o dall'ultima)."""
    from ..models_mpq import TechnicalPlanRevisione

    base = plan.revisione_corrente or plan.revisioni.order_by("-numero").first()
    numero = (plan.revisioni.aggregate(m=Max("numero"))["m"] or 0) + 1
    with transaction.atomic():
        rev = TechnicalPlanRevisione.objects.create(plan=plan, numero=numero, modifiche=modifiche,
                                                    data=data or timezone.localdate())
        if base is not None:
            for p in base.passi.all():
                p.pk = None
                p.revisione = rev
                p.save()
    return rev


def approva(revisione, *, approvato_da: str, data=None, documento=None) -> None:
    """Approvazione del Certify Agent: la revisione diventa valida, la precedente valida è superata."""
    from ..models_mpq import TechnicalPlanRevisione

    with transaction.atomic():
        (TechnicalPlanRevisione.objects.filter(plan=revisione.plan, stato=TechnicalPlanRevisione.STATO_APPROVATA)
         .exclude(pk=revisione.pk).update(stato=TechnicalPlanRevisione.STATO_SUPERATA))
        revisione.stato = TechnicalPlanRevisione.STATO_APPROVATA
        revisione.approvato_da = approvato_da
        revisione.data_approvazione = data or timezone.localdate()
        campi = ["stato", "approvato_da", "data_approvazione"]
        if documento is not None:
            revisione.documento = documento
            revisione.documento_nome_originale = getattr(documento, "name", "")[:255]
            campi += ["documento", "documento_nome_originale"]
        revisione.save(update_fields=campi)


def registra_riga(registro, **dati) -> dict:
    """Aggiunge una riga al MOD.176. ``{"riga", "tcp_raggiunto", "oltre"}`` (oltre = quantità sopra il TCP)."""
    from ..models_mpq import RegistroUtensile, RegistroUtensileRiga

    if registro.stato != RegistroUtensile.STATO_IN_USO:
        raise ValueError("Il registro non è più in uso: apri un nuovo utensile/kit.")
    with transaction.atomic():
        riga = RegistroUtensileRiga.objects.create(registro=registro, **dati)
        usato = registro.righe.aggregate(s=Sum("quantita"))["s"] or 0
        limite = registro.passo.tcp_limite
        raggiunto = limite is not None and usato >= limite
        if raggiunto:
            registro.stato = RegistroUtensile.STATO_TCP
            registro.save(update_fields=["stato"])
    return {"riga": riga, "tcp_raggiunto": raggiunto, "oltre": max(0, usato - limite) if limite else 0}


def chiudi(registro, *, data=None) -> None:
    """Registro compilato e consegnato a IN1 (archiviato nella cartella del P/N)."""
    from ..models_mpq import RegistroUtensile

    registro.stato = RegistroUtensile.STATO_CHIUSO
    registro.chiuso_il = data or timezone.localdate()
    registro.save(update_fields=["stato", "chiuso_il"])


def riepilogo(processo) -> dict:
    """Numeri per il dettaglio del processo."""
    from ..models_mpq import RegistroUtensile, TechnicalPlanRevisione

    registri = RegistroUtensile.objects.filter(passo__revisione__plan__processo=processo)
    return {
        "utensili": processo.utensili_critici.filter(attivo=True).count(),
        "plan": processo.technical_plan.count(),
        "in_approvazione": TechnicalPlanRevisione.objects.filter(
            plan__processo=processo, stato=TechnicalPlanRevisione.STATO_BOZZA).count(),
        "in_uso": registri.filter(stato=RegistroUtensile.STATO_IN_USO).count(),
        "al_tcp": registri.filter(stato=RegistroUtensile.STATO_TCP).count(),
    }
