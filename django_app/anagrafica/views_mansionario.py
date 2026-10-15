"""Mansionario (fase 2): struttura ruolo → mansione e scheda della mansione.

Cancelli server-side all'inizio di ogni view:

- lettura: amministrazione anagrafica o dati HR (come la skill matrix);
- modifica di configurazione e assegnazioni: amministrazione anagrafica.

Le pagine mostrano livelli di esperienza I/L/U/O, mai dati sanitari.
"""
from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.audit import log_action

from .models import AbilitazioneMacchina, CompetenzaSkm, Mansione, Reparto, RuoloOperativo
from .services import mansionario_struttura as svc

MODULE = "anagrafica"


def _puo_vedere(request) -> bool:
    from .views import _check_hr_permission, _is_anagrafica_admin
    return _is_anagrafica_admin(request) or _check_hr_permission(request)


def _puo_gestire(request) -> bool:
    from .views import _is_anagrafica_admin
    return _is_anagrafica_admin(request)


def _nega(request, testo="Non hai i permessi per il Mansionario."):
    messages.error(request, testo)
    return redirect("anagrafica:index")


def _ids(request, nome) -> list[int]:
    return [int(v) for v in request.POST.getlist(nome) if str(v).isdigit()]


def _schede(righe: list[dict]) -> list[dict]:
    """Una scheda per mansione: barra per livello I/L/U/O, operativi in evidenza."""
    from .services import sezioni_c

    out = []
    for r in righe:
        m = r["mansione"]
        lv = r["livelli"]
        ruoli = ", ".join(x.nome for x in r["ruoli"]) or "nessun ruolo"
        rischi = ", ".join(x.nome for x in r["rischi"])
        out.append(sezioni_c.scheda(
            titolo=r["nome"],
            href=reverse("anagrafica:mansionario_mansione", args=[m.pk]),
            codice=r["reparto"] or "",
            meta=f"{m.get_tipo_display()} · {ruoli}",
            tags=(m.tipo, *("ruolo-" + sezioni_c.tag_slug(x.nome) for x in r["ruoli"])),
            # Colori dei segmenti: O/U operativi in verde, L in giallo, I in grigio.
            seg=[("ok", lv["O"] + lv["U"]), ("s90", lv["L"]), ("mai", lv["I"])],
            principale=str(r["operativi"]), principale_label="operativ" + ("o" if r["operativi"] == 1 else "i"),
            principale_sub=f"su {r['in_lista']} in lista",
            pillole=[
                sezioni_c.pillola("fmd-c-ko", "nessun operativo") if not r["operativi"] else
                (sezioni_c.pillola("fmd-c-s30", "uomo solo") if r["uomo_solo"] else None),
                sezioni_c.pillola("fmd-c-mai", "senza ruolo") if not r["ruoli"] else None,
                sezioni_c.pillola("fmd-c-mai", "senza mansione di rischio") if not r["rischi"] else None,
            ],
            piede=f"Rischio: {rischi}" if rischi else "Mansione di rischio da indicare",
            piede_muted=not rischi,
            vai="Apri →",
            ordini={"gap": (r["operativi"], r["in_lista"])},
        ))
    out.sort(key=lambda s: s["ordini"]["gap"])
    for i, s in enumerate(out):
        s["ordini"]["gap"] = i
    return out


@login_required
def mansionario(request):
    if not _puo_vedere(request):
        return _nega(request)
    from .services import sezioni_c

    righe = svc.riepilogo()
    ruoli_presenti = sorted({x.nome for r in righe for x in r["ruoli"]}, key=str.casefold)
    griglia = sezioni_c.griglia(
        id="fmd-mansionario", titolo="Mansioni", icona="i-grid",
        aside="Persone in lista per livello · clic per persone e configurazione",
        schede=_schede(righe),
        filtri=[("", "Tutte"), (CompetenzaSkm.TIPO_MACCHINA, "Macchine"), (CompetenzaSkm.TIPO_PROCESSO, "Processi")]
        + [("ruolo-" + sezioni_c.tag_slug(n), n) for n in ruoli_presenti],
        etichetta_filtri="Filtra per tipo o ruolo",
        ordini=[("gap", "Prima le meno coperte"), ("az", "A–Z")],
        legenda=[("ok", "autonomo o esperto"), ("s90", "intermedio"), ("mai", "in formazione")],
        vuoto_titolo="Nessuna mansione attiva",
        vuoto_testo="Le mansioni sono le colonne macchina e processo della skill matrix MOD.187.",
    )
    aree = sezioni_c.aree_visibili(request, [
        sezioni_c.Area("anagrafica:skill_matrix_macchina", "Skill matrix", "Persone × macchine, livelli I/L/U/O", icona="i-grid"),
        sezioni_c.Area("anagrafica:skm_refresh", "Refresh abilitazioni", "Rivalutazione dei livelli per reparto", icona="i-refresh"),
        sezioni_c.Area("anagrafica:mansioni_list", "Mansioni di rischio", "DPI, visite e schede di sicurezza", icona="i-alert-tri"),
        sezioni_c.Area("anagrafica:ruoli_operativi_list", "Ruoli", "Catalogo dei ruoli e organigramma", icona="i-users"),
        sezioni_c.Area("anagrafica:mpq_cruscotto", "Processi qualificati (MOD.128)", "Abilitazioni ai processi speciali", icona="i-cap"),
    ])
    return render(request, "anagrafica/pages/mansionario.html", {
        "page_title": "Mansionario",
        "righe": righe,
        "kpi": svc.kpi(righe),
        "griglia": griglia,
        "aree": aree,
        "is_admin": _puo_gestire(request),
    })


@login_required
def mansionario_mansione(request, mansione_id: int):
    if not _puo_vedere(request):
        return _nega(request)
    mansione = get_object_or_404(
        CompetenzaSkm.objects.select_related("asset", "reparto").prefetch_related("ruoli", "mansioni_rischio"),
        pk=mansione_id, tipo__in=svc.TIPI_MANSIONE,
    )
    is_admin = _puo_gestire(request)
    if request.method == "POST":
        if not is_admin:
            return _nega(request, "Non hai i permessi per modificare il Mansionario.")
        svc.salva_configurazione(
            mansione, ruoli_ids=_ids(request, "ruoli"), rischi_ids=_ids(request, "mansioni_rischio"),
            reparto_id=(request.POST.get("reparto") or "").strip() or None,
            attiva=request.POST.get("attiva") == "on",
        )
        log_action(request, "mansionario_configurazione", MODULE, {
            "mansione": mansione.pk, "ruoli": _ids(request, "ruoli"),
            "mansioni_rischio": _ids(request, "mansioni_rischio"), "attiva": mansione.attiva,
        }, oggetto=mansione)
        messages.success(request, f"Mansione «{mansione.nome}» salvata.")
        return redirect("anagrafica:mansionario_mansione", mansione_id=mansione.pk)

    from core.legacy_anagrafica import fetch_anagrafica_rows
    from core import naming

    persone = svc.persone(mansione)
    in_lista = {p["legacy_id"] for p in persone}
    candidati = []
    if is_admin:
        candidati = sorted(
            ({"id": int(r["id"]), "nome": naming.nome_completo(r.get("nome"), r.get("cognome"))}
             for r in fetch_anagrafica_rows(deduplicate=True)
             if r.get("attivo", True) and r.get("id") and int(r["id"]) not in in_lista),
            key=lambda c: c["nome"].casefold(),
        )
    return render(request, "anagrafica/pages/mansionario_mansione.html", {
        "page_title": mansione.nome,
        "mansione": mansione,
        "persone": persone,
        "candidati": candidati,
        "livelli": svc.LIVELLI,
        "ruoli_opts": list(RuoloOperativo.objects.filter(is_active=True).select_related("ambito").order_by("nome")),
        "rischi_opts": list(Mansione.objects.filter(is_active=True).order_by("nome")),
        "reparti_opts": list(Reparto.objects.filter(is_active=True).order_by("nome")),
        "sel_ruoli": {r.pk for r in mansione.ruoli.all()},
        "sel_rischi": {m.pk for m in mansione.mansioni_rischio.all()},
        "is_admin": is_admin,
    })


@login_required
@require_POST
def mansionario_assegna(request, mansione_id: int):
    if not _puo_gestire(request):
        return _nega(request, "Non hai i permessi per modificare il Mansionario.")
    mansione = get_object_or_404(CompetenzaSkm, pk=mansione_id, tipo__in=svc.TIPI_MANSIONE)
    lid = request.POST.get("persona") or ""
    if not lid.isdigit():
        messages.error(request, "Scegli la persona.")
        return redirect("anagrafica:mansionario_mansione", mansione_id=mansione.pk)
    try:
        svc.assegna(mansione, legacy_anagrafica_id=int(lid), livello=request.POST.get("livello"), user=request.user)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("anagrafica:mansionario_mansione", mansione_id=mansione.pk)
    log_action(request, "mansionario_assegna", MODULE, {
        "mansione": mansione.pk, "legacy_anagrafica_id": int(lid), "livello": request.POST.get("livello"),
    }, oggetto=mansione)
    messages.success(request, "Persona assegnata alla mansione.")
    return redirect("anagrafica:mansionario_mansione", mansione_id=mansione.pk)


@login_required
@require_POST
def mansionario_togli(request, mansione_id: int, abilitazione_id: int):
    if not _puo_gestire(request):
        return _nega(request, "Non hai i permessi per modificare il Mansionario.")
    ab = get_object_or_404(AbilitazioneMacchina, pk=abilitazione_id, competenza_id=mansione_id)
    svc.togli(ab)
    log_action(request, "mansionario_togli", MODULE, {
        "mansione": mansione_id, "legacy_anagrafica_id": ab.legacy_anagrafica_id,
    }, oggetto=ab)
    messages.success(request, "Persona tolta dalla mansione.")
    return redirect("anagrafica:mansionario_mansione", mansione_id=mansione_id)
