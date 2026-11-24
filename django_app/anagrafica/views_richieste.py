"""Richieste su mansioni e competenze: «Da fare», elenco, nuova richiesta, dettaglio e decisione.

Le pagine si aprono a chi apre «Il mio team» (stesso permesso di rotta); che cosa si vede
e che cosa si può fare lo decide ``services/richieste.py`` a ogni richiesta, lato server:
il responsabile vede il suo team, RDD e MSO ciò che devono approvare, HR e Qualità tutto,
la persona le richieste che la riguardano.
"""
from __future__ import annotations

import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.audit import log_action

from .models_richieste import RichiestaCompetenze as R
from .services import esplora_semplice, richieste as svc
from .services import mansionario_struttura as mstr

logger = logging.getLogger(__name__)
MODULE = "anagrafica"


def _int(valore) -> int | None:
    try:
        return int(valore)
    except (TypeError, ValueError):
        return None


def _notifica(ids, messaggio: str, url: str) -> None:
    """Avviso in pagina alle persone indicate (id anagrafica): chi non ha un utente non lo riceve."""
    ids = [i for i in ids if i]
    if not ids:
        return
    try:
        from core.legacy_anagrafica import fetch_anagrafica_rows
        from core.notifiche import invia_notifica

        for riga in fetch_anagrafica_rows(ids=ids):
            if riga.get("utente_id"):
                invia_notifica(int(riga["utente_id"]), "competenze_richiesta", messaggio, url)
    except Exception:
        logger.exception("Richieste: avviso non inviato")


@login_required
def da_fare(request):
    a = svc.attore(request)
    dati = svc.da_fare(a)
    return render(request, "anagrafica/pages/richieste_da_fare.html", {
        "da_approvare": dati["da_approvare"], "in_attesa": dati["in_attesa"],
        "puo_chiedere": bool(svc.tipi_ammessi(a)),
    })


@login_required
def elenco(request):
    a = svc.attore(request)
    stato = request.GET.get("stato") or ""
    qs = svc.visibili(a)
    # Le richieste di una sola mansione: ci si arriva da «Esplora la struttura».
    from .models import CompetenzaSkm

    mansione = CompetenzaSkm.objects.filter(pk=_int(request.GET.get("mansione"))).first()
    if mansione is not None:
        qs = qs.filter(mansione=mansione)
    conteggi = {chiave: qs.filter(stato=chiave).count() for chiave, _ in R.STATO_CHOICES}
    if stato in dict(R.STATO_CHOICES):
        qs = qs.filter(stato=stato)
    else:
        stato = ""
    return render(request, "anagrafica/pages/richieste_elenco.html", {
        "righe": svc.righe(qs[:300]), "stato": stato, "mansione": mansione,
        "stati": [{"chiave": c, "nome": n, "n": conteggi[c]} for c, n in R.STATO_CHOICES],
        "puo_chiedere": bool(svc.tipi_ammessi(a)),
    })


def _contesto_nuova(a, dati: dict, errore: str = "") -> dict:
    from .models import CompetenzaCatalogo

    tipi = svc.tipi_ammessi(a)
    mansioni = [{"id": m.pk, "nome": m.nome, "reparto": m.reparto_effettivo or ""} for m in mstr.mansioni()]
    mansioni.sort(key=lambda m: m["nome"].casefold())
    return {
        "tipi": [{"chiave": c, "nome": n} for c, n in R.TIPO_CHOICES if c in tipi],
        "persone": svc.persone_ammesse(a), "mansioni": mansioni,
        "competenze": list(CompetenzaCatalogo.objects.filter(attiva=True).order_by("nome").values("id", "nome")),
        "livelli": esplora_semplice.LEGENDA, "dati": dati, "errore": errore,
        "tipi_mansione": list(R.TIPI_MANSIONE), "tipi_senza_livello": list(R.TIPI_SENZA_SESSIONE),
    }


@login_required
def nuova(request):
    a = svc.attore(request)
    if not svc.tipi_ammessi(a):
        messages.error(request, "Non puoi aprire richieste: serve essere responsabile di un team, HR o MSO.")
        return redirect("anagrafica:richieste_da_fare")
    sorgente = request.POST if request.method == "POST" else request.GET
    dati = {"tipo": sorgente.get("tipo") or "", "persona": _int(sorgente.get("persona")),
            "mansione": _int(sorgente.get("mansione")), "competenza": _int(sorgente.get("competenza")),
            "livello": (sorgente.get("livello") or "").upper(), "motivazione": sorgente.get("motivazione") or ""}
    if request.method != "POST":
        if not dati["livello"]:
            dati["livello"] = "U"
        return render(request, "anagrafica/pages/richiesta_nuova.html", _contesto_nuova(a, dati))
    try:
        richiesta = svc.crea(a, tipo=dati["tipo"], persona_id=dati["persona"], mansione_id=dati["mansione"],
                             competenza_id=dati["competenza"], livello=dati["livello"], motivazione=dati["motivazione"])
    except svc.RichiestaNonValida as exc:
        return render(request, "anagrafica/pages/richiesta_nuova.html", _contesto_nuova(a, dati, str(exc)))
    url = reverse("anagrafica:richiesta", args=[richiesta.pk])
    log_action(request, "richiesta_competenze_creata", MODULE, {
        "richiesta": richiesta.codice, "tipo": richiesta.tipo, "persona": richiesta.legacy_anagrafica_id,
        "mansione": richiesta.mansione_id, "competenza": richiesta.competenza_id, "livello": richiesta.livello,
    }, oggetto=richiesta)
    sigla = svc.sigla_approva(richiesta)
    _notifica(svc.titolari(sigla) - {a.legacy_id}, f"{richiesta.codice}: richiesta da approvare ({sigla}).", url)
    messages.success(request, f"Richiesta {richiesta.codice} inviata: ora tocca a {sigla}.")
    return redirect(url)


@login_required
def dettaglio(request, pk: int):
    a = svc.attore(request)
    richiesta = get_object_or_404(R.objects.select_related("mansione", "competenza"), pk=pk)
    if not svc.puo_vedere(a, richiesta):
        raise Http404
    riga = svc.righe([richiesta])[0]
    fabbisogno = svc.fabbisogno(richiesta)
    return render(request, "anagrafica/pages/richiesta_dettaglio.html", {
        "r": richiesta, "persona": riga["persona"], "tocca_a": riga["tocca_a"], "passi": svc.passi(richiesta),
        "fabbisogno": fabbisogno, "da_formare": sum(1 for f in fabbisogno if not f["presente"]),
        "livello": esplora_semplice.livello(richiesta.livello), "legenda": esplora_semplice.LEGENDA,
        "sigla": svc.sigla_approva(richiesta), "motivo_non_decide": svc.motivo_non_decide(a, richiesta),
        "eventi": list(richiesta.eventi.all()),
    })


@login_required
@require_POST
def decidi(request, pk: int):
    a = svc.attore(request)
    richiesta = get_object_or_404(R, pk=pk)
    if not svc.puo_vedere(a, richiesta):
        raise Http404
    approva = request.POST.get("azione") == "approva"
    url = reverse("anagrafica:richiesta", args=[richiesta.pk])
    try:
        richiesta = svc.decidi(a, richiesta, approva=approva, nota=request.POST.get("nota") or "")
    except svc.RichiestaNonValida as exc:
        messages.error(request, str(exc))
        return redirect(url)
    log_action(request, "richiesta_competenze_approvata" if approva else "richiesta_competenze_respinta", MODULE, {
        "richiesta": richiesta.codice, "stato": richiesta.stato, "persona": richiesta.legacy_anagrafica_id,
    }, oggetto=richiesta)
    esito = "approvata" if approva else "respinta"
    _notifica({richiesta.richiedente_legacy_id} - {a.legacy_id}, f"{richiesta.codice}: richiesta {esito}.", url)
    messages.success(request, f"Richiesta {richiesta.codice} {esito}.")
    return redirect(url)
