"""Prospetto dei cambiamenti (05/11/2026): confronto Oggi/Dopo prima di cambiare la struttura.

Vedere: chi vede la Struttura organizzativa. Preparare e applicare: amministrazione
dell'anagrafica. RML e costo orario solo con il permesso sui dati HR riservati, anche
nell'export; i nomi delle visite solo con il permesso visite mediche. Ogni creazione,
modifica e applicazione finisce nel registro attività.
"""
from __future__ import annotations

from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from core.audit import log_action

from .models_struttura import ProspettoModifica as M
from .models_struttura import ProspettoStruttura as P
from .services import prospetto_struttura as svc
from .services import ruoli_in_blocco
from .views_mansionario import _nega, _puo_gestire, _puo_vedere

MODULE = "anagrafica"
LIVELLI = ("I", "L", "U", "O")


def puo_costi(request) -> bool:
    from .views import _check_hr_permission

    return bool(_check_hr_permission(request))


def puo_visite(request) -> bool:
    from .views import _helpers

    return bool(_helpers._can_view_visite_mediche(request))


def _torna(prospetto, ancora=""):
    return redirect(reverse("anagrafica:prospetto", args=[prospetto.pk]) + (f"#{ancora}" if ancora else ""))


def _intero(valore):
    testo = str(valore or "").strip()
    return int(testo) if testo.isdigit() and len(testo) < 10 else None


@login_required
def prospetti(request):
    if not _puo_vedere(request):
        return _nega(request, "Non hai accesso alla struttura organizzativa.")
    return render(request, "anagrafica/pages/prospetti.html", {
        "page_title": "Prospetto dei cambiamenti",
        "bozze": P.objects.filter(stato=P.STATO_BOZZA).prefetch_related("modifiche").select_related("creato_da"),
        "storico": P.objects.exclude(stato=P.STATO_BOZZA).prefetch_related("modifiche").select_related("creato_da", "applicato_da")[:50],
        "is_admin": _puo_gestire(request),
    })


@login_required
@require_POST
def prospetto_crea(request):
    if not _puo_gestire(request):
        return _nega(request, "I prospetti li prepara l'amministrazione dell'anagrafica.")
    nome = " ".join((request.POST.get("nome") or "").split())[:150]
    if not nome:
        messages.error(request, "Dai un nome al prospetto.")
        return redirect("anagrafica:prospetti")
    p = P.objects.create(nome=nome, creato_da=request.user)
    log_action(request, "prospetto_crea", MODULE, {"prospetto": p.pk, "nome": nome}, oggetto=p)
    return _torna(p)


def _scelte(base) -> dict:
    d = base.dati
    per_area: dict = {}
    for pid in d.in_forza:
        per_area.setdefault(d.area_di.get(pid), []).append({"id": pid, "nome": base.nome_persona(pid)})
    gruppi = [{"nome": base.nome_area(a), "persone": sorted(v, key=lambda x: x["nome"].casefold())}
              for a, v in sorted(per_area.items(), key=lambda kv: (kv[0] is None, base.nome_area(kv[0]).casefold()))]
    return {
        "persone_gruppi": gruppi,
        "aree": [a for a in d.aree if a.is_active],
        "centri": [c for c in d.centri if c.is_active],
        "ruoli": sorted((r for r in base.ruoli.values() if r.is_active), key=lambda r: r.nome.casefold()),
        "mansioni": sorted((m for m in d.mansioni), key=lambda m: m.nome.casefold()),
        "mansioni_spostabili": sorted((m for m in d.mansioni if not m.is_responsabilita), key=lambda m: m.nome.casefold()),
        "modi_ruolo": list(ruoli_in_blocco.MODI.items()),
        "livelli": LIVELLI,
    }


@login_required
def prospetto(request, pk: int):
    if not _puo_vedere(request):
        return _nega(request, "Non hai accesso alla struttura organizzativa.")
    p = get_object_or_404(P.objects.select_related("creato_da", "applicato_da"), pk=pk)
    if p.stato != P.STATO_BOZZA:
        return render(request, "anagrafica/pages/prospetto_applicato.html", {
            "page_title": p.nome, "p": p, "righe": p.modifiche.all(), "fotografia": p.fotografia or {},
        })
    altro = P.objects.filter(pk=_intero(request.GET.get("con")), stato=P.STATO_BOZZA).exclude(pk=p.pk).first()
    ctx = svc.costruisci(p, altro=altro, visite=puo_visite(request))
    base = ctx.pop("base")
    ctx.update({
        "page_title": p.nome, "p": p, "altro": altro, "scelte": _scelte(base), "is_admin": _puo_gestire(request),
        "puo_costi": puo_costi(request), "oggi": timezone.localdate(), "puo_soglie": _puo_soglie(request),
        "altri_prospetti": P.objects.filter(stato=P.STATO_BOZZA).exclude(pk=p.pk),
        "ha_ostacoli": any(r["problema"] for r in ctx["righe_modifiche"]),
    })
    return render(request, "anagrafica/pages/prospetto.html", ctx)


def _puo_soglie(request) -> bool:
    """Stesso controllo della pagina Impostazioni Skill Matrix: serve solo a mostrare il link."""
    from core.permessi.impostazioni import impostazioni_o

    from .acl_bootstrap import PERM_SKM_MANAGE
    from .views.qualifiche import _check_skm_permission

    return impostazioni_o(request, "anagrafica", lambda r: _check_skm_permission(r, PERM_SKM_MANAGE))


def _bozza(request, pk):
    p = get_object_or_404(P, pk=pk)
    if not _puo_gestire(request):
        return p, _nega(request, "I prospetti li prepara l'amministrazione dell'anagrafica.")
    if p.stato != P.STATO_BOZZA:
        messages.error(request, "Questo prospetto è chiuso: preparane uno nuovo.")
        return p, _torna(p)
    return p, None


def _aggiungi(p, tipo, soggetto, destinazione, *, modo="", livello="") -> None:
    """Una riga per soggetto: una seconda scelta sullo stesso soggetto sostituisce la prima."""
    filtro = {"tipo": tipo, "soggetto_id": soggetto}
    if tipo in (M.PERSONA_RUOLO, M.PERSONA_MANSIONE):
        filtro["destinazione_id"] = destinazione
    P_righe = p.modifiche.filter(**filtro)
    riga = P_righe.first()
    if riga is None:
        M.objects.create(prospetto=p, tipo=tipo, soggetto_id=soggetto, destinazione_id=destinazione, modo=modo, livello=livello)
    else:
        riga.destinazione_id, riga.modo, riga.livello = destinazione, modo, livello
        riga.save(update_fields=["destinazione_id", "modo", "livello"])


@login_required
@require_POST
def prospetto_aggiungi(request, pk: int):
    p, negato = _bozza(request, pk)
    if negato is not None:
        return negato
    tipo = request.POST.get("tipo") or ""
    persone = [i for i in (_intero(v) for v in request.POST.getlist("persone")) if i]
    aggiunte = 0
    if tipo == M.REPARTO_CENTRO:
        area = _intero(request.POST.get("area"))
        if not area:
            messages.error(request, "Scegli il reparto.")
            return _torna(p, "aggiungi")
        _aggiungi(p, tipo, area, _intero(request.POST.get("centro")))
        aggiunte = 1
    elif tipo == M.MANSIONE_REPARTO:
        mansione, area = _intero(request.POST.get("mansione")), _intero(request.POST.get("area"))
        if not mansione or not area:
            messages.error(request, "Scegli la mansione e il reparto.")
            return _torna(p, "aggiungi")
        _aggiungi(p, tipo, mansione, area)
        aggiunte = 1
    elif tipo in (M.PERSONA_REPARTO, M.PERSONA_RUOLO, M.PERSONA_MANSIONE):
        if not persone:
            messages.error(request, "Spunta almeno una persona.")
            return _torna(p, "aggiungi")
        if tipo == M.PERSONA_REPARTO:
            area = _intero(request.POST.get("area"))
            if not area:
                messages.error(request, "Scegli il reparto di destinazione.")
                return _torna(p, "aggiungi")
            modo = M.TIENE if request.POST.get("mansioni") == M.TIENE else M.LASCIA
            for pid in persone:
                _aggiungi(p, tipo, pid, area, modo=modo)
        elif tipo == M.PERSONA_RUOLO:
            ruolo, modo = _intero(request.POST.get("ruolo")), request.POST.get("modo") or ""
            if not ruolo or modo not in ruoli_in_blocco.MODI:
                messages.error(request, "Scegli il ruolo e che cosa fare.")
                return _torna(p, "aggiungi")
            for pid in persone:
                _aggiungi(p, tipo, pid, ruolo, modo=modo)
        else:
            mansione = _intero(request.POST.get("mansione"))
            modo = M.TOGLI if request.POST.get("modo") == M.TOGLI else M.ENTRA
            livello = request.POST.get("livello") if request.POST.get("livello") in LIVELLI else "U"
            if not mansione:
                messages.error(request, "Scegli la mansione.")
                return _torna(p, "aggiungi")
            for pid in persone:
                _aggiungi(p, tipo, pid, mansione, modo=modo, livello=livello if modo == M.ENTRA else "")
        aggiunte = len(persone)
    else:
        messages.error(request, "Scegli che tipo di cambiamento provare.")
        return _torna(p, "aggiungi")
    log_action(request, "prospetto_modifica", MODULE, {"prospetto": p.pk, "tipo": tipo, "righe": aggiunte}, oggetto=p)
    messages.success(request, f"Aggiunt{'o' if aggiunte == 1 else 'i'} {aggiunte} cambiament{'o' if aggiunte == 1 else 'i'}: il confronto è aggiornato.")
    return _torna(p, "confronto")


@login_required
@require_POST
def prospetto_togli(request, pk: int, riga_id: int):
    p, negato = _bozza(request, pk)
    if negato is not None:
        return negato
    p.modifiche.filter(pk=riga_id).delete()
    log_action(request, "prospetto_modifica", MODULE, {"prospetto": p.pk, "tolta": riga_id}, oggetto=p)
    return _torna(p, "confronto")


@login_required
@require_POST
def prospetto_applica(request, pk: int):
    p, negato = _bozza(request, pk)
    if negato is not None:
        return negato
    if request.POST.get("conferma") != "1":
        messages.error(request, "Per applicare spunta la conferma.")
        return _torna(p, "applica")
    if not p.modifiche.exists():
        messages.error(request, "Il prospetto non ha cambiamenti.")
        return _torna(p)
    try:
        data = date.fromisoformat(request.POST.get("decorrenza") or "")
    except ValueError:
        messages.error(request, "Indica la decorrenza degli spostamenti.")
        return _torna(p, "applica")
    esito = svc.applica(p, data=data, user=request.user)
    log_action(request, "prospetto_applica", MODULE, {"prospetto": p.pk, "decorrenza": data.isoformat(), **esito}, oggetto=p)
    if esito.get("errori"):
        messages.warning(request, f"Applicati {esito.get('ok', 0)} cambiamenti, {esito['errori']} non riusciti: il motivo è sulla riga.")
    else:
        messages.success(request, f"Applicati {esito.get('ok', 0)} cambiamenti.")
    return _torna(p)


@login_required
@require_POST
def prospetto_annulla(request, pk: int):
    p, negato = _bozza(request, pk)
    if negato is not None:
        return negato
    p.stato = P.STATO_ANNULLATO
    p.save(update_fields=["stato", "updated_at"])
    log_action(request, "prospetto_annulla", MODULE, {"prospetto": p.pk}, oggetto=p)
    messages.success(request, "Prospetto archiviato: nulla è stato cambiato.")
    return redirect("anagrafica:prospetti")
