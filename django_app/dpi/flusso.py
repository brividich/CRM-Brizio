"""Flusso richiesta DPI: dipendente -> responsabile/preposto approva -> avviso a
magazzino/amministrazione -> report di consegna all'amministrazione.

Regola dell'approvatore (come assenze e organigramma): il responsabile effettivo
del dipendente e' quello dell'AREA AZIENDALE, altrimenti il caporeparto del
REPARTO (``reparto_canonico.resolve_responsabile_effettivo``); si aggiungono i
co-responsabili di area/reparto e i colleghi della stessa area con ruolo
operativo «Preposto». I gestori DPI restano approvatori di ripiego (gate in view).

Le notifiche sono fail-soft: un errore di invio non blocca mai il flusso.
"""
from __future__ import annotations

import logging
from datetime import date

logger = logging.getLogger(__name__)

RUOLO_PREPOSTO = "preposto"


def _split_emails(text: str) -> list[str]:
    raw = (text or "").replace(";", "\n").replace(",", "\n")
    seen: list[str] = []
    for line in raw.splitlines():
        value = line.strip()
        if value and value.lower() not in {s.lower() for s in seen}:
            seen.append(value)
    return seen


def _area_reparto(legacy_id: int):
    from anagrafica.models import DipendenteAnagraficaAziendale

    az = (
        DipendenteAnagraficaAziendale.objects.filter(legacy_anagrafica_id=int(legacy_id))
        .select_related("area_aziendale", "area_aziendale__reparto")
        .first()
    )
    area = az.area_aziendale if az and az.area_aziendale_id else None
    reparto = area.reparto if area is not None and area.reparto_id else None
    return area, reparto


def approvatori_di(legacy_id: int | None) -> set[int]:
    """ID legacy anagrafica di chi puo' approvare le richieste di ``legacy_id``."""
    if not legacy_id:
        return set()
    from anagrafica.models import DipendenteAnagraficaAziendale, DipendenteRuoloOperativo
    from anagrafica.services.reparto_canonico import resolve_responsabile_effettivo

    ids: set[int] = set()
    try:
        area, reparto = _area_reparto(legacy_id)
        principale = resolve_responsabile_effettivo(area=area, reparto=reparto)
        if principale:
            ids.add(int(principale))
        if area is not None:
            ids.update(int(i) for i in area.responsabili.values_list("id", flat=True))
        if reparto is not None:
            ids.update(int(i) for i in reparto.responsabili.values_list("id", flat=True))
        if area is not None:
            colleghi = DipendenteAnagraficaAziendale.objects.filter(area_aziendale=area).values_list(
                "legacy_anagrafica_id", flat=True
            )
            ids.update(
                int(i)
                for i in DipendenteRuoloOperativo.objects.filter(
                    legacy_anagrafica_id__in=list(colleghi), ruolo__nome__iexact=RUOLO_PREPOSTO, data_fine__isnull=True
                ).values_list("legacy_anagrafica_id", flat=True)
            )
    except Exception:
        logger.warning("approvatori_di fallita per %s", legacy_id, exc_info=True)
    ids.discard(int(legacy_id))  # nessuno approva la propria richiesta come capo di se stesso
    return ids


def dipendenti_di_approvatore(approvatore_legacy_id: int | None) -> set[int]:
    """ID legacy dei dipendenti le cui richieste puo' approvare ``approvatore_legacy_id``.

    Inverso di :func:`approvatori_di`, calcolato con poche query (serve a ogni
    apertura della pagina DPI): aree/reparti guidati, co-responsabili, preposto."""
    if not approvatore_legacy_id:
        return set()
    from django.db.models import Q

    from anagrafica.models import AreaAziendale, DipendenteAnagraficaAziendale, DipendenteRuoloOperativo

    me = int(approvatore_legacy_id)
    result: set[int] = set()
    try:
        # Aree guidate (responsabile o co-responsabile) + aree di un reparto senza
        # responsabile d'area proprio guidato da me (caporeparto = ripiego) o co-guidato.
        aree = AreaAziendale.objects.filter(
            Q(responsabile_legacy_id=me)
            | Q(responsabili__id=me)
            | Q(reparto__responsabili__id=me)
            | Q(reparto__caporeparto_legacy_id=me, responsabile_legacy_id__isnull=True)
        ).values_list("id", flat=True)
        area_ids = set(aree)
        # Preposto: le persone della propria area.
        if DipendenteRuoloOperativo.objects.filter(
            legacy_anagrafica_id=me, ruolo__nome__iexact=RUOLO_PREPOSTO, data_fine__isnull=True
        ).exists():
            mie = DipendenteAnagraficaAziendale.objects.filter(legacy_anagrafica_id=me).values_list(
                "area_aziendale_id", flat=True
            )
            area_ids.update(a for a in mie if a)
        if area_ids:
            result.update(
                int(i)
                for i in DipendenteAnagraficaAziendale.objects.filter(area_aziendale_id__in=area_ids).values_list(
                    "legacy_anagrafica_id", flat=True
                )
            )
    except Exception:
        logger.warning("dipendenti_di_approvatore fallita per %s", me, exc_info=True)
    result.discard(me)
    return result


def _email_persona(legacy_id: int) -> str:
    from core.caporeparto_digest import capo_notification_email

    return capo_notification_email(legacy_id)


def _destinatari_approvatori(richiesta) -> list[str]:
    emails = [e for e in (_email_persona(i) for i in approvatori_di(richiesta.richiedente_legacy_id)) if e]
    if not emails:
        from anagrafica.services.reminders import get_reminder_recipients

        emails = get_reminder_recipients("dpi_car_emails")
    return sorted(set(emails), key=str.lower)


def destinatari_magazzino() -> list[str]:
    from .models import DPIImpostazioni

    return _split_emails(DPIImpostazioni.get_singleton().magazzino_emails)


def destinatari_amministrazione() -> list[str]:
    from .models import DPIImpostazioni

    return _split_emails(DPIImpostazioni.get_singleton().amministrazione_emails)


def _riga_dpi(richiesta) -> str:
    parti = [richiesta.categoria.nome]
    if richiesta.tipo_dpi:
        parti.append(richiesta.tipo_dpi.nome)
    if richiesta.modello_dpi:
        parti.append(f"{richiesta.modello_dpi.codice} {richiesta.modello_dpi.nome}".strip())
    if richiesta.taglia_dpi:
        parti.append(f"taglia {richiesta.taglia_dpi.valore}")
    return " - ".join(parti) + f" (x{richiesta.quantita})"


def _mail(subject: str, body: str, recipients: list[str], *, title: str, attachments=None) -> int:
    if not recipients:
        return 0
    from core.email_utils import send_hub_mail

    return send_hub_mail(
        subject=subject,
        body_text=body,
        recipients=recipients,
        title=title,
        email_type="DPI",
        section_label="Richieste DPI",
        attachments=attachments,
        fail_silently=True,
    )


def _dettaglio_richiesta(richiesta) -> str:
    righe = [
        f"Richiesta: {richiesta.numero}",
        f"Dipendente: {richiesta.richiedente_nome}"
        + (f" ({richiesta.richiedente_reparto})" if richiesta.richiedente_reparto else ""),
        f"DPI: {_riga_dpi(richiesta)}",
    ]
    if richiesta.motivazione:
        righe.append(f"Motivazione: {richiesta.motivazione}")
    return "\n".join(righe)


from automazioni.managed_flows import event_flow


@event_flow("dpi_richiesta_da_approvare", skipped_result=None)
def notifica_nuova_richiesta(richiesta) -> None:
    """Passo 1 -> 2: avvisa il responsabile/preposto che c'e' una richiesta da approvare."""
    try:
        destinatari = _destinatari_approvatori(richiesta)
        _mail(
            f"[DPI] Richiesta da approvare {richiesta.numero} - {richiesta.richiedente_nome}",
            _dettaglio_richiesta(richiesta) + "\n\nApri il portale (DPI > Gestione richieste) per approvarla o rifiutarla.",
            destinatari,
            title="Richiesta DPI da approvare",
        )
    except Exception:
        logger.warning("Notifica nuova richiesta DPI fallita (%s)", getattr(richiesta, "numero", "?"), exc_info=True)


@event_flow("dpi_avviso_consegna", skipped_result=None)
def notifica_approvata(richiesta) -> None:
    """Passo 2 -> 3: avviso di consegna a magazzino e amministrazione."""
    try:
        destinatari = sorted(set(destinatari_magazzino()) | set(destinatari_amministrazione()), key=str.lower)
        _mail(
            f"[DPI] Da consegnare {richiesta.numero} - {richiesta.richiedente_nome}",
            _dettaglio_richiesta(richiesta) + "\n\nLa richiesta e' stata approvata: preparare e consegnare il DPI, poi registrare la consegna in DPI > Gestione richieste.",
            destinatari,
            title="DPI da consegnare",
        )
    except Exception:
        logger.warning("Avviso di consegna DPI fallito (%s)", getattr(richiesta, "numero", "?"), exc_info=True)


@event_flow("dpi_report_consegna", skipped_result=None)
def notifica_consegnata(consegna) -> None:
    """Passo 4: report di consegna all'amministrazione (con il modulo PDF in allegato)."""
    richiesta = consegna.richiesta
    try:
        destinatari = destinatari_amministrazione()
        if not destinatari:
            return
        attachments = None
        try:
            from .pdf import render_modulo_consegna_dpi

            pdf = render_modulo_consegna_dpi(consegna)
            attachments = [(f"consegna_dpi_{richiesta.numero}.pdf", pdf, "application/pdf")]
        except Exception:
            logger.warning("PDF report consegna DPI non allegato (%s)", richiesta.numero, exc_info=True)
        data = consegna.data_consegna
        righe = [
            _dettaglio_richiesta(richiesta),
            f"Consegnato il: {data:%d/%m/%Y}" if isinstance(data, date) else "",
            f"Consegnato da: {consegna.consegnato_da_nome}" if getattr(consegna, "consegnato_da_nome", "") else "",
            "Ricevuta firmata: " + ("si" if consegna.firmato_ricevuta else "no"),
        ]
        scadenza = getattr(consegna, "scadenza_calcolata", None)
        if scadenza:
            righe.append(f"Scadenza stimata: {scadenza:%d/%m/%Y}")
        _mail(
            f"[DPI] Report di consegna {richiesta.numero} - {richiesta.richiedente_nome}",
            "\n".join(r for r in righe if r),
            destinatari,
            title="Report di consegna DPI",
            attachments=attachments,
        )
    except Exception:
        logger.warning("Report consegna DPI fallito (%s)", richiesta.numero, exc_info=True)
