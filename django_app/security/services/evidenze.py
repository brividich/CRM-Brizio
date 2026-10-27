"""Integrità e catena di custodia delle prove (ISO 27001 5.28).

Ogni contenitore di evidenze riceve alla nascita un'impronta SHA-256 del suo contenuto (titolo,
traccia di decisione e ogni elemento: tipo, evento, report, contenuto). «Verifica integrità»
ricalcola l'impronta e la confronta: ``verified`` se coincide, ``altered`` se il contenuto è
cambiato. La catena di custodia (``SecurityEvidenceCustody``) registra chi ha creato, sigillato,
guardato, esportato e verificato il contenitore. I contenitori nati prima di questa funzione
vengono sigillati dal ciclo periodico (``sigilla_mancanti``).
"""
from __future__ import annotations

import hashlib
import json

from django.utils import timezone

from security.models import SecurityEvidenceContainer, SecurityEvidenceCustody

VERIFIED = "verified"
ALTERED = "altered"
LABELS = {VERIFIED: "Integra", ALTERED: "Alterata", "": "Non verificata"}
TONES = {VERIFIED: "success", ALTERED: "critical", "": "muted"}


def _canonico(valore) -> str:
    return json.dumps(valore, sort_keys=True, ensure_ascii=True, separators=(",", ":"), default=str)


def impronta(container) -> str:
    """SHA-256 del contenuto del contenitore, indipendente dall'ordine dei campi."""
    items = [
        {"id": item.pk, "item_type": item.item_type, "event": item.event_id, "report": item.report_id, "content": item.content}
        for item in container.items.order_by("id")
    ]
    corpo = {"id": str(container.pk), "title": container.title, "decision_trace": container.decision_trace, "items": items}
    return hashlib.sha256(_canonico(corpo).encode("utf-8")).hexdigest()


def custodia(container, azione, actor="system", esito="", **details):
    return SecurityEvidenceCustody.objects.create(container=container, azione=azione, actor=actor or "system", esito=esito, details=details)


def sigilla(container, actor="system"):
    """Calcola e salva l'impronta (solo se manca: un sigillo non si rifà)."""
    if container.sha256:
        return container
    container.sha256 = impronta(container)
    container.sigillata_il = timezone.now()
    container.save(update_fields=["sha256", "sigillata_il"])
    custodia(container, "sealed", actor, sha256=container.sha256)
    return container


def verifica(container, actor="system") -> dict:
    """Ricalcola l'impronta e registra l'esito; un contenitore senza sigillo viene sigillato ora."""
    if not container.sha256:
        sigilla(container, actor)
    attuale = impronta(container)
    esito = VERIFIED if attuale == container.sha256 else ALTERED
    container.integrita = esito
    container.integrita_verificata_il = timezone.now()
    container.save(update_fields=["integrita", "integrita_verificata_il"])
    custodia(container, "verified", actor, esito=esito, sha256_attesa=container.sha256, sha256_attuale=attuale)
    return {"esito": esito, "label": LABELS[esito], "sha256": container.sha256, "attuale": attuale}


def registra_visione(containers, actor):
    """«Visto da» una volta al giorno per persona e contenitore: la pagina alert si apre spesso."""
    oggi = timezone.localdate()
    for container in containers:
        gia = SecurityEvidenceCustody.objects.filter(container=container, azione="viewed", actor=actor, created_at__date=oggi).exists()
        if not gia:
            custodia(container, "viewed", actor)


def esporta(container, actor) -> dict:
    """Contenuto completo del contenitore con impronta: l'esportazione resta in custodia."""
    custodia(container, "exported", actor)
    return {
        "id": str(container.pk),
        "title": container.title,
        "created_at": container.created_at.isoformat(),
        "sha256": container.sha256,
        "sigillata_il": container.sigillata_il.isoformat() if container.sigillata_il else None,
        "integrita": container.integrita,
        "decision_trace": container.decision_trace,
        "items": [
            {"id": item.pk, "item_type": item.item_type, "event": item.event_id, "report": item.report_id,
             "created_at": item.created_at.isoformat(), "content": item.content}
            for item in container.items.order_by("id")
        ],
        "custodia": [
            {"quando": c.created_at.isoformat(), "azione": c.azione, "chi": c.actor, "esito": c.esito}
            for c in container.custodia.order_by("created_at")
        ],
    }


def sigilla_mancanti(limit=500) -> int:
    """Passo del ciclo periodico: sigilla i contenitori ancora senza impronta."""
    done = 0
    for container in SecurityEvidenceContainer.objects.filter(sha256="").order_by("created_at")[:limit]:
        sigilla(container)
        done += 1
    return done


def riepilogo() -> dict:
    qs = SecurityEvidenceContainer.objects.all()
    return {
        "totali": qs.count(),
        "verificate": qs.filter(integrita=VERIFIED).count(),
        "alterate": qs.filter(integrita=ALTERED).count(),
    }
