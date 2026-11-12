"""Gestione admin dei cataloghi della stanza «Sapere».

Un catalogo è una raccolta ordinata di voci: risorse della bacheca, guide del
Centro guide o collegamenti liberi (pagina del portale «/…» o indirizzo
http(s)). Copertina facoltativa (``core.copertine``), visibilità per ruolo
legacy (nessun ruolo = tutti). Pagine SSR con form POST e redirect; solo
amministratori (``@legacy_admin_required``).
"""
from __future__ import annotations

from django.contrib import messages
from django.db import transaction
from django.db.models import Max
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.text import slugify
from django.views.decorators.http import require_http_methods

from core import sapere
from core.audit import log_action
from core.copertine import (
    COPERTINA_ACCEPT,
    COPERTINA_MAX_MB,
    CopertinaNonValida,
    rimuovi_copertina,
    sostituisci_copertina,
)
from core.legacy_models import Ruolo
from core.models import Catalogo, CatalogoRoleAccess, CatalogoVoce, HubLink

from .decorators import legacy_admin_required
from .views_bacheca import _clean_colore


def _ruoli():
    try:
        return list(Ruolo.objects.all().order_by("nome"))
    except Exception:
        return []


def _slug_unico(titolo: str, escludi_pk=None) -> str:
    base = slugify(titolo)[:120] or "catalogo"
    slug, i = base, 2
    qs = Catalogo.objects.all()
    if escludi_pk:
        qs = qs.exclude(pk=escludi_pk)
    while qs.filter(slug=slug).exists():
        slug = f"{base}-{i}"
        i += 1
    return slug


def _salva_ruoli(catalogo: Catalogo, valori) -> None:
    CatalogoRoleAccess.objects.filter(catalogo=catalogo).delete()
    ids = {int(v) for v in valori if str(v).strip().lstrip("-").isdigit()}
    CatalogoRoleAccess.objects.bulk_create(
        [CatalogoRoleAccess(catalogo=catalogo, legacy_role_id=rid) for rid in sorted(ids)]
    )


def _applica_copertina(request, obj) -> bool:
    """Copertina dal campo «copertina» o rimozione con «rimuovi_copertina». False se l'immagine non va."""
    upload = request.FILES.get("copertina")
    try:
        if upload:
            sostituisci_copertina(obj, upload)
        elif request.POST.get("rimuovi_copertina"):
            rimuovi_copertina(obj)
    except CopertinaNonValida as exc:
        messages.error(request, str(exc))
        return False
    return True


@legacy_admin_required
@require_http_methods(["GET", "POST"])
def sapere_cataloghi(request):
    if request.method == "POST":
        titolo = (request.POST.get("titolo") or "").strip()[:120]
        if not titolo:
            messages.error(request, "Dai un titolo al catalogo.")
            return redirect("admin_portale:sapere_cataloghi")
        catalogo = Catalogo(
            titolo=titolo, slug=_slug_unico(titolo),
            descrizione=(request.POST.get("descrizione") or "").strip()[:300],
            colore=_clean_colore(request.POST.get("colore")),
            ordine=(Catalogo.objects.aggregate(m=Max("ordine"))["m"] or 0) + 10,
            created_by=request.user, updated_by=request.user,
        )
        if not _applica_copertina(request, catalogo):
            return redirect("admin_portale:sapere_cataloghi")
        with transaction.atomic():
            catalogo.save()
            _salva_ruoli(catalogo, request.POST.getlist("ruoli"))
        log_action(request, "create", "sapere_catalogo", {"catalogo_id": catalogo.pk, "titolo": titolo})
        messages.success(request, f"Catalogo «{titolo}» creato: ora aggiungi le voci.")
        return redirect("admin_portale:sapere_catalogo", pk=catalogo.pk)

    cataloghi = (Catalogo.objects.prefetch_related("role_accesses", "voci")
                 .order_by("ordine", "titolo", "id"))
    ruoli = _ruoli()
    nomi_ruoli = {r.id: r.nome for r in ruoli}
    righe = [{
        "obj": c,
        "copertina": sapere.url_copertina("catalogo", c),
        "sigla": sapere.sigla_da_titolo(c.titolo),
        "colore": c.colore or sapere.COLORE_DEFAULT,
        "ruoli": [nomi_ruoli.get(a.legacy_role_id, f"ruolo #{a.legacy_role_id}") for a in c.role_accesses.all()],
        "voci": len(c.voci.all()),
    } for c in cataloghi]
    return render(request, "admin_portale/pages/sapere_cataloghi.html", {
        "righe": righe,
        "ruoli": ruoli,
        "accept": COPERTINA_ACCEPT,
        "max_mb": COPERTINA_MAX_MB,
        "colore_default": sapere.COLORE_DEFAULT,
    })


def _sposta(qs, obj, direzione: int, campo: str = "ordine") -> None:
    """Scambia la posizione con il vicino; riscrive l'ordine 10, 20, 30…"""
    elenco = list(qs)
    i = next((n for n, o in enumerate(elenco) if o.pk == obj.pk), None)
    j = None if i is None else i + direzione
    if i is None or j < 0 or j >= len(elenco):
        return
    elenco[i], elenco[j] = elenco[j], elenco[i]
    for n, o in enumerate(elenco):
        valore = (n + 1) * 10
        if getattr(o, campo) != valore:
            type(o).objects.filter(pk=o.pk).update(**{campo: valore})


def _aggiungi_voce(request, catalogo: Catalogo) -> None:
    tipo = request.POST.get("tipo") or ""
    voce = CatalogoVoce(
        catalogo=catalogo, tipo=tipo,
        titolo=(request.POST.get("titolo") or "").strip()[:160],
        descrizione=(request.POST.get("descrizione") or "").strip()[:300],
        sigla=(request.POST.get("sigla") or "").strip()[:8],
        ordine=(catalogo.voci.aggregate(m=Max("ordine"))["m"] or 0) + 10,
    )
    if tipo == CatalogoVoce.TIPO_RISORSA:
        try:
            voce.hub_link = HubLink.objects.get(pk=int(request.POST.get("hub_link_id") or 0))
        except (HubLink.DoesNotExist, ValueError):
            messages.error(request, "Scegli la risorsa della bacheca da aggiungere.")
            return
    elif tipo == CatalogoVoce.TIPO_GUIDA:
        from core import guide_moduli

        slug = (request.POST.get("guida_slug") or "").strip()
        if guide_moduli.per_slug(slug) is None:
            messages.error(request, "Scegli la guida da aggiungere.")
            return
        voce.guida_slug = slug
    elif tipo == CatalogoVoce.TIPO_COLLEGAMENTO:
        voce.url = (request.POST.get("url") or "").strip()[:500]
        if not voce.titolo:
            messages.error(request, "Un collegamento ha bisogno di un titolo.")
            return
        if not sapere.url_collegamento_valido(voce.url):
            messages.error(request, "Indirizzo non valido: usa una pagina del portale che inizia con «/» "
                                    "oppure un indirizzo che inizia con https://.")
            return
    else:
        messages.error(request, "Tipo di voce non valido.")
        return
    if not _applica_copertina(request, voce):
        return
    voce.save()
    log_action(request, "create", "sapere_catalogo", {"catalogo_id": catalogo.pk, "voce_id": voce.pk, "tipo": tipo})
    messages.success(request, "Voce aggiunta al catalogo.")


@legacy_admin_required
@require_http_methods(["GET", "POST"])
def sapere_catalogo(request, pk: int):
    catalogo = get_object_or_404(Catalogo.objects.prefetch_related("role_accesses"), pk=pk)
    if request.method == "POST":
        azione = request.POST.get("azione") or ""
        if azione == "salva":
            titolo = (request.POST.get("titolo") or "").strip()[:120]
            if not titolo:
                messages.error(request, "Il titolo non può essere vuoto.")
                return redirect("admin_portale:sapere_catalogo", pk=pk)
            if titolo != catalogo.titolo:
                catalogo.slug = _slug_unico(titolo, escludi_pk=catalogo.pk)
            catalogo.titolo = titolo
            catalogo.descrizione = (request.POST.get("descrizione") or "").strip()[:300]
            catalogo.colore = _clean_colore(request.POST.get("colore"))
            catalogo.is_visible = bool(request.POST.get("is_visible"))
            catalogo.updated_by = request.user
            if _applica_copertina(request, catalogo):
                with transaction.atomic():
                    catalogo.save()
                    _salva_ruoli(catalogo, request.POST.getlist("ruoli"))
                log_action(request, "update", "sapere_catalogo", {"catalogo_id": catalogo.pk})
                messages.success(request, "Catalogo salvato.")
        elif azione == "elimina":
            titolo = catalogo.titolo
            for voce in catalogo.voci.all():
                rimuovi_copertina(voce)
            rimuovi_copertina(catalogo)
            catalogo.delete()
            log_action(request, "delete", "sapere_catalogo", {"catalogo_id": pk, "titolo": titolo})
            messages.success(request, f"Catalogo «{titolo}» eliminato. Le risorse della bacheca restano dove sono.")
            return redirect("admin_portale:sapere_cataloghi")
        elif azione in ("su", "giu"):
            _sposta(Catalogo.objects.order_by("ordine", "titolo", "id"), catalogo, -1 if azione == "su" else 1)
            return redirect("admin_portale:sapere_cataloghi")
        elif azione == "aggiungi_voce":
            _aggiungi_voce(request, catalogo)
        elif azione.startswith("voce_"):
            voce = get_object_or_404(CatalogoVoce, pk=request.POST.get("voce_id"), catalogo=catalogo)
            if azione == "voce_elimina":
                rimuovi_copertina(voce)
                voce.delete()
                messages.success(request, "Voce tolta dal catalogo.")
            elif azione in ("voce_su", "voce_giu"):
                _sposta(catalogo.voci.order_by("ordine", "id"), voce, -1 if azione == "voce_su" else 1)
            elif azione == "voce_copertina":
                if _applica_copertina(request, voce):
                    voce.save()
                    messages.success(request, "Copertina della voce aggiornata.")
        return redirect("admin_portale:sapere_catalogo", pk=pk)

    ident = sapere.identita(request)
    voci = []
    for voce in catalogo.voci.select_related("hub_link__category").order_by("ordine", "id"):
        sorgente, avviso, titolo = "", "", ""
        if voce.tipo == CatalogoVoce.TIPO_RISORSA:
            link = voce.hub_link
            sorgente, titolo = f"{link.category.name} · {link.title}", link.title
            if not link.is_visible:
                avviso = "Risorsa nascosta nella bacheca: nel catalogo non si vede."
        elif voce.tipo == CatalogoVoce.TIPO_GUIDA:
            from core import guide_moduli

            guida = guide_moduli.per_slug(voce.guida_slug)
            sorgente = titolo = guida["titolo"] if guida else voce.guida_slug
            if guida is None:
                avviso = "La guida non esiste più: nel catalogo non si vede."
            elif guida["solo_admin"]:
                avviso = "Guida riservata agli amministratori: gli altri non la vedono."
        else:
            sorgente = voce.url
        voci.append({
            "obj": voce,
            "sorgente": sorgente,
            "avviso": avviso,
            "titolo": voce.titolo or titolo or sorgente,
            "copertina": sapere.url_copertina("voce", voce)
                         or (sapere.url_copertina("risorsa", voce.hub_link) if voce.hub_link_id else ""),
        })
    risorse = (HubLink.objects.select_related("category")
               .order_by("category__order", "category__name", "order", "title"))
    return render(request, "admin_portale/pages/sapere_catalogo.html", {
        "catalogo": catalogo,
        "copertina": sapere.url_copertina("catalogo", catalogo),
        "colore_default": sapere.COLORE_DEFAULT,
        "ruoli": _ruoli(),
        "ruoli_scelti": {a.legacy_role_id for a in catalogo.role_accesses.all()},
        "voci": voci,
        "tipi": CatalogoVoce.TIPO_CHOICES,
        "risorse": risorse,
        "guide": sapere.guide_disponibili(ident),
        "accept": COPERTINA_ACCEPT,
        "max_mb": COPERTINA_MAX_MB,
    })
