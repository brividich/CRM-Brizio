"""Firma e test dal telefono con il QR d'aula (``/corso-aperto/aula/<token>/``, senza login).

Il docente mostra il QR della sessione: chi è iscritto scrive matricola e cognome
e firma l'ingresso (poi l'uscita) solo nell'orario della lezione, ±30'. Se il
docente ha aperto il test, dallo stesso telefono si fa il test con le domande della
sessione o del corso. Nessuna email.
"""
from __future__ import annotations

from django.conf import settings
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from core.net import client_ip
from core.public_headers import risposta_pubblica_con_form

from .services import formazione_aula as aula
from .services import sessione_online as so
from .views_corso_aperto import _conta, _testo


def _sessione(token: str):
    s = aula.sessione_da_token(token)
    if s is None:
        raise Http404
    return s


COOKIE_ORE = 16  # una giornata d'aula intera: la sessione del portale scade dopo un'ora di inattività


def _chiave(sessione) -> str:
    return f"pn_aula_{sessione.pk}"


def _iscrizione(request, sessione):
    """Chi ha già firmato da questo telefono: cookie firmato, valido una giornata."""
    try:
        eid = request.get_signed_cookie(_chiave(sessione), default=None, salt="aula", max_age=COOKIE_ORE * 3600)
    except Exception:
        eid = None
    if not eid or not str(eid).isdigit():
        return None
    return sessione.iscrizioni.filter(pk=int(eid)).exclude(stato="RITIRATO").first()


def _ricorda(response, sessione, enr):
    response.set_signed_cookie(_chiave(sessione), str(enr.pk), salt="aula", max_age=COOKIE_ORE * 3600,
                               path=f"/corso-aperto/aula/{sessione.token_aula}/", secure=bool(getattr(settings, "SESSION_COOKIE_SECURE", False)), httponly=True,
                               samesite="Lax")
    return response


@require_http_methods(["GET", "POST"])
@risposta_pubblica_con_form
def firma(request, token: str):
    sessione = _sessione(token)
    lezione = aula.lezione_aperta(sessione)
    errori, esito, ricorda = [], None, None
    enr = _iscrizione(request, sessione)
    if request.method == "POST":
        if request.POST.get("sito_web"):
            raise Http404
        ip = client_ip(request) or ""
        if _conta(f"aula_firma:{sessione.pk}:{ip}", 40, 600):
            errori.append("Troppi tentativi da questo telefono: riprova tra qualche minuto.")
        elif lezione is None:
            errori.append("Adesso non c'è una lezione aperta: la firma vale da mezz'ora prima a mezz'ora dopo l'orario.")
        else:
            try:
                if request.POST.get("matricola") or not enr:
                    enr = aula.identifica(sessione, _testo(request.POST.get("matricola"), 40),
                                          _testo(request.POST.get("cognome"), 100))
                cosa, ora = aula.firma_telefono(lezione, enr, ip=ip)
                ricorda = enr
                esito = f"{'Ingresso' if cosa == 'ingresso' else 'Uscita'} firmat{'o' if cosa == 'ingresso' else 'a'} alle {ora}."
            except aula.AulaError as exc:
                errori.append(str(exc))
    presenza = None
    if enr is not None and lezione is not None:
        presenza = lezione.presenze.filter(legacy_anagrafica_id=enr.legacy_anagrafica_id).first()
    from .views import _helpers
    nome = _helpers._build_nomi_map().get(enr.legacy_anagrafica_id, "") if enr else ""
    resp = render(request, "anagrafica/corso_aperto/aula_firma.html", {
        "corso": sessione.corso, "sessione": sessione, "lezione": lezione, "errori": errori, "esito": esito,
        "enr": enr, "nome": nome, "presenza": presenza, "test_aperto": aula.test_aperto(sessione),
        "adesso": timezone.localtime(),
    })
    return _ricorda(resp, sessione, ricorda) if ricorda is not None else resp


@require_http_methods(["GET", "POST"])
@risposta_pubblica_con_form
def test(request, token: str):
    sessione = _sessione(token)
    enr = _iscrizione(request, sessione)
    if enr is None:
        return redirect("corso_aperto:aula", token=token)
    cfg = so.config(sessione)
    errori, tentativo = [], None
    if not (cfg and cfg.test_in_aula):
        errori.append("Il docente non ha ancora aperto il test.")
    domande = so.domande_valide(sessione) if not errori else []
    prog = so.avanzamento(enr)
    if not errori and (motivo := so.motivo_test_chiuso(cfg, prog, 0)):
        errori.append(motivo)
        domande = []
    if request.method == "POST" and domande:
        if request.POST.get("sito_web"):
            raise Http404
        scelte = {}
        for d in domande:
            ids = {int(x) for x in request.POST.getlist(f"q_{d.pk}") if str(x).isdigit()}
            scelte[d.pk] = ids
        try:
            tentativo = so.correggi(enr, cfg, scelte)
        except so.LezioneOnlineError as exc:
            errori.append(str(exc))
    elenco = [{"id": d.pk, "testo": d.testo, "multipla": sum(1 for o in d.opzioni.all() if o.corretta) > 1,
               "opzioni": [(o.pk, o.testo) for o in d.opzioni.all()]} for d in domande]
    return render(request, "anagrafica/corso_aperto/aula_test.html", {
        "corso": sessione.corso, "sessione": sessione, "domande": elenco, "errori": errori,
        "tentativo": tentativo, "token": token,
    })
