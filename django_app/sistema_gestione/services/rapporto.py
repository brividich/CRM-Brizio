"""Rapporto MOD.035B emesso: PDF congelato con impronta, mai rigenerato dopo la chiusura."""
from __future__ import annotations

from hashlib import sha256
from uuid import uuid4

from django.core.files.base import ContentFile
from django.db.models import Max

from ..models import Audit, AuditRapportoVersione


def _snapshot(audit: Audit) -> dict:
    return {
        "riepilogo": audit.riepilogo_generato, "giudizio": audit.giudizio, "punti_forza": audit.punti_forza,
        "valutazione_rdd": audit.valutazione_rdd, "car_autorizzate": audit.car_autorizzate,
        "firma_auditor": str(audit.rapporto_firmato_auditor_il), "auditor_id": audit.rapporto_firmato_auditor_da_id,
        "convalida_ente": str(audit.rapporto_convalidato_ente_il), "ente_id": audit.rapporto_convalidato_ente_da_id,
        "valutazione_il": str(audit.rapporto_valutato_rdd_il), "rdd_id": audit.rapporto_valutato_rdd_da_id,
    }


def archivia_rapporto(audit: Audit, *, tipo: str, motivo: str, autore) -> AuditRapportoVersione:
    """Genera il PDF dallo stato attuale, lo archivia con SHA-256 e restituisce la versione."""
    from ..audit_exports import rapporto_audit_pdf, rapporto_isms_pdf

    corpo = rapporto_isms_pdf(audit) if audit.is_isms else rapporto_audit_pdf(audit)
    numero = (audit.versioni_rapporto.aggregate(n=Max("numero"))["n"] or 0) + 1
    versione = AuditRapportoVersione(
        audit=audit, numero=numero, tipo=tipo, motivo=motivo[:500], autore=autore,
        sha256=sha256(corpo).hexdigest(), snapshot=_snapshot(audit),
        copia_firmata=audit.copia_firmata_rapporto.name if tipo == AuditRapportoVersione.TIPO_REVISIONE else "",
    )
    versione.pdf.save(uuid4().hex + ".pdf", ContentFile(corpo), save=False)
    try:
        versione.save()
    except Exception:
        versione.pdf.delete(save=False)
        raise
    return versione


def emetti_rapporto(audit: Audit, *, autore) -> AuditRapportoVersione:
    return archivia_rapporto(
        audit, tipo=AuditRapportoVersione.TIPO_EMISSIONE,
        motivo="Emissione alla chiusura dell'audit", autore=autore,
    )


def rapporto_emesso(audit: Audit) -> AuditRapportoVersione | None:
    """L'ultima emissione valida: solo per un audit chiuso, perché una revisione la supera."""
    if audit.stato != Audit.STATO_CHIUSO:
        return None
    return audit.versioni_rapporto.filter(tipo=AuditRapportoVersione.TIPO_EMISSIONE).order_by("-numero").first()
