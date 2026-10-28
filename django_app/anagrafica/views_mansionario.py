"""Mansionario (fase 2): struttura ruolo → mansione e scheda della mansione.

Cancelli server-side all'inizio di ogni view:

- lettura: amministrazione anagrafica o dati HR (come la skill matrix);
- modifica di configurazione e assegnazioni: amministrazione anagrafica.

Le pagine mostrano livelli di esperienza I/L/U/O, mai dati sanitari.
"""
from __future__ import annotations

from collections import Counter

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from core.audit import log_action

from .models import (
    AbilitazioneMacchina,
    AbilitazioneMacchinaVoce,
    CompetenzaCatalogo,
    CompetenzaSkm,
    Mansione,
    Reparto,
    RuoloOperativo,
    VoceMacchinaCatalogo,
)
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


def _alla_scheda(mansione_id: int, tab: str = ""):
    """Redirect alla scheda della mansione, sulla tab indicata (persone è la prima)."""
    url = reverse("anagrafica:mansionario_mansione", args=[mansione_id])
    return redirect(f"{url}#{tab}" if tab else url)


LIVELLO_LABEL = {"I": "in formazione", "L": "intermedio", "U": "autonomo", "O": "esperto"}


def _ids(request, nome) -> list[int]:
    return [int(v) for v in request.POST.getlist(nome) if str(v).isdigit()]


LEGENDA_LIVELLI = [("ok", "autonomo o esperto"), ("s90", "intermedio"), ("mai", "in formazione")]


def _scheda(r: dict, *, ruolo_gruppo=None, persone: dict | None = None) -> dict:
    """Una scheda per mansione: barra per livello I/L/U/O, operativi in evidenza.

    Dentro il gruppo del ruolo il ruolo non si ripete: la riga dice solo il tipo e,
    se la mansione serve anche ad altri ruoli, quali. Le «Responsabilità» (una
    persona per definizione) mostrano chi è il titolare, non operativi e «uomo solo».
    ``persone``: ``legacy_id`` → dati della persona (nome, reparto, area) per
    titolari, ricerca e filtri.
    """
    from .services import sezioni_c

    persone = persone or {}
    m = r["mansione"]
    lv = r["livelli"]
    altri = [x.nome for x in r["ruoli"] if ruolo_gruppo is None or x.pk != ruolo_gruppo.pk]
    meta = m.get_tipo_display() + (f" · anche {', '.join(altri)}" if altri and ruolo_gruppo else "")
    rischi = ", ".join(x.nome for x in r["rischi"])
    nomi = [persone[i]["nome"] for i in r["persone_ids"] if i in persone]
    area = m.area.nome if m.area_id else ""
    filtri = {
        "reparto": sezioni_c.tag_slug(r["reparto"] or ""), "area": sezioni_c.tag_slug(area),
        "persone": " " + " ".join(str(i) for i in r["persone_ids"]) + " ",
        "classi": " " + " ".join(r.get("classi", [])) + " ",
    }
    q = " ".join([r["nome"], r["reparto"] or "", area, rischi, *(x.nome for x in r["ruoli"]), *nomi]).casefold()
    if m.is_responsabilita:
        flag = ["responsabilita"] + ([] if nomi else ["senza-titolare", "scoperta"])
        dove = f"dell'area {area}" if m.responsabilita_area_id else f"del reparto {r['reparto']}"
        s = sezioni_c.scheda(
            titolo=r["nome"],
            href=reverse("anagrafica:mansionario_mansione", args=[m.pk]),
            codice=r["reparto"] or "",
            meta=f"Chi la ha è il capo {dove}",
            tags=(m.tipo, *flag),
            seg=[("ok", lv["O"] + lv["U"]), ("s90", lv["L"]), ("mai", lv["I"])],
            principale=", ".join(nomi) if nomi else "",
            principale_label="" if nomi else "",
            principale_sub=" (co-capi)" if len(nomi) > 1 else "",
            pillole=[None if nomi else sezioni_c.pillola("fmd-c-ko", "nessun titolare")],
            piede="Titolare della responsabilità" if nomi else "Assegnala da «Reparti, aree e capi»",
            piede_muted=not nomi,
            vai="Apri →",
        )
        s["q"], s["filtri"] = q, filtri
        return s
    flag = []
    if not r["operativi"]:
        flag.append("scoperta")
    if not r["ruoli"]:
        flag.append("senza-ruolo")
    if not r["rischi"]:
        flag.append("senza-rischio")
    if r["uomo_solo"] and r["operativi"]:
        flag.append("uomo-solo")
    s = sezioni_c.scheda(
        titolo=r["nome"],
        href=reverse("anagrafica:mansionario_mansione", args=[m.pk]),
        codice=r["reparto"] or "",
        meta=meta,
        tags=(m.tipo, *flag),
        # Colori dei segmenti: O/U operativi in verde, L in giallo, I in grigio.
        seg=[("ok", lv["O"] + lv["U"]), ("s90", lv["L"]), ("mai", lv["I"])],
        principale=str(r["operativi"]), principale_label="operativ" + ("o" if r["operativi"] == 1 else "i"),
        principale_sub=f"su {r['in_lista']} in lista",
        pillole=[
            sezioni_c.pillola("fmd-c-ko", "nessun operativo") if not r["operativi"] else
            (sezioni_c.pillola("fmd-c-s30", "uomo solo") if r["uomo_solo"] else None),
            sezioni_c.pillola("fmd-c-mai", "senza mansione di rischio") if not r["rischi"] else None,
        ],
        piede=f"Rischio: {rischi}" if rischi else "Mansione di rischio da indicare",
        piede_muted=not rischi,
        vai="Apri →",
    )
    s["q"], s["filtri"] = q, filtri
    return s


def _persone_in_forza() -> dict[int, dict]:
    """``legacy_id`` → nome, reparto, area e ruoli di oggi, per chi è in forza."""
    from django.db.models import Q
    from django.utils import timezone

    from core import naming
    from core.legacy_anagrafica import fetch_anagrafica_rows

    from .models import DipendenteAnagraficaAziendale, DipendenteRuoloOperativo

    out = {int(r["id"]): {"id": int(r["id"]), "nome": naming.nome_completo(r.get("nome"), r.get("cognome")),
                          "reparto": "", "area": "", "ruoli": set()}
           for r in fetch_anagrafica_rows(deduplicate=True) if r.get("attivo", True) and r.get("id")}
    for a in (DipendenteAnagraficaAziendale.objects.filter(legacy_anagrafica_id__in=list(out),
                                                           area_aziendale__isnull=False)
              .select_related("area_aziendale__reparto")):
        p = out[a.legacy_anagrafica_id]
        p["area"] = a.area_aziendale.nome
        p["reparto"] = a.area_aziendale.reparto.nome if a.area_aziendale.reparto_id else ""
    oggi = timezone.localdate()
    for lid, rid in (DipendenteRuoloOperativo.objects.filter(Q(data_fine__isnull=True) | Q(data_fine__gte=oggi),
                                                             legacy_anagrafica_id__in=list(out))
                     .values_list("legacy_anagrafica_id", "ruolo_id")):
        out[lid]["ruoli"].add(rid)
    return out


def _chi_ha_il_ruolo(ruolo, righe_g: list[dict], persone: dict[int, dict]) -> dict:
    """Chi ricopre il ruolo, indipendentemente dalle mansioni, e i disallineamenti.

    - con il ruolo ma su nessuna mansione del gruppo: «nessuna mansione»;
    - in lista su una mansione del gruppo ma senza il ruolo: «senza il ruolo».
    """
    in_lista = {i for r in righe_g for i in r["persone_ids"]}
    con_ruolo = [p for p in persone.values() if ruolo.pk in p["ruoli"]]
    righe = [{**p, "senza_mansione": p["id"] not in in_lista} for p in con_ruolo]
    righe.sort(key=lambda p: (not p["senza_mansione"], p["reparto"].casefold(), p["nome"].casefold()))
    senza_ruolo = sorted((persone[i] for i in in_lista if i in persone and ruolo.pk not in persone[i]["ruoli"]),
                         key=lambda p: p["nome"].casefold())
    return {"persone": righe, "senza_mansione": sum(1 for p in righe if p["senza_mansione"]),
            "senza_ruolo": senza_ruolo}


def _gruppi_per_ruolo(righe: list[dict], persone: dict[int, dict] | None = None) -> list[dict]:
    """Ruolo → mansioni. Una mansione con più ruoli compare sotto ciascuno; quelle
    senza ruolo finiscono in fondo, in «Da collegare a un ruolo». Dentro il gruppo
    prima le meno coperte; il gruppo dice anche chi ricopre il ruolo."""
    persone = persone if persone is not None else {}
    per_ruolo: dict[int, dict] = {}
    senza = []
    for r in righe:
        if not r["ruoli"]:
            senza.append(r)
        for ruolo in r["ruoli"]:
            per_ruolo.setdefault(ruolo.pk, {"ruolo": ruolo, "righe": []})["righe"].append(r)

    def _gruppo(nome, righe_g, *, ruolo=None, da_collegare=False):
        righe_g = sorted(righe_g, key=lambda x: (x["operativi"], x["in_lista"], x["nome"].casefold()))
        chi = _chi_ha_il_ruolo(ruolo, righe_g, persone) if ruolo is not None else None
        ids = {i for x in righe_g for i in x["persone_ids"]} | ({p["id"] for p in chi["persone"]} if chi else set())
        return {
            "nome": nome, "ruolo": ruolo, "da_collegare": da_collegare,
            "schede": [_scheda(x, ruolo_gruppo=ruolo, persone=persone) for x in righe_g],
            "scoperte": sum(1 for x in righe_g if not x["operativi"]),
            "in_lista": sum(x["in_lista"] for x in righe_g),
            "chi": chi,
            "persone_ids": " " + " ".join(str(i) for i in sorted(ids)) + " ",
        }

    gruppi = [_gruppo(g["ruolo"].nome, g["righe"], ruolo=g["ruolo"])
              for g in sorted(per_ruolo.values(), key=lambda g: g["ruolo"].nome.casefold())]
    if senza:
        gruppi.append(_gruppo("Da collegare a un ruolo", senza, da_collegare=True))
    return gruppi


@login_required
def mansionario(request):
    if not _puo_vedere(request):
        return _nega(request)
    from .services import sezioni_c

    righe = svc.riepilogo()
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
    persone = _persone_in_forza()
    gruppi = _gruppi_per_ruolo(righe, persone)
    kpi["ruoli"] = sum(1 for g in gruppi if not g["da_collegare"])
    kpi["responsabilita_senza_titolare"] = sum(
        1 for r in righe if r["mansione"].is_responsabilita and not any(i in persone for i in r["persone_ids"]))
    kpi["uomo_solo"] = sum(1 for r in righe if r["uomo_solo"] and r["operativi"]
                           and not r["mansione"].is_responsabilita)
    kpi["ruolo_senza_mansione"] = sum(g["chi"]["senza_mansione"] for g in gruppi if g["chi"])
    from .services.mansioni_coefficienti import CLASSIFICAZIONI
    from .services.sezioni_c import tag_slug

    filtri = {  # (valore come nei data-f-* delle schede, etichetta)
        "reparti": [(tag_slug(n), n) for n in sorted({r["reparto"] for r in righe if r["reparto"]}, key=str.casefold)],
        "aree": [(tag_slug(n), n) for n in sorted({r["mansione"].area.nome for r in righe if r["mansione"].area_id},
                                                  key=str.casefold)],
        "persone": sorted(persone.values(), key=lambda p: p["nome"].casefold()),
        "classi": [*CLASSIFICAZIONI.items(), ("-", "Non classificata")],
    }
    return render(request, "anagrafica/pages/mansionario.html", {
        "page_title": "Mansionario",
        "righe": righe,
        "kpi": kpi,
        "gruppi": gruppi,
        "filtri": filtri,
        "legenda": LEGENDA_LIVELLI,
        "cc_card": {"legenda": LEGENDA_LIVELLI},
        "aree": aree,
        "is_admin": _puo_gestire(request),
    })


@login_required
def mansionario_mansione(request, mansione_id: int):
    # Chi valuta (gestore skill matrix, es. il caporeparto) deve poter aprire la
    # mansione e usarne Assegna / Valuta / Togli, non solo passare dal refresh.
    puo_valutare = _puo_valutare(request)
    if not (_puo_vedere(request) or puo_valutare):
        return _nega(request)
    mansione = get_object_or_404(
        CompetenzaSkm.objects.select_related("asset", "reparto").prefetch_related("ruoli", "mansioni_rischio"),
        pk=mansione_id, tipo__in=svc.TIPI_MANSIONE,
    )
    is_admin = _puo_gestire(request)
    if request.method == "POST":
        if not is_admin:
            return _nega(request, "Non hai i permessi per modificare il Mansionario.")
        from django.db import transaction

        try:
            with transaction.atomic():
                nome_prima = svc.rinomina(mansione, request.POST.get("nome")) if "nome" in request.POST else None
                svc.salva_configurazione(
                    mansione, ruoli_ids=_ids(request, "ruoli"), rischi_ids=_ids(request, "mansioni_rischio"),
                    reparto_id=_int_o_none(request.POST.get("reparto")),
                    attiva=request.POST.get("attiva") == "on",
                )
        except ValueError as exc:
            messages.error(request, f"Niente salvato. {exc}")
            return _alla_scheda(mansione.pk, "impostazioni")
        log_action(request, "mansionario_configurazione", MODULE, {
            "mansione": mansione.pk, "ruoli": _ids(request, "ruoli"),
            "mansioni_rischio": _ids(request, "mansioni_rischio"), "attiva": mansione.attiva,
            "nome": mansione.nome, "nome_prima": nome_prima,
        }, oggetto=mansione)
        messages.success(request, f"Mansione «{mansione.nome}» salvata." + (
            f" Prima si chiamava «{nome_prima}»: persone, competenze e rischi restano collegati." if nome_prima else ""))
        return _alla_scheda(mansione.pk, "impostazioni")

    from .services import mansionario_competenze as comp_svc

    competenze = list(comp_svc.competenze(mansione))
    persone = svc.persone(mansione)
    requisiti = comp_svc.Requisiti([p["legacy_id"] for p in persone], competenze)
    for p in persone:
        val = comp_svc.valuta(p["abilitazione"], voci=competenze, requisiti=requisiti)
        p["valutazione"] = val
        p["livello_label"] = LIVELLO_LABEL.get(p["livello"], "")
        # Nessun livello registrato sulle competenze: la cosa da fare è valutarla,
        # non leggere l'elenco di tutte le competenze «mancanti».
        p["da_valutare"] = bool(competenze) and not any(r["livello"] or r["requisito"] for r in val.voci)
        # Matrice persone × competenze: il livello salvato (quello che si cambia) e
        # quello che conta, col tetto quando manca il requisito formale.
        salvati = {v.voce_id: v.livello for v in p["abilitazione"].voci.all()}
        p["celle"] = [{**r, "salvato": salvati.get(r["voce"].pk, "")} for r in val.voci]
    # Ogni persona in una sola casella: sospesa, da valutare, poi l'esito calcolato.
    for p in persone:
        p["stato"] = "sospesa" if p["sospesa"] else "da_valutare" if p["da_valutare"] else p["valutazione"].esito
    conta = Counter(p["stato"] for p in persone)
    stato = {
        "operativi": conta[comp_svc.ABILITATO],
        "addestramento": conta[comp_svc.IN_ADDESTRAMENTO],
        "non_abilitati": conta[comp_svc.NON_ABILITATO],
        "da_valutare": conta["da_valutare"],
        "sospese": conta["sospesa"],
    }
    in_lista = {p["legacy_id"] for p in persone}
    candidati = []
    ruoli_mansione = {r.pk for r in mansione.ruoli.all()}
    if puo_valutare and ruoli_mansione:
        # Solo chi ricopre uno dei ruoli della mansione. Il reparto nell'etichetta:
        # cercando il reparto e «Seleziona tutti» si aggiunge un reparto intero.
        candidati = sorted((p for lid, p in _persone_in_forza().items()
                            if lid not in in_lista and p["ruoli"] & ruoli_mansione),
                           key=lambda c: c["nome"].casefold())
    return render(request, "anagrafica/pages/mansionario_mansione.html", {
        "page_title": mansione.nome,
        "mansione": mansione,
        "competenze": competenze,
        "persone": persone,
        "stato": stato,
        "candidati": candidati,
        **(_opzioni_requisiti() if is_admin else {}),
        "livelli": svc.LIVELLI,
        "livelli_label": list(LIVELLO_LABEL.items()),
        "ruoli_opts": list(RuoloOperativo.objects.filter(is_active=True).select_related("ambito").order_by("nome")),
        "rischi_opts": list(Mansione.objects.filter(is_active=True).order_by("nome")),
        "reparti_opts": list(Reparto.objects.filter(is_active=True).order_by("nome")),
        "sel_ruoli": {r.pk for r in mansione.ruoli.all()},
        "sel_rischi": {m.pk for m in mansione.mansioni_rischio.all()},
        "nomi_precedenti": svc.nomi_precedenti(mansione),
        "completezza": svc.completezza(mansione, n_competenze=len(competenze), n_persone=len(persone)),
        "regole": svc.regole_correnti(),
        "catalogo_nomi": list(CompetenzaCatalogo.objects.filter(attiva=True).order_by("nome")
                              .values_list("nome", flat=True)) if is_admin else [],
        "regole_formazione": list(
            mansione.regole_formazione.filter(is_active=True, is_mandatory=True)
            .select_related("corso", "piano").order_by("corso__titolo", "piano__nome")
        ),
        "is_admin": is_admin,
        "puo_valutare": puo_valutare,
    })


@login_required
@require_POST
def mansionario_assegna(request, mansione_id: int):
    if not _puo_valutare(request):
        return _nega(request, "Non hai i permessi per modificare il Mansionario.")
    mansione = get_object_or_404(CompetenzaSkm, pk=mansione_id, tipo__in=svc.TIPI_MANSIONE)
    # Una o più persone (picker multiplo): stesso percorso della pagina «in blocco».
    ids = _ids(request, "persona")
    if not ids:
        messages.error(request, "Scegli almeno una persona.")
        return redirect("anagrafica:mansionario_mansione", mansione_id=mansione.pk)
    from .services import mansioni_in_blocco as mb
    try:
        esiti = mb.esegui(ids, mansione=mansione, modo=mb.ASSEGNA, livello=request.POST.get("livello"),
                          user=request.user, applica=True)
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect("anagrafica:mansionario_mansione", mansione_id=mansione.pk)
    fatti = [e for e in esiti if e.azione == "cambia"]
    errori = [e for e in esiti if e.azione == "errore"]
    log_action(request, "mansionario_assegna", MODULE, {
        "mansione": mansione.pk, "legacy_anagrafica_ids": [e.legacy_id for e in fatti],
        "livello": request.POST.get("livello"), "errori": len(errori),
    }, oggetto=mansione)
    if fatti:
        messages.success(request, "Persona assegnata alla mansione." if len(fatti) == 1
                         else f"{len(fatti)} persone assegnate alla mansione.")
    if errori:
        messages.error(request, "Non assegnate: " + "; ".join(f"{e.nome} ({e.dettaglio})" for e in errori))
    elif not fatti:
        messages.info(request, "Niente da fare: le persone scelte erano già in lista con quel livello.")
    return _torna_a_next(request) or redirect("anagrafica:mansionario_mansione", mansione_id=mansione.pk)


def _torna_a_next(request):
    """Dalla scheda dipendente o dall'onboarding si torna lì (solo URL interni)."""
    from django.utils.http import url_has_allowed_host_and_scheme

    prossima = request.POST.get("next") or ""
    if prossima and url_has_allowed_host_and_scheme(prossima, allowed_hosts={request.get_host()},
                                                     require_https=request.is_secure()):
        return redirect(prossima)
    return None


@login_required
@require_POST
def mansionario_voce_livello(request, mansione_id: int, abilitazione_id: int, voce_id: int):
    """Una cella della matrice persone × competenze: livello della competenza, poi il
    livello sulla mansione si ricalcola (storico per competenza e per mansione + audit)."""
    if not _puo_valutare(request):
        return _nega(request, "Non hai i permessi per modificare il Mansionario.")
    from .services import mansionario_competenze as comp_svc

    ab = get_object_or_404(AbilitazioneMacchina.objects.select_related("competenza"),
                           pk=abilitazione_id, competenza_id=mansione_id, in_lista=True)
    voce = get_object_or_404(VoceMacchinaCatalogo, pk=voce_id, mansione_id=mansione_id, attiva=True)
    livello = (request.POST.get("livello") or "").strip().upper()
    if livello and livello not in svc.LIVELLI:
        messages.error(request, "Livello non valido.")
        return _torna_a_next(request) or _alla_scheda(mansione_id, "persone")
    prima_voce = AbilitazioneMacchinaVoce.objects.filter(abilitazione=ab, voce=voce).values_list(
        "livello", flat=True).first() or ""
    if prima_voce != livello:
        prima = ab.livello
        val = comp_svc.registra_livelli(ab, {voce.pk: livello}, user=request.user)
        log_action(request, "mansionario_voce_livello", MODULE, {
            "mansione": mansione_id, "legacy_anagrafica_id": ab.legacy_anagrafica_id, "competenza": voce.nome,
            "livello_prima": prima_voce, "livello": livello, "mansione_prima": prima, "mansione_dopo": ab.livello,
            "esito": val.esito,
        }, oggetto=ab)
        messages.success(request, f"«{voce.nome}»: {prima_voce or '—'} → {livello or '—'}. "
                                  f"Livello sulla mansione {prima or '—'} → {ab.livello or '—'} ({val.esito_label.lower()}).")
    return _torna_a_next(request) or _alla_scheda(mansione_id, "persone")


@login_required
@require_POST
def mansionario_livello(request, mansione_id: int, abilitazione_id: int):
    """Cambio livello in riga (scheda mansione o scheda persona): storico + audit."""
    if not _puo_valutare(request):
        return _nega(request, "Non hai i permessi per modificare il Mansionario.")
    ab = get_object_or_404(AbilitazioneMacchina.objects.select_related("competenza"),
                           pk=abilitazione_id, competenza_id=mansione_id)
    try:
        prima = svc.cambia_livello(ab, request.POST.get("livello"), user=request.user)
    except ValueError as exc:
        messages.error(request, str(exc))
        return _torna_a_next(request) or redirect("anagrafica:mansionario_mansione", mansione_id=mansione_id)
    if prima is not None:
        log_action(request, "mansionario_livello", MODULE, {
            "mansione": mansione_id, "legacy_anagrafica_id": ab.legacy_anagrafica_id,
            "livello_prima": prima, "livello": ab.livello,
        }, oggetto=ab)
        messages.success(request, f"Livello su «{ab.competenza.nome}»: {prima or '—'} → {ab.livello}.")
    return _torna_a_next(request) or redirect("anagrafica:mansionario_mansione", mansione_id=mansione_id)


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
    # Dalla scheda dipendente (mansioni da rivedere dopo uno spostamento) si torna lì.
    return _torna_a_next(request) or redirect("anagrafica:mansionario_mansione", mansione_id=mansione_id)


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
        return _alla_scheda(mansione.pk, "competenze")
    log_action(request, "mansionario_competenza", MODULE, {
        "mansione": mansione.pk, "competenza": voce.pk, "nome": voce.nome, "livello_minimo": voce.livello_minimo,
        "bloccante": voce.bloccante, "corso": voce.corso_id, "qualifica": voce.qualifica_id, "mod128": voce.processo_mpq_id,
    }, oggetto=mansione)
    messages.success(request, f"Competenza «{voce.nome}» salvata.")
    return _alla_scheda(mansione.pk, "competenze")


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
    return _alla_scheda(mansione_id, "competenze")


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
    valutazione = comp_svc.valuta(ab, voci=competenze)
    # Catalogo unico: il livello già valutato su un'altra mansione si propone qui; più l'ultima modifica.
    from .models import ValutazioneCompetenzaStorico
    from .services.competenze_catalogo import livelli_noti

    noti = livelli_noti(ab.legacy_anagrafica_id, escludi_abilitazione_id=ab.pk)
    ultimi: dict[int, ValutazioneCompetenzaStorico] = {}
    for s in ValutazioneCompetenzaStorico.objects.filter(legacy_anagrafica_id=ab.legacy_anagrafica_id,
                                                         voce_id__in=[v.pk for v in competenze]):
        ultimi.setdefault(s.voce_id, s)
    for r in valutazione.voci:
        noto = noti.get(r["voce"].catalogo_id)
        r["noto"] = noto if noto and noto["livello"] != r["livello"] else None
        r["ultimo"] = ultimi.get(r["voce"].pk)
    return render(request, "anagrafica/pages/mansionario_valuta.html", {
        "page_title": f"Valutazione · {nome}",
        "abilitazione": ab, "mansione": ab.competenza, "nome": nome,
        "valutazione": valutazione,
        "proposte_altrove": sum(1 for r in valutazione.voci if r["noto"] and not r["livello"]),
        "livelli": svc.LIVELLI,
        "da": "refresh" if request.GET.get("da") == "refresh" else "",
        "reparto_refresh": (request.GET.get("reparto") or "").strip(),
    })


@login_required
def mansionario_regole(request):
    """Soglia operativa, regola multi-competenza e minimo uomo solo, con prova d'impatto.

    Stessi valori della configurazione skill matrix: li cambia chi amministra
    l'anagrafica o gestisce la skill matrix. «Prova» non salva; «Applica»
    salva e ricalcola i livelli scritti.
    """
    if not _puo_valutare(request):
        return _nega(request, "Le regole del Mansionario le cambia l'amministrazione dell'anagrafica o della skill matrix.")
    from .models import SkillMatrixConfig
    from .services import mansionario_regole as regole_svc

    config = SkillMatrixConfig.get_instance()
    scelta = {"soglia": config.soglia_operativa, "regola": config.regola_multivoce, "uomo_solo": config.soglia_uomo_solo}
    impatto = None
    if request.method == "POST":
        scelta = {"soglia": request.POST.get("soglia") or "", "regola": request.POST.get("regola") or "",
                  "uomo_solo": request.POST.get("uomo_solo") or ""}
        try:
            if request.POST.get("azione") == "applica":
                esito = regole_svc.applica(scelta["soglia"], scelta["regola"], scelta["uomo_solo"], user=request.user)
                log_action(request, "mansionario_regole", MODULE, esito, oggetto=config)
                messages.success(request, "Regole salvate" + (
                    f": ricalcolato il livello di {esito['ricalcolati']} person{'a' if esito['ricalcolati'] == 1 else 'e'}."
                    if esito["ricalcolati"] else "."))
                return redirect("anagrafica:mansionario_regole")
            impatto = regole_svc.simula(scelta["soglia"], scelta["regola"], scelta["uomo_solo"])
        except ValueError as exc:
            messages.error(request, str(exc))
    return render(request, "anagrafica/pages/mansionario_regole.html", {
        "page_title": "Regole del Mansionario",
        "config": config,
        "scelta": scelta,
        "impatto": impatto,
        "cambia_qualcosa": impatto is not None and (
            scelta["soglia"] != config.soglia_operativa or scelta["regola"] != config.regola_multivoce
            or str(scelta["uomo_solo"]) != str(config.soglia_uomo_solo) or impatto.n_cambi),
        "livelli_label": list(LIVELLO_LABEL.items()),
        "regole_opts": SkillMatrixConfig.REGOLA_MULTIVOCE_CHOICES,
        "max_righe": regole_svc.MAX_RIGHE,
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

    from .services.competenze_catalogo import storico_persona

    righe = fetch_anagrafica_rows(ids=[legacy_id])
    if not righe:
        messages.error(request, "Dipendente non trovato.")
        return redirect("anagrafica:mansionario")
    dip = righe[0]
    puo_valutare = _puo_valutare(request)
    assegnabili, ruoli_persona = [], []
    if puo_valutare:
        from .services.mansioni_in_blocco import mansioni_assegnabili
        from .services.ruoli_in_blocco import ruoli_in_essere
        # Solo le mansioni dei ruoli che la persona ricopre oggi.
        ruoli_persona = [f"«{a.ruolo.nome}»" for a in ruoli_in_essere([legacy_id]).get(legacy_id, [])]
        assegnabili = [{"id": m.pk, "nome": m.nome, "reparto": m.reparto_effettivo,
                        "ruoli": ", ".join(r.nome for r in m.ruoli.all())} for m in mansioni_assegnabili(legacy_id)]
    return render(request, "anagrafica/pages/mansionario_persona.html", {
        "page_title": naming.nome_completo(dip.get("nome"), dip.get("cognome")),
        "legacy_id": legacy_id,
        "nome": naming.nome_completo(dip.get("nome"), dip.get("cognome")),
        "mansione_anagrafica": (dip.get("mansione") or "").strip(),
        "scheda": comp_svc.scheda_persona(legacy_id),
        "storico": storico_persona(legacy_id),
        "storico_mansioni": svc.storico_mansioni_persona(legacy_id),
        "puo_valutare": puo_valutare,
        "assegnabili": assegnabili,
        "ruoli_persona": ruoli_persona,
        "livelli_label": list(LIVELLO_LABEL.items()),
        **_rischi_persona(legacy_id, (dip.get("mansione") or "").strip()),
    })


@login_required
@require_POST
def mansionario_persona_assegna(request, legacy_id: int):
    """Più mansioni alla stessa persona in un colpo, dalla sua scheda del Mansionario."""
    if not _puo_valutare(request):
        return _nega(request, "Non hai i permessi per modificare il Mansionario.")
    from core.legacy_anagrafica import fetch_anagrafica_rows

    from .services import mansioni_in_blocco as mb

    torna = redirect("anagrafica:mansionario_persona", legacy_id=legacy_id)
    if not [r for r in fetch_anagrafica_rows(ids=[legacy_id]) if r.get("attivo", True)]:
        messages.error(request, "Dipendente non trovato o non attivo.")
        return torna
    try:
        esiti = mb.assegna_mansioni(legacy_id, _ids(request, "mansione"), livello=request.POST.get("livello"),
                                    user=request.user)
    except ValueError as exc:
        messages.error(request, str(exc))
        return torna
    fatte = [m for m, azione, _ in esiti if azione == "cambia"]
    errori = [(m, dettaglio) for m, azione, dettaglio in esiti if azione == "errore"]
    log_action(request, "mansionario_persona_assegna", MODULE, {
        "legacy_anagrafica_id": legacy_id, "mansioni": [m.pk for m in fatte],
        "livello": request.POST.get("livello"), "errori": len(errori),
    })
    if fatte:
        messages.success(request, f"Mansione «{fatte[0].nome}» assegnata." if len(fatte) == 1
                         else f"{len(fatte)} mansioni assegnate.")
    if errori:
        messages.error(request, "Non assegnate: " + "; ".join(f"{m.nome} ({d})" for m, d in errori))
    elif not fatte:
        messages.info(request, "Niente da fare: la persona aveva già le mansioni scelte.")
    return torna


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


@login_required
def mansionario_catalogo(request):
    """Catalogo unico delle competenze: chi le usa, rinomina e unione (amministrazione)."""
    if not _puo_vedere(request):
        return _nega(request)
    from .models import CompetenzaCatalogo
    from .services import competenze_catalogo as cat_svc

    is_admin = _puo_gestire(request)
    if request.method == "POST":
        if not is_admin:
            return _nega(request, "Non hai i permessi per modificare il Mansionario.")
        cat = get_object_or_404(CompetenzaCatalogo, pk=_int_o_none(request.POST.get("competenza")) or 0)
        azione = request.POST.get("azione")
        try:
            if azione == "rinomina":
                prima = cat.nome
                n = cat_svc.rinomina(cat, request.POST.get("nome"))
                log_action(request, "competenza_catalogo_rinominata", MODULE,
                           {"competenza": cat.pk, "prima": prima, "nome": cat.nome, "voci": n}, oggetto=cat)
                messages.success(request, f"«{prima}» ora si chiama «{cat.nome}» in {n} mansion{'e' if n == 1 else 'i'}.")
            elif azione == "unisci":
                in_ = get_object_or_404(CompetenzaCatalogo, pk=_int_o_none(request.POST.get("in")) or 0, attiva=True)
                n = cat_svc.unisci(cat, in_)
                log_action(request, "competenza_catalogo_unita", MODULE,
                           {"da": cat.pk, "da_nome": cat.nome, "in": in_.pk, "in_nome": in_.nome, "voci": n}, oggetto=in_)
                messages.success(request, f"«{cat.nome}» unita a «{in_.nome}»: {n} voc{'e' if n == 1 else 'i'} spostat{'a' if n == 1 else 'e'}, livelli e storico restano.")
        except ValueError as exc:
            messages.error(request, str(exc))
        return redirect("anagrafica:mansionario_catalogo")
    righe = cat_svc.elenco()
    q = (request.GET.get("q") or "").strip()
    if q:
        righe = [r for r in righe if q.casefold() in r["catalogo"].nome.casefold()]
    return render(request, "anagrafica/pages/mansionario_catalogo.html", {
        "page_title": "Catalogo competenze",
        "righe": righe, "q": q, "is_admin": is_admin,
        "tutte": [r["catalogo"] for r in cat_svc.elenco()] if is_admin else [],
    })


@login_required
def mansionario_matrice_competenze(request):
    """Persone × competenze del catalogo (livello più alto su qualsiasi mansione), per reparto; Excel."""
    if not _puo_vedere(request):
        return _nega(request)
    from .services import competenze_catalogo as cat_svc

    reparto_id = _int_o_none(request.GET.get("reparto"))
    reparto = Reparto.objects.filter(pk=reparto_id).first() if reparto_id else None
    dati = cat_svc.matrice(reparto.pk if reparto else None)
    if request.GET.get("formato") == "xlsx":
        from core.excel_export import make_xlsx_response

        intestazioni = ["Persona"] + [c.nome for c in dati["colonne"]]
        righe = [[r["nome"], *r["livelli"]] for r in dati["righe"]]
        log_action(request, "matrice_competenze_export", MODULE, {"reparto": reparto.pk if reparto else None,
                                                                  "righe": len(righe)})
        from django.utils import timezone
        from django.utils.text import slugify

        return make_xlsx_response(
            filename=f"matrice-competenze{'-' + slugify(reparto.nome) if reparto else ''}-{timezone.localdate():%Y%m%d}.xlsx",
            columns=intestazioni, rows=righe, sheet_title="Matrice competenze",
            title="Matrice delle competenze", subtitle=f"{reparto.nome if reparto else 'Tutti i reparti'} · livello più "
            f"alto su qualsiasi mansione, al {timezone.localdate():%d/%m/%Y}",
        )
    return render(request, "anagrafica/pages/mansionario_matrice_competenze.html", {
        "page_title": "Matrice delle competenze",
        **dati, "reparto": reparto,
        "reparti": list(Reparto.objects.filter(is_active=True).order_by("nome")),
    })
