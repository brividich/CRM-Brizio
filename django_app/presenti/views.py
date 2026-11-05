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
    esterni = services.filtra(s.get("esterni", []), **filtri)
    return {
        "stato": s,
        "righe": righe,
        "esterni": esterni,
        "n_esterni": len(s.get("esterni", [])),
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
    contenuto = pdf.genera_pdf(s["presenti"], s["aggiornato_il"], esterni=s.get("esterni", []))
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
    persone.sort(key=lambda p: (p["contato"], (p.get("cognome") or "").lower(), (p.get("nome") or "").lower()))
    contati = sum(1 for p in persone if p["contato"])
    return {
        "n_esterni": sum(1 for p in persone if p.get("esterno")),
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
                                       "incarichi", "entrata", "verifica")}
                for p in s["presenti"]
            ]
            # Esterni dal GuestPortal (visitatori, ditte, docenti): all'appello vanno contati anche loro.
            persone += [
                {k: p.get(k) for k in ("solari_id", "esterno", "cognome", "nome", "azienda", "referente",
                                       "tipo", "badge", "entrata")}
                for p in s.get("esterni", [])
            ]
            aperto = Appello.objects.create(
                aperto_da=request.user, persone=persone,
                esercitazione=request.POST.get("esercitazione") == "1",
                nota=(request.POST.get("nota") or "").strip()[:300],
            )
            log_action(request, "appello_avviato", "presenti",
                       {"appello": aperto.pk, "persone": len(persone),
                        "esterni": sum(1 for p in persone if p.get("esterno")),
                        "esercitazione": aperto.esercitazione},
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
        # Dopo la chiusura si passa al verbale: si scrivono subito le osservazioni.
        return redirect("presenti:appello_verbale", pk=a.pk)
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
        sorted((p for p in a.persone if not p.get("esterno")), key=lambda p: (p["cognome"], p["nome"])),
        timezone.localtime(),
        esterni=[p for p in a.persone if p.get("esterno")],
        titolo="APPELLO DI EVACUAZIONE",
        sottotitolo=f"{tipo} del {aperto_il:%d/%m/%Y} avviato alle {aperto_il:%H:%M} · {stato_txt}",
        contati=contati,
    )
    resp = HttpResponse(contenuto, content_type="application/pdf")
    resp["Content-Disposition"] = f'inline; filename="Appello_{aperto_il:%Y%m%d_%H%M}.pdf"'
    return resp


# ── Verbale ───────────────────────────────────────────────────────────────────

def _puo_eliminare(request, a: Appello) -> bool:
    """Solo le esercitazioni, e solo chi l'ha avviata o l'amministratore del modulo.

    Un appello di emergenza reale non si cancella: è la traccia dell'evento.
    """
    if not a.esercitazione:
        return False
    return a.aperto_da_id == request.user.pk or request_has_permission_code(request, PERM_IMPOSTAZIONI)


def _durata(delta) -> str:
    if delta is None:
        return "—"
    secondi = max(0, int(delta.total_seconds()))
    m, s = divmod(secondi, 60)
    return f"{m} min {s:02d} s" if m < 60 else f"{m // 60} h {m % 60:02d} min"


def _dati_verbale(a: Appello) -> dict:
    """Numeri del verbale: tempi, soglie di conta, chi ha contato, chi mancava."""
    spunte = list(a.spunte.select_related("contato_da").order_by("contato_il"))
    totale = len(a.persone)
    fine = a.chiuso_il or timezone.now()
    soglie = []
    for perc in (50, 90, 100):
        serve = -(-totale * perc // 100) if totale else 0  # arrotondato per eccesso
        quando = spunte[serve - 1].contato_il if serve and len(spunte) >= serve else None
        soglie.append({"perc": perc, "serve": serve,
                       "tempo": _durata(quando - a.aperto_il) if quando else "non raggiunto"})
    per_chi: dict[str, int] = {}
    for s in spunte:
        nome = _nome_utente(s.contato_da) or "—"
        per_chi[nome] = per_chi.get(nome, 0) + 1
    contati_ids = {s.solari_id for s in spunte}
    mancanti = sorted((p for p in a.persone if p["solari_id"] not in contati_ids),
                      key=lambda p: ((p.get("cognome") or "").lower(), (p.get("nome") or "").lower()))
    return {
        "appello": a,
        "tipo": "Esercitazione di evacuazione" if a.esercitazione else "Evacuazione di emergenza",
        "aperto_il": timezone.localtime(a.aperto_il),
        "chiuso_il": timezone.localtime(a.chiuso_il) if a.chiuso_il else None,
        "aperto_da": _nome_utente(a.aperto_da) or "—",
        "chiuso_da": _nome_utente(a.chiuso_da) or "—",
        "durata": _durata(fine - a.aperto_il),
        "n_totale": totale,
        "n_dipendenti": sum(1 for p in a.persone if not p.get("esterno")),
        "n_esterni": sum(1 for p in a.persone if p.get("esterno")),
        "n_contati": len(contati_ids),
        "soglie": soglie,
        "per_chi": sorted(per_chi.items(), key=lambda kv: (-kv[1], kv[0])),
        "mancanti": mancanti,
    }


@login_required
def appello_verbale(request, pk: int):
    a = get_object_or_404(Appello, pk=pk)
    if request.method == "POST":
        a.osservazioni = (request.POST.get("osservazioni") or "").strip()[:4000]
        a.save(update_fields=["osservazioni", "aggiornato_il"])
        log_action(request, "appello_verbale_osservazioni", "presenti", {"appello": a.pk}, oggetto=a)
        from django.contrib import messages

        messages.success(request, "Osservazioni salvate nel verbale.")
        return redirect("presenti:appello_verbale", pk=a.pk)
    return render(request, "presenti/verbale.html", _ctx(
        request, "appello", **_dati_verbale(a), puo_eliminare=_puo_eliminare(request, a),
    ))


@login_required
@require_GET
def appello_verbale_pdf(request, pk: int):
    a = get_object_or_404(Appello, pk=pk)
    dati = _dati_verbale(a)
    contenuto = pdf.genera_verbale(dati)
    resp = HttpResponse(contenuto, content_type="application/pdf")
    resp["Content-Disposition"] = f'inline; filename="Verbale_evacuazione_{dati["aperto_il"]:%Y%m%d_%H%M}.pdf"'
    return resp


@login_required
@require_POST
def appello_elimina(request, pk: int):
    a = get_object_or_404(Appello, pk=pk)
    if not _puo_eliminare(request, a):
        from django.http import HttpResponseForbidden

        return HttpResponseForbidden("Si possono eliminare solo le esercitazioni, da chi le ha avviate o dall'amministratore.")
    dati = {"appello": a.pk, "aperto_il": a.aperto_il.isoformat(), "persone": len(a.persone),
            "contati": a.spunte.count(), "esercitazione": True}
    a.delete()
    log_action(request, "appello_eliminato", "presenti", dati)
    from django.contrib import messages

    messages.success(request, "Esercitazione eliminata.")
    return redirect("presenti:appello")


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
