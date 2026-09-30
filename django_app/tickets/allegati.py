"""Allegati ticket caricati sul campo e validazione del team gestore.

Caso d'uso: il tecnico esterno consegna il rapportino al capo reparto; chi ha il
foglio scansiona il QR sulla macchina (anche senza login) e fotografa/allega il
documento al ticket aperto di quell'asset. Il file nasce ``DA_VALIDARE`` e il
team MAN lo valida o lo rifiuta dalla gestione ticket.

Un'unica funzione di caricamento serve tutte le superfici (QR pubblico, landing
QR autenticata, dettaglio ticket, API storica): stessa validazione di tipo e
dimensione, stesso audit, stessa notifica.
"""
from __future__ import annotations

import logging

from django.conf import settings
from django.db.models import Count, IntegerField, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from core.upload_mime import UploadMimeValidationError, safe_filename, validate_extension_and_mime

from .models import (
    OrigineAllegato,
    StatoTicket,
    StatoValidazioneAllegato,
    Ticket,
    TicketAllegato,
    TicketCommento,
    TicketImpostazioni,
    TipoDocumentoAllegato,
)

logger = logging.getLogger(__name__)

#: Dal QR pubblico si accettano solo foto e PDF (scansione del rapportino):
#: niente Office/zip da uno sconosciuto con in mano solo il token della macchina.
QR_ALLOWED_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png"}
QR_ALLOWED_MIMES = {"application/pdf", "image/jpeg", "image/png"}
QR_MAX_BYTES = 15 * 1024 * 1024
QR_MAX_FILES = 5

#: Stati in cui un ticket accetta ancora documenti dal campo. RISOLTO resta
#: dentro: il rapportino arriva spesso dopo la risoluzione.
STATI_CARICAMENTO = (
    StatoTicket.APERTA,
    StatoTicket.IN_CARICO,
    StatoTicket.IN_ATTESA,
    StatoTicket.RISOLTO,
)

NOTIFICA_TIPO = "ticket_allegato"


#: Tetto anti-abuso sul QR pubblico: invii per IP e per macchina in finestra.
QR_RATE_LIMIT_IP = 10
QR_RATE_LIMIT_ASSET = 30
QR_RATE_WINDOW = 600


class AllegatoError(ValueError):
    """Caricamento rifiutato: messaggio mostrabile all'utente."""


def qr_rate_limited(request, asset_id: int) -> bool:
    """True se IP o asset hanno superato il tetto di invii dal QR pubblico.

    Contatori in cache (DatabaseCache in prod). Fail-open su errore cache:
    l'upload resta comunque validato per tipo/dimensione e "da validare".
    """
    from django.core.cache import cache

    ip = ""
    remote = request.META.get("REMOTE_ADDR", "") or ""
    if remote in set(getattr(settings, "TRUSTED_PROXY_IPS", set()) or set()):
        ip = (request.META.get("HTTP_X_FORWARDED_FOR", "") or "").split(",")[0].strip()
    ip = ip or remote or "unknown"
    keys = ((f"tkt_qr_rl_ip:{ip}", QR_RATE_LIMIT_IP), (f"tkt_qr_rl_asset:{asset_id}", QR_RATE_LIMIT_ASSET))
    try:
        for key, limit in keys:
            if int(cache.get(key, 0) or 0) >= limit:
                return True
        for key, _limit in keys:
            cache.set(key, int(cache.get(key, 0) or 0) + 1, timeout=QR_RATE_WINDOW)
    except Exception:
        logger.warning("qr_rate_limited: cache non disponibile", exc_info=True)
    return False


def ticket_accetta_allegati(ticket: Ticket) -> bool:
    return ticket.stato in STATI_CARICAMENTO


def subquery_conteggio_allegati(stato: str | None = None):
    """Conteggio allegati per ticket come subquery correlata.

    Niente ``Count`` aggregato: su SQL Server il GROUP BY su tutte le colonne del
    ticket (TextField) e sulle altre subquery annotate non e' ammesso.
    """
    qs = TicketAllegato.objects.filter(ticket_id=OuterRef("pk"))
    if stato:
        qs = qs.filter(stato_validazione=stato)
    return Coalesce(
        Subquery(
            qs.order_by().values("ticket_id").annotate(n=Count("id")).values("n")[:1],
            output_field=IntegerField(),
        ),
        Value(0),
    )


def ticket_aperti_asset(asset_id: int):
    """Ticket non chiusi dell'asset, con il conteggio degli allegati per stato."""
    return (
        Ticket.objects.filter(asset_id=asset_id, stato__in=STATI_CARICAMENTO)
        .annotate(
            n_allegati=subquery_conteggio_allegati(),
            n_allegati_da_validare=subquery_conteggio_allegati(StatoValidazioneAllegato.DA_VALIDARE),
        )
        .order_by("-created_at")
    )


def carica_allegato(
    ticket: Ticket,
    file,
    *,
    caricato_da_nome: str,
    caricato_da_email: str = "",
    ditta: str = "",
    origine: str = OrigineAllegato.PORTALE,
    tipo_documento: str = "",
    descrizione: str = "",
    da_validare: bool = True,
    allowed_extensions=None,
    allowed_mimes=None,
    max_bytes: int = QR_MAX_BYTES,
) -> TicketAllegato:
    """Valida e salva un allegato. Solleva :class:`AllegatoError` se rifiutato."""
    if file is None:
        raise AllegatoError("Nessun file selezionato.")
    try:
        detected_mime = validate_extension_and_mime(
            file,
            allowed_extensions=allowed_extensions or QR_ALLOWED_EXTENSIONS,
            allowed_mimes=allowed_mimes or QR_ALLOWED_MIMES,
            max_bytes=max_bytes,
            allow_empty=False,
        )
    except UploadMimeValidationError as exc:
        raise AllegatoError(str(exc)) from exc

    nome = safe_filename(getattr(file, "name", "")) or "allegato"
    if tipo_documento not in TipoDocumentoAllegato.values:
        tipo_documento = ""
    stato = StatoValidazioneAllegato.DA_VALIDARE if da_validare else StatoValidazioneAllegato.VALIDATO
    allegato = TicketAllegato.objects.create(
        ticket=ticket,
        file=file,
        nome_originale=nome[:255],
        tipo_mime=(detected_mime or "")[:100],
        uploaded_by_nome=(caricato_da_nome or "Sconosciuto")[:200],
        uploaded_by_email=(caricato_da_email or "")[:200],
        uploaded_by_ditta=(ditta or "")[:200],
        origine=origine,
        tipo_documento=tipo_documento,
        descrizione=(descrizione or "")[:500],
        stato_validazione=stato,
    )
    return allegato


def registra_caricamento(ticket: Ticket, allegati: list[TicketAllegato]) -> None:
    """Traccia il caricamento nel ticket e avvisa il team se c'e' da validare."""
    if not allegati:
        return
    primo = allegati[0]
    chi = primo.uploaded_by_nome
    if primo.uploaded_by_ditta:
        chi = f"{chi} ({primo.uploaded_by_ditta})"
    via = " tramite QR code" if primo.origine == OrigineAllegato.QR else ""
    nomi = ", ".join(a.nome_originale for a in allegati)
    da_validare = [a for a in allegati if a.is_da_validare]
    testo = f"{chi} ha caricato {len(allegati)} allegat{'o' if len(allegati) == 1 else 'i'}{via}: {nomi}."
    if primo.descrizione:
        testo += f"\nNote: {primo.descrizione}"
    if da_validare:
        testo += "\nIn attesa di validazione del team gestore."
    TicketCommento.objects.create(
        ticket=ticket,
        autore_nome=chi[:200],
        autore_email=primo.uploaded_by_email,
        testo=testo,
        is_interno=False,
    )
    if da_validare:
        notifica_team(ticket, len(da_validare))


def notifica_team(ticket: Ticket, n: int) -> int:
    """Notifica in-app al team gestori del tipo; idempotente per ticket non letto."""
    try:
        from core.models import Notifica
        from core.notifiche import legacy_user_ids_for_email
    except Exception:  # pragma: no cover - core sempre presente
        return 0
    imp = TicketImpostazioni.objects.filter(tipo=ticket.tipo).first()
    destinatari: set[int] = set()
    for g in (imp.team_gestori if imp else []) or []:
        email = str(g.get("email") or "").strip() if isinstance(g, dict) else ""
        if email:
            try:
                destinatari.update(legacy_user_ids_for_email(email))
            except Exception:
                logger.warning("notifica allegato: email %s non risolta", email, exc_info=True)
    url = f"/tickets/gestione/{ticket.pk}/#allegati"
    messaggio = f"{ticket.numero_ticket}: {n} allegat{'o' if n == 1 else 'i'} da validare — {ticket.titolo}"[:500]
    created = 0
    for uid in destinatari:
        try:
            esistente = Notifica.objects.filter(
                legacy_user_id=uid, tipo=NOTIFICA_TIPO, url_azione=url, letta=False
            ).first()
            if esistente:
                esistente.messaggio = messaggio
                esistente.save(update_fields=["messaggio"])
                continue
            Notifica.objects.create(legacy_user_id=uid, tipo=NOTIFICA_TIPO, messaggio=messaggio, url_azione=url)
            created += 1
        except Exception:
            logger.warning("notifica allegato fallita ticket=%s uid=%s", ticket.pk, uid, exc_info=True)
    return created


def valida_allegato(allegato: TicketAllegato, *, esito: str, nome: str, email: str = "", nota: str = "") -> None:
    """Esito della validazione (VALIDATO / RIFIUTATO) con traccia nel ticket."""
    if esito not in (StatoValidazioneAllegato.VALIDATO, StatoValidazioneAllegato.RIFIUTATO):
        raise AllegatoError("Esito di validazione non valido.")
    nota = (nota or "").strip()
    if esito == StatoValidazioneAllegato.RIFIUTATO and not nota:
        raise AllegatoError("Indica il motivo del rifiuto.")
    allegato.stato_validazione = esito
    allegato.validato_da_nome = (nome or "")[:200]
    allegato.validato_at = timezone.now()
    allegato.nota_validazione = nota[:500]
    allegato.save(update_fields=["stato_validazione", "validato_da_nome", "validato_at", "nota_validazione"])
    azione = "validato" if esito == StatoValidazioneAllegato.VALIDATO else "rifiutato"
    testo = f"Allegato «{allegato.nome_originale}» {azione}."
    if nota:
        testo += f"\nNota: {nota}"
    TicketCommento.objects.create(
        ticket=allegato.ticket,
        autore_nome=(nome or "Gestore")[:200],
        autore_email=email or "",
        testo=testo,
        is_interno=False,
    )
