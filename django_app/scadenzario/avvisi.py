"""Avvisi per mail delle scadenze generiche (come il vecchio scadenzario, più gli scaduti).

- **Avviso dell'attività** (ogni giorno): alle email dell'attività, quando mancano
  meno giorni del preavviso; si ripete ogni N giorni finché non si rinnova. Dopo
  la scadenza continua se la categoria ha «Avvisa anche dopo la scadenza».
- **Riepilogo mensile della categoria** (il 1° del mese): alle email della
  categoria, le attività scadute o in scadenza nei prossimi N giorni.

Preavviso, ripetizione e finestra del riepilogo predefiniti in ``SiteConfig``.
Ogni invio, riuscito o no, finisce in ``AvvisoInviato``.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta
from html import escape

from django.utils import timezone

logger = logging.getLogger(__name__)

KEY_PREAVVISO = "scadenzario_preavviso_giorni"
KEY_RIPETI = "scadenzario_ripeti_giorni"
KEY_RIEPILOGO = "scadenzario_riepilogo_giorni"
DEFAULT_PREAVVISO = 30
DEFAULT_RIPETI = 7
DEFAULT_RIEPILOGO = 60


def _intero(chiave: str, predefinito: int) -> int:
    from core.models import SiteConfig

    try:
        return max(1, int(SiteConfig.get(chiave, "") or predefinito))
    except (TypeError, ValueError):
        return predefinito


def impostazioni() -> dict:
    return {
        "preavviso": _intero(KEY_PREAVVISO, DEFAULT_PREAVVISO),
        "ripeti": _intero(KEY_RIPETI, DEFAULT_RIPETI),
        "riepilogo": _intero(KEY_RIEPILOGO, DEFAULT_RIEPILOGO),
    }


def _link(path: str) -> str:
    try:
        from core.accounts.portal_links import portal_link

        return portal_link(path) or path
    except Exception:
        return path


def _stato(giorni: int) -> str:
    if giorni < 0:
        return f"scaduta da {abs(giorni)} giorni"
    if giorni == 0:
        return "scade oggi"
    return f"scade tra {giorni} giorni"


def _ultimo_avviso_riuscito(scadenza):
    from .models import AvvisoInviato

    return (AvvisoInviato.objects.filter(scadenza=scadenza, tipo=AvvisoInviato.TIPO_ATTIVITA, riuscito=True)
            .order_by("-inviato_il").first())


MOTIVO_SENZA_DESTINATARI = "nessun destinatario"
MOTIVO_NON_DOVUTA = "ripetizione non ancora dovuta"


def da_avvisare(scadenza, oggi: date, conf: dict) -> tuple[bool, str]:
    if not scadenza.is_active or not scadenza.categoria.is_active or not scadenza.data_scadenza:
        return False, "senza scadenza o sospesa"
    giorni = (scadenza.data_scadenza - oggi).days
    if giorni > scadenza.preavviso_effettivo(conf["preavviso"]):
        return False, "fuori preavviso"
    if giorni < 0 and not scadenza.categoria.avvisa_dopo_scadenza:
        return False, "scaduta, la categoria non avvisa dopo la scadenza"
    if not scadenza.destinatari:
        return False, MOTIVO_SENZA_DESTINATARI
    ultimo = _ultimo_avviso_riuscito(scadenza)
    if ultimo and timezone.localdate(ultimo.inviato_il) > oggi - timedelta(days=scadenza.ripeti_effettivo(conf["ripeti"])):
        return False, MOTIVO_NON_DOVUTA
    return True, "da inviare"


def invia_avvisi_attivita(*, oggi: date | None = None, dry_run: bool = False) -> dict:
    from django.urls import reverse

    from core.email_utils import send_hub_mail

    from .collegamenti import allinea_unite
    from .models import AvvisoInviato, ScadenzaGenerica

    oggi = oggi or timezone.localdate()
    if not dry_run:
        allinea_unite()
    conf = impostazioni()
    inviati = errori = 0
    candidati = ScadenzaGenerica.objects.select_related("categoria").filter(
        is_active=True, categoria__is_active=True, data_scadenza__isnull=False,
    )
    for s in candidati:
        ok, _motivo = da_avvisare(s, oggi, conf)
        if not ok:
            continue
        giorni = (s.data_scadenza - oggi).days
        if dry_run:
            inviati += 1
            continue
        link = _link(reverse("scadenzario:scadenza_dettaglio", args=[s.pk]))
        corpo = (
            f"Attività: {s.titolo}\nCategoria: {s.categoria.nome}\n"
            + (f"Ubicazione: {s.ubicazione}\n" if s.ubicazione else "")
            + (f"Descrizione: {s.descrizione}\n" if s.descrizione else "")
            + f"Scadenza: {s.data_scadenza:%d/%m/%Y} ({_stato(giorni)})\n\n"
            + ("La data viene dal modulo collegato: aggiornala lì. Scheda: " if s.unita
               else "Quando l'attività è fatta registra il rinnovo nello Scadenzario: ")
            + link
        )
        try:
            send_hub_mail(
                f"[SCADENZA] {s.titolo} - {s.data_scadenza:%d/%m/%Y}", corpo, s.destinatari,
                title="Promemoria scadenza", email_type="Scadenzario",
                badge="Scaduta" if giorni < 0 else "In scadenza", section_label=s.categoria.nome,
            )
            AvvisoInviato.objects.create(scadenza=s, categoria=s.categoria, destinatari=", ".join(s.destinatari),
                                         riuscito=True, esito=_stato(giorni))
            inviati += 1
        except Exception as exc:
            logger.exception("scadenzario: avviso non inviato per %s", s.pk)
            AvvisoInviato.objects.create(scadenza=s, categoria=s.categoria, destinatari=", ".join(s.destinatari),
                                         riuscito=False, esito=f"Errore: {exc}"[:500])
            errori += 1
    return {"inviati": inviati, "errori": errori}


def invia_riepiloghi_categorie(*, oggi: date | None = None, dry_run: bool = False) -> dict:
    from django.urls import reverse

    from core.email_utils import send_hub_mail

    from .collegamenti import allinea_unite
    from .models import AvvisoInviato, CategoriaScadenza

    oggi = oggi or timezone.localdate()
    if not dry_run:
        allinea_unite()
    finestra = impostazioni()["riepilogo"]
    limite = oggi + timedelta(days=finestra)
    inviati = errori = 0
    for cat in CategoriaScadenza.objects.filter(is_active=True):
        righe = list(cat.scadenze.filter(is_active=True, data_scadenza__isnull=False,
                                         data_scadenza__lte=limite).order_by("data_scadenza"))
        if not righe or not cat.destinatari:
            continue
        if dry_run:
            inviati += 1
            continue
        link = _link(reverse("scadenzario:elenco") + f"?categoria={cat.pk}")
        testo = "\n".join(f"- {s.data_scadenza:%d/%m/%Y} {s.titolo} ({_stato((s.data_scadenza - oggi).days)})" for s in righe)
        html_righe = "".join(
            f"<tr><td style='padding:6px 8px;border-bottom:1px solid #e2e8f0'>{escape(s.titolo)}</td>"
            f"<td style='padding:6px 8px;border-bottom:1px solid #e2e8f0'>{escape(s.ubicazione or '')}</td>"
            f"<td style='padding:6px 8px;border-bottom:1px solid #e2e8f0;white-space:nowrap'>{s.data_scadenza:%d/%m/%Y}</td>"
            f"<td style='padding:6px 8px;border-bottom:1px solid #e2e8f0;color:{'#b91c1c' if s.data_scadenza < oggi else '#334155'}'>"
            f"{escape(_stato((s.data_scadenza - oggi).days))}</td></tr>"
            for s in righe
        )
        frammento = (
            f"<p>Attività della categoria <strong>{escape(cat.nome)}</strong> scadute o in scadenza nei prossimi {finestra} giorni.</p>"
            "<table style='width:100%;border-collapse:collapse;font-size:13px'>"
            "<tr><th align='left' style='padding:6px 8px'>Attività</th><th align='left' style='padding:6px 8px'>Ubicazione</th>"
            "<th align='left' style='padding:6px 8px'>Scadenza</th><th align='left' style='padding:6px 8px'>Stato</th></tr>"
            f"{html_righe}</table><p><a href='{escape(link)}'>Apri lo Scadenzario</a></p>"
        )
        try:
            send_hub_mail(
                f"[RIEPILOGO SCADENZE] {cat.nome} - prossimi {finestra} giorni", testo + f"\n\n{link}", cat.destinatari,
                title="Riepilogo scadenze", email_type="Scadenzario", section_label=cat.nome,
                body_html_fragment=frammento,
            )
            AvvisoInviato.objects.create(tipo=AvvisoInviato.TIPO_RIEPILOGO, categoria=cat,
                                         destinatari=", ".join(cat.destinatari), riuscito=True,
                                         esito=f"{len(righe)} attività")
            inviati += 1
        except Exception as exc:
            logger.exception("scadenzario: riepilogo non inviato per la categoria %s", cat.pk)
            AvvisoInviato.objects.create(tipo=AvvisoInviato.TIPO_RIEPILOGO, categoria=cat,
                                         destinatari=", ".join(cat.destinatari), riuscito=False,
                                         esito=f"Errore: {exc}"[:500])
            errori += 1
    return {"inviati": inviati, "errori": errori}


# Come i cron di automazioni/schedules.py (scadenzario_avvisi_attivita, scadenzario_riepilogo_mensile).
ORA_AVVISI = (7, 15)
ORA_RIEPILOGO = (8, 0)


def prossimo_invio(adesso=None) -> date:
    adesso = timezone.localtime(adesso or timezone.now())
    giorno = adesso.date()
    if (adesso.hour, adesso.minute) >= ORA_AVVISI:
        giorno += timedelta(days=1)
    return giorno


def prossimo_riepilogo(adesso=None) -> date:
    adesso = timezone.localtime(adesso or timezone.now())
    giorno = adesso.date()
    if giorno.day == 1 and (adesso.hour, adesso.minute) < ORA_RIEPILOGO:
        return giorno
    return (giorno.replace(day=1) + timedelta(days=32)).replace(day=1)


def anteprima(*, oggi: date | None = None, categorie=None) -> dict:
    """Cosa farebbe l'invio degli avvisi di quel giorno. Non invia e non scrive nulla.

    Stessa decisione di ``invia_avvisi_attivita`` (``da_avvisare``). ``categorie``
    limita alle categorie indicate (None = tutte).
    """
    from .models import ScadenzaGenerica

    oggi = oggi or prossimo_invio()
    conf = impostazioni()
    esito = {"giorno": oggi, "partono": [], "senza": [], "aspettano": []}
    qs = ScadenzaGenerica.objects.select_related("categoria").filter(
        is_active=True, categoria__is_active=True, data_scadenza__isnull=False,
    ).order_by("data_scadenza", "titolo")
    if categorie is not None:
        qs = qs.filter(categoria_id__in=categorie)
    for s in qs:
        ok, motivo = da_avvisare(s, oggi, conf)
        riga = {"scadenza": s, "stato": _stato((s.data_scadenza - oggi).days), "destinatari": s.destinatari}
        if ok:
            esito["partono"].append(riga)
        elif motivo == MOTIVO_SENZA_DESTINATARI:
            esito["senza"].append(riga)
        elif motivo == MOTIVO_NON_DOVUTA:
            ultimo = timezone.localdate(_ultimo_avviso_riuscito(s).inviato_il)
            riga["ultimo"] = ultimo
            riga["prossimo"] = ultimo + timedelta(days=s.ripeti_effettivo(conf["ripeti"]))
            esito["aspettano"].append(riga)
    return esito
