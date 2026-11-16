"""«Annuncia una visita» per ogni dipendente e richieste di appuntamento degli esterni.

- ``annuncia``: pagina personale (permesso ``reception.annuncia.view``, dotazione base di ogni ruolo).
  Il dipendente annuncia un ospite e diventa il suo referente; vede le richieste degli esterni
  rivolte a lui e le decide. Decide solo il referente della richiesta (controllo nella view).
- ``richieste``: elenco nel pannello della reception (stesso permesso di Accessi esterni).
- «Le tue visite» (stessa pagina): ospiti attesi, presenti e passati negli ultimi ``GIORNI_LE_TUE_VISITE``
  giorni; le visite di lavoro si collegano a un ticket IT/MAN o a un OdL (``annuncia_collega``): è il
  collegamento di Fornitori («Presenze in azienda»), vedi ``interventi``. Solo il referente della visita.

Codici e QR valgono solo al chiosco dell'HUB: senza ``RECEPTION_NATIVA`` si può guardare, non creare.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from core.audit import log_action

from . import interventi, mail, sale, servizi
from .models import CategoriaVisita, Preregistrazione, Referente, RichiestaAppuntamento, Visita
from .views import _autore, _ctx, _manda_invito, _ora, prenota_sala, sala_dal_post

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
        elif errore := servizi.errore_visita(giorno, oggi=oggi, giorno_obbligatorio=True):
            messages.error(request, errore)
        elif (scelta_sala := sala_dal_post(request, giorno, _ora(dati.get("ora_inizio")), _ora(dati.get("ora_fine"))))[1]:
            messages.error(request, scelta_sala[1])
        else:
            io = servizi.referente_per_utente(request.user, crea=True)
            ticket, odl = interventi.scelta(request, dati) if dati.get("motivo", "").strip().lower() in interventi.motivi_di_lavoro() else (None, None)
            pre = servizi.crea_preregistrazione(
                ospite_nome=nome, ospite_email=ospite_email, ospite_azienda=dati.get("azienda", ""), referente=io,
                motivo=dati.get("motivo", ""), creata_da=_autore(request), data_visita=giorno,
                ora_inizio=_ora(dati.get("ora_inizio")), ora_fine=_ora(dati.get("ora_fine")), sala=scelta_sala[0],
                ticket=ticket, ordine_lavoro=odl,
            )
            log_action(request, "reception_visita_annunciata", "reception", {
                "preregistrazione": pre.pk, "sala": pre.sala_id, "ticket": pre.ticket_id, "ordine_lavoro": pre.ordine_lavoro_id})
            prenota_sala(request, pre)
            if _manda_invito(request, pre):
                messages.success(request, f"Fatto: {pre.ospite_nome} ha ricevuto codice e QR, tu l'invito in calendario.")
            return redirect("reception:annuncia")
    mie_visite, visite, richieste = [], [], RichiestaAppuntamento.objects.none()
    if "@" in email:
        mie_visite = list(Preregistrazione.objects.select_related("sala", "ticket", "ordine_lavoro").filter(
            referente_email__iexact=email, scade_il__gte=timezone.now(), usata_il__isnull=True,
        ).order_by("data_visita", "ora_inizio")[:50])
        dal = timezone.now() - timedelta(days=GIORNI_LE_TUE_VISITE)
        visite = list(Visita.objects.select_related("ospite", "ditta").filter(
            Q(stato=Visita.DENTRO) | Q(ingresso__gte=dal), referente_email__iexact=email,
        ).order_by("-ingresso", "-pk")[:MAX_LE_TUE_VISITE])
        richieste = RichiestaAppuntamento.objects.filter(referente__email__iexact=email, stato=RichiestaAppuntamento.IN_ATTESA).order_by("data_visita")
    motivi = interventi.motivi_di_lavoro()
    legami = interventi.collegamenti([v.pk for v in visite])
    cache_proposte: dict = {}
    for riga in [*mie_visite, *visite]:
        riga.collegati = legami.get(riga.pk, []) if isinstance(riga, Visita) else []
        riga.collegabile = interventi.collegabile(riga, motivi, collegata=bool(riga.collegati))
        if riga.collegabile:
            fornitore = interventi.fornitore_della_visita(riga) if isinstance(riga, Visita) else None
            chiave = fornitore.pk if fornitore is not None else None
            if chiave not in cache_proposte:
                cache_proposte[chiave] = interventi.proposte(request, fornitore)
            riga.proposte = cache_proposte[chiave]
    return render(request, "reception/annuncia.html", {
        "nativa": _nativa(), "ha_email": "@" in email, "referente": io, "mie_visite": mie_visite, "richieste": richieste,
        "presenti": [v for v in visite if v.stato == Visita.DENTRO],
        "passate": [v for v in visite if v.stato != Visita.DENTRO], "giorni_visite": GIORNI_LE_TUE_VISITE,
        "categorie": CategoriaVisita.objects.filter(attiva=True), "motivi_lavoro": sorted(motivi), "oggi": timezone.localdate(),
        "sale_riunioni": list(sale.sale_attive()),
        "proposte_mie": interventi.proposte(request) if "@" in email and motivi else {"ticket": [], "odl": []},
    })


GIORNI_LE_TUE_VISITE = 30
MAX_LE_TUE_VISITE = 100


@login_required
@require_POST
def annuncia_collega(request, cosa, pk):
    """Il referente collega la sua visita (``cosa=visita``) o il suo ospite atteso (``cosa=invito``) a un
    ticket o a un OdL; ``azione=togli`` + ``link`` toglie un collegamento fatto da lui."""
    from fornitori import ingressi
    from fornitori.models import IngressoIntervento

    modello = {"visita": Visita, "invito": Preregistrazione}.get(cosa)
    if modello is None:
        return HttpResponseForbidden("Azione non riconosciuta.")
    riga = get_object_or_404(modello, pk=pk)
    if not interventi.e_il_referente(request.user, riga):
        return HttpResponseForbidden("Puoi collegare solo le visite di cui sei il referente.")
    torna = redirect(reverse("reception:annuncia") + "#le-tue-visite")
    azione = request.POST.get("azione")
    if cosa == "invito":
        if riga.usata_il:
            messages.error(request, "L'ospite è già entrato: collega la visita.")
            return torna
        ticket, odl = (None, None) if azione == "togli" else interventi.scelta(request, request.POST)
        if azione != "togli" and ticket is None and odl is None:
            messages.error(request, "Scegli un ticket o un OdL che puoi collegare.")
            return torna
        riga.ticket, riga.ordine_lavoro = ticket, odl
        riga.save(update_fields=["ticket", "ordine_lavoro"])
        log_action(request, "reception_invito_intervento", "reception",
                   {"preregistrazione": riga.pk, "ticket": riga.ticket_id, "ordine_lavoro": riga.ordine_lavoro_id})
        messages.success(request, "Fatto: il collegamento si crea quando l'ospite entra." if azione != "togli" else "Collegamento tolto.")
        return torna
    if azione == "togli":
        link = IngressoIntervento.objects.filter(pk=request.POST.get("link") or 0, visita_gp_id=riga.pk).first()
        if link is None or link.collegato_da_id != request.user.pk or ingressi.intervento_del_link(link).chiuso:
            return HttpResponseForbidden("Puoi togliere solo i collegamenti fatti da te, su ticket e OdL non annullati.")
        log_action(request, "ingresso_esterno_scollegato", "reception", {"visita": riga.pk, "link": link.pk})
        link.delete()
        messages.success(request, "Collegamento tolto.")
        return torna
    ticket, odl = interventi.scelta(request, request.POST)
    if ticket is None and odl is None:
        messages.error(request, "Scegli un ticket o un OdL che puoi collegare.")
        return torna
    errori = interventi.collega(riga.pk, ticket=ticket, odl=odl, utente=request.user, autore=_autore_mail(request),
                                ditta_ticket=ticket is not None and interventi.gestisce_ticket(request, ticket))
    for errore in errori:
        messages.error(request, errore)
    if not errori:
        log_action(request, "ingresso_esterno_collegato", "reception",
                   {"visita": riga.pk, "ticket": getattr(ticket, "pk", None), "ordine_lavoro": getattr(odl, "pk", None)})
        messages.success(request, "Visita collegata: la trovi anche nel riquadro «Presenze in azienda» del ticket/OdL.")
    return torna


def _autore_mail(request) -> tuple[str, str]:
    u = request.user
    return ((u.get_full_name() or u.get_username())[:200], (u.email or "")[:200])


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

    dati = disponibilita_giorno(giorno, organizer_email=(request.user.email or "").strip(),
                                sale=list(sale.sale_attive()), blocchi_extra=sale.blocchi_giorno(giorno))
    return JsonResponse({"ok": True, **dati})
