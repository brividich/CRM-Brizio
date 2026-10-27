"""Flusso richiesta DPI: dipendente -> responsabile/preposto approva (la richiesta
di un CAR/preposto e' approvata da sola) -> avviso al magazzino -> il magazzino
segna «Pronto per il ritiro» e il dipendente e' avvisato (o subito all'approvazione,
da Impostazioni) -> consegna -> report al preposto e, per le categorie che lo
prevedono, all'amministrazione.

Regola dell'approvatore (come assenze e organigramma): il responsabile effettivo
del dipendente e' quello dell'AREA AZIENDALE, altrimenti il caporeparto del
REPARTO (``reparto_canonico.resolve_responsabile_effettivo``); si aggiungono i
co-responsabili di area/reparto e i colleghi della stessa area con ruolo
operativo «Preposto». I gestori DPI restano approvatori di ripiego (gate in view).
Con la regola unica capo/team di Anagrafica accesa (``capo_team``) il capo
diretto viene da lì; co-responsabili e preposto restano.

Le notifiche sono fail-soft: un errore di invio non blocca mai il flusso.
"""
from __future__ import annotations

import logging
from datetime import date

logger = logging.getLogger(__name__)

RUOLO_PREPOSTO = "preposto"


def ruoli_preposto_ids() -> list[int]:
    """Ruoli operativi del preposto: per nome attuale o per un nome precedente,
    così una rinomina del ruolo (es. «Preposto di reparto») non spegne le approvazioni."""
    from anagrafica.models import RuoloOperativo

    ids = []
    for pk, nome, precedenti in RuoloOperativo.objects.values_list("pk", "nome", "nomi_precedenti"):
        nomi = [nome or ""] + (precedenti or "").splitlines()
        if any(n.strip().casefold() == RUOLO_PREPOSTO for n in nomi):
            ids.append(pk)
    return ids


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


def _capo_regola_unica(legacy_id) -> int | None:
    """Capo diretto dalla regola unica di Anagrafica, se accesa (None altrimenti)."""
    try:
        from anagrafica.services import capo_team

        return capo_team.capo_effettivo(legacy_id) if capo_team.regola_unica_attiva() else None
    except Exception:
        return None


def _team_regola_unica(legacy_id) -> set[int] | None:
    """Team diretto dalla regola unica, se accesa (None = regola di prima)."""
    try:
        from anagrafica.services import capo_team

        return capo_team.team_anagrafica(legacy_id, solo_diretti=True) if capo_team.regola_unica_attiva() else None
    except Exception:
        return None


def _co_capi_regola_unica(legacy_id) -> set[int] | None:
    """Co-capi dalla regola unica, se accesa (None = regola di prima)."""
    try:
        from anagrafica.services import capo_team

        if not capo_team.regola_unica_attiva():
            return None
        return set(capo_team.co_capi_in_cache().get(int(legacy_id), []))
    except Exception:
        return None


def approvatori_di(legacy_id: int | None) -> set[int]:
    """ID legacy anagrafica di chi puo' approvare le richieste di ``legacy_id``."""
    if not legacy_id:
        return set()
    from anagrafica.models import DipendenteAnagraficaAziendale, DipendenteRuoloOperativo
    from anagrafica.services.reparto_canonico import resolve_responsabile_effettivo

    ids: set[int] = set()
    try:
        area, reparto = _area_reparto(legacy_id)
        principale = _capo_regola_unica(legacy_id)
        co_capi = _co_capi_regola_unica(legacy_id)
        if principale is None and co_capi is None:
            principale = resolve_responsabile_effettivo(area=area, reparto=reparto)
        if principale:
            ids.add(int(principale))
        if co_capi is not None:
            # Regola unica: i co-capi sono le altre persone con la mansione del capo.
            ids.update(co_capi)
        else:
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
                    legacy_anagrafica_id__in=list(colleghi), ruolo_id__in=ruoli_preposto_ids(), data_fine__isnull=True
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
        team_unico = _team_regola_unica(me)
        if team_unico is not None:
            # Regola unica accesa: il capo diretto e i co-capi (stessa mansione
            # del capo) li dice lei; resta il preposto (sotto).
            result.update(team_unico)
            from anagrafica.services import capo_team

            result.update(p for p, co in capo_team.co_capi_in_cache().items() if me in co)
            aree = AreaAziendale.objects.none().values_list("id", flat=True)
        else:
            aree = AreaAziendale.objects.filter(
                Q(responsabile_legacy_id=me)
                | Q(responsabili__id=me)
                | Q(reparto__responsabili__id=me)
                | Q(reparto__caporeparto_legacy_id=me, responsabile_legacy_id__isnull=True)
            ).values_list("id", flat=True)
        area_ids = set(aree)
        # Preposto: le persone della propria area.
        if DipendenteRuoloOperativo.objects.filter(
            legacy_anagrafica_id=me, ruolo_id__in=ruoli_preposto_ids(), data_fine__isnull=True
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


def e_capo_o_preposto(legacy_id: int | None) -> bool:
    """True se ``legacy_id`` approva le richieste di qualcuno (CAR, responsabile o preposto):
    le sue richieste DPI sono approvate da sole."""
    return bool(legacy_id) and bool(dipendenti_di_approvatore(legacy_id))


def email_preposti(richiesta) -> list[str]:
    """Email dei responsabili/preposti del richiedente (senza ripieghi)."""
    emails = [e for e in (_email_persona(i) for i in approvatori_di(richiesta.richiedente_legacy_id)) if e]
    return sorted({e.lower(): e for e in emails}.values(), key=str.lower)


def email_dipendente(richiesta) -> str:
    """Email di notifica del richiedente; in mancanza quella salvata sulla richiesta."""
    email = _email_persona(richiesta.richiedente_legacy_id) if richiesta.richiedente_legacy_id else ""
    return email or (richiesta.richiedente_email or "").strip()


def _destinatari_approvatori(richiesta) -> list[str]:
    emails = email_preposti(richiesta)
    if not emails:
        from anagrafica.services.reminders import get_reminder_recipients

        emails = get_reminder_recipients("dpi_car_emails")
    from .models import DPIImpostazioni

    if DPIImpostazioni.get_singleton().notifica_nuova_richiesta:
        # Spunta «Email ai referenti per ogni nuova richiesta» delle Impostazioni DPI.
        emails = list(emails) + destinatari_referenti()
    return sorted({e.lower(): e for e in emails}.values(), key=str.lower)


def destinatari_referenti() -> list[str]:
    """Referenti DPI delle Impostazioni: responsabili + email notifiche aggiuntive."""
    from .models import DPIImpostazioni

    impost = DPIImpostazioni.get_singleton()
    emails = [
        str(p.get("email", "")).strip()
        for p in (impost.responsabili or [])
        if isinstance(p, dict) and p.get("email")
    ]
    if impost.responsabile_email:
        emails.append(impost.responsabile_email.strip())
    emails.extend(_split_emails(impost.notifica_email_extra))
    return _split_emails("\n".join(emails))


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
    """Passo 2 -> 3: avviso al magazzino di preparare il DPI."""
    from .models import DPIImpostazioni

    if DPIImpostazioni.get_singleton().avviso_ritiro_all_approvazione:
        passo = "il dipendente e' gia' stato avvisato di passare a ritirarlo: consegnalo e registra la consegna"
    else:
        passo = ("preparalo, poi in DPI > Gestione richieste premi «Pronto per il ritiro» (avvisa il dipendente) "
                 "e alla consegna registra la consegna")
    try:
        _mail(
            f"[DPI] Da consegnare {richiesta.numero} - {richiesta.richiedente_nome}",
            _dettaglio_richiesta(richiesta) + f"\n\nLa richiesta e' stata approvata: {passo}.",
            destinatari_magazzino(),
            title="DPI da consegnare",
        )
    except Exception:
        logger.warning("Avviso di consegna DPI fallito (%s)", getattr(richiesta, "numero", "?"), exc_info=True)


@event_flow("dpi_pronta_ritiro", skipped_result=None)
def notifica_pronta_ritiro(richiesta) -> None:
    """Passo 3: il DPI e' pronto, il dipendente passa a ritirarlo."""
    try:
        email = email_dipendente(richiesta)
        _mail(
            f"[DPI] Il tuo DPI e' pronto: passa a ritirarlo ({richiesta.numero})",
            _dettaglio_richiesta(richiesta)
            + "\n\nIl DPI che hai richiesto e' pronto: passa in magazzino a ritirarlo. Alla consegna firmerai la ricevuta.",
            [email] if email else [],
            title="DPI pronto per il ritiro",
        )
    except Exception:
        logger.warning("Avviso di ritiro DPI fallito (%s)", getattr(richiesta, "numero", "?"), exc_info=True)


@event_flow("dpi_report_consegna", skipped_result=None)
def notifica_consegnata(consegna) -> None:
    """Passo 4: report di consegna (con il modulo PDF in allegato) al preposto del
    dipendente e, se la categoria lo prevede, all'Amministrazione."""
    richiesta = consegna.richiesta
    try:
        destinatari = list(email_preposti(richiesta))
        if richiesta.categoria.avvisa_amministrazione_consegna:
            destinatari += destinatari_amministrazione()
        destinatari = sorted({e.lower(): e for e in destinatari}.values(), key=str.lower)
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


@event_flow("dpi_consegna_annullata", skipped_result=None)
def notifica_rifiutata_dopo_approvazione(richiesta) -> None:
    """Rifiuto di una richiesta gia' approvata: il magazzino aveva ricevuto l'avviso
    di preparare il DPI, va detto di non consegnarlo."""
    try:
        destinatari = destinatari_magazzino()
        motivo = f"\nMotivazione: {richiesta.note_gestione}" if richiesta.note_gestione else ""
        _mail(
            f"[DPI] Consegna annullata {richiesta.numero} - {richiesta.richiedente_nome}",
            _dettaglio_richiesta(richiesta)
            + "\n\nLa richiesta, gia' approvata, e' stata rifiutata: NON consegnare il DPI." + motivo,
            destinatari,
            title="Consegna DPI annullata",
        )
    except Exception:
        logger.warning("Avviso di consegna annullata DPI fallito (%s)", getattr(richiesta, "numero", "?"), exc_info=True)
