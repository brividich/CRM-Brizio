"""Viste del modulo Presenti in azienda (namespace ``presenti``, montato a /presenti/).

- Lista live: la pagina ricarica da sola la tabella ogni ``AGGIORNA_LISTA`` secondi
  (HTMX), leggendo la fotografia condivisa di ``services.stato()``.
- Appello di evacuazione: fotografia dei presenti all'avvio, spunte «contato»
  condivise fra tutti quelli che contano (la lista si riallinea ogni
  ``AGGIORNA_APPELLO`` secondi e subito dopo ogni spunta).
- Uscite non timbrate: giornate chiuse con un'entrata e senza uscita.

Permessi in ``presenti.acl_bootstrap``; le viste ripetono solo il controllo fine
(uscite di tutti vs della propria squadra).
"""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from core.acl_v2 import request_has_permission_code
from core.audit import log_action

from . import guida as guida_mod
from . import impostazioni, pdf, services, solari, uscite
from .acl_bootstrap import PERM_APPELLO, PERM_IMPOSTAZIONI, PERM_USCITE, PERM_USCITE_TUTTE
from .models import Appello, AppelloSpunta

AGGIORNA_LISTA = 30  # secondi
AGGIORNA_APPELLO = 3  # secondi


def _ctx(request, corrente: str, **extra) -> dict:
    return {
        "pres_corrente": corrente,
        "pres_puo_appello": request_has_permission_code(request, PERM_APPELLO),
        "pres_puo_uscite": request_has_permission_code(request, PERM_USCITE),
        "pres_puo_impostazioni": request_has_permission_code(request, PERM_IMPOSTAZIONI),
        "appello_aperto": Appello.objects.filter(chiuso_il__isnull=True).first(),
        **extra,
    }


def _dati_lista(request) -> dict:
    s = services.stato()
    filtri = {k: (request.GET.get(k) or "").strip() for k in ("q", "reparto", "incarico")}
    righe = services.filtra(s["presenti"], **filtri)
    return {
        "stato": s,
        "righe": righe,
        "riepilogo": services.riepilogo(s["presenti"]),
        "filtri": filtri,
        "filtrato": any(filtri.values()),
        "reparti": sorted({p["reparto"] for p in s["presenti"] if p.get("reparto")}),
        "incarichi": sorted({i["nome"] for p in s["presenti"] for i in p.get("incarichi", [])}),
        "aggiorna_ogni": AGGIORNA_LISTA,
    }


@login_required
@require_GET
def home(request):
    return render(request, "presenti/home.html", _ctx(request, "home", **_dati_lista(request)))


@login_required
@require_GET
def lista_parziale(request):
    return render(request, "presenti/_lista.html", _dati_lista(request))


@login_required
@require_GET
def pdf_presenti(request):
    s = services.stato()
    contenuto = pdf.genera_pdf(s["presenti"], s["aggiornato_il"])
    resp = HttpResponse(contenuto, content_type="application/pdf")
    resp["Content-Disposition"] = f'inline; filename="Presenti_{s["aggiornato_il"]:%Y%m%d_%H%M}.pdf"'
    return resp


@login_required
@require_GET
def guida(request):
    if (request.GET.get("formato") or "") == "pdf":
        from core.guida_pdf import render_guida_pdf

        contenuto = render_guida_pdf(
            titolo=guida_mod.TITOLO, sottotitolo=guida_mod.SOTTOTITOLO, sezioni=guida_mod.SEZIONI,
            generato_da=request.user.get_username(), generato_il=timezone.localdate().strftime("%d-%m-%Y"),
        )
        resp = HttpResponse(contenuto, content_type="application/pdf")
        resp["Content-Disposition"] = 'attachment; filename="Guida_Presenti_in_azienda.pdf"'
        return resp
    return render(request, "presenti/guida.html", _ctx(
        request, "guida", sezioni=guida_mod.SEZIONI, titolo=guida_mod.TITOLO, sottotitolo=guida_mod.SOTTOTITOLO,
    ))


# ── Appello di evacuazione ────────────────────────────────────────────────────

def _nome_utente(user) -> str:
    if user is None:
        return ""
    return (user.get_full_name() or user.get_username() or "").strip()


def _dati_appello(appello: Appello) -> dict:
    spunte = {s.solari_id: s for s in appello.spunte.select_related("contato_da")}
    persone = []
    for p in appello.persone:
        s = spunte.get(p["solari_id"])
        persone.append({**p, "contato": s is not None,
                        "contato_il": timezone.localtime(s.contato_il) if s else None,
                        "contato_da": _nome_utente(s.contato_da) if s else ""})
    # Da trovare in cima: chi conta vede subito chi manca.
    persone.sort(key=lambda p: (p["contato"], p["cognome"], p["nome"]))
    contati = sum(1 for p in persone if p["contato"])
    return {
        "appello": appello,
        "persone": persone,
        "n_totale": len(persone),
        "n_contati": contati,
        "n_mancanti": len(persone) - contati,
        "percentuale": round(contati * 100 / len(persone)) if persone else 100,
        "aggiorna_ogni": AGGIORNA_APPELLO,
    }


@login_required
@require_GET
def appello(request):
    aperto = Appello.objects.filter(chiuso_il__isnull=True).first()
    ctx = {"storico": Appello.objects.filter(chiuso_il__isnull=False)[:10], "solari_ok": solari.configurato()}
    if aperto:
        ctx.update(_dati_appello(aperto))
    return render(request, "presenti/appello.html", _ctx(request, "appello", **ctx))


@login_required
@require_POST
def appello_avvia(request):
    with transaction.atomic():
        # Un solo appello aperto alla volta: se un collega l'ha appena avviato, si entra in quello.
        aperto = Appello.objects.select_for_update().filter(chiuso_il__isnull=True).first()
        if aperto is None:
            s = services.stato(forza=True)
            if s["errore"]:
                # Senza Solari si apre lo stesso dall'ultima fotografia valida, se c'è: mai bloccare un'emergenza.
                s = services.stato()
            persone = [
                {k: p.get(k) for k in ("solari_id", "legacy_id", "cognome", "nome", "matricola", "reparto",
                                       "incarichi", "entrata")}
                for p in s["presenti"]
            ]
            aperto = Appello.objects.create(
                aperto_da=request.user, persone=persone,
                esercitazione=request.POST.get("esercitazione") == "1",
                nota=(request.POST.get("nota") or "").strip()[:300],
            )
            log_action(request, "appello_avviato", "presenti",
                       {"appello": aperto.pk, "persone": len(persone), "esercitazione": aperto.esercitazione},
                       oggetto=aperto)
    return redirect("presenti:appello")


@login_required
@require_GET
def appello_parziale(request, pk: int):
    a = get_object_or_404(Appello, pk=pk)
    return render(request, "presenti/_appello_lista.html", _dati_appello(a))


@login_required
@require_POST
def appello_spunta(request, pk: int):
    a = get_object_or_404(Appello, pk=pk)
    try:
        solari_id = int(request.POST.get("solari_id") or "")
    except ValueError:
        return HttpResponseBadRequest("Persona non valida.")
    if not a.aperto:
        return render(request, "presenti/_appello_lista.html", _dati_appello(a))
    if solari_id not in {p["solari_id"] for p in a.persone}:
        return HttpResponseBadRequest("La persona non è nell'elenco dell'appello.")
    contato = request.POST.get("contato") == "1"
    if contato:
        try:
            with transaction.atomic():
                AppelloSpunta.objects.create(appello=a, solari_id=solari_id, contato_da=request.user)
        except IntegrityError:
            pass  # già spuntata da un collega nello stesso istante: va bene così
    else:
        AppelloSpunta.objects.filter(appello=a, solari_id=solari_id).delete()
    log_action(request, "appello_spunta" if contato else "appello_spunta_tolta", "presenti",
               {"appello": a.pk, "solari_id": solari_id}, oggetto=a)
    return render(request, "presenti/_appello_lista.html", _dati_appello(a))


@login_required
@require_POST
def appello_chiudi(request, pk: int):
    a = get_object_or_404(Appello, pk=pk)
    if a.aperto:
        a.chiuso_il = timezone.now()
        a.chiuso_da = request.user
        a.save(update_fields=["chiuso_il", "chiuso_da", "aggiornato_il"])
        d = _dati_appello(a)
        log_action(request, "appello_chiuso", "presenti",
                   {"appello": a.pk, "contati": d["n_contati"], "mancanti": d["n_mancanti"]}, oggetto=a)
    return redirect("presenti:appello")


@login_required
@require_GET
def appello_stampa(request, pk: int):
    a = get_object_or_404(Appello, pk=pk)
    contati = set(a.spunte.values_list("solari_id", flat=True))
    aperto_il = timezone.localtime(a.aperto_il)
    tipo = "Esercitazione di evacuazione" if a.esercitazione else "Appello di evacuazione"
    stato_txt = (f"chiuso alle {timezone.localtime(a.chiuso_il):%H:%M}" if a.chiuso_il
                 else f"in corso, stampato alle {timezone.localtime():%H:%M}")
    contenuto = pdf.genera_pdf(
        sorted(a.persone, key=lambda p: (p["cognome"], p["nome"])), timezone.localtime(),
        titolo="APPELLO DI EVACUAZIONE",
        sottotitolo=f"{tipo} del {aperto_il:%d/%m/%Y} avviato alle {aperto_il:%H:%M} · {stato_txt}",
        contati=contati,
    )
    resp = HttpResponse(contenuto, content_type="application/pdf")
    resp["Content-Disposition"] = f'inline; filename="Appello_{aperto_il:%Y%m%d_%H%M}.pdf"'
    return resp


# ── Uscite non timbrate ───────────────────────────────────────────────────────

@login_required
@require_GET
def uscite_view(request):
    try:
        giorni = max(1, min(31, int(request.GET.get("giorni") or 7)))
    except ValueError:
        giorni = 7
    oggi = timezone.localdate()
    tutte = request_has_permission_code(request, PERM_USCITE_TUTTE)
    righe, errore = [], ""
    try:
        righe = uscite.elenco(oggi - timedelta(days=giorni), oggi - timedelta(days=1))
    except solari.SolariNonConfigurato as exc:
        errore = str(exc)
    except Exception:
        errore = "Il database delle timbrature non risponde. Riprova fra qualche minuto."
    squadra: set[int] | None = None
    if not tutte:
        from anagrafica.services.capo_team import team_di
        from core.operational_roles import get_legacy_anagrafica_id

        mio = get_legacy_anagrafica_id(request.user)
        squadra = team_di(mio) if mio else set()
        righe = [r for r in righe if r.get("legacy_id") in squadra]
    from .models import AvvisoUscitaMancante

    avvisi = {(a.solari_id, a.giorno): a for a in AvvisoUscitaMancante.objects.filter(
        giorno__gte=oggi - timedelta(days=giorni))}
    for r in righe:
        r["avviso"] = avvisi.get((r["solari_id"], r["giorno"]))
    return render(request, "presenti/uscite.html", _ctx(
        request, "uscite", righe=righe, errore=errore, giorni=giorni, tutte=tutte,
        squadra_vuota=squadra is not None and not squadra,
        avviso_attivo=impostazioni.attivo("presenti_avviso_uscite_attivo"),
    ))


# ── Impostazioni ──────────────────────────────────────────────────────────────

@login_required
def impostazioni_view(request):
    from django.contrib import messages

    if request.method == "POST":
        azione = request.POST.get("azione") or "salva"
        if azione == "salva":
            for chiave in impostazioni.CAMPI:
                if chiave == "presenti_sp_ultimo_esito":
                    continue
                if chiave in ("presenti_sp_attivo", "presenti_avviso_uscite_attivo"):
                    impostazioni.scrivi(chiave, "1" if request.POST.get(chiave) == "1" else "0")
                else:
                    impostazioni.scrivi(chiave, request.POST.get(chiave, ""))
            log_action(request, "impostazioni_salvate", "presenti", {})
            messages.success(request, "Impostazioni salvate.")
        elif azione == "pubblica":
            from .tasks import pubblica_pdf

            esito = pubblica_pdf(forza=True)
            (messages.success if esito.get("ok") else messages.error)(request, esito.get("messaggio", ""))
        return redirect("presenti:impostazioni")
    return render(request, "presenti/impostazioni.html", _ctx(
        request, "impostazioni", valori=impostazioni.tutte(), solari_ok=solari.configurato(),
    ))
