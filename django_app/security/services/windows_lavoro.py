"""Piano di aggiornamento Windows: un caso con un'attività per PC fuori supporto o in scadenza.

Dal filtro «Sistema fuori supporto» di Dispositivi (o da quello «Supporto in scadenza») si apre **un caso** del
SOC (``SecurityRemediationTicket``, come il lavoro di una CVE) con un'attività per PC: «PC-01: Windows 11 24H2 Pro,
fine supporto 13/10/2026». Le attività seguono l'inventario a ogni ricalcolo: quando il PC risulta su una release
supportata (o sparisce dall'inventario) l'attività si spunta da sola; un PC nuovo fuori supporto aggiunge
un'attività; quando non resta nessun PC il caso si chiude, a meno che qualcuno abbia aggiunto attività a mano.

Quasi sempre non serve un PC nuovo: basta passare alla release corrente della stessa edizione (per esempio da
24H2 a 25H2), che è gratuita. Il caso è uno solo per volta (``affected_product`` = ``MARCATORE``).
"""
from __future__ import annotations

import logging

from django.db import IntegrityError, transaction
from django.utils import timezone

from security.models import SecurityAlertActionLog, SecurityCaseTask, SecurityRemediationTicket, Status
from security.services.dedup import make_hash

logger = logging.getLogger(__name__)
ATTIVI = (Status.NEW, Status.OPEN, Status.IN_PROGRESS)
ATTORE = "system:windows"
MARCATORE = "windows-fuori-supporto"


def pc_da_aggiornare(oggi=None) -> dict[str, dict]:
    """{host: stato del sistema} dei PC con Windows fuori supporto o in scadenza (entro 90 giorni)."""
    from security.services.rischio_asset import sistemi_per_host

    return {host: stato for host, stato in sistemi_per_host(oggi).items() if stato["fuori"] or stato["in_scadenza"]}


def lavoro_aperto():
    return SecurityRemediationTicket.objects.filter(affected_product=MARCATORE, status__in=ATTIVI).first()


def _titolo_attivita(host, stato):
    quando = f"fine supporto {stato['fine']:%d/%m/%Y}" if stato.get("fine") else "fine supporto non nota"
    verbo = "fuori supporto" if stato["fuori"] else "in scadenza"
    return f"{host}: {stato['nome']} {verbo}, {quando}"[:255]


def _titolo_caso(pcs):
    fuori = sum(1 for s in pcs.values() if s["fuori"])
    scad = len(pcs) - fuori
    pezzi = []
    if fuori:
        pezzi.append(f"{fuori} fuori supporto")
    if scad:
        pezzi.append(f"{scad} in scadenza")
    return f"Aggiornare Windows su {len(pcs)} PC ({', '.join(pezzi)})"[:255]


def apri_lavoro(user, oggi=None):
    """Il caso del piano di aggiornamento, con un'attività per PC. Se c'è già un caso aperto ritorna quello."""
    from security.services.cve_impact import impact_source

    esistente = lavoro_aperto()
    if esistente:
        return esistente
    pcs = pc_da_aggiornare(oggi)
    if not pcs:
        raise ValueError("Nessun PC ha Windows fuori supporto o in scadenza.")
    source = impact_source()
    descrizione = "\n".join((
        "PC con una release di Windows che non riceve più aggiornamenti di sicurezza, o che smette di riceverli entro 90 giorni.",
        "Di solito basta passare alla release corrente della stessa edizione (per esempio da 24H2 a 25H2), senza cambiare PC.",
        "Le attività dei PC si spuntano da sole quando l'inventario vede una release supportata.",
    ))
    fuori = any(s["fuori"] for s in pcs.values())
    try:
        with transaction.atomic():
            caso = SecurityRemediationTicket.objects.create(
                source=source, affected_product=MARCATORE, title=_titolo_caso(pcs), description=descrizione,
                status=Status.IN_PROGRESS, severity="high" if fuori else "medium", max_exposed_devices=len(pcs),
                dedup_hash=make_hash(source.pk, MARCATORE), origin=SecurityRemediationTicket.ORIGIN_MANUAL,
                created_by=user if getattr(user, "pk", None) else None, assignee=user if getattr(user, "pk", None) else None,
            )
            SecurityCaseTask.objects.bulk_create([
                SecurityCaseTask(ticket=caso, title=_titolo_attivita(host, stato), cve_host=host[:255], created_by=caso.created_by)
                for host, stato in sorted(pcs.items())
            ], batch_size=100)
            SecurityAlertActionLog.objects.create(ticket=caso, action="windows_lavoro_aperto", actor=getattr(user, "username", "") or "ui",
                                                  details={"pc": len(pcs)})
    except IntegrityError:
        return lavoro_aperto()
    return caso


def aggiorna(oggi=None):
    """Allinea il caso aperto all'inventario. Ritorna ``True`` se il caso si è chiuso."""
    caso = lavoro_aperto()
    if caso is None:
        return False
    pcs = pc_da_aggiornare(oggi)
    adesso = timezone.now()
    fatte, riaperte, nuove = [], [], []
    attivita = {t.cve_host: t for t in caso.tasks.exclude(cve_host="")}
    for host, task in attivita.items():
        if host not in pcs and not task.done:
            task.done, task.done_at, task.done_by = True, adesso, None
            task.save(update_fields=["done", "done_at", "done_by"])
            fatte.append(host)
        elif host in pcs and task.done:
            task.done, task.done_at, task.done_by = False, None, None
            task.save(update_fields=["done", "done_at", "done_by"])
            riaperte.append(host)
    for host, stato in pcs.items():
        if host not in attivita:
            SecurityCaseTask.objects.create(ticket=caso, title=_titolo_attivita(host, stato), cve_host=host[:255])
            nuove.append(host)
    if fatte or riaperte or nuove:
        SecurityAlertActionLog.objects.create(ticket=caso, action="windows_lavoro_aggiornato", actor=ATTORE,
                                              details={"fatti": fatte, "riaperti": riaperte, "nuovi": nuove})
        titolo = _titolo_caso(pcs) if pcs else caso.title
        if titolo != caso.title:
            caso.title = titolo
            caso.save(update_fields=["title", "updated_at"])
    if pcs or caso.tasks.filter(done=False).exists():
        return False
    from security.services.cve_lavoro import _chiudi

    caso.resolution = "Risolto da solo: nessun PC ha più Windows fuori supporto o in scadenza."
    return _chiudi(caso)


def riepilogo():
    """Per Dispositivi: il caso aperto e a che punto è, o ``None``."""
    caso = lavoro_aperto()
    if caso is None:
        return None
    attivita = list(caso.tasks.exclude(cve_host=""))
    fatti, totale = sum(1 for t in attivita if t.done), len(attivita)
    return {"caso": caso, "fatti": fatti, "totale": totale, "percento": round(100 * fatti / totale) if totale else 0}
