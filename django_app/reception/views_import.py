"""Reception: gruppi da Excel (vedi ``reception.importa`` e ``reception.gruppi``) e allegati delle visite.

Permessi: le rotte copiano in migrazione (reception 0012) il binding di «Registra ingresso» (import,
modello, gruppo dell'invito, togli partecipante) e della scheda della visita (allegati).
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.audit import log_action
from core.net import client_ip

from . import gruppi, mail, servizi
from . import importa as imp
from .models import AllegatoVisita, CategoriaVisita, PartecipanteGruppo, Preregistrazione, Referente, Visita
from .views import _autore, _ctx, _data_ora, _elenco_referenti, _ora


def _inviti_aperti():
    return Preregistrazione.objects.filter(usata_il__isnull=True, scade_il__gte=timezone.now()).order_by("data_visita", "ora_inizio", "ospite_nome")


def _nuovo_invito(request, referenti):
    """(invito creato o None, errore) dai campi «Nuovo invito» del modulo di import."""
    dati = request.POST
    cognome, nome = dati.get("capo_cognome", "").strip()[:100], dati.get("capo_nome", "").strip()[:100]
    email = dati.get("capo_email", "").strip().lower()[:255]
    referente = referenti.filter(pk=dati.get("referente") or 0).first()
    giorno = _data_ora(dati.get("giorno", ""), "00:00")
    if not cognome or not nome or referente is None or giorno is None:
        return None, "Per il nuovo invito servono cognome e nome del capogruppo, referente e giorno."
    if email and "@" not in email:
        return None, "L'email del capogruppo non è valida."
    errore = servizi.errore_visita(giorno.date())
    if errore:
        return None, errore
    pre = servizi.crea_preregistrazione(
        ospite_nome=f"{nome} {cognome}", ospite_email=email, ospite_azienda=dati.get("capo_azienda", ""),
        referente=referente, motivo=dati.get("motivo", "Altro"), creata_da=_autore(request),
        data_visita=giorno.date(), ora_inizio=_ora(dati.get("ora_inizio")),
    )
    return pre, ""


@login_required
def importa(request):
    referenti = Referente.objects.filter(attivo=True)
    errori: list[str] = []
    dati = request.POST if request.method == "POST" else request.GET
    if request.method == "POST":
        destinazione = dati.get("destinazione", "")
        file = request.FILES.get("file")
        pre = capo = None
        errore = ""
        if file is None:
            errore = "Scegli il file Excel."
        elif destinazione == "invito":
            pre = _inviti_aperti().filter(pk=dati.get("invito") or 0).first()
            errore = "" if pre else "Scegli l'invito."
        elif destinazione == "dentro":
            capo = Visita.objects.filter(pk=dati.get("visita") or 0, stato=Visita.DENTRO).first()
            errore = "" if capo else "Scegli chi accompagna il gruppo tra chi è dentro."
        elif destinazione != "nuovo":
            errore = "Scegli a chi collegare l'elenco."
        righe = []
        if not errore:
            try:
                righe = imp.leggi_xlsx(file)
                errori = imp.controlla(righe)
                if errori:
                    raise imp.ImportNonValido("Nessuno è stato aggiunto: correggi il file e ricaricalo.", errori)
            except imp.ImportNonValido as exc:
                errore, errori = str(exc), exc.righe
        if not errore and destinazione == "nuovo":
            pre, errore = _nuovo_invito(request, referenti)
        if errore:
            messages.error(request, errore)
        else:
            try:
                esito = imp.salva_partecipanti(righe, preregistrazione=pre, visita_capo=capo,
                                               con_cartellini=dati.get("cartellini") == "1", autore=_autore(request))
            except imp.ImportNonValido as exc:
                if destinazione == "nuovo" and pre is not None:
                    pre.delete()
                messages.error(request, str(exc))
                errori = exc.righe
            else:
                if capo is not None and dati.get("allega") == "1":
                    file.seek(0)
                    imp.allega(capo, file, autore=_autore(request))
                log_action(request, "reception_import_gruppo", "reception",
                           {"invito": pre.pk if pre else None, "visita": capo.pk if capo else None,
                            "aggiunti": esito.aggiunti, "entrati": esito.entrati})
                testo = f"Aggiunte {esito.aggiunti} persone al gruppo."
                if capo is not None:
                    testo += f" Entrate adesso: {esito.entrati}."
                elif pre is not None:
                    testo += f" Entreranno con {pre.ospite_nome} (codice {pre.codice})."
                if esito.doppi:
                    testo += f" Già nel gruppo, saltati: {', '.join(esito.doppi)}."
                messages.success(request, testo)
                if destinazione == "nuovo" and pre.ospite_email:
                    try:
                        mail.invia_invito(pre)
                    except Exception:  # noqa: BLE001 - il codice resta valido, si rimanda da Inviti
                        messages.warning(request, f"La mail con il codice {pre.codice} non è partita: rimandala da Inviti.")
                if capo is not None:
                    return redirect("reception:visita_scheda", visita_id=capo.pk)
                return redirect("reception:invito_gruppo", pk=pre.pk)
    presenti = Visita.objects.select_related("ospite").filter(stato=Visita.DENTRO).exclude(creata_da="GRUPPO") \
        .order_by("ospite__cognome", "ospite__nome")
    return render(request, "reception/importa.html", _ctx(
        request, "importa", referenti_json=_elenco_referenti(), categorie=CategoriaVisita.objects.filter(attiva=True),
        inviti=_inviti_aperti()[:200], presenti=presenti, dati=dati, errori=errori,
        n_liberi=len(servizi.cartellini_liberi()), max_righe=imp.MAX_RIGHE, oggi=timezone.localdate(),
        referente_scelto=referenti.filter(pk=dati.get("referente") or 0).first(),
        destinazione=dati.get("destinazione") or ("dentro" if dati.get("visita") else "invito" if dati.get("invito") else "nuovo"),
    ))


@login_required
def importa_modello(request):
    risposta = HttpResponse(imp.modello_xlsx(),
                            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    risposta["Content-Disposition"] = 'attachment; filename="modello_import_ospiti.xlsx"'
    return risposta


@login_required
def invito_gruppo(request, pk):
    pre = get_object_or_404(Preregistrazione, pk=pk)
    return render(request, "reception/gruppo.html", _ctx(
        request, "preregistrazioni", pre=pre, partecipanti=gruppi.partecipanti_di(preregistrazione=pre),
    ))


@login_required
@require_POST
def partecipante_togli(request, pk):
    """Toglie una persona dal gruppo. Se è già dentro registra anche la sua uscita."""
    p = get_object_or_404(PartecipanteGruppo.objects.select_related("visita"), pk=pk)
    nome, visita_capo_id, pre_id = str(p), p.visita_capo_id, p.preregistrazione_id
    if p.visita_id and p.visita.stato == Visita.DENTRO:
        try:
            servizi.registra_uscita(p.visita_id, autore=_autore(request), ip=client_ip(request) or "", origine="PANNELLO")
        except servizi.OperazioneNonValida:
            pass
    p.delete()
    log_action(request, "reception_gruppo_tolto", "reception", {"partecipante": pk, "invito": pre_id, "visita": visita_capo_id})
    messages.success(request, f"{nome} tolto dal gruppo.")
    if visita_capo_id:
        return redirect("reception:visita_scheda", visita_id=visita_capo_id)
    return redirect("reception:invito_gruppo", pk=pre_id)


@login_required
@require_POST
def visita_allegati(request, visita_id):
    visita = get_object_or_404(Visita, pk=visita_id)
    ip = client_ip(request) or ""
    if request.POST.get("azione") == "elimina":
        allegato = get_object_or_404(AllegatoVisita, pk=request.POST.get("allegato") or 0, visita=visita)
        nome = allegato.nome
        imp.elimina_allegato(allegato)
        servizi._evento(visita.pk, "ALLEGATO_TOLTO", _autore(request), ip, nome=nome)
        log_action(request, "reception_allegato_tolto", "reception", {"visita": visita.pk, "nome": nome})
        messages.success(request, f"Allegato «{nome}» eliminato.")
    else:
        file = request.FILES.get("file")
        errore = imp.controlla_allegato(file)
        if errore:
            messages.error(request, errore)
        else:
            allegato = imp.allega(visita, file, autore=_autore(request))
            servizi._evento(visita.pk, "ALLEGATO", _autore(request), ip, nome=allegato.nome)
            log_action(request, "reception_allegato", "reception", {"visita": visita.pk, "allegato": allegato.pk})
            messages.success(request, f"Allegato «{allegato.nome}» aggiunto.")
    return redirect("reception:visita_scheda", visita_id=visita.pk)


@login_required
def visita_allegato(request, visita_id, allegato_id):
    allegato = get_object_or_404(AllegatoVisita, pk=allegato_id, visita_id=visita_id)
    if not allegato.file:
        raise Http404
    log_action(request, "reception_allegato_scaricato", "reception", {"visita": visita_id, "allegato": allegato.pk})
    return FileResponse(allegato.file.open("rb"), as_attachment=True, filename=allegato.nome)
