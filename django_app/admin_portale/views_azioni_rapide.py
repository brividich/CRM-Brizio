"""Gestione admin delle «Azioni rapide» della home.

Tre livelli, dal più generale al più specifico (``dashboard.azioni_rapide``):
predefinite per tutti, predefinite per ruolo legacy, lista della singola
persona (impostabile in blocco su più persone). Ogni persona vede comunque solo
le voci che i suoi permessi le fanno aprire: il filtro è nella home, non qui.
Pagina SSR con form POST e redirect; solo amministratori.
"""
from __future__ import annotations

from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from core.audit import log_action
from core.legacy_models import Ruolo
from core.models import UserUiPreference
from dashboard import azioni_rapide as ar

from .decorators import legacy_admin_required


def _ruoli() -> list:
    try:
        return list(Ruolo.objects.all().order_by("nome"))
    except Exception:
        return []


def _int(v) -> int | None:
    s = str(v or "").strip()
    return int(s) if s.isdigit() else None


def _standard() -> list[str]:
    from dashboard.views_home_portale import HOME_AZIONI_MAX

    return ar.standard()[:HOME_AZIONI_MAX]


def _voci(keys: list[str] | None, per_key: dict) -> list[dict]:
    return [per_key[k] for k in (keys or []) if k in per_key]


def _persone() -> list[dict]:
    User = get_user_model()
    utenti = (
        User.objects.filter(is_active=True)
        .select_related("profile", "ui_prefs")
        .order_by("last_name", "first_name", "username")
    )
    out = []
    for u in utenti:
        profilo = getattr(u, "profile", None)
        try:
            pref = u.ui_prefs
        except UserUiPreference.DoesNotExist:
            pref = None
        home = pref.home_prefs if pref and isinstance(pref.home_prefs, dict) else {}
        personali = home.get("azioni") if isinstance(home.get("azioni"), list) else None
        out.append({
            "id": u.pk,
            "nome": u.get_full_name() or u.get_username(),
            "username": u.get_username(),
            "ruolo_id": getattr(profilo, "legacy_ruolo_id", None),
            "ruolo": getattr(profilo, "legacy_ruolo", "") or "",
            "personali": personali,
            "fonte": (home.get("azioni_fonte") or ar.FONTE_UTENTE) if personali is not None else "",
        })
    return out


def _redirect(**params):
    url = reverse("admin_portale:home_azioni_rapide")
    params = {k: v for k, v in params.items() if v not in (None, "")}
    return redirect(f"{url}?{urlencode(params)}" if params else url)


def _applica_a_persone(user_ids: list[int], keys: list[str] | None) -> int:
    """keys None = torna alle predefinite (toglie la lista personale)."""
    User = get_user_model()
    n = 0
    with transaction.atomic():
        for user in User.objects.filter(pk__in=user_ids, is_active=True):
            pref, _ = UserUiPreference.objects.get_or_create(user=user)
            home = dict(pref.home_prefs) if isinstance(pref.home_prefs, dict) else {}
            if keys is None:
                if "azioni" not in home and "azioni_fonte" not in home:
                    continue
                home.pop("azioni", None)
                home.pop("azioni_fonte", None)
            else:
                home["azioni"] = list(keys)
                home["azioni_fonte"] = ar.FONTE_ADMIN
            pref.home_prefs = home
            pref.save(update_fields=["home_prefs"])
            n += 1
    return n


@legacy_admin_required
@require_http_methods(["GET", "POST"])
def home_azioni_rapide(request):
    if request.method == "POST":
        return _post(request)

    catalogo = ar.catalogo()
    per_key = {v["key"]: v for v in catalogo}
    ruoli = _ruoli()
    ruolo_sel = _int(request.GET.get("ruolo"))
    persone = _persone()
    utente_sel = _int(request.GET.get("utente"))
    persona_sel = next((p for p in persone if p["id"] == utente_sel), None)
    predefinite = ar.leggi_predefinite()
    personalizzati = ar.ruoli_personalizzati()
    nomi_ruolo = {r.id: r.nome for r in ruoli}
    ruolo_lista = ar.leggi_ruolo(ruolo_sel) if ruolo_sel else None

    # Lista di partenza dell'editor «Persone»: quella della persona scelta, se c'è.
    if persona_sel is not None:
        base_persone = persona_sel["personali"]
        if base_persone is None:
            base_persone, _, limite = ar.lista_effettiva({}, persona_sel["ruolo_id"])
            base_persone = base_persone[:limite] if limite else base_persone
    else:
        base_persone = predefinite if predefinite is not None else _standard()

    for p in persone:
        p["n_voci"] = len(p["personali"] or [])
        p["voci_label"] = ", ".join(v["label"] for v in _voci(p["personali"], per_key))

    return render(request, "admin_portale/pages/home_azioni_rapide.html", {
        "catalogo": catalogo,
        "azioni_max": ar.AZIONI_MAX,
        "predefinite": _voci(predefinite if predefinite is not None else _standard(), per_key),
        "predefinite_personalizzate": predefinite is not None,
        "ruoli": ruoli,
        "ruolo_sel": ruolo_sel,
        "ruolo_sel_nome": nomi_ruolo.get(ruolo_sel, ""),
        "ruolo_lista": _voci(ruolo_lista, per_key) if ruolo_lista is not None else _voci(
            predefinite if predefinite is not None else _standard(), per_key),
        "ruolo_personalizzato": ruolo_lista is not None,
        "ruoli_personalizzati": [
            {"id": rid, "nome": nomi_ruolo.get(rid, f"Ruolo {rid}"), "voci": _voci(ar.leggi_ruolo(rid), per_key)}
            for rid in sorted(personalizzati, key=lambda r: nomi_ruolo.get(r, "").lower())
        ],
        "persone": persone,
        "persone_personalizzate": [p for p in persone if p["personali"] is not None],
        "persona_sel": persona_sel,
        "persone_lista": _voci(base_persone, per_key),
    })


def _post(request):
    azione = request.POST.get("azione") or ""
    keys = ar.pulisci(request.POST.getlist("voce"))
    if azione == "predefinite_salva":
        ar.salva_predefinite(keys)
        log_action(request, "update", "home_azioni_rapide", {"livello": "tutti", "voci": keys})
        messages.success(request, "Azioni rapide predefinite salvate: valgono per chi non ha una lista del ruolo o personale.")
        return _redirect()
    if azione == "predefinite_standard":
        ar.salva_predefinite(None)
        log_action(request, "update", "home_azioni_rapide", {"livello": "tutti", "voci": "standard"})
        messages.success(request, "Ripristinate le azioni rapide standard del portale.")
        return _redirect()
    if azione in ("ruolo_salva", "ruolo_togli"):
        ruolo = _int(request.POST.get("ruolo"))
        if ruolo is None:
            messages.error(request, "Scegli un ruolo.")
            return _redirect()
        ar.salva_ruolo(ruolo, keys if azione == "ruolo_salva" else None)
        log_action(request, "update", "home_azioni_rapide",
                   {"livello": "ruolo", "ruolo_id": ruolo, "voci": keys if azione == "ruolo_salva" else None})
        messages.success(request, "Lista del ruolo salvata." if azione == "ruolo_salva"
                         else "Il ruolo torna alle azioni predefinite per tutti.")
        return _redirect(ruolo=ruolo)
    if azione in ("persone_applica", "persone_ripristina"):
        ids = [i for i in (_int(v) for v in request.POST.getlist("utenti")) if i is not None]
        utente = _int(request.POST.get("utente_sel"))
        if not ids:
            messages.error(request, "Seleziona almeno una persona.")
            return _redirect(utente=utente)
        n = _applica_a_persone(ids, keys if azione == "persone_applica" else None)
        log_action(request, "update", "home_azioni_rapide", {
            "livello": "persone", "utenti": ids, "voci": keys if azione == "persone_applica" else None,
        })
        if azione == "persone_applica":
            messages.success(request, f"Azioni rapide impostate per {n} persone. Ognuna può cambiarle da «⚙ Personalizza».")
        else:
            messages.success(request, f"{n} persone tornano alle azioni predefinite.")
        return _redirect(utente=utente)
    messages.error(request, "Azione non valida.")
    return _redirect()
