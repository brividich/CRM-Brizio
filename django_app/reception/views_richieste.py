"""«Annuncia una visita» per ogni dipendente e richieste di appuntamento degli esterni.

- ``annuncia``: pagina personale (permesso ``reception.annuncia.view``, dotazione base di ogni ruolo).
  Il dipendente annuncia un ospite e diventa il suo referente; vede le richieste degli esterni
  rivolte a lui e le decide. Decide solo il referente della richiesta (controllo nella view).
- ``richieste``: elenco nel pannello della reception (stesso permesso di Accessi esterni).

Codici e QR valgono solo al chiosco dell'HUB: senza ``RECEPTION_NATIVA`` si può guardare, non creare.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from core.audit import log_action

from . import mail, sale, servizi
from .models import CategoriaVisita, Preregistrazione, Referente, RichiestaAppuntamento
from .views import _autore, _ctx, _manda_invito, _ora, prenota_sala, sala_dal_post

MAX_ANTICIPO_ANNUNCIO = 365


def _nativa() -> bool:
    return bool(getattr(settings, "RECEPTION_NATIVA", False))


def _data(valore: str):
    try:
        return datetime.strptime(valore or "", "%Y-%m-%d").date()
    except ValueError:
        return None


def _decidi(request, richiesta: RichiestaAppuntamento, *, referente: Referente | None = None) -> None:
    """Approva o rifiuta (``azione`` nel POST). Approvata: codice e QR all'esterno; rifiutata: mail di risposta."""
    azione, nota = request.POST.get("azione"), request.POST.get("nota", "")
    if azione == "approva" and not _nativa():
        messages.error(request, "Si approva dopo il passaggio della reception all'HUB: prima il codice non varrebbe al chiosco.")
        return
    try:
        if azione == "approva":
            inizio = _ora(request.POST.get("ora_inizio")) or richiesta.ora_inizio
            fine = _ora(request.POST.get("ora_fine"))
            scelta, errore = sala_dal_post(request, richiesta.data_visita, inizio, fine)
            if errore:
                messages.error(request, errore)
                return
            richiesta = servizi.approva_richiesta(richiesta.pk, autore=_autore(request), referente=referente,
                                                  ora_inizio=inizio, ora_fine=fine, sala=scelta, nota=nota)
            log_action(request, "reception_richiesta_approvata", "reception",
                       {"richiesta": richiesta.pk, "sala": getattr(scelta, "pk", None)})
            prenota_sala(request, richiesta.preregistrazione)
            if _manda_invito(request, richiesta.preregistrazione):
                messages.success(request, f"Richiesta approvata: codice inviato a {richiesta.email}.")
        elif azione == "rifiuta":
            richiesta = servizi.rifiuta_richiesta(richiesta.pk, autore=_autore(request), nota=nota)
            log_action(request, "reception_richiesta_rifiutata", "reception", {"richiesta": richiesta.pk})
            try:
                mail.invia_rifiuto(richiesta)
                messages.success(request, f"Richiesta rifiutata: risposta inviata a {richiesta.email}.")
            except Exception:  # noqa: BLE001 - la decisione resta; si avvisa chi ha deciso
                messages.warning(request, f"Richiesta rifiutata, ma la mail a {richiesta.email} non è partita: avvisalo tu.")
        else:
            messages.error(request, "Azione non riconosciuta.")
    except servizi.OperazioneNonValida as exc:
        messages.error(request, str(exc))


@login_required
def annuncia(request):
    io = servizi.referente_per_utente(request.user)
    email = (request.user.email or "").strip().lower()
    if request.method == "POST":
        dati = request.POST
        nome, ospite_email = dati.get("nome", "").strip(), dati.get("email", "").strip().lower()
        giorno, oggi = _data(dati.get("data_visita")), timezone.localdate()
        if not _nativa():
            messages.error(request, "Il servizio parte con il passaggio della reception all'HUB: per ora chiedi alla reception.")
        elif "@" not in email:
            messages.error(request, "Il tuo utente non ha un'email: chiedi alla reception di annunciare l'ospite.")
        elif not nome or "@" not in ospite_email or giorno is None:
            messages.error(request, "Nome, email dell'ospite e giorno sono obbligatori.")
        elif not oggi <= giorno <= oggi + timedelta(days=MAX_ANTICIPO_ANNUNCIO):
            messages.error(request, "Il giorno deve essere da oggi a un anno.")
        elif (scelta_sala := sala_dal_post(request, giorno, _ora(dati.get("ora_inizio")), _ora(dati.get("ora_fine"))))[1]:
            messages.error(request, scelta_sala[1])
        else:
            io = servizi.referente_per_utente(request.user, crea=True)
            pre = servizi.crea_preregistrazione(
                ospite_nome=nome, ospite_email=ospite_email, ospite_azienda=dati.get("azienda", ""), referente=io,
                motivo=dati.get("motivo", ""), creata_da=_autore(request), data_visita=giorno,
                ora_inizio=_ora(dati.get("ora_inizio")), ora_fine=_ora(dati.get("ora_fine")), sala=scelta_sala[0],
            )
            log_action(request, "reception_visita_annunciata", "reception", {"preregistrazione": pre.pk, "sala": pre.sala_id})
            prenota_sala(request, pre)
            if _manda_invito(request, pre):
                messages.success(request, f"Fatto: {pre.ospite_nome} ha ricevuto codice e QR, tu l'invito in calendario.")
            return redirect("reception:annuncia")
    mie_visite = Preregistrazione.objects.none()
    richieste = RichiestaAppuntamento.objects.none()
    if "@" in email:
        mie_visite = Preregistrazione.objects.select_related("sala").filter(referente_email__iexact=email, scade_il__gte=timezone.now()).order_by("data_visita", "ora_inizio")[:50]
        richieste = RichiestaAppuntamento.objects.filter(referente__email__iexact=email, stato=RichiestaAppuntamento.IN_ATTESA).order_by("data_visita")
    return render(request, "reception/annuncia.html", {
        "nativa": _nativa(), "ha_email": "@" in email, "referente": io, "mie_visite": mie_visite, "richieste": richieste,
        "categorie": CategoriaVisita.objects.filter(attiva=True), "oggi": timezone.localdate(),
        "sale_riunioni": list(sale.sale_attive()),
    })


@login_required
@require_POST
def annuncia_decidi(request, pk):
    richiesta = get_object_or_404(RichiestaAppuntamento, pk=pk)
    email = (request.user.email or "").strip().lower()
    if not (richiesta.referente and "@" in email and richiesta.referente.email.lower() == email):
        return HttpResponseForbidden("Puoi decidere solo le richieste rivolte a te.")
    _decidi(request, richiesta)
    return redirect("reception:annuncia")


@login_required
def richieste(request):
    limite = timezone.now() - timedelta(days=servizi.GIORNI_CONSERVAZIONE_RICHIESTE)
    return render(request, "reception/richieste.html", _ctx(
        request, "richieste", referenti=Referente.objects.filter(attivo=True),
        in_attesa=RichiestaAppuntamento.objects.select_related("referente").filter(stato=RichiestaAppuntamento.IN_ATTESA).order_by("data_visita"),
        decise=RichiestaAppuntamento.objects.select_related("referente", "preregistrazione").filter(decisa_il__gte=limite).order_by("-decisa_il")[:100],
        da_confermare=RichiestaAppuntamento.objects.filter(stato=RichiestaAppuntamento.DA_CONFERMARE).count(),
        pubbliche=bool(getattr(settings, "RECEPTION_RICHIESTE_PUBBLICHE", False)), sale_riunioni=list(sale.sale_attive()),
        link_pubblico=reverse("reception_pubblica:richiesta"),
    ))


@login_required
@require_POST
def richiesta_azione(request, pk):
    richiesta = get_object_or_404(RichiestaAppuntamento, pk=pk)
    referente = Referente.objects.filter(attivo=True, pk=request.POST.get("referente") or 0).first()
    _decidi(request, richiesta, referente=referente)
    return redirect("reception:richieste")


@require_GET
def sale_disponibilita(request):
    """Disponibilità delle sale in un giorno (portale + Outlook) per chi annuncia o invita un ospite.

    Gate: ``API_ACL_GATE_PATHS`` mappa ``/reception/api/sale/`` su «Annuncia una visita».
    Outlook si interroga con l'email di chi guarda: vede gli stessi occupato/libero del KICK-OFF.
    """
    if not request.user.is_authenticated:
        return JsonResponse({"ok": False, "reason": "Accesso richiesto."}, status=401)
    giorno = _data(request.GET.get("data"))
    if giorno is None:
        return JsonResponse({"ok": False, "reason": "Data non valida."}, status=400)
    from tasks.services.sale import disponibilita_giorno

    dati = disponibilita_giorno(giorno, organizer_email=(request.user.email or "").strip())
    return JsonResponse({"ok": True, **dati})
