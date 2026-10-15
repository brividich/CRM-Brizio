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
from core.permessi.organigramma import provenienze_per_utenti
from core.permessi.preset import PRESETS_PER_CHIAVE, applica_preset
from core.permessi.registro import AMBITI, AMBITI_LABEL, AZIONI_LABEL, AZIONI_STANDARD, moduli_registrati
from core.permessi.sync import (
    capacita_permessi,
    codici_per_modulo,
    dati_anteprima_ruolo,
    sincronizza_ruolo,
    sincronizza_tutti,
    stato_pagine_ruolo,
)

from .decorators import legacy_admin_required

TABS = ("persone", "matrice", "modulo", "anteprima", "registro", "sistema", "guida")
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


def _data(valore):
    """(data, errata) da un campo data del form: vuoto = (None, False)."""
    testo = str(valore or "").strip()
    if not testo:
        return None, False
    from datetime import datetime

    for formato in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(testo, formato).date(), False
        except ValueError:
            continue
    return None, True


def _ruoli_per_persona(ids) -> dict[int, list]:
    """Ruoli assegnati a mano; ogni gruppo porta ``scade_il`` e ``scaduto`` dell'appartenenza."""
    from django.utils import timezone

    oggi = timezone.localdate()
    mappa: dict[int, list] = {}
    for m in AccessGroupMembership.objects.filter(legacy_user_id__in=list(ids)).select_related("group"):
        gruppo = m.group
        gruppo.scade_il = m.scade_il
        gruppo.scaduto = bool(m.scade_il and m.scade_il < oggi)
        mappa.setdefault(int(m.legacy_user_id), []).append(gruppo)
    for gruppi in mappa.values():
        gruppi.sort(key=lambda g: -int(g.priority or 0))
    return mappa


def _ruoli_da_organigramma(ids) -> dict[int, list[dict]]:
    """Per persona: ruoli del portale che arrivano dall'organigramma, con i ruoli che li danno."""
    provenienze = provenienze_per_utenti(list(ids))
    gruppi = {g.id: g for g in AccessGroup.objects.filter(id__in={g for p in provenienze.values() for g in p})}
    mappa: dict[int, list[dict]] = {}
    for persona_id, per_gruppo in provenienze.items():
        righe = [
            {"gruppo": gruppi[g], "da": ", ".join(sorted(nomi))}
            for g, nomi in per_gruppo.items()
            if g in gruppi
        ]
        righe.sort(key=lambda r: -int(r["gruppo"].priority or 0))
        mappa[persona_id] = righe
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
        "modulo": _ctx_modulo,
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
    organigramma_map = _ruoli_da_organigramma([p.id for p in persone] + ([persona_id] if persona_id else []))
    organigramma_selezionata = organigramma_map.get(persona_id, []) if persona_id else []
    ruoli_mano_selezionata = _ruoli_per_persona([persona_id]).get(persona_id, []) if persona_id else []
    scadenze = sorted({g.scade_il for g in ruoli_mano_selezionata if g.scade_il})
    return {
        "q": q,
        "solo_con_ruoli": solo_con_ruoli,
        "persone": [
            {
                "persona": p,
                "ruoli": ruoli_map.get(int(p.id), []),
                "da_organigramma": organigramma_map.get(int(p.id), []),
            }
            for p in persone
        ],
        "selezionata": selezionata,
        "ruoli_selezionata": {g.id for g in ruoli_mano_selezionata},
        "scadenza_selezionata": scadenze[0] if scadenze else None,
        "organigramma_selezionata": organigramma_selezionata,
        "ids_organigramma_selezionata": {r["gruppo"].id for r in organigramma_selezionata},
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
    scade_il, scadenza_errata = _data(request.POST.get("scade_il"))
    if scadenza_errata:
        messages.error(request, "Data di scadenza non valida: usa il formato della data (gg/mm/aaaa).")
        return redirect(_url("persone", persona=persona.id, q=request.POST.get("q", "")))
    scadenza_prima = set(
        AccessGroupMembership.objects.filter(legacy_user_id=persona.id).values_list("scade_il", flat=True)
    )
    with transaction.atomic():
        for gruppo_id in aggiunti:
            AccessGroupMembership.objects.create(
                group_id=gruppo_id, legacy_user_id=persona.id, note=nota, scade_il=scade_il
            )
        AccessGroupMembership.objects.filter(legacy_user_id=persona.id, group_id__in=tolti).delete()
        # Una sola scadenza per i ruoli a mano della persona (caso tipico: un esterno).
        cambiata_scadenza = (
            AccessGroupMembership.objects.filter(legacy_user_id=persona.id).exclude(scade_il=scade_il).update(
                scade_il=scade_il
            )
            if scade_il
            else AccessGroupMembership.objects.filter(legacy_user_id=persona.id, scade_il__isnull=False).update(
                scade_il=None
            )
        )
    if cambiata_scadenza and not (aggiunti or tolti):
        log_action(
            request,
            "permessi_scadenza_persona",
            MODULO_AUDIT,
            {
                "persona": persona.nome,
                "legacy_user_id": persona.id,
                "prima": sorted(str(d) for d in scadenza_prima if d),
                "dopo": str(scade_il) if scade_il else "",
            },
            oggetto_tipo="utente",
            oggetto_id=str(persona.id),
        )
        invalida_permessi()
        messages.success(request, f"Scadenza dei ruoli di {persona.nome} aggiornata.")
    elif aggiunti or tolti:
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
                "scade_il": str(scade_il) if scade_il else "",
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
    pagine = {}
    anteprima = None
    if ruolo is not None:
        celle = {
            (c.modulo, c.azione): (c.ambito if c.consentito else VALORE_NO)
            for c in RuoloPermessoModulo.objects.filter(ruolo=ruolo)
        }
        if not ruolo.amministratore:
            # Stato reale dei permessi di pagina: riflette anche le modifiche
            # fatte a mano dalla pagina Accessi. Solo lettura, non scrive nulla.
            capacita, per_modulo = capacita_permessi(), codici_per_modulo()
            pagine = stato_pagine_ruolo(ruolo, capacita=capacita, per_modulo=per_modulo)
            # Anteprima lato pagina: come saranno i badge dopo «Salva matrice».
            anteprima = dati_anteprima_ruolo(ruolo, capacita=capacita, per_modulo=per_modulo)
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
                        "pagine": pagine.get((spec.chiave, azione)),
                    }
                    for azione in AZIONI_STANDARD
                ],
                # Azioni proprie del modulo (dichiarate nel registro), sotto la riga.
                "extra": [
                    {
                        "azione": azione,
                        "label": spec.etichetta_azione(azione),
                        "valore": celle.get((spec.chiave, azione), ""),
                    }
                    for azione, _label in spec.azioni_extra
                ],
            }
        )
    return {
        "ruolo": ruolo,
        "righe": righe,
        "anteprima_pagine": anteprima,
        "azioni_header": [AZIONI_LABEL[a] for a in AZIONI_STANDARD],
        "ambiti": AMBITI,
        "preset_ruolo": PRESETS_PER_CHIAVE.get(getattr(ruolo, "preset", "")),
        "persone_ruolo": AccessGroupMembership.objects.filter(group=ruolo).count() if ruolo else 0,
        **_ctx_collegamento_organigramma(ruolo),
    }


def _ctx_collegamento_organigramma(ruolo) -> dict:
    """Ruoli d'organigramma per ambito, con quelli che danno il ruolo del portale spuntati."""
    if ruolo is None:
        return {"organigramma_ambiti": [], "organigramma_collegati": 0, "persone_organigramma": 0}
    from django.db.models import Count

    from anagrafica.models import RuoloOperativo
    from core.permessi.team import _assegnazioni_attive

    try:
        collegati = set(ruolo.ruoli_organigramma.values_list("id", flat=True))
        catalogo = list(
            RuoloOperativo.objects.filter(Q(is_active=True) | Q(id__in=collegati))
            .select_related("ambito")
            .order_by("ambito__ordine", "ambito__nome", "nome")
        )
        persone_per_ruolo = dict(
            _assegnazioni_attive()
            .values("ruolo_id")
            .annotate(n=Count("legacy_anagrafica_id", distinct=True))
            .order_by()
            .values_list("ruolo_id", "n")
        )
        persone_organigramma = (
            _assegnazioni_attive()
            .filter(ruolo_id__in=collegati)
            .values("legacy_anagrafica_id")
            .distinct()
            .count()
            if collegati
            else 0
        )
    except DatabaseError:
        return {"organigramma_ambiti": [], "organigramma_collegati": 0, "persone_organigramma": 0}
    ambiti: list[dict] = []
    for r in catalogo:
        etichetta = r.ambito_label
        if not ambiti or ambiti[-1]["nome"] != etichetta:
            ambiti.append({"nome": etichetta, "ruoli": []})
        ambiti[-1]["ruoli"].append(
            {"ruolo": r, "collegato": r.id in collegati, "persone": persone_per_ruolo.get(r.id, 0)}
        )
    return {
        "organigramma_ambiti": ambiti,
        "organigramma_collegati": len(collegati),
        "persone_organigramma": persone_organigramma,
    }


@legacy_admin_required
@require_POST
def ruoli_portale_organigramma(request, ruolo_id: int):
    """Collega il ruolo del portale ai ruoli d'organigramma che lo concedono in automatico."""
    from anagrafica.models import RuoloOperativo

    ruolo = AccessGroup.objects.filter(id=ruolo_id).first()
    if ruolo is None:
        messages.error(request, "Ruolo non trovato.")
        return redirect(_url("matrice"))
    if ruolo.amministratore:
        messages.error(request, "Un ruolo amministratore si assegna solo a mano: non si collega all'organigramma.")
        return redirect(_url("matrice", ruolo=ruolo.id))
    if ruolo.preset == PRESET_BASE:
        messages.error(request, "Il ruolo base vale già per tutti: non serve collegarlo all'organigramma.")
        return redirect(_url("matrice", ruolo=ruolo.id))
    attuali = set(ruolo.ruoli_organigramma.values_list("id", flat=True))
    voluti = {i for i in (_int(v) for v in request.POST.getlist("ruoli_organigramma")) if i}
    # Si collegano ruoli attivi; un collegamento a un ruolo disattivato resta se non lo si toglie.
    validi = set(
        RuoloOperativo.objects.filter(Q(is_active=True) | Q(id__in=attuali), id__in=voluti).values_list("id", flat=True)
    )
    aggiunti, tolti = validi - attuali, attuali - validi
    if not aggiunti and not tolti:
        messages.info(request, "Nessuna modifica ai collegamenti con l'organigramma.")
        return redirect(_url("matrice", ruolo=ruolo.id))
    with transaction.atomic():
        if aggiunti:
            ruolo.ruoli_organigramma.add(*aggiunti)
        if tolti:
            ruolo.ruoli_organigramma.remove(*tolti)
    nomi = dict(RuoloOperativo.objects.filter(id__in=aggiunti | tolti).values_list("id", "nome"))
    log_action(
        request,
        "permessi_ruolo_organigramma",
        MODULO_AUDIT,
        {
            "ruolo": ruolo.label,
            "collegati": sorted(nomi[i] for i in aggiunti),
            "scollegati": sorted(nomi[i] for i in tolti),
        },
        oggetto_tipo="ruolo",
        oggetto_id=str(ruolo.id),
    )
    invalida_permessi()
    messages.success(request, f"Collegamenti di «{ruolo.label}» con l'organigramma aggiornati.")
    return redirect(_url("matrice", ruolo=ruolo.id))


# ── Riepilogo per modulo ─────────────────────────────────────────────────────


def _ctx_modulo(request) -> dict:
    """Per un modulo: cosa concede ogni ruolo e quali pagine/API sono aperte a chi."""
    from core.acl_capability import capability_index
    from core.models import GroupPermissionGrant, PermissionDefinition
    from core.permessi.sync import NOTA_MATRICE, capacita_permessi, codici_per_modulo

    specs = moduli_registrati()
    chiave = str(request.GET.get("modulo") or "").strip()
    if chiave not in specs:
        chiave = next(iter(specs), "")
    spec = specs.get(chiave)
    ruoli = _ruoli()
    base = {
        "moduli": [{"chiave": s.chiave, "nome": s.nome, "area": s.area} for s in specs.values()],
        "modulo_scelto": chiave,
        "spec": spec,
        "ruoli_colonne": ruoli,
    }
    if spec is None:
        return {**base, "riepilogo_ruoli": [], "pagine": []}

    azioni = list(AZIONI_STANDARD) + [a for a, _label in spec.azioni_extra]
    celle = {}
    for c in RuoloPermessoModulo.objects.filter(modulo=chiave):
        celle[(c.ruolo_id, c.azione)] = (c.ambito if c.consentito else VALORE_NO)
    riepilogo = []
    for ruolo in ruoli:
        if ruolo.amministratore:
            voci = [{"label": "tutto", "valore": "tutti"}]
        else:
            voci = [
                {"label": spec.etichetta_azione(a), "valore": celle[(ruolo.id, a)]}
                for a in azioni
                if (ruolo.id, a) in celle
            ]
        riepilogo.append({"ruolo": ruolo, "voci": voci, "vede_tutto": ruolo.vede_tutto and not spec.solo_amministratore})

    codes = codici_per_modulo().get(chiave, [])
    capacita = capacita_permessi()
    indice = capability_index(use_cache=True)
    definizioni = {
        d.code: d for d in PermissionDefinition.objects.filter(code__in=codes)
    }
    grant = {
        (g.group_id, g.permission_id): g
        for g in GroupPermissionGrant.objects.filter(permission_id__in=codes)
    }
    pagine = []
    for code in codes:
        rotte = sorted(set(indice.governed_routes.get(code, [])) | {r for r, _c in indice.subtree_routes.get(code, [])})
        stati = []
        aperto_a = 0
        for ruolo in ruoli:
            g = grant.get((ruolo.id, code))
            if ruolo.amministratore:
                stato = "admin"
            elif g is not None and g.enabled:
                stato = "matrice" if g.note == NOTA_MATRICE else "mano"
            elif g is not None:
                stato = "no"
            else:
                stato = ""
            if stato in {"admin", "matrice", "mano"}:
                aperto_a += 1
            stati.append(stato)
        d = definizioni.get(code)
        pagine.append(
            {
                "code": code,
                "label": d.label if d else code,
                "capacita": capacita.get(code, ""),
                "rotte": rotte,
                "api": [r for r in rotte if "api" in r.lower()],
                "stati": stati,
                "nessuno": aperto_a == 0,
            }
        )
    return {
        **base,
        "riepilogo_ruoli": riepilogo,
        "pagine": pagine,
        "pagine_senza_ruolo": sum(1 for p in pagine if p["nessuno"]),
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
            messages.error(request, "Il ruolo base «Operatore» non si disattiva: e' il minimo di ogni utente.")
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
        if ruolo.amministratore and ruolo.ruoli_organigramma.exists():
            messages.warning(
                request,
                "Il ruolo è amministratore: i collegamenti con l'organigramma restano ma non danno il ruolo a nessuno. "
                "Un amministratore si assegna solo a mano.",
            )
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
        "ruoli_senza_persone": [
            r for r in _ruoli()
            if r.preset != PRESET_BASE and not r.memberships.exists() and not r.ruoli_organigramma.exists()
        ],
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
