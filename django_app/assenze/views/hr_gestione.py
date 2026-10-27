"""Viste del modulo Assenze — area HR: cruscotto, saldi, calendario aziendale, contatori, copertura.

Riservate a chi amministra il modulo (capability ``admin_assenze``, la stessa di
Impostazioni). I calcoli stanno in ``assenze.hr``: qui solo lettura dei form,
salvataggio e contesto per il template ``assenze/pages/hr.html``.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.http import require_http_methods


from .. import hr as calcoli
from ..models import (
    AssenzaModifica,
    ChiusuraAziendale,
    ContatoreAssenza,
    SogliaCopertura,
)
from . import _helpers

logger = logging.getLogger(__name__)

SEZIONI = (
    ("cruscotto", "Cruscotto", "assenze_hr"),
    ("saldi", "Saldi ferie e permessi", "assenze_hr_saldi"),
    ("calendario", "Calendario aziendale", "assenze_hr_calendario"),
    ("contatori", "Contatori", "assenze_hr_contatori"),
    ("copertura", "Copertura reparti", "assenze_hr_copertura"),
)

# Contatori proposti dal pulsante «Aggiungi i contatori consigliati». La
# motivazione va poi allineata al testo esatto usato nelle richieste.
CONTATORI_CONSIGLIATI = (
    {"nome": "Assemblea sindacale", "motivazione": "Assemblea sindacale", "unita": "ore", "limite": Decimal("10"),
     "periodo": "anno"},
    {"nome": "Permessi Legge 104", "motivazione": "Legge 104", "unita": "giorni", "limite": Decimal("3"),
     "periodo": "mese"},
)

# Ferie residue oltre questa quantità di giornate: segnalate in elenco (le ferie
# vanno godute entro i termini del D.Lgs. 66/2003).
GIORNATE_FERIE_ELEVATE = 10


def _puo_gestire(request) -> bool:
    return _helpers.user_can_modulo_action(request, "assenze", "admin_assenze")


def _utente(request) -> str:
    return str(request.user.get_username() or "")[:200]


def _decimale(value) -> Decimal | None:
    testo = str(value if value is not None else "").strip().replace(" ", "")
    if not testo:
        return None
    if "," in testo:
        testo = testo.replace(".", "").replace(",", ".")
    try:
        return Decimal(testo).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def _data(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    testo = str(value or "").strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(testo[:10], fmt).date()
        except ValueError:
            continue
    return None


def _render(request, sezione: str, extra: dict):
    return _helpers.render(
        request,
        "assenze/pages/hr.html",
        {
            "sezione": sezione,
            "sezioni": SEZIONI,
            "is_assenze_admin": True,
            **extra,
            **_helpers._template_perm_context(request),
        },
    )


def _vietato(request):
    return HttpResponseForbidden("Permessi insufficienti: l'area HR delle assenze è riservata a chi amministra il modulo.")


# ─── Cruscotto ───────────────────────────────────────────────────────────────


@login_required
def hr_cruscotto(request):
    if not _puo_gestire(request):
        return _vietato(request)
    dati = calcoli.cruscotto(timezone.localdate())
    massimo = dati["massimo_mese"] or Decimal("1")
    for m in dati["mesi"]:
        m["percentuale"] = int((m["totale"] * 100 / massimo)) if massimo else 0
        m["barre"] = [
            {"categoria": c, "valore": m["valori"][c],
             "percentuale": int(m["valori"][c] * 100 / massimo) if massimo else 0}
            for c in dati["categorie"]
        ]
    saldi = calcoli.saldi_anagrafica(calcoli.dipendenti_attivi())
    res = calcoli.residui(saldi.values())
    soglia_ore = calcoli.impostazioni().ore_giornata * GIORNATE_FERIE_ELEVATE
    return _render(request, "cruscotto", {
        "cruscotto": dati,
        "n_saldi": len(saldi),
        "n_saldi_negativi": sum(1 for r in res.values() if r.ferie_residue < 0 or r.permessi_residui < 0),
        "n_ferie_elevate": sum(1 for r in res.values() if r.ferie_residue >= soglia_ore),
        "giornate_ferie_elevate": GIORNATE_FERIE_ELEVATE,
        "n_contatori_oltre": sum(c["oltre"] for c in calcoli.riepilogo_contatori()),
        "n_in_attesa": len(_helpers._fetch_all_dict(
            "SELECT id FROM assenze WHERE COALESCE(moderation_status, 2) = 2", []
        )) if _helpers._table_exists("assenze") else 0,
    })


# ─── Saldi ───────────────────────────────────────────────────────────────────


@login_required
@require_http_methods(["GET"])
def hr_saldi(request):
    """Saldi in sola lettura: la fonte è l'ultimo cedolino in Anagrafica > Ratei."""
    if not _puo_gestire(request):
        return _vietato(request)
    attivi = calcoli.dipendenti_attivi()
    saldi = calcoli.saldi_anagrafica(attivi)
    res = calcoli.residui(saldi.values())
    imp = calcoli.impostazioni()
    soglia_elevate = imp.ore_giornata * GIORNATE_FERIE_ELEVATE
    righe = []
    for aid in sorted(attivi, key=lambda i: attivi[i]["nominativo"].casefold()):
        r = res.get(aid)
        righe.append({
            "anagrafica_id": aid,
            "nominativo": attivi[aid]["nominativo"],
            "reparto": attivi[aid].get("reparto", ""),
            "saldo": saldi.get(aid),
            "residuo": r,
            "negativo": bool(r and (r.ferie_residue < 0 or r.permessi_residui < 0)),
            "elevate": bool(r and r.ferie_residue >= soglia_elevate),
        })
    date_saldi = sorted({s.situazione_al for s in saldi.values()}, reverse=True)
    return _render(request, "saldi", {
        "righe_saldi": righe,
        "n_con_saldo": len(saldi),
        "n_senza_saldo": len(attivi) - len(saldi),
        "n_negativi": sum(1 for r in righe if r["negativo"]),
        "n_elevate": sum(1 for r in righe if r["elevate"]),
        "ultimo_cedolino": date_saldi[0] if date_saldi else None,
        "giornate_ferie_elevate": GIORNATE_FERIE_ELEVATE,
        "ore_giornata": imp.ore_giornata,
    })


# ─── Calendario aziendale e impostazioni ─────────────────────────────────────


def _salva_impostazioni(request) -> None:
    imp = calcoli.impostazioni()
    ore = _decimale(request.POST.get("ore_giornata"))
    if ore is None or not (Decimal("1") <= ore <= Decimal("24")):
        messages.error(request, "Le ore di una giornata devono stare fra 1 e 24.")
        return
    giorno = _helpers._as_int(request.POST.get("patrono_giorno"))
    mese = _helpers._as_int(request.POST.get("patrono_mese"))
    if (giorno or mese) and not (giorno and mese):
        messages.error(request, "Per il patrono servono sia il giorno sia il mese.")
        return
    if giorno and mese:
        try:
            date(2024, mese, giorno)
        except ValueError:
            messages.error(request, "La data del patrono non esiste.")
            return
    dopo = _helpers._as_int(request.POST.get("sollecito_dopo_giorni"))
    ripeti = _helpers._as_int(request.POST.get("sollecito_ripeti_giorni"))
    if dopo is None or ripeti is None or not (1 <= dopo <= 60) or not (1 <= ripeti <= 60):
        messages.error(request, "I giorni dei solleciti devono stare fra 1 e 60.")
        return
    imp.ore_giornata = ore
    imp.sabato_lavorativo = request.POST.get("sabato_lavorativo") == "1"
    imp.patrono_giorno = giorno or None
    imp.patrono_mese = mese or None
    imp.patrono_nome = str(request.POST.get("patrono_nome") or "").strip()[:100]
    imp.sollecito_attivo = request.POST.get("sollecito_attivo") == "1"
    imp.sollecito_dopo_giorni = dopo
    imp.sollecito_ripeti_giorni = ripeti
    imp.outlook_capo_attivo = request.POST.get("outlook_capo_attivo") == "1"
    if request.POST.get("outlook_capo_modo") in ("richiesta", "tutte"):
        imp.outlook_capo_modo = request.POST["outlook_capo_modo"]
    imp.updated_by = _utente(request)
    imp.save()
    _helpers.log_action(request, "assenze_impostazioni_hr", "assenze", {
        "ore_giornata": str(ore), "sabato_lavorativo": imp.sabato_lavorativo,
        "patrono": f"{giorno}/{mese}" if giorno else "", "sollecito_attivo": imp.sollecito_attivo,
        "sollecito_dopo_giorni": dopo, "sollecito_ripeti_giorni": ripeti,
        "outlook_capo_attivo": imp.outlook_capo_attivo, "outlook_capo_modo": imp.outlook_capo_modo,
    })
    messages.success(request, "Impostazioni salvate.")


@login_required
@require_http_methods(["GET", "POST"])
def hr_calendario(request):
    if not _puo_gestire(request):
        return _vietato(request)
    if request.method == "POST":
        azione = str(request.POST.get("form") or "")
        if azione == "impostazioni":
            _salva_impostazioni(request)
        elif azione == "chiusura_elimina":
            ch = ChiusuraAziendale.objects.filter(pk=_helpers._as_int(request.POST.get("id"))).first()
            if ch is not None:
                _helpers.log_action(request, "assenze_chiusura_eliminata", "assenze", {
                    "descrizione": ch.descrizione, "dal": ch.data_inizio.isoformat(), "al": ch.data_fine.isoformat(),
                })
                ch.delete()
                messages.success(request, "Chiusura eliminata.")
        else:
            dal = _data(request.POST.get("data_inizio"))
            al = _data(request.POST.get("data_fine")) or dal
            descrizione = str(request.POST.get("descrizione") or "").strip()[:200]
            if dal is None or al is None or al < dal or not descrizione:
                messages.error(request, "Indica descrizione, data di inizio e una data di fine non precedente.")
            else:
                ChiusuraAziendale.objects.create(
                    data_inizio=dal, data_fine=al, descrizione=descrizione,
                    scala_ferie=request.POST.get("scala_ferie") == "1", created_by=_utente(request),
                )
                _helpers.log_action(request, "assenze_chiusura_aggiunta", "assenze", {
                    "descrizione": descrizione, "dal": dal.isoformat(), "al": al.isoformat(),
                })
                messages.success(request, f"Chiusura «{descrizione}» aggiunta.")
        return redirect("assenze_hr_calendario")

    anno = _helpers._as_int(request.GET.get("anno")) or timezone.localdate().year
    anno = min(max(anno, 2000), 2100)
    imp = calcoli.impostazioni()
    cal = calcoli.calendario(date(anno, 1, 1), date(anno, 12, 31), imp)
    chiusure = []
    for ch in ChiusuraAziendale.objects.order_by("-data_inizio"):
        giorni = calcoli.calendario(ch.data_inizio, ch.data_fine, imp)
        lavorativi = [d for d in giorni.chiusure if giorni.settimanale(d) and d not in giorni.festivi]
        chiusure.append({"obj": ch, "giorni_lavorativi": len(lavorativi)})
    festivita = [
        {"data": d, "nome": nome, "feriale": cal.settimanale(d)}
        for d, nome in sorted(calcoli.festivita(anno, imp).items())
    ]
    from .. import outlook_sync

    return _render(request, "calendario", {
        "imp": imp,
        "outlook": outlook_sync.stato(),
        "anno": anno,
        "anno_prec": anno - 1,
        "anno_succ": anno + 1,
        "festivita": festivita,
        "chiusure": chiusure,
        "giorni_lavorativi_anno": len(cal.giorni_lavorativi(date(anno, 1, 1), date(anno, 12, 31))),
        "mesi": [(i, nome) for i, nome in enumerate(
            ("gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto",
             "settembre", "ottobre", "novembre", "dicembre"), start=1)],
    })


# ─── Contatori ───────────────────────────────────────────────────────────────


@login_required
@require_http_methods(["GET", "POST"])
def hr_contatori(request):
    if not _puo_gestire(request):
        return _vietato(request)
    if request.method == "POST":
        azione = str(request.POST.get("form") or "")
        if azione == "consigliati":
            creati = 0
            for c in CONTATORI_CONSIGLIATI:
                if not ContatoreAssenza.objects.filter(motivazione__iexact=c["motivazione"]).exists():
                    ContatoreAssenza.objects.create(**c, updated_by=_utente(request))
                    creati += 1
            messages.success(request, f"Contatori aggiunti: {creati}." if creati else "I contatori consigliati ci sono già.")
        elif azione == "elimina":
            cont = ContatoreAssenza.objects.filter(pk=_helpers._as_int(request.POST.get("id"))).first()
            if cont is not None:
                _helpers.log_action(request, "assenze_contatore_eliminato", "assenze", {"nome": cont.nome})
                cont.delete()
                messages.success(request, "Contatore eliminato.")
        else:
            cont = ContatoreAssenza.objects.filter(pk=_helpers._as_int(request.POST.get("id"))).first() or ContatoreAssenza()
            nome = str(request.POST.get("nome") or "").strip()[:100]
            motivazione = str(request.POST.get("motivazione") or "").strip()[:200]
            limite = _decimale(request.POST.get("limite"))
            unita = request.POST.get("unita")
            periodo = request.POST.get("periodo")
            if not nome or not motivazione or limite is None or limite <= 0 \
                    or unita not in dict(ContatoreAssenza.UNITA_CHOICES) \
                    or periodo not in dict(ContatoreAssenza.PERIODO_CHOICES):
                messages.error(request, "Compila nome, motivazione, un limite maggiore di zero, unità e periodo.")
            else:
                cont.nome, cont.motivazione, cont.limite = nome, motivazione, limite
                cont.unita, cont.periodo = unita, periodo
                cont.attivo = request.POST.get("attivo") == "1"
                cont.updated_by = _utente(request)
                cont.save()
                _helpers.log_action(request, "assenze_contatore_salvato", "assenze", {
                    "nome": nome, "motivazione": motivazione, "limite": str(limite), "unita": unita, "periodo": periodo,
                })
                messages.success(request, f"Contatore «{nome}» salvato.")
        return redirect("assenze_hr_contatori")

    from .richieste import _motivazioni_options

    usate = set()
    if _helpers._table_exists("assenze"):
        for r in _helpers._fetch_all_dict(
            "SELECT DISTINCT motivazione_richiesta FROM assenze WHERE motivazione_richiesta IS NOT NULL", []
        ):
            testo = _helpers._strip_tipo_metadata_from_motivazione(r.get("motivazione_richiesta"))
            if testo and len(testo) <= 80:
                usate.add(testo)
    motivazioni = sorted(set(_motivazioni_options()) | usate, key=str.casefold)
    return _render(request, "contatori", {
        "contatori": list(ContatoreAssenza.objects.all()),
        "riepilogo": calcoli.riepilogo_contatori(timezone.localdate()),
        "motivazioni": motivazioni,
        "unita_choices": ContatoreAssenza.UNITA_CHOICES,
        "periodo_choices": ContatoreAssenza.PERIODO_CHOICES,
    })


# ─── Copertura ───────────────────────────────────────────────────────────────


@login_required
@require_http_methods(["GET", "POST"])
def hr_copertura(request):
    if not _puo_gestire(request):
        return _vietato(request)
    attivi = calcoli.dipendenti_attivi()
    persone: dict[str, int] = {}
    nomi: dict[str, str] = {}
    for d in attivi.values():
        if d["reparto"]:
            k = calcoli.chiave_reparto(d["reparto"])
            persone[k] = persone.get(k, 0) + 1
            nomi.setdefault(k, d["reparto"])
    soglie = {calcoli.chiave_reparto(s.reparto): s for s in SogliaCopertura.objects.all()}
    for k, s in soglie.items():
        nomi.setdefault(k, s.reparto)

    if request.method == "POST":
        salvate, tolte = 0, 0
        for k, nome in nomi.items():
            valore = str(request.POST.get(f"soglia__{k}") or "").strip()
            esistente = soglie.get(k)
            if not valore:
                if esistente is not None:
                    esistente.delete()
                    tolte += 1
                continue
            n = _helpers._as_int(valore)
            if n is None or n < 0 or n > 999:
                messages.error(request, f"Soglia non valida per {nome}.")
                continue
            if esistente is None or esistente.max_assenti != n:
                SogliaCopertura.objects.update_or_create(
                    reparto=esistente.reparto if esistente else nome,
                    defaults={"max_assenti": n, "updated_by": _utente(request)},
                )
                salvate += 1
        _helpers.log_action(request, "assenze_soglie_copertura", "assenze", {"salvate": salvate, "tolte": tolte})
        messages.success(request, f"Soglie aggiornate: {salvate} salvate, {tolte} tolte.")
        return redirect("assenze_hr_copertura")

    righe = [
        {"chiave": k, "reparto": nomi[k], "persone": persone.get(k, 0), "soglia": soglie.get(k)}
        for k in sorted(nomi, key=lambda x: nomi[x].casefold())
    ]
    return _render(request, "copertura", {"righe_copertura": righe})


# ─── Storico di una richiesta ────────────────────────────────────────────────


@login_required
@require_http_methods(["GET"])
def api_storico(request, item_id: int):
    """Storico di una richiesta per chi può gestirla, per l'Amministrazione e per l'interessato."""
    perms = _helpers._assenze_permissions(request)
    current = _helpers._get_assenza(item_id)
    consentito = _puo_gestire(request) or perms.get("can_update_any")
    if not consentito and current is not None:
        consentito = _helpers._can_manage_record(request, current) or _helpers._e_mia_richiesta(request, current)
    if not consentito:
        return _helpers._json_error("Permessi insufficienti: non puoi vedere lo storico di questa richiesta.", status=403)
    voci = [
        {
            "quando": timezone.localtime(m.quando).strftime("%d/%m/%Y %H:%M"),
            "utente": m.utente,
            "azione": m.get_azione_display(),
            "modifiche": m.modifiche or [],
            "motivo": m.motivo,
        }
        for m in AssenzaModifica.objects.filter(assenza_id=item_id)[:100]
    ]
    return JsonResponse({"ok": True, "item_id": item_id, "voci": voci})


@login_required
@require_http_methods(["GET"])
def api_verifica_richiesta(request):
    """Controlli HR live per il form di richiesta: saldo, contatori, chiusure. Non bloccano l'invio.

    Senza ``dipendente_id`` vale per chi compila; con ``dipendente_id`` solo per
    chi può inserire richieste per quel dipendente.
    """
    perms = _helpers._assenze_permissions(request)
    if not perms.get("can_insert"):
        return _helpers._json_error("Permessi insufficienti.", status=403)
    dip_id = _helpers._as_int(request.GET.get("dipendente_id"))
    if dip_id is not None:
        if not perms.get("can_insert_for_others") or not _helpers._can_insert_for_dipendente(request, dip_id):
            return _helpers._json_error("Permessi insufficienti per questo dipendente.", status=403)
        anagrafica_id = dip_id
    else:
        name, email, legacy_id = _helpers._legacy_identity(request)
        anagrafica_id = _helpers._resolve_anagrafica_employee_id_for_user(
            legacy_user_id=legacy_id, email=email, username=request.user.get_username(), name=name,
        )
    tipo = _helpers._norm_tipo(request.GET.get("tipo"))
    inizio = _helpers._parse_input_dt(request.GET.get("inizio"))
    fine = _helpers._parse_input_dt(request.GET.get("fine"))
    avvisi = []
    if inizio is not None and fine is not None:
        avvisi = calcoli.avvisi_richiesta(
            anagrafica_id=anagrafica_id, tipo=tipo, motivazione=request.GET.get("motivazione") or "",
            inizio=inizio, fine=fine,
        )
    return JsonResponse({"ok": True, "saldo": calcoli.riepilogo_saldo(anagrafica_id), "avvisi": avvisi})
