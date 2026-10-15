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


def _puo_valutare(request) -> bool:
    """Valutare e mettere/togliere persone: amministrazione anagrafica o chi gestisce
    la skill matrix (il caporeparto durante il refresh, fase 4)."""
    if _puo_gestire(request):
        return True
    from .acl_bootstrap import PERM_SKM_MANAGE
    from .views import _check_skm_permission
    return _check_skm_permission(request, PERM_SKM_MANAGE)


def _ritorno_refresh(request):
    """Redirect alla pagina del refresh quando la valutazione parte da lì."""
    da = request.POST.get("da") or request.GET.get("da")
    reparto = (request.POST.get("reparto") or request.GET.get("reparto") or "").strip()
    if da != "refresh" or not reparto:
        return None
    from urllib.parse import urlencode
    return redirect(f"{reverse('anagrafica:skm_refresh')}?{urlencode({'reparto': reparto})}")


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
        sezioni_c.Area("anagrafica:mansionario_lacune", "Lacune di competenza", "Chi non è abilitato e cosa manca", icona="i-alert-cir"),
        sezioni_c.Area("anagrafica:skill_matrix_macchina", "Skill matrix", "Persone × macchine, livelli I/L/U/O", icona="i-grid"),
        sezioni_c.Area("anagrafica:skm_refresh", "Refresh abilitazioni", "Rivalutazione dei livelli per reparto", icona="i-refresh"),
        sezioni_c.Area("anagrafica:mansioni_list", "Mansioni di rischio", "DPI, visite e schede di sicurezza", icona="i-alert-tri"),
        sezioni_c.Area("anagrafica:ruoli_operativi_list", "Ruoli", "Catalogo dei ruoli e organigramma", icona="i-users"),
        sezioni_c.Area("anagrafica:mpq_cruscotto", "Processi qualificati (MOD.128)", "Abilitazioni ai processi speciali", icona="i-cap"),
    ])
    from .services import mansionario_competenze as comp_svc
    lacune = comp_svc.lacune()
    kpi = svc.kpi(righe)
    kpi["non_abilitati"] = sum(1 for r in lacune if r["valutazione"].esito == comp_svc.NON_ABILITATO)
    kpi["in_addestramento"] = sum(1 for r in lacune if r["valutazione"].esito == comp_svc.IN_ADDESTRAMENTO)
    return render(request, "anagrafica/pages/mansionario.html", {
        "page_title": "Mansionario",
        "righe": righe,
        "kpi": kpi,
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

    from .services import mansionario_competenze as comp_svc

    competenze = list(comp_svc.competenze(mansione))
    persone = svc.persone(mansione)
    for p in persone:
        p["valutazione"] = comp_svc.valuta(p["abilitazione"], voci=competenze)
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
        "competenze": competenze,
        "persone": persone,
        "candidati": candidati,
        **(_opzioni_requisiti() if is_admin else {}),
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
    if not _puo_valutare(request):
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
    if not _puo_valutare(request):
        return _nega(request, "Non hai i permessi per modificare il Mansionario.")
    ab = get_object_or_404(AbilitazioneMacchina, pk=abilitazione_id, competenza_id=mansione_id)
    svc.togli(ab)
    log_action(request, "mansionario_togli", MODULE, {
        "mansione": mansione_id, "legacy_anagrafica_id": ab.legacy_anagrafica_id,
    }, oggetto=ab)
    messages.success(request, "Persona tolta dalla mansione.")
    return redirect("anagrafica:mansionario_mansione", mansione_id=mansione_id)


# ═══════════════════════════════════════════════════════════════════════════
# Fase 3: competenze, valutazione, scheda persona, lacune
# ═══════════════════════════════════════════════════════════════════════════

def _opzioni_requisiti() -> dict:
    from .models import TipoQualifica, TrainingCourse
    from .models_mpq import ProcessoQualificato
    return {
        "corsi_opts": list(TrainingCourse.objects.filter(is_active=True).order_by("titolo").only("id", "titolo")),
        "qualifiche_opts": list(TipoQualifica.objects.filter(is_active=True).order_by("nome")),
        "processi_opts": list(ProcessoQualificato.objects.order_by("nome").only("id", "nome")),
    }


def _int_o_none(valore):
    valore = (valore or "").strip()
    return int(valore) if valore.isdigit() else None


@login_required
@require_POST
def mansionario_competenza_salva(request, mansione_id: int):
    if not _puo_gestire(request):
        return _nega(request, "Non hai i permessi per modificare il Mansionario.")
    from .models import VoceMacchinaCatalogo
    from .services import mansionario_competenze as comp_svc

    mansione = get_object_or_404(CompetenzaSkm, pk=mansione_id, tipo__in=svc.TIPI_MANSIONE)
    voce_id = _int_o_none(request.POST.get("voce"))
    voce = get_object_or_404(VoceMacchinaCatalogo, pk=voce_id, mansione=mansione) if voce_id else None
    try:
        voce = comp_svc.salva_competenza(
            mansione, voce=voce, nome=request.POST.get("nome"),
            livello_minimo=(request.POST.get("livello_minimo") or "U").strip().upper(),
            bloccante=request.POST.get("bloccante") == "on",
            corso_id=_int_o_none(request.POST.get("corso")), qualifica_id=_int_o_none(request.POST.get("qualifica")),
            processo_id=_int_o_none(request.POST.get("processo_mpq")), ordine=_int_o_none(request.POST.get("ordine")) or 0,
        )
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("anagrafica:mansionario_mansione", mansione_id=mansione.pk)
    log_action(request, "mansionario_competenza", MODULE, {
        "mansione": mansione.pk, "competenza": voce.pk, "nome": voce.nome, "livello_minimo": voce.livello_minimo,
        "bloccante": voce.bloccante, "corso": voce.corso_id, "qualifica": voce.qualifica_id, "mod128": voce.processo_mpq_id,
    }, oggetto=mansione)
    messages.success(request, f"Competenza «{voce.nome}» salvata.")
    return redirect("anagrafica:mansionario_mansione", mansione_id=mansione.pk)


@login_required
@require_POST
def mansionario_competenza_disattiva(request, mansione_id: int, voce_id: int):
    if not _puo_gestire(request):
        return _nega(request, "Non hai i permessi per modificare il Mansionario.")
    from .models import VoceMacchinaCatalogo

    voce = get_object_or_404(VoceMacchinaCatalogo, pk=voce_id, mansione_id=mansione_id)
    voce.attiva = False
    voce.save(update_fields=["attiva"])
    log_action(request, "mansionario_competenza_tolta", MODULE, {"mansione": mansione_id, "competenza": voce.pk}, oggetto=voce)
    messages.success(request, f"Competenza «{voce.nome}» tolta dalla mansione (i livelli registrati restano).")
    return redirect("anagrafica:mansionario_mansione", mansione_id=mansione_id)


@login_required
def mansionario_valuta(request, mansione_id: int, abilitazione_id: int):
    """Livello della persona su ogni competenza della mansione (amministrazione o
    gestione skill matrix, es. il caporeparto dal refresh)."""
    if not _puo_valutare(request):
        return _nega(request, "Non hai i permessi per modificare il Mansionario.")
    from core import naming
    from core.legacy_anagrafica import fetch_anagrafica_rows
    from .services import mansionario_competenze as comp_svc

    ab = get_object_or_404(AbilitazioneMacchina.objects.select_related("competenza__asset"),
                           pk=abilitazione_id, competenza_id=mansione_id)
    competenze = list(comp_svc.competenze(ab.competenza))
    if request.method == "POST":
        livelli = {v.pk: request.POST.get(f"livello_{v.pk}", "") for v in competenze}
        val = comp_svc.registra_livelli(ab, livelli, user=request.user)
        log_action(request, "mansionario_valutazione", MODULE, {
            "mansione": mansione_id, "legacy_anagrafica_id": ab.legacy_anagrafica_id,
            "livelli": {str(k): v for k, v in livelli.items()}, "esito": val.esito, "livello": ab.livello,
        }, oggetto=ab)
        messages.success(request, f"Valutazione salvata: {val.esito_label}, livello {ab.livello}.")
        return _ritorno_refresh(request) or redirect("anagrafica:mansionario_mansione", mansione_id=mansione_id)
    righe = fetch_anagrafica_rows(ids=[ab.legacy_anagrafica_id])
    nome = naming.nome_completo(righe[0].get("nome"), righe[0].get("cognome")) if righe else f"#{ab.legacy_anagrafica_id}"
    return render(request, "anagrafica/pages/mansionario_valuta.html", {
        "page_title": f"Valutazione · {nome}",
        "abilitazione": ab, "mansione": ab.competenza, "nome": nome,
        "valutazione": comp_svc.valuta(ab, voci=competenze),
        "livelli": svc.LIVELLI,
        "da": "refresh" if request.GET.get("da") == "refresh" else "",
        "reparto_refresh": (request.GET.get("reparto") or "").strip(),
    })


def _rischi_persona(legacy_id: int, mansione_nome: str) -> dict:
    """Mansioni di rischio effettive della persona (solo nomi e provenienza)."""
    from .services import mansionario
    det = mansionario.requisiti_dipendente_dettaglio(legacy_id, mansione_nome=mansione_nome)
    return {"rischi_effettivi": det["mansioni_rischio"], "rischi_esclusi": det["mansioni_rischio_escluse"]}


@login_required
def mansionario_persona(request, legacy_id: int):
    if not _puo_vedere(request):
        return _nega(request)
    from core import naming
    from core.legacy_anagrafica import fetch_anagrafica_rows
    from .services import mansionario_competenze as comp_svc

    righe = fetch_anagrafica_rows(ids=[legacy_id])
    if not righe:
        messages.error(request, "Dipendente non trovato.")
        return redirect("anagrafica:mansionario")
    dip = righe[0]
    return render(request, "anagrafica/pages/mansionario_persona.html", {
        "page_title": naming.nome_completo(dip.get("nome"), dip.get("cognome")),
        "legacy_id": legacy_id,
        "nome": naming.nome_completo(dip.get("nome"), dip.get("cognome")),
        "mansione_anagrafica": (dip.get("mansione") or "").strip(),
        "scheda": comp_svc.scheda_persona(legacy_id),
        **_rischi_persona(legacy_id, (dip.get("mansione") or "").strip()),
    })


@login_required
def mansionario_lacune(request):
    if not _puo_vedere(request):
        return _nega(request)
    from .services import mansionario_competenze as comp_svc

    lacune = comp_svc.lacune()
    esito = (request.GET.get("esito") or "").strip()
    if esito in comp_svc.ESITI_LABEL:
        lacune = [r for r in lacune if r["valutazione"].esito == esito]
    if request.GET.get("formato") == "csv":
        from django.http import HttpResponse
        from core.csv_export import safe_csv_writer
        resp = HttpResponse(content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = 'attachment; filename="mansionario_lacune.csv"'
        resp.write("\ufeff")
        w = safe_csv_writer(resp)
        w.writerow(["Persona", "Mansione", "Reparto", "Esito", "Livello", "Cosa manca"])
        for r in lacune:
            v = r["valutazione"]
            w.writerow([r["nome"], r["mansione"].nome, r["reparto"], v.esito_label, v.livello, "; ".join(v.mancanze)])
        return resp
    return render(request, "anagrafica/pages/mansionario_lacune.html", {
        "page_title": "Lacune di competenza",
        "lacune": lacune, "esito": esito, "esiti": comp_svc.ESITI_LABEL,
    })
