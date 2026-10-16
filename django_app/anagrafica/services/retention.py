"""Retention GDPR dei dati HR: cosa sarebbe da cancellare, senza cancellare.

Un solo punto di calcolo per il comando ``cleanup_expired_documents`` (che con
``--apply`` cancella) e per il report settimanale in monitoring, che e' solo
in lettura: dice quanti documenti e candidati hanno superato la conservazione,
mai chi sono ne' cosa contengono.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

from django.utils import timezone

logger = logging.getLogger(__name__)

CHECK_NAME = "anagrafica_retention_report"
# Candidati chiusi senza esito utile (non assunti, non tenuti «in database"):
# oltre questi mesi dall'ultima modifica i loro dati vanno rivalutati.
MESI_CONSERVAZIONE_CANDIDATI = 24


@dataclass
class EsitoDocumenti:
    esaminati: int = 0
    saltati_attivi: int = 0
    saltati_retention: int = 0
    da_eliminare: list = field(default_factory=list)  # [(documento, data_cessazione)]


def documenti_scaduti(*, oggi: date | None = None, tipo: str = "", limit: int | None = None) -> EsitoDocumenti:
    """Documenti con retention scaduta di persone cessate da piu' degli anni di legge.

    Criteri (tutti veri): ``retention_until`` passato, data di cessazione valorizzata,
    ``cessazione + anni di retention del tipo`` passata. Un dipendente attivo non
    perde mai documenti.
    """
    from anagrafica.models import DipendenteAnagraficaAziendale, DocumentoDipendente, _add_months

    oggi = oggi or timezone.localdate()
    qs = DocumentoDipendente.objects.filter(
        retention_until__isnull=False, retention_until__lt=oggi,
    ).order_by("retention_until", "id")
    if tipo:
        qs = qs.filter(tipo=tipo)
    legacy_ids = list(qs.values_list("legacy_anagrafica_id", flat=True).distinct())
    cessazioni = dict(
        DipendenteAnagraficaAziendale.objects.filter(legacy_anagrafica_id__in=legacy_ids)
        .values_list("legacy_anagrafica_id", "data_cessazione")
    )
    esito = EsitoDocumenti()
    for doc in (qs[:limit] if limit else qs):
        esito.esaminati += 1
        cessazione = cessazioni.get(doc.legacy_anagrafica_id)
        if cessazione is None:
            esito.saltati_attivi += 1
            continue
        anni = DocumentoDipendente._RETENTION_ANNI.get(doc.tipo, 10)
        if _add_months(cessazione, anni * 12) >= oggi:
            esito.saltati_retention += 1
            continue
        esito.da_eliminare.append((doc, cessazione))
    return esito


def candidati_da_rivalutare(*, oggi: date | None = None) -> int:
    """Candidati chiusi (non idonei, rinunce, annullati) fermi da oltre la conservazione."""
    from anagrafica.models_recruiting import Candidato
    from anagrafica.models import _add_months

    oggi = oggi or timezone.localdate()
    soglia = _add_months(oggi, -MESI_CONSERVAZIONE_CANDIDATI)
    return Candidato.objects.filter(
        stato__in=(Candidato.STATO_SCARTATO, Candidato.STATO_RINUNCIA, Candidato.STATO_ANNULLATO),
        updated_at__date__lt=soglia,
    ).count()


def report_retention(*, oggi: date | None = None) -> dict:
    """Riepilogo in sola lettura: conteggi per tipo documento e candidati da rivalutare."""
    esito = documenti_scaduti(oggi=oggi)
    per_tipo: dict[str, int] = {}
    for doc, _cessazione in esito.da_eliminare:
        per_tipo[doc.tipo] = per_tipo.get(doc.tipo, 0) + 1
    return {
        "documenti_da_eliminare": len(esito.da_eliminare),
        "documenti_per_tipo": dict(sorted(per_tipo.items())),
        "documenti_di_attivi": esito.saltati_attivi,
        "candidati_da_rivalutare": candidati_da_rivalutare(oggi=oggi),
    }


def pubblica_in_monitoring(report: dict) -> dict:
    """Una Issue (dedup) in monitoring se c'e' qualcosa oltre la conservazione.

    Il messaggio contiene solo conteggi: nessun nome, nessun dato sanitario.
    Nulla viene cancellato: la cancellazione resta ``cleanup_expired_documents --apply``.
    """
    from monitoring.models import Issue
    from monitoring.services import open_or_update_issue_from_health_check, resolve_health_check_issue

    documenti = report["documenti_da_eliminare"]
    candidati = report["candidati_da_rivalutare"]
    if not documenti and not candidati:
        resolve_health_check_issue(check_name=CHECK_NAME, category=Issue.Category.DATA,
                                   summary="Retention HR: nessun dato oltre la conservazione.")
        return report
    righe = [f"Documenti dipendente oltre la conservazione: {documenti}"]
    righe += [f"  {tipo}: {n}" for tipo, n in report["documenti_per_tipo"].items()]
    righe.append(f"Candidati chiusi fermi da oltre {MESI_CONSERVAZIONE_CANDIDATI} mesi: {candidati}")
    righe.append("Report in sola lettura: nulla e' stato cancellato. Verifica con "
                 "«manage.py cleanup_expired_documents» (dry-run) prima di qualsiasi --apply.")
    open_or_update_issue_from_health_check(
        check_name=CHECK_NAME,
        title=f"Retention HR: {documenti} documenti, {candidati} candidati oltre la conservazione",
        message="\n".join(righe)[:8000],
        severity=Issue.Severity.LOW,
        category=Issue.Category.DATA, module_name="anagrafica",
        extra_json=report,
        notify=False,
    )
    return report
