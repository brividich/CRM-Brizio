"""Da «Presenti in azienda»: registrare al volo chi è già dentro (permesso reception.pannello.manage).

- ``presenti_registra``: ingresso di un fornitore (ditta + nominativo, creati se mancano) o di un
  ospite che non è passato dal chiosco. Nessuna mail al referente: la persona è già dentro.
- ``presenti_come_fornitore``: chi è entrato come visitatore diventa nominativo della sua ditta.

Funzionano solo con ``RECEPTION_NATIVA``: con il GuestPortal gli esterni si registrano lì.
"""
from __future__ import annotations

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.audit import log_action
from core.net import client_ip

from . import servizi
from .models import CategoriaVisita, Referente, Visita
from .views import _autore, _data_ora

TORNA = "presenti:home"


def _aggiorna_presenti() -> None:
    try:
        from presenti import services

        services.stato(forza=True)
    except Exception:  # noqa: BLE001 - la lista si aggiorna comunque al giro successivo
        pass


def _nativa(request) -> bool:
    if getattr(settings, "RECEPTION_NATIVA", False):
        return True
    messages.error(request, "Si registra dall'HUB dopo il passaggio della reception: per ora usa il GuestPortal.")
    return False


@login_required
@require_POST
def presenti_registra(request):
    if not _nativa(request):
        return redirect(TORNA)
    dati = request.POST
    tipo = dati.get("tipo", "ospite")
    nome, cognome = dati.get("nome", "").strip()[:100], dati.get("cognome", "").strip()[:100]
    azienda = dati.get("azienda", "").strip()[:200]
    referente = Referente.objects.filter(attivo=True, pk=dati.get("referente") or 0).first()
    if not nome or not cognome or referente is None:
        messages.error(request, "Nome, cognome e referente sono obbligatori.")
        return redirect(TORNA)
    quando = _data_ora(timezone.localdate().isoformat(), dati.get("ora", "")) if dati.get("ora") else None
    comuni = {"referente_nome": referente.nome_elenco, "referente_email": referente.email, "creata_da": "PRESENTI",
              "cartellino": dati.get("cartellino", ""), "quando": quando, "invia_mail": False}
    try:
        if tipo == "fornitore":
            ditta, contatto = servizi.ditta_e_contatto(azienda, nome, cognome)
            ospite = servizi.ospite_fornitore(nome=contatto.nome, cognome=contatto.cognome, azienda=ditta.nome)
            visita = servizi.registra_ingresso(ospite, motivo=ditta.nome, tipo=Visita.FORNITORE, ditta=ditta,
                                               contatto=contatto, **comuni)
        else:
            motivi = {c.nome for c in CategoriaVisita.objects.filter(attiva=True)}
            motivo = dati.get("motivo") if dati.get("motivo") in motivi else "Altro"
            ospite = servizi.trova_ospite_fornitore(nome, cognome, azienda) or servizi.ospite_da_dati(
                nome=nome, cognome=cognome, azienda=azienda)
            visita = servizi.registra_ingresso(ospite, motivo=motivo, **comuni)
    except servizi.GiaDentro:
        messages.error(request, f"{nome} {cognome} risulta già dentro.")
    except servizi.CartelliniFiniti:
        messages.error(request, "Il cartellino scelto non è più libero: scegline un altro o «Senza cartellino».")
    except servizi.OperazioneNonValida as exc:
        messages.error(request, str(exc))
    else:
        log_action(request, "reception_ingresso_da_presenti", "reception", {"visita": visita.pk, "tipo": visita.tipo})
        cart = "" if visita.cartellino == Visita.SENZA_CARTELLINO else f", cartellino {visita.cartellino}"
        come = f"fornitore di {visita.ditta.nome}" if visita.tipo == Visita.FORNITORE else "ospite"
        messages.success(request, f"{visita.ospite.nome_completo} registrato come {come}{cart}.")
        _aggiorna_presenti()
    return redirect(TORNA)


@login_required
@require_POST
def presenti_come_fornitore(request, visita_id: int):
    if not _nativa(request):
        return redirect(TORNA)
    try:
        visita = servizi.visita_come_fornitore(visita_id, autore=_autore(request), ip=client_ip(request) or "")
    except servizi.OperazioneNonValida as exc:
        messages.error(request, str(exc))
    else:
        log_action(request, "reception_visita_come_fornitore", "reception", {"visita": visita.pk, "ditta": visita.ditta_id})
        messages.success(request, f"{visita.ospite.nome_completo} ora è un fornitore di {visita.ditta.nome}: "
                                  "dal prossimo ingresso il chiosco lo riconosce.")
        _aggiorna_presenti()
    return redirect(TORNA)
