"""Report pianificati: generazione per conto del proprietario e invio per mail.

Non c'è un secondo motore di report. La variante pianificabile di una voce
(:class:`core.report_centro.catalogo.Variante`) indica una route di export
**senza argomenti**: qui la si esegue con una richiesta interna il cui utente è
il **proprietario** della pianificazione. Così valgono, identici, i controlli
della vista (permessi, dati sanitari mostrati solo a chi può vederli…) e
l'ACL della route, come se il proprietario scaricasse il file a mano.

Ogni destinatario riceve il file solo se a sua volta può aprire la stessa
route (stessa politica del middleware); gli altri vengono saltati e
l'esecuzione risulta «Inviato in parte». Ogni invio finisce nel registro
emissioni e nell'audit.
"""
from __future__ import annotations

import calendar
import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.conf import settings
from django.urls import resolve, reverse
from django.utils import timezone

from core.report_centro import catalogo, registro

logger = logging.getLogger(__name__)

MAX_ALLEGATO_BYTE = 10 * 1024 * 1024
CONTENT_TYPE = {
    "pdf": "application/pdf",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "zip": "application/zip",
}


class GenerazioneNonRiuscita(Exception):
    """Il report non si è potuto generare (permessi, vista in errore, risposta non file)."""


@dataclass
class File:
    nome: str
    contenuto: bytes
    formato: str

    @property
    def content_type(self) -> str:
        return CONTENT_TYPE.get(self.formato, "application/octet-stream")


@dataclass
class Esito:
    esito: str
    messaggio: str
    inviati: int = 0
    esclusi: int = 0


# ---------------------------------------------------------------------------
# Calendario
# ---------------------------------------------------------------------------

def calcola_prossima(p, dopo: datetime | None = None) -> datetime:
    """Prossima esecuzione strettamente successiva a ``dopo`` (ora locale)."""
    dopo = timezone.localtime(dopo or timezone.now())
    ora = min(max(int(p.ora), 0), 23)
    if p.frequenza == p.FREQ_SETTIMANALE:
        giorno = min(max(int(p.giorno_settimana), 0), 6)
        candidato = dopo.replace(hour=ora, minute=0, second=0, microsecond=0)
        candidato += timedelta(days=(giorno - candidato.weekday()) % 7)
        if candidato <= dopo:
            candidato += timedelta(days=7)
        return candidato
    giorno = min(max(int(p.giorno_mese), 1), 28)
    anno, mese = dopo.year, dopo.month
    for _ in range(2):
        giorno_effettivo = min(giorno, calendar.monthrange(anno, mese)[1])
        candidato = dopo.replace(year=anno, month=mese, day=giorno_effettivo, hour=ora, minute=0, second=0, microsecond=0)
        if candidato > dopo:
            return candidato
        anno, mese = (anno + 1, 1) if mese == 12 else (anno, mese + 1)
    return candidato  # pragma: no cover - due mesi bastano sempre


def descrivi_frequenza(p) -> str:
    giorni = ("lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica")
    if p.frequenza == p.FREQ_SETTIMANALE:
        return f"Ogni {giorni[min(max(int(p.giorno_settimana), 0), 6)]} alle {int(p.ora):02d}:00"
    return f"Ogni mese il giorno {int(p.giorno_mese)} alle {int(p.ora):02d}:00"


# ---------------------------------------------------------------------------
# Generazione
# ---------------------------------------------------------------------------

def _host() -> str:
    for host in getattr(settings, "ALLOWED_HOSTS", []) or []:
        host = str(host).lstrip(".")
        if host and host != "*":
            return host
    return "localhost"


def _richiesta_interna(utente, path: str, parametri: dict):
    from django.contrib.messages.storage import default_storage
    from django.contrib.sessions.backends.base import SessionBase
    from django.test import RequestFactory

    from core.legacy_utils import get_legacy_user

    request = RequestFactory(HTTP_HOST=_host()).get(path, parametri)
    request.user = utente
    request.session = SessionBase()
    request._messages = default_storage(request)
    request.legacy_user = get_legacy_user(utente)
    request.resolver_match = resolve(path)
    request._report_pianificato = True
    return request


def genera(variante: catalogo.Variante, utente) -> File:
    """Esegue la route della variante per conto di ``utente`` e restituisce il file."""
    from core import audit_middleware
    from core.middleware import acl_allows_path

    if utente is None or not getattr(utente, "is_active", False):
        raise GenerazioneNonRiuscita("Il proprietario della pianificazione non esiste più o è disattivato.")
    path = reverse(variante.route)
    request = _richiesta_interna(utente, path, dict(variante.parametri))
    if not acl_allows_path(path, django_user=utente, legacy_user=request.legacy_user, request=request):
        raise GenerazioneNonRiuscita("Il proprietario non ha più accesso a questo report.")

    precedente = audit_middleware.get_current_request()
    audit_middleware._thread_local.request = request
    try:
        match = request.resolver_match
        response = match.func(request, *match.args, **match.kwargs)
        if hasattr(response, "render") and callable(response.render):
            response = response.render()
    except Exception as exc:
        logger.exception("Report pianificato: la vista %s è andata in errore", variante.route)
        raise GenerazioneNonRiuscita(f"La generazione è andata in errore ({exc.__class__.__name__}).") from exc
    finally:
        audit_middleware._thread_local.request = precedente

    if getattr(response, "status_code", 0) != 200:
        raise GenerazioneNonRiuscita(f"La pagina del report ha risposto {getattr(response, 'status_code', '?')}.")
    formato = registro.formato_risposta(response)
    if not formato:
        raise GenerazioneNonRiuscita("La pagina del report non ha restituito un file.")
    if getattr(response, "streaming", False):
        contenuto = b"".join(response.streaming_content)
    else:
        contenuto = response.content or b""
    nome = registro._nome_file(response) or f"report.{formato}"
    return File(nome=nome, contenuto=contenuto, formato=formato)


# ---------------------------------------------------------------------------
# Esecuzione
# ---------------------------------------------------------------------------

def destinatari_ammessi(p, path: str) -> tuple[list, list]:
    """Divide i destinatari tra chi può ricevere il report e chi no (senza mail o senza accesso)."""
    from core.legacy_utils import get_legacy_user
    from core.middleware import acl_allows_path

    ammessi, esclusi = [], []
    for u in p.destinatari.all().order_by("last_name", "first_name", "username"):
        email = (u.email or "").strip()
        if not u.is_active or not email:
            esclusi.append(u)
            continue
        try:
            ok = acl_allows_path(path, django_user=u, legacy_user=get_legacy_user(u))
        except Exception:
            logger.warning("Report pianificato: ACL non valutabile per l'utente %s", u.pk, exc_info=True)
            ok = False
        (ammessi if ok else esclusi).append(u)
    return ammessi, esclusi


def _invia(p, voce, variante, file: File, destinatario) -> None:
    from core.email_utils import email_facts_table, send_hub_mail

    righe = [
        ("Report", voce.nome),
        ("Contenuto", variante.etichetta),
        ("Modulo", voce.modulo_etichetta),
        ("Frequenza", descrivi_frequenza(p)),
        ("File", file.nome),
    ]
    avviso = (
        "Il file contiene dati personali: usalo solo per lavoro e non inoltrarlo fuori dall'azienda."
        if voce.dati_personali else ""
    )
    testo = (
        f"In allegato il report «{voce.nome}» ({variante.etichetta}), pianificazione «{p.nome}».\n"
        + (f"{avviso}\n" if avviso else "")
        + "Lo ricevi perché un amministratore ti ha inserito tra i destinatari nel Centro report del portale."
    )
    send_hub_mail(
        f"Report pianificato: {p.nome}",
        testo,
        [destinatario.email],
        title=voce.nome,
        email_type="Report pianificato",
        badge="Dati personali" if voce.dati_personali else "",
        body_html_fragment=email_facts_table(righe) + (f"<p><strong>{avviso}</strong></p>" if avviso else ""),
        footer_note="Per non ricevere più questo report chiedi all'amministratore del portale.",
        attachments=[(file.nome, file.contenuto, file.content_type)],
    )


def _registra_emissione(p, voce, file: File, *, inviati: int, esclusi: int, manuale: bool) -> None:
    from core.models import ReportEmissione

    proprietario = p.proprietario
    legacy_id = None
    if proprietario is not None:
        from core.legacy_utils import get_legacy_user

        legacy_id = getattr(get_legacy_user(proprietario), "id", None)
    ReportEmissione.objects.create(
        legacy_user_id=legacy_id,
        utente_display=f"Pianificazione «{p.nome}»"[:200],
        report_chiave=voce.chiave,
        modulo=voce.modulo,
        titolo=voce.nome,
        route_name=f"pianificazione:{p.pk}",
        formato=file.formato if file.formato in dict(ReportEmissione.FORMATO_CHOICES) else "altro",
        nome_file=file.nome[:255],
        dimensione_byte=len(file.contenuto),
        sha256=hashlib.sha256(file.contenuto).hexdigest(),
        parametri={
            "pianificazione": p.pk,
            "variante": p.variante,
            "destinatari": inviati,
            "esclusi": esclusi,
            "avvio": "manuale" if manuale else "automatico",
        },
        dati_personali=bool(voce.dati_personali),
    )


def esegui(p, *, manuale: bool = False, adesso: datetime | None = None) -> Esito:
    """Genera e invia una pianificazione; aggiorna esito e prossima esecuzione."""
    adesso = adesso or timezone.now()
    voce = catalogo.voce_per_chiave(p.voce_chiave)
    variante = voce.variante(p.variante) if voce else None
    esito: Esito
    if variante is None:
        esito = Esito(p.ESITO_ERRORE, "Il report o la variante non esistono più nel catalogo.")
    else:
        try:
            file = genera(variante, p.proprietario)
            if len(file.contenuto) > MAX_ALLEGATO_BYTE:
                raise GenerazioneNonRiuscita("Il file supera i 10 MB e non può essere allegato.")
            ammessi, esclusi = destinatari_ammessi(p, reverse(variante.route))
            if not ammessi:
                raise GenerazioneNonRiuscita("Nessun destinatario può ricevere questo report (email mancante o senza accesso).")
            inviati, errori = 0, []
            for u in ammessi:
                try:
                    _invia(p, voce, variante, file, u)
                    inviati += 1
                except Exception as exc:
                    logger.exception("Report pianificato %s: invio a %s fallito", p.pk, u.pk)
                    errori.append(exc.__class__.__name__)
            _registra_emissione(p, voce, file, inviati=inviati, esclusi=len(esclusi) + len(errori), manuale=manuale)
            if inviati == 0:
                esito = Esito(p.ESITO_ERRORE, "Invio della mail non riuscito.", 0, len(esclusi) + len(errori))
            elif esclusi or errori:
                nomi = ", ".join((u.get_full_name() or u.username) for u in esclusi[:5])
                messaggio = f"Inviato a {inviati}; saltati {len(esclusi) + len(errori)}"
                if nomi:
                    messaggio += f" (senza email o senza accesso: {nomi})"
                esito = Esito(p.ESITO_PARZIALE, messaggio, inviati, len(esclusi) + len(errori))
            else:
                esito = Esito(p.ESITO_OK, f"Inviato a {inviati} destinatar{'io' if inviati == 1 else 'i'}.", inviati, 0)
        except GenerazioneNonRiuscita as exc:
            esito = Esito(p.ESITO_ERRORE, str(exc))

    p.ultima_esecuzione = adesso
    p.ultimo_esito = esito.esito
    p.ultimo_messaggio = esito.messaggio[:500]
    if not manuale or p.prossima_esecuzione is None:
        p.prossima_esecuzione = calcola_prossima(p, adesso)
    p.save(update_fields=["ultima_esecuzione", "ultimo_esito", "ultimo_messaggio", "prossima_esecuzione", "updated_at"])
    return esito


def esegui_scadute(adesso: datetime | None = None) -> dict:
    """Esegue le pianificazioni attive arrivate a scadenza (task orario)."""
    from core.models import ReportPianificazione

    adesso = adesso or timezone.now()
    conteggi = {"eseguite": 0, "ok": 0, "parziale": 0, "errore": 0}
    for p in ReportPianificazione.objects.filter(attiva=True, prossima_esecuzione__lte=adesso).order_by("prossima_esecuzione"):
        try:
            esito = esegui(p, adesso=adesso)
        except Exception:
            logger.exception("Report pianificato %s: esecuzione fallita", p.pk)
            continue
        conteggi["eseguite"] += 1
        conteggi[esito.esito] = conteggi.get(esito.esito, 0) + 1
    return conteggi
