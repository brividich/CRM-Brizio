"""Pagina «Ruoli e permessi»: persone, matrice, anteprima, registro, sistema.

Guscio HTTP sopra :mod:`core.permessi`. Ogni modifica (ruoli di una persona,
celle della matrice, proprieta' di un ruolo, interruttore del sistema) va in
AuditLog con ``modulo="permessi"``: chi, cosa, quando, e il prima/dopo.
"""
from __future__ import annotations

from django.contrib import messages
from django.db import DatabaseError, transaction
from django.db.models import Q
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.audit import log_action
from core.legacy_models import UtenteLegacy
from core.models import AccessGroup, AccessGroupMembership, AuditLog, RuoloPermessoModulo, SiteConfig
from core.permessi.cache import invalida_permessi
from core.permessi.motore import (
    PRESET_BASE,
    SITECONFIG_SISTEMA_ATTIVO,
    anteprima,
    contesto_per,
    sistema_ruoli_attivo,
)
from core.permessi.preset import PRESETS_PER_CHIAVE, applica_preset
from core.permessi.registro import AMBITI, AMBITI_LABEL, AZIONI_LABEL, AZIONI_STANDARD, moduli_registrati
from core.permessi.sync import sincronizza_ruolo, sincronizza_tutti

from .decorators import legacy_admin_required

TABS = ("persone", "matrice", "anteprima", "registro", "sistema", "guida")
VALORE_NO = "no"
MODULO_AUDIT = "permessi"


def _int(value) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _url(tab: str, **params) -> str:
    query = "&".join(f"{k}={v}" for k, v in params.items() if v not in (None, ""))
    return f"{reverse('admin_portale:ruoli_portale')}?tab={tab}" + (f"&{query}" if query else "")


def _ruoli():
    return list(AccessGroup.objects.all().order_by("-priority", "label", "id"))


def _ruoli_per_persona(ids) -> dict[int, list]:
    mappa: dict[int, list] = {}
    for m in AccessGroupMembership.objects.filter(legacy_user_id__in=list(ids)).select_related("group"):
        mappa.setdefault(int(m.legacy_user_id), []).append(m.group)
    for gruppi in mappa.values():
        gruppi.sort(key=lambda g: -int(g.priority or 0))
    return mappa


def _contesto_anteprima(legacy_user):
    """L'utente Django della persona: l'anteprima usa lo stesso motore del runtime."""
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.filter(profile__legacy_user_id=legacy_user.id).first()
    if user is None:
        return None
    return user


@legacy_admin_required
def ruoli_portale(request):
    tab = str(request.GET.get("tab") or "persone").strip().lower()
    if tab not in TABS:
        tab = "persone"
    ctx: dict = {
        "page_title": "Ruoli e permessi",
        "tab": tab,
        "sistema_attivo": sistema_ruoli_attivo(),
        "ruoli": _ruoli(),
        "azioni_label": AZIONI_LABEL,
        "ambiti_label": AMBITI_LABEL,
    }
    builder = {
        "persone": _ctx_persone,
        "matrice": _ctx_matrice,
        "anteprima": _ctx_anteprima,
        "registro": _ctx_registro,
        "sistema": _ctx_sistema,
        "guida": lambda request: {},
    }[tab]
    ctx.update(builder(request))
    return render(request, "admin_portale/pages/ruoli_portale.html", ctx)


# ── Persone ──────────────────────────────────────────────────────────────────


def _ctx_persone(request) -> dict:
    q = str(request.GET.get("q") or "").strip()
    solo_con_ruoli = request.GET.get("con_ruoli") == "1"
    persone = UtenteLegacy.objects.filter(attivo=True)
    if q:
        persone = persone.filter(Q(nome__icontains=q) | Q(email__icontains=q))
    if solo_con_ruoli:
        persone = persone.filter(id__in=AccessGroupMembership.objects.values("legacy_user_id"))
    persone = list(persone.order_by("nome", "id")[:200])
    ruoli_map = _ruoli_per_persona(p.id for p in persone)
    selezionata = None
    persona_id = _int(request.GET.get("persona"))
    if persona_id:
        selezionata = UtenteLegacy.objects.filter(id=persona_id).first()
    return {
        "q": q,
        "solo_con_ruoli": solo_con_ruoli,
        "persone": [{"persona": p, "ruoli": ruoli_map.get(int(p.id), [])} for p in persone],
        "selezionata": selezionata,
        "ruoli_selezionata": {g.id for g in _ruoli_per_persona([persona_id]).get(persona_id, [])} if persona_id else set(),
    }


@legacy_admin_required
@require_POST
def ruoli_portale_persona(request, legacy_user_id: int):
    persona = UtenteLegacy.objects.filter(id=legacy_user_id).first()
    if persona is None:
        messages.error(request, "Persona non trovata.")
        return redirect(_url("persone"))
    voluti = {i for i in (_int(v) for v in request.POST.getlist("ruoli")) if i}
    validi = set(AccessGroup.objects.filter(id__in=voluti).values_list("id", flat=True))
    attuali = set(
        AccessGroupMembership.objects.filter(legacy_user_id=persona.id).values_list("group_id", flat=True)
    )
    aggiunti, tolti = validi - attuali, attuali - validi
    nota = str(request.POST.get("nota") or "").strip()[:255]
    with transaction.atomic():
        for gruppo_id in aggiunti:
            AccessGroupMembership.objects.create(group_id=gruppo_id, legacy_user_id=persona.id, note=nota)
        AccessGroupMembership.objects.filter(legacy_user_id=persona.id, group_id__in=tolti).delete()
    if aggiunti or tolti:
        etichette = dict(AccessGroup.objects.filter(id__in=aggiunti | tolti).values_list("id", "label"))
        log_action(
            request,
            "permessi_ruoli_persona",
            MODULO_AUDIT,
            {
                "persona": persona.nome,
                "legacy_user_id": persona.id,
                "aggiunti": sorted(etichette[i] for i in aggiunti),
                "tolti": sorted(etichette[i] for i in tolti),
                "nota": nota,
            },
            oggetto_tipo="utente",
            oggetto_id=str(persona.id),
        )
        invalida_permessi()
        messages.success(request, f"Ruoli di {persona.nome} aggiornati.")
    else:
        messages.info(request, "Nessuna modifica.")
    return redirect(_url("persone", persona=persona.id, q=request.POST.get("q", "")))


# ── Matrice ──────────────────────────────────────────────────────────────────


def _ctx_matrice(request) -> dict:
    ruoli = _ruoli()
    ruolo = None
    ruolo_id = _int(request.GET.get("ruolo"))
    if ruolo_id:
        ruolo = next((r for r in ruoli if r.id == ruolo_id), None)
    if ruolo is None and ruoli:
        ruolo = ruoli[0]
    celle = {}
    if ruolo is not None:
        celle = {
            (c.modulo, c.azione): (c.ambito if c.consentito else VALORE_NO)
            for c in RuoloPermessoModulo.objects.filter(ruolo=ruolo)
        }
    righe = []
    for spec in moduli_registrati().values():
        righe.append(
            {
                "spec": spec,
                "celle": [
                    {
                        "azione": azione,
                        "label": spec.etichetta_azione(azione),
                        "valore": celle.get((spec.chiave, azione), ""),
                    }
                    for azione in AZIONI_STANDARD
                ],
                "extra": len(spec.azioni) > len(AZIONI_STANDARD),
            }
        )
    return {
        "ruolo": ruolo,
        "righe": righe,
        "azioni_header": [AZIONI_LABEL[a] for a in AZIONI_STANDARD],
        "ambiti": AMBITI,
        "preset_ruolo": PRESETS_PER_CHIAVE.get(getattr(ruolo, "preset", "")),
        "persone_ruolo": AccessGroupMembership.objects.filter(group=ruolo).count() if ruolo else 0,
    }


@legacy_admin_required
@require_POST
def ruoli_portale_matrice(request, ruolo_id: int):
    ruolo = AccessGroup.objects.filter(id=ruolo_id).first()
    if ruolo is None:
        messages.error(request, "Ruolo non trovato.")
        return redirect(_url("matrice"))
    esistenti = {(c.modulo, c.azione): c for c in RuoloPermessoModulo.objects.filter(ruolo=ruolo)}
    modifiche = []
    with transaction.atomic():
        for spec in moduli_registrati().values():
            for azione in spec.azioni:
                chiave = f"c__{spec.chiave}__{azione}"
                if chiave not in request.POST:
                    continue
                valore = str(request.POST.get(chiave) or "").strip()
                cella = esistenti.get((spec.chiave, azione))
                prima = "" if cella is None else (cella.ambito if cella.consentito else VALORE_NO)
                if valore == prima:
                    continue
                if not valore:
                    cella.delete()
                elif valore == VALORE_NO or valore in AMBITI:
                    if cella is None:
                        cella = RuoloPermessoModulo(ruolo=ruolo, modulo=spec.chiave, azione=azione)
                    cella.consentito = valore != VALORE_NO
                    cella.ambito = valore if valore in AMBITI else cella.ambito or "tutti"
                    cella.note = "modificata a mano"
                    cella.save()
                else:
                    continue
                modifiche.append({"modulo": spec.chiave, "azione": azione, "prima": prima or "-", "dopo": valore or "-"})
    if modifiche:
        esito = sincronizza_ruolo(ruolo)
        invalida_permessi()
        log_action(
            request,
            "permessi_matrice",
            MODULO_AUDIT,
            {"ruolo": ruolo.label, "modifiche": modifiche, "pagine": {"+": esito.accesi, "-": esito.spenti}},
            oggetto_tipo="ruolo",
            oggetto_id=str(ruolo.id),
        )
        messages.success(
            request,
            f"Matrice di «{ruolo.label}» salvata: {len(modifiche)} celle cambiate, "
            f"permessi di pagina +{esito.accesi} / -{esito.spenti}.",
        )
    else:
        messages.info(request, "Nessuna modifica alla matrice.")
    return redirect(_url("matrice", ruolo=ruolo.id))


@legacy_admin_required
@require_POST
def ruoli_portale_ruolo(request, ruolo_id: int | None = None):
    """Crea un ruolo o ne modifica nome, ordine, flag e stato."""
    dati = {
        "label": str(request.POST.get("label") or "").strip()[:160],
        "description": str(request.POST.get("description") or "").strip()[:500],
        "priority": _int(request.POST.get("priority")) or 100,
        "amministratore": request.POST.get("amministratore") == "1",
        "vede_tutto": request.POST.get("vede_tutto") == "1",
        "is_active": request.POST.get("is_active", "1") == "1",
    }
    if not dati["label"]:
        messages.error(request, "Il nome del ruolo e' obbligatorio.")
        return redirect(_url("matrice", ruolo=ruolo_id))
    if ruolo_id is None:
        from django.utils.text import slugify

        base = f"ruolo-{slugify(dati['label'])[:60]}" or "ruolo"
        code, n = base, 2
        while AccessGroup.objects.filter(code=code).exists():
            code, n = f"{base}-{n}", n + 1
        ruolo = AccessGroup.objects.create(code=code, **dati)
        log_action(request, "permessi_ruolo_creato", MODULO_AUDIT, {"ruolo": ruolo.label, **dati},
                   oggetto_tipo="ruolo", oggetto_id=str(ruolo.id))
        messages.success(request, f"Ruolo «{ruolo.label}» creato: compila la sua matrice.")
    else:
        ruolo = AccessGroup.objects.filter(id=ruolo_id).first()
        if ruolo is None:
            messages.error(request, "Ruolo non trovato.")
            return redirect(_url("matrice"))
        if ruolo.preset == PRESET_BASE and not dati["is_active"]:
            messages.error(request, "Il ruolo base «Dipendente» non si disattiva: e' il minimo di ogni utente.")
            return redirect(_url("matrice", ruolo=ruolo.id))
        prima = {k: getattr(ruolo, k) for k in dati}
        for chiave, valore in dati.items():
            setattr(ruolo, chiave, valore)
        ruolo.save()
        cambiati = {k: {"prima": prima[k], "dopo": dati[k]} for k in dati if prima[k] != dati[k]}
        if cambiati:
            log_action(request, "permessi_ruolo_modificato", MODULO_AUDIT, {"ruolo": ruolo.label, "campi": cambiati},
                       oggetto_tipo="ruolo", oggetto_id=str(ruolo.id))
        messages.success(request, f"Ruolo «{ruolo.label}» salvato.")
    sincronizza_ruolo(ruolo)
    invalida_permessi()
    return redirect(_url("matrice", ruolo=ruolo.id))


@legacy_admin_required
@require_POST
def ruoli_portale_preset(request):
    chiave = str(request.POST.get("preset") or "").strip()
    reset = request.POST.get("reset") == "1"
    applica_preset(chiavi=[chiave] if chiave else None, reset=reset, request=request)
    sincronizza_tutti()
    messages.success(
        request,
        ("Ruolo riportato al preset." if reset else "Preset applicati: creati ruoli e celle mancanti.")
        + " Permessi di pagina sincronizzati.",
    )
    ruolo = AccessGroup.objects.filter(preset=chiave).first() if chiave else None
    return redirect(_url("matrice", ruolo=getattr(ruolo, "id", None)))


# ── Anteprima ────────────────────────────────────────────────────────────────


def _ctx_anteprima(request) -> dict:
    persona_id = _int(request.GET.get("persona"))
    q = str(request.GET.get("q") or "").strip()
    risultati = []
    if q:
        risultati = list(
            UtenteLegacy.objects.filter(attivo=True).filter(Q(nome__icontains=q) | Q(email__icontains=q))
            .order_by("nome")[:20]
        )
    if not persona_id:
        return {"q": q, "risultati": risultati}
    persona = UtenteLegacy.objects.filter(id=persona_id).first()
    if persona is None:
        return {"q": q, "risultati": risultati, "errore": "Persona non trovata."}
    user = _contesto_anteprima(persona)
    if user is None:
        return {
            "q": q,
            "risultati": risultati,
            "persona": persona,
            "errore": "Questa persona non ha ancora fatto il primo accesso: l'anteprima si calcola dal primo login.",
        }
    righe = anteprima(user)
    ctx = contesto_per(user)
    team = []
    if ctx.team:
        team = list(UtenteLegacy.objects.filter(id__in=list(ctx.team)).order_by("nome").values_list("nome", flat=True))
    return {
        "q": q,
        "risultati": risultati,
        "persona": persona,
        "righe": righe,
        "ruoli_persona": ctx.ruoli,
        "amministratore": ctx.amministratore or ctx.superuser,
        "team": team,
    }


# ── Registro ─────────────────────────────────────────────────────────────────


_AZIONI_REGISTRO = {
    "permessi_ruoli_persona": "Ruoli di una persona",
    "permessi_matrice": "Matrice di un ruolo",
    "permessi_ruolo_creato": "Ruolo creato",
    "permessi_ruolo_modificato": "Ruolo modificato",
    "permessi_preset_applicati": "Preset applicati",
    "permessi_sincronizzati": "Permessi di pagina sincronizzati",
    "permessi_sistema_attiva": "Sistema dei ruoli ATTIVATO",
    "permessi_sistema_disattiva": "Sistema dei ruoli spento",
}


def _descrivi(voce) -> str:
    d = voce.dettaglio or {}
    if voce.azione == "permessi_ruoli_persona":
        parti = []
        if d.get("aggiunti"):
            parti.append("aggiunti: " + ", ".join(d["aggiunti"]))
        if d.get("tolti"):
            parti.append("tolti: " + ", ".join(d["tolti"]))
        return f"{d.get('persona', '')} — " + "; ".join(parti) + (f" (nota: {d['nota']})" if d.get("nota") else "")
    if voce.azione == "permessi_matrice":
        celle = [f"{m['modulo']}.{m['azione']}: {m['prima']} → {m['dopo']}" for m in d.get("modifiche", [])]
        return f"{d.get('ruolo', '')} — " + "; ".join(celle)
    if voce.azione == "permessi_ruolo_modificato":
        campi = [f"{k}: {v['prima']} → {v['dopo']}" for k, v in (d.get("campi") or {}).items()]
        return f"{d.get('ruolo', '')} — " + "; ".join(campi)
    if voce.azione == "permessi_ruolo_creato":
        return str(d.get("ruolo", ""))
    if voce.azione == "permessi_preset_applicati":
        return ", ".join(d.get("preset") or []) + (" (ripristino)" if d.get("reset") else "")
    return ""


def _ctx_registro(request) -> dict:
    try:
        voci = list(AuditLog.objects.filter(modulo=MODULO_AUDIT).order_by("-id")[:200])
    except DatabaseError:
        voci = []
    return {
        "voci": [
            {"voce": v, "titolo": _AZIONI_REGISTRO.get(v.azione, v.azione), "descrizione": _descrivi(v)}
            for v in voci
        ]
    }


# ── Sistema ──────────────────────────────────────────────────────────────────


def _ctx_sistema(request) -> dict:
    con_ruolo = (
        AccessGroupMembership.objects.filter(group__is_active=True).values("legacy_user_id").distinct().count()
    )
    attivi = UtenteLegacy.objects.filter(attivo=True).count()
    return {
        "persone_con_ruolo": con_ruolo,
        "persone_attive": attivi,
        "ruoli_senza_persone": [r for r in _ruoli() if r.preset != PRESET_BASE and not r.memberships.exists()],
        "amministratori": AccessGroupMembership.objects.filter(group__amministratore=True, group__is_active=True).count(),
    }


@legacy_admin_required
@require_POST
def ruoli_portale_sistema(request):
    azione = str(request.POST.get("azione") or "").strip()
    if azione == "sincronizza":
        esiti = sincronizza_tutti()
        log_action(request, "permessi_sincronizzati", MODULO_AUDIT,
                   {"ruoli": [{"ruolo": e.ruolo, "+": e.accesi, "-": e.spenti} for e in esiti]})
        messages.success(request, "Permessi di pagina sincronizzati con la matrice.")
    elif azione in {"attiva", "disattiva"}:
        attiva = azione == "attiva"
        if attiva and request.POST.get("conferma") != "1":
            messages.error(request, "Spunta la conferma per attivare il sistema dei ruoli.")
            return redirect(_url("sistema"))
        if attiva:
            sincronizza_tutti()
        SiteConfig.set(SITECONFIG_SISTEMA_ATTIVO, "1" if attiva else "0", "Sistema dei ruoli del portale attivo")
        invalida_permessi()
        log_action(request, "permessi_sistema_" + azione, MODULO_AUDIT, {"attivo": attiva})
        messages.success(
            request,
            "Sistema dei ruoli ATTIVO: da ora decidono solo i ruoli." if attiva
            else "Sistema dei ruoli spento: tornano a valere le regole storiche dei moduli.",
        )
    return redirect(_url("sistema"))
