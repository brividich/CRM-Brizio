"""Viste anagrafica — Qualifiche, skill matrix e DPI.

Spacchettamento di ``anagrafica/views.py`` (18/10/2026): le funzioni condivise stanno in
``_helpers`` e si chiamano ``_helpers.nome`` così i test patchano un solo punto.
"""
from __future__ import annotations

import logging

from django.contrib import messages
from django.db.models import Count, Q
from django.http import (
    HttpResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
# Alias esplicito: in questo file `timezone` è già importato dentro varie
# funzioni (come `tz`/`_tz`) e `datetime.timezone` è un'altra cosa ancora.
from django.views.decorators.http import require_POST

from django.contrib.auth.decorators import login_required
from core import naming
from core.csv_export import BOM, CSV_CONTENT_TYPE, safe_csv_writer
from core.legacy_anagrafica import (
    fetch_anagrafica_rows,
)
from core.legacy_utils import get_legacy_user
from core.permessi.impostazioni import impostazioni_o

from ..models import (
    DipendenteQualifica,
    QualificaSessione,
    TipoQualifica,
)


from . import _helpers  # noqa: E402

logger = logging.getLogger(__name__)


def _check_skm_permission(request, code: str) -> bool:
    """Permesso canonico Skill Matrix MOD.187 (governabile in /admin-portale/acl-canonico/).

    Bypass per superuser/admin legacy; altrimenti richiede il grant del ruolo sul
    ``code`` canonico (``anagrafica.skillmatrix.view`` / ``.manage``). Allinea la
    guardia in-view alla decisione del middleware ACL canonico, così ciò che si
    imposta in ACL canonico governa davvero l'accesso (in dev/test il middleware è
    disattivo: qui resta l'unico controllo).
    """
    from core.acl_v2 import evaluate_permission_code_access
    try:
        legacy_user = get_legacy_user(request.user)
    except Exception:
        legacy_user = None
    return bool(evaluate_permission_code_access(
        permission_code=code, legacy_user=legacy_user, django_user=request.user,
    ).get("allowed"))


# ---------------------------------------------------------------------------
# Qualifiche — gestione catalogo + panoramica scadenze
# ---------------------------------------------------------------------------

@login_required
def qualifiche_list(request):
    from datetime import timedelta
    from django.utils import timezone as tz

    legacy_user = get_legacy_user(request.user)
    is_admin = _helpers._is_anagrafica_admin(request)

    # Catalogo unico, viste filtrate per categoria: la pagina è la "casa" delle
    # qualifiche (modulo Formazione) ma può aprirsi già filtrata (es. Salute e
    # Sicurezza → ?categoria=SICUREZZA).
    # Pseudo-categoria virtuale per i Processi qualificati MOD.128: NON è una choice
    # del modello (riusa i ProcessoQualificato caricati più sotto), quindi vive solo
    # come voce di tab + flag di visibilità. Nessuna migrazione (stream 3).
    CAT_PROCESSI, LBL_PROCESSI = "PROCESSI", "Processi qualificati"
    valid_cats = {c for c, _ in TipoQualifica.CATEGORIA_CHOICES} | {CAT_PROCESSI}
    cat_filter = (request.GET.get("categoria") or "").strip().upper()
    if cat_filter not in valid_cats:
        cat_filter = ""

    tipi = list(
        TipoQualifica.objects.annotate(n_assegnazioni=Count("assegnazioni"))
        .prefetch_related("corsi")  # corso(i) che rilasciano la qualifica (Step 3)
        .order_by("categoria", "nome")
    )

    oggi = tz.localdate()
    soglia = oggi + timedelta(days=60)

    # Qualifiche in scadenza o scadute
    scadenze_qs = list(
        DipendenteQualifica.objects.filter(data_scadenza__isnull=False)
        .filter(data_scadenza__lte=soglia)
        .select_related("tipo")
        .order_by("data_scadenza")
    )

    # Arricchisce con nome dipendente
    legacy_ids = list({q.legacy_anagrafica_id for q in scadenze_qs})
    nome_map: dict[int, str] = {}
    if legacy_ids:
        try:
            rows = fetch_anagrafica_rows(ids=legacy_ids)
            for r in rows:
                rid = int(r.get("id") or 0)
                if rid:
                    nome_map[rid] = naming.nome_completo(r.get("nome"), r.get("cognome"))
        except Exception:
            pass

    scadenze = []
    for q in scadenze_qs:
        scadenze.append({
            "id": q.id,
            "legacy_anagrafica_id": q.legacy_anagrafica_id,
            "dipendente": nome_map.get(q.legacy_anagrafica_id, f"Dip. #{q.legacy_anagrafica_id}"),
            "tipo_nome": q.tipo.nome,
            "tipo_categoria": q.tipo.categoria,
            "data_conseguimento": q.data_conseguimento,
            "data_scadenza": q.data_scadenza,
            "scaduta": q.data_scadenza < oggi,
            "in_scadenza": oggi <= q.data_scadenza <= soglia,
            "note": q.note,
        })

    tipi_suggeriti = [
        ("Patentino carrellista", "PROFESSIONALE", 60),
        ("Primo soccorso", "SICUREZZA", 36),
        ("Addetto antincendio (livello 1)", "SICUREZZA", 60),
        ("Addetto antincendio (livello 2)", "SICUREZZA", 60),
        ("Addetto antincendio (livello 3)", "SICUREZZA", 60),
        ("RSPP", "SICUREZZA", 60),
        ("RLS", "SICUREZZA", 60),
        ("Preposto sicurezza", "SICUREZZA", 60),
        ("Uso DPI anticaduta", "SICUREZZA", 60),
    ]

    # Raggruppa tipi per categoria
    cat_order_q = [c for c, _ in TipoQualifica.CATEGORIA_CHOICES]
    cat_labels_q = dict(TipoQualifica.CATEGORIA_CHOICES)
    tipi_grouped: list[tuple[str, str, list]] = []
    for cat_code in cat_order_q:
        items = [t for t in tipi if t.categoria == cat_code]
        if items:
            tipi_grouped.append((cat_code, cat_labels_q[cat_code], items))

    # Barra tab "Tutte + categorie" con conteggi (sempre su tutto il catalogo).
    tabs = [("", "Tutte", len(tipi))]
    for cat_code in cat_order_q:
        tabs.append((cat_code, cat_labels_q[cat_code],
                     sum(1 for t in tipi if t.categoria == cat_code)))

    # Vista filtrata: restringe gruppi e scadenze alla categoria selezionata.
    if cat_filter:
        tipi_grouped = [g for g in tipi_grouped if g[0] == cat_filter]
        scadenze = [s for s in scadenze if s["tipo_categoria"] == cat_filter]

    # Processi qualificati MOD.128 (modulo additivo, fail-safe): mostrati nel
    # catalogo come famiglia a sé, così si vedono nella sezione Qualifiche.
    processi_qualificati = []
    try:
        from ..models_mpq import ProcessoQualificato as _PQ
        processi_qualificati = list(
            _PQ.objects.select_related("cliente")
            .annotate(n_abil=Count("abilitazioni", distinct=True))
            .order_by("cliente__nome", "nome")
        )
    except Exception:
        processi_qualificati = []

    # Chip virtuale "Processi qualificati": voce di tab (con conteggio MOD.128) +
    # flag di visibilità. `mostra_processi` regge la sezione MOD.128 (Tutte + filtro
    # PROCESSI); `solo_processi` nasconde il catalogo tipi quando si filtra su PROCESSI.
    # Con cat_filter == "PROCESSI" il blocco `if cat_filter:` ha già svuotato
    # tipi_grouped e scadenze (nessun gruppo/scadenza ha quella categoria).
    tabs.append((CAT_PROCESSI, LBL_PROCESSI, len(processi_qualificati)))
    mostra_processi = cat_filter in ("", CAT_PROCESSI)
    solo_processi = cat_filter == CAT_PROCESSI

    return render(request, "anagrafica/pages/qualifiche_list.html", {
        "tipi": tipi,
        "tipi_grouped": tipi_grouped,
        "processi_qualificati": processi_qualificati,
        "mostra_processi": mostra_processi,
        "solo_processi": solo_processi,
        "scadenze": scadenze,
        "is_admin": is_admin,
        "oggi": oggi,
        "CATEGORIA_CHOICES": TipoQualifica.CATEGORIA_CHOICES,
        "tipi_suggeriti": tipi_suggeriti,
        "tabs": tabs,
        "active_categoria": cat_filter,
        "active_categoria_label": LBL_PROCESSI if cat_filter == CAT_PROCESSI else cat_labels_q.get(cat_filter, ""),
        "is_safety_view": cat_filter == TipoQualifica.CAT_SICUREZZA,
    })


def _classifica_scadenza_qualifica(data_scadenza, oggi, soglia_30, soglia_60):
    """Stato RAG di una qualifica in base alla scadenza. Fonte unica per
    cruscotto e scadenzario dedicato (coerente con matrice/scadenzario unificato)."""
    if data_scadenza is None:
        return ("permanente", "Permanente")
    if data_scadenza < oggi:
        return ("scaduta", "Scaduta")
    if data_scadenza <= soglia_30:
        return ("s30", "In scadenza ≤30gg")
    if data_scadenza <= soglia_60:
        return ("s60", "In scadenza ≤60gg")
    return ("valida", "Valida")


@login_required
def qualifiche_dashboard(request):
    """Cruscotto Qualifiche & Certificazioni — vista trasversale di sola lettura.

    AGGREGA (non duplica) i tre modelli sorgente — ``TipoQualifica``,
    ``DipendenteQualifica``, ``QualificaSessione`` — le stesse fonti usate da
    Formazione, ``matrice_competenze``, ``conformita_report`` e dalla scheda
    dipendente: qualsiasi rilascio/rinnovo fatto altrove si riflette qui.

    Le scadenze (promemoria email) restano gestite dal modulo automazioni
    (report settimanale + pacchetto ``au12``): il cruscotto le mostra e linka
    alla loro configurazione, non le ridefinisce.
    """
    from datetime import timedelta
    from collections import OrderedDict
    from django.utils import timezone as _tz

    oggi = _tz.localdate()
    soglia_30 = oggi + timedelta(days=30)
    soglia_60 = oggi + timedelta(days=60)
    is_admin = _helpers._is_anagrafica_admin(request)

    tipi_attivi = TipoQualifica.objects.filter(is_active=True).count()

    quals = list(DipendenteQualifica.objects.select_related("tipo").all())
    n_valide = n_scadute = n_s30 = n_s60 = n_permanenti = 0
    n_con_evidenza = n_da_verificare = 0
    dipendenti_ids: set[int] = set()
    cat_labels = dict(TipoQualifica.CATEGORIA_CHOICES)
    dist_cat = {c: 0 for c, _ in TipoQualifica.CATEGORIA_CHOICES}

    # Timeline scadenze prossimi 12 mesi
    buckets: "OrderedDict[tuple[int, int], int]" = OrderedDict()
    yy, mm = oggi.year, oggi.month
    for _ in range(12):
        buckets[(yy, mm)] = 0
        mm += 1
        if mm > 12:
            mm, yy = 1, yy + 1
    primo_del_mese = oggi.replace(day=1)

    for q in quals:
        dipendenti_ids.add(q.legacy_anagrafica_id)
        if q.tipo.categoria in dist_cat:
            dist_cat[q.tipo.categoria] += 1
        if q.documento:
            n_con_evidenza += 1
            if not q.verificata:
                n_da_verificare += 1
        d = q.data_scadenza
        if d is None:
            n_permanenti += 1
            n_valide += 1
        elif d < oggi:
            n_scadute += 1
        elif d <= soglia_30:
            n_s30 += 1
        elif d <= soglia_60:
            n_s60 += 1
        else:
            n_valide += 1
        if d and d >= primo_del_mese and (d.year, d.month) in buckets:
            buckets[(d.year, d.month)] += 1

    mesi_abbr = ["gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"]
    max_n = max(buckets.values()) if buckets else 0
    timeline = [
        {"label": f"{mesi_abbr[m - 1]} {str(y)[2:]}", "n": n,
         "pct": int(round(n / max_n * 100)) if max_n else 0}
        for (y, m), n in buckets.items()
    ]

    distribuzione = [
        {"code": c, "label": cat_labels[c], "n": dist_cat[c]}
        for c, _ in TipoQualifica.CATEGORIA_CHOICES if dist_cat[c]
    ]

    # Top scadenze urgenti (scadute + ≤60gg)
    nomi = _helpers._build_nomi_map()
    urgenti = sorted(
        (q for q in quals if q.data_scadenza is not None and q.data_scadenza <= soglia_60),
        key=lambda q: q.data_scadenza,
    )[:15]
    scadenze_urgenti = []
    for q in urgenti:
        stato_code, stato_label = _classifica_scadenza_qualifica(q.data_scadenza, oggi, soglia_30, soglia_60)
        scadenze_urgenti.append({
            "legacy_id": q.legacy_anagrafica_id,
            "dipendente": nomi.get(q.legacy_anagrafica_id, f"#{q.legacy_anagrafica_id}"),
            "tipo_id": q.tipo_id,
            "tipo_nome": q.tipo.nome,
            "categoria": q.tipo.get_categoria_display(),
            "data_scadenza": q.data_scadenza,
            "giorni": (q.data_scadenza - oggi).days,
            "stato": stato_code,
            "stato_label": stato_label,
        })

    # Prossime sessioni di rilascio/rinnovo collettivo
    prossime_sessioni = list(
        QualificaSessione.objects.select_related("tipo")
        .filter(data_conseguimento__gte=oggi)
        .order_by("data_conseguimento")[:8]
    )

    # MOD.128 — riepilogo processi qualificati (modulo additivo, fail-safe).
    mpq = None
    try:
        from ..models_mpq import ProcessoQualificato as _PQ
        _procs = list(_PQ.objects.all())
        _mpq_scaduti = _mpq_scad60 = 0
        for _p in _procs:
            _se = _p.scadenza_effettiva
            if _se is None:
                continue
            if _se < oggi:
                _mpq_scaduti += 1
            elif _se <= soglia_60:
                _mpq_scad60 += 1
        mpq = {
            "n": len(_procs),
            "attivi": sum(1 for _p in _procs if _p.stato == "ATTIVO"),
            "scaduti": _mpq_scaduti,
            "in_scadenza": _mpq_scad60,
        }
    except Exception:
        mpq = None

    # Stile C: una scheda per tipo di qualifica (stessa classificazione dei KPI).
    from ..services import sezioni_c
    prossime_per_tipo: dict[int, QualificaSessione] = {}
    for s in sorted(prossime_sessioni, key=lambda s: s.data_conseguimento):
        prossime_per_tipo.setdefault(s.tipo_id, s)
    schede = sezioni_c.schede_qualifiche(
        quals, oggi=oggi, soglia_30=soglia_30, soglia_60=soglia_60, prossime_per_tipo=prossime_per_tipo,
    )
    presenti = {s["tags"] for s in schede}
    copertura_qualifiche = sezioni_c.griglia(
        id="fmd-qualifiche", titolo="Qualifiche per tipo", icona="i-cap",
        aside="Persone abilitate per tipo · clic per lo scadenzario del tipo",
        schede=schede,
        filtri=[("", f"Tutte · {len(quals)}")] + [
            (c, f"{cat_labels[c]} · {dist_cat[c]}") for c, _ in TipoQualifica.CATEGORIA_CHOICES
            if sezioni_c.tag_slug(c) in presenti
        ],
        etichetta_filtri="Filtra per categoria",
        ordini=[("gap", "Prima le più scoperte"), ("az", "A–Z")],
        legenda=[("ok", "valide"), ("s90", "≤60gg"), ("s30", "≤30gg"), ("ko", "scadute")],
        vuoto_titolo="Nessuna qualifica registrata",
        vuoto_testo="Le schede compaiono quando si assegna una qualifica a un dipendente.",
    )
    aree = sezioni_c.aree_visibili(request, [
        sezioni_c.Area("anagrafica:qualifiche_list", "Catalogo qualifiche", "Tipi · categorie · validità", icona="i-cap"),
        sezioni_c.Area("anagrafica:qualifiche_scadenzario", "Scadenzario qualifiche", "Scadute · ≤30gg · ≤60gg · export", icona="i-alarm"),
        sezioni_c.Area("anagrafica:matrice_competenze", "Matrice qualifiche", "Dipendenti × abilitazioni (ISO 45001)", icona="i-grid"),
        sezioni_c.Area("anagrafica:qualifica_sessioni_list", "Sessioni di rinnovo", "Rilascio/rinnovo collettivo", icona="i-calendar"),
        sezioni_c.Area("anagrafica:mpq_cruscotto", "Processi qualificati (MOD.128)", "Processi speciali · abilitati per ruolo · doppia scadenza", icona="i-clipboard"),
        sezioni_c.Area("anagrafica:conformita_report", "Conformità / idoneità", "Gap qualifiche obbligatorie per mansione", icona="i-shield"),
        sezioni_c.Area("automazioni:automazioni_settings", "Promemoria scadenze", "Report email settimanale (modulo automazioni)", icona="i-gear"),
    ])

    return render(request, "anagrafica/pages/qualifiche_dashboard.html", {
        "oggi": oggi,
        "is_admin": is_admin,
        "copertura_qualifiche": copertura_qualifiche,
        "aree": aree,
        "mpq": mpq,
        "tipi_attivi": tipi_attivi,
        "tot_assegnazioni": len(quals),
        "dipendenti_con_qualifica": len(dipendenti_ids),
        "n_valide": n_valide,
        "n_scadute": n_scadute,
        "n_in_scadenza": n_s30 + n_s60,
        "n_s30": n_s30,
        "n_permanenti": n_permanenti,
        "n_con_evidenza": n_con_evidenza,
        "n_da_verificare": n_da_verificare,
        "distribuzione": distribuzione,
        "timeline": timeline,
        "scadenze_urgenti": scadenze_urgenti,
        "prossime_sessioni": prossime_sessioni,
    })


def _raggruppa_voci_per_tipo(voci, *, tipo_of, scaduta_of, giorni_of):
    """Raggruppa voci di scadenzario per «tipo» (vista a gruppi espandibili).

    Generico: ``tipo_of``/``scaduta_of``/``giorni_of`` estraggono da ogni voce
    il nome-tipo, il flag «scaduta» e i giorni residui. Ordina le voci coi più
    urgenti in cima e i gruppi con scadute per primi. Riusato dagli scadenzari
    qualifiche e skill-matrix (lo scadenzario anagrafica ha il proprio helper).
    """
    from collections import OrderedDict

    buckets = OrderedDict()
    for v in voci:
        buckets.setdefault(tipo_of(v) or "—", []).append(v)
    gruppi = []
    for tipo_nome, gv in buckets.items():
        gv_sorted = sorted(gv, key=lambda x: (not scaduta_of(x), giorni_of(x)))
        n_scadute = sum(1 for x in gv if scaduta_of(x))
        worst = min((giorni_of(x) for x in gv), default=99999)
        gruppi.append({
            "tipo_nome": tipo_nome,
            "voci": gv_sorted,
            "n_totale": len(gv),
            "n_scadute": n_scadute,
            "worst_giorni": worst,
            "has_scadute": n_scadute > 0,
        })
    gruppi.sort(key=lambda g: (not g["has_scadute"], g["worst_giorni"], str(g["tipo_nome"]).lower()))
    return gruppi


@login_required
def qualifiche_scadenzario(request):
    """Scadenzario dedicato alle sole qualifiche/certificazioni.

    È lo ``scadenzario`` unificato ristretto alle qualifiche, ma più ricco:
    filtri per stato / categoria / reparto / tipo ed export CSV. Legge le stesse
    ``DipendenteQualifica`` di tutto il resto: nessun dato duplicato.
    """
    from datetime import timedelta
    from django.utils import timezone as _tz

    oggi = _tz.localdate()
    soglia_30 = oggi + timedelta(days=30)
    soglia_60 = oggi + timedelta(days=60)

    filtro_stato = (request.GET.get("stato") or "").strip()      # scaduta/30/60/valide/tutte/""
    filtro_cat = (request.GET.get("categoria") or "").strip().upper()
    filtro_reparto = (request.GET.get("reparto") or "").strip()
    filtro_tipo = (request.GET.get("tipo") or "").strip()
    export_csv = request.GET.get("format") == "csv"
    valid_cats = {c for c, _ in TipoQualifica.CATEGORIA_CHOICES}
    if filtro_cat not in valid_cats:
        filtro_cat = ""

    dip_rows = fetch_anagrafica_rows(deduplicate=True)
    dip_map = {int(r["id"]): r for r in dip_rows if r.get("id")}

    qs = DipendenteQualifica.objects.select_related("tipo")
    if filtro_cat:
        qs = qs.filter(tipo__categoria=filtro_cat)
    if filtro_tipo.isdigit():
        qs = qs.filter(tipo_id=int(filtro_tipo))

    # Filtro stato lato DB
    if filtro_stato == "scaduta":
        qs = qs.filter(data_scadenza__isnull=False, data_scadenza__lt=oggi)
    elif filtro_stato == "30":
        qs = qs.filter(data_scadenza__gte=oggi, data_scadenza__lte=soglia_30)
    elif filtro_stato == "60":
        qs = qs.filter(data_scadenza__gte=oggi, data_scadenza__lte=soglia_60)
    elif filtro_stato == "valide":
        qs = qs.filter(Q(data_scadenza__isnull=True) | Q(data_scadenza__gt=soglia_60))
    elif filtro_stato == "tutte":
        pass
    else:  # default: tutto ciò che richiede attenzione (scadute + ≤60gg)
        qs = qs.filter(data_scadenza__isnull=False, data_scadenza__lte=soglia_60)

    qs = qs.order_by("data_scadenza", "tipo__nome")

    nomi = _helpers._build_nomi_map()
    voci: list[dict] = []
    counts = {"scaduta": 0, "s30": 0, "s60": 0, "valida": 0, "permanente": 0}
    for q in qs:
        dip = dip_map.get(q.legacy_anagrafica_id, {})
        reparto = str(dip.get("reparto") or "").strip()
        if filtro_reparto and reparto.casefold() != filtro_reparto.casefold():
            continue
        stato_code, stato_label = _classifica_scadenza_qualifica(q.data_scadenza, oggi, soglia_30, soglia_60)
        counts[stato_code] = counts.get(stato_code, 0) + 1
        voci.append({
            "legacy_id": q.legacy_anagrafica_id,
            "dipendente": nomi.get(q.legacy_anagrafica_id, f"#{q.legacy_anagrafica_id}"),
            "reparto": reparto,
            "tipo_nome": q.tipo.nome,
            "tipo_id": q.tipo_id,
            "categoria": q.tipo.get_categoria_display(),
            "numero": q.numero,
            "livello": q.livello,
            "ente": q.ente,
            "data_conseguimento": q.data_conseguimento,
            "data_scadenza": q.data_scadenza,
            "giorni": (q.data_scadenza - oggi).days if q.data_scadenza else None,
            "stato": stato_code,
            "stato_label": stato_label,
            "ha_evidenza": bool(q.documento),
            "verificata": q.verificata,
            "note": q.note,
        })

    if export_csv:
        resp = HttpResponse(content_type=CSV_CONTENT_TYPE)
        resp["Content-Disposition"] = 'attachment; filename="scadenzario_qualifiche.csv"'
        resp.write(BOM)  # una volta sola: Excel riconosce l'UTF-8
        writer = safe_csv_writer(resp, delimiter=";")
        writer.writerow(["Dipendente", "Reparto", "Qualifica", "Categoria", "N°", "Livello",
                         "Ente", "Conseguimento", "Scadenza", "Giorni", "Stato",
                         "Evidenza", "Verificata"])
        for v in voci:
            writer.writerow([
                v["dipendente"], v["reparto"], v["tipo_nome"], v["categoria"],
                v["numero"], v["livello"], v["ente"],
                v["data_conseguimento"].strftime("%d/%m/%Y") if v["data_conseguimento"] else "",
                v["data_scadenza"].strftime("%d/%m/%Y") if v["data_scadenza"] else "",
                v["giorni"] if v["giorni"] is not None else "",
                v["stato_label"],
                "Sì" if v["ha_evidenza"] else "No",
                "Sì" if v["verificata"] else "No",
            ])
        return resp

    reparti = sorted({str(r.get("reparto") or "").strip() for r in dip_rows if str(r.get("reparto") or "").strip()})
    tipi_opts = list(TipoQualifica.objects.order_by("categoria", "nome").values("id", "nome"))

    gruppi = _raggruppa_voci_per_tipo(
        voci,
        tipo_of=lambda v: v["tipo_nome"],
        scaduta_of=lambda v: v["stato"] == "scaduta",
        giorni_of=lambda v: v["giorni"] if v["giorni"] is not None else 99999,
    )

    return render(request, "anagrafica/pages/qualifiche_scadenzario.html", {
        "oggi": oggi,
        "voci": voci,
        "gruppi": gruppi,
        "counts": counts,
        "totale": len(voci),
        "filtro_stato": filtro_stato,
        "filtro_categoria": filtro_cat,
        "filtro_reparto": filtro_reparto,
        "filtro_tipo": filtro_tipo,
        "reparti": reparti,
        "tipi_opts": tipi_opts,
        "CATEGORIA_CHOICES": TipoQualifica.CATEGORIA_CHOICES,
    })


@login_required
def tipo_qualifica_detail(request, tipo_id: int):
    """Dettaglio di una singola qualifica/abilitazione: chi la possiede (con
    stato), corsi collegati, sessioni di rinnovo, e la formazione collegata
    (sessioni corso, lezioni, attestati/completamenti) — modello qualifica àncora.
    """
    from datetime import timedelta
    from django.utils import timezone as _tz
    from ..models_formazione import TrainingSession, TrainingEmployeeRecord, TrainingLesson

    tipo = get_object_or_404(TipoQualifica, pk=tipo_id)
    is_admin = _helpers._qualifiche_can_edit(request)
    oggi = _tz.localdate()
    soglia = oggi + timedelta(days=60)

    corsi = list(tipo.corsi.select_related("piano").order_by("titolo"))
    corso_ids = [c.id for c in corsi]

    nomi = _helpers._build_nomi_map()
    ordine = _helpers._build_ordine_map()
    holders: list[dict] = []
    n_scaduti = n_scadenza = 0
    for q in (DipendenteQualifica.objects.filter(tipo=tipo)
              .select_related("record_formazione", "record_formazione__corso", "sessione")
              .order_by("data_scadenza", "id")):
        if q.data_scadenza is None:
            stato = "valida"
        elif q.data_scadenza < oggi:
            stato = "scaduta"; n_scaduti += 1
        elif q.data_scadenza <= soglia:
            stato = "in_scadenza"; n_scadenza += 1
        else:
            stato = "valida"
        holders.append({
            "q": q, "stato": stato,
            "nome": nomi.get(q.legacy_anagrafica_id, f"#{q.legacy_anagrafica_id}"),
        })
    _ord = {"scaduta": 0, "in_scadenza": 1, "valida": 2}
    holders.sort(key=lambda h: (
        _ord.get(h["stato"], 9),
        ordine.get(h["q"].legacy_anagrafica_id, h["nome"]).casefold(),
    ))

    sessioni = list(
        QualificaSessione.objects.filter(tipo=tipo)
        .annotate(n_part=Count("qualifiche")).order_by("-data_conseguimento", "-id")
    )

    corso_sessioni: list = []
    attestati_recenti: list = []
    n_attestati = n_lezioni = 0
    if corso_ids:
        corso_sessioni = list(
            TrainingSession.objects.filter(corso_id__in=corso_ids)
            .select_related("corso")
            .annotate(n_lezioni=Count("lezioni", distinct=True),
                      n_iscritti=Count("iscrizioni", distinct=True))
            .order_by("-data_inizio")[:30]
        )
        n_lezioni = TrainingLesson.objects.filter(sessione__corso_id__in=corso_ids).count()
        rec_qs = (TrainingEmployeeRecord.objects.filter(corso_id__in=corso_ids)
                  .select_related("corso").order_by("-data_completamento", "-id"))
        n_attestati = rec_qs.count()
        for r in rec_qs[:30]:
            attestati_recenti.append({
                "r": r, "nome": nomi.get(r.legacy_anagrafica_id, f"#{r.legacy_anagrafica_id}"),
            })

    return render(request, "anagrafica/pages/tipo_qualifica_detail.html", {
        "tipo": tipo,
        "is_admin": is_admin,
        "corsi": corsi,
        "holders": holders,
        "n_holders": len(holders),
        "n_scaduti": n_scaduti,
        "n_scadenza": n_scadenza,
        "sessioni": sessioni,
        "corso_sessioni": corso_sessioni,
        "attestati_recenti": attestati_recenti,
        "n_attestati": n_attestati,
        "n_lezioni": n_lezioni,
    })


@login_required
@require_POST
def tipo_qualifica_create(request):
    legacy_user = get_legacy_user(request.user)
    if not _helpers._is_anagrafica_admin(request):
        messages.error(request, "Non hai i permessi per creare tipi di qualifica.")
        return _helpers._back_to_caller(request, "anagrafica:qualifiche_list")

    nome = (request.POST.get("nome") or "").strip()[:150]
    if not nome:
        messages.error(request, "Il nome della qualifica è obbligatorio.")
        return _helpers._back_to_caller(request, "anagrafica:qualifiche_list")

    durata_raw = request.POST.get("durata_mesi") or "0"
    try:
        durata_mesi = max(0, int(durata_raw))
    except ValueError:
        durata_mesi = 0

    _, created = TipoQualifica.objects.get_or_create(
        nome__iexact=nome,
        defaults={
            "nome": nome,
            "categoria": (request.POST.get("categoria") or TipoQualifica.CAT_ALTRO).strip()[:20],
            "durata_mesi": durata_mesi,
            "descrizione": (request.POST.get("descrizione") or "").strip(),
        },
    )
    if created:
        messages.success(request, f'Tipo qualifica "{nome}" creato.')
    else:
        messages.warning(request, f'Esiste già un tipo qualifica con il nome "{nome}".')
    return _helpers._back_to_caller(request, "anagrafica:qualifiche_list")


@login_required
@require_POST
def tipo_qualifica_edit(request, tipo_id: int):
    legacy_user = get_legacy_user(request.user)
    if not _helpers._is_anagrafica_admin(request):
        messages.error(request, "Non hai i permessi per modificare tipi di qualifica.")
        return _helpers._back_to_caller(request, "anagrafica:qualifiche_list")

    tipo = get_object_or_404(TipoQualifica, pk=tipo_id)
    nome = (request.POST.get("nome") or "").strip()[:150]
    if not nome:
        messages.error(request, "Il nome della qualifica è obbligatorio.")
        return _helpers._back_to_caller(request, "anagrafica:qualifiche_list")

    durata_raw = request.POST.get("durata_mesi") or "0"
    try:
        durata_mesi = max(0, int(durata_raw))
    except ValueError:
        durata_mesi = 0

    tipo.nome = nome
    tipo.categoria = (request.POST.get("categoria") or TipoQualifica.CAT_ALTRO).strip()[:20]
    tipo.durata_mesi = durata_mesi
    tipo.descrizione = (request.POST.get("descrizione") or "").strip()
    tipo.is_active = request.POST.get("is_active") == "1"
    tipo.save()
    messages.success(request, f'Tipo qualifica "{tipo.nome}" aggiornato.')
    return _helpers._back_to_caller(request, "anagrafica:qualifiche_list")


@login_required
@require_POST
def tipo_qualifica_delete(request, tipo_id: int):
    legacy_user = get_legacy_user(request.user)
    if not _helpers._is_anagrafica_admin(request):
        messages.error(request, "Non hai i permessi per eliminare tipi di qualifica.")
        return _helpers._back_to_caller(request, "anagrafica:qualifiche_list")

    tipo = get_object_or_404(TipoQualifica, pk=tipo_id)
    n_uso = tipo.assegnazioni.count()
    if n_uso:
        if tipo.is_active:
            tipo.is_active = False
            tipo.save(update_fields=["is_active"])
            messages.warning(request, f'"{tipo.nome}" è in uso ({n_uso} assegnazioni): disattivato (non eliminato) per preservare lo storico. Puoi riattivarlo dalla modifica.')
        else:
            messages.error(request, f'"{tipo.nome}" ha {n_uso} assegnazioni: non eliminabile (già disattivo).')
        return _helpers._back_to_caller(request, "anagrafica:qualifiche_list")

    nome = tipo.nome
    tipo.delete()
    messages.success(request, f'Tipo qualifica "{nome}" eliminato.')
    return _helpers._back_to_caller(request, "anagrafica:qualifiche_list")


def _build_candidati_qualifica(tipo, oggi) -> list[dict]:
    """Dipendenti (in forza) che detengono già la qualifica, con lo stato di
    rinnovo: scaduta / in scadenza (≤90gg) / valida. I nuovi rilasci si
    aggiungono dal picker. Pre-seleziona scadute e in scadenza."""
    from datetime import timedelta
    soglia = oggi + timedelta(days=90)
    ultima_per_id: dict[int, "DipendenteQualifica"] = {}
    for q in (DipendenteQualifica.objects.filter(tipo=tipo)
              .order_by("legacy_anagrafica_id", "-data_conseguimento", "-id")):
        ultima_per_id.setdefault(q.legacy_anagrafica_id, q)
    nomi = _helpers._build_nomi_map()
    ordine = _helpers._build_ordine_map()
    cessati = _helpers._cessati_legacy_ids()
    out: list[dict] = []
    for lid, q in ultima_per_id.items():
        if lid in cessati:
            continue
        if q.data_scadenza is None:
            status = "valida"
        elif q.data_scadenza < oggi:
            status = "scaduta"
        elif q.data_scadenza <= soglia:
            status = "in_scadenza"
        else:
            status = "valida"
        out.append({
            "legacy_id": lid, "nome": nomi.get(lid, f"#{lid}"),
            "ultima": q, "status": status,
            "preselect": status in ("scaduta", "in_scadenza"),
        })
    order = {"scaduta": 0, "in_scadenza": 1, "valida": 2}
    out.sort(key=lambda c: (
        order.get(c["status"], 9),
        ordine.get(c["legacy_id"], c["nome"]).casefold(),
    ))
    return out


@login_required
def qualifica_sessioni_list(request):
    qs = QualificaSessione.objects.select_related("tipo").annotate(n_part=Count("qualifiche"))
    filtro_tipo = (request.GET.get("tipo") or "").strip()
    q_text = (request.GET.get("q") or "").strip()
    if filtro_tipo.isdigit():
        qs = qs.filter(tipo_id=int(filtro_tipo))
    if q_text:
        qs = qs.filter(Q(tipo__nome__icontains=q_text) | Q(ente__icontains=q_text))
    sessioni = list(qs.order_by("-data_conseguimento", "-id"))
    # Tipi con almeno una sessione, per il filtro a tendina.
    tipi_con_sessioni = list(
        TipoQualifica.objects.filter(sessioni__isnull=False).distinct().order_by("nome")
    )
    return render(request, "anagrafica/pages/qualifica_sessioni_list.html", {
        "sessioni": sessioni,
        "is_admin": _helpers._qualifiche_can_edit(request),
        "tipi_con_sessioni": tipi_con_sessioni,
        "filtro_tipo": filtro_tipo,
        "q_text": q_text,
    })


@login_required
def qualifica_sessione_create(request):
    if not _helpers._qualifiche_can_edit(request):
        messages.error(request, "Non hai i permessi per creare sessioni di rinnovo.")
        return redirect("anagrafica:qualifiche_list")

    from datetime import date as _date
    from django.utils import timezone as _tz
    from django.db import transaction

    oggi = _tz.localdate()
    tipi = list(TipoQualifica.objects.filter(is_active=True).order_by("categoria", "nome"))

    # ---- Step 2: salva la sessione e i record dei partecipanti ----------
    if request.method == "POST" and request.POST.get("step") == "2":
        try:
            tipo = TipoQualifica.objects.get(pk=request.POST.get("tipo_id", "").strip(), is_active=True)
        except (TipoQualifica.DoesNotExist, ValueError):
            messages.error(request, "Tipo qualifica non valido.")
            return redirect("anagrafica:qualifica_sessione_create")
        try:
            data_cons = _date.fromisoformat(request.POST.get("data_conseguimento", "").strip())
        except (ValueError, TypeError):
            messages.error(request, "Data conseguimento non valida.")
            return redirect("anagrafica:qualifica_sessione_create")
        data_scad = None
        ds_raw = (request.POST.get("data_scadenza") or "").strip()
        if ds_raw:
            try:
                data_scad = _date.fromisoformat(ds_raw)
            except (ValueError, TypeError):
                data_scad = None
        ente = (request.POST.get("ente") or "").strip()[:200]
        note = (request.POST.get("note") or "").strip()

        ids: list[int] = []
        seen: set[int] = set()
        raw = list(request.POST.getlist("dipendenti_selezionati"))
        raw += [x for x in (request.POST.get("extra_ids") or "").split(",")]
        for s in raw:
            s = str(s).strip()
            if s.isdigit():
                lid = int(s)
                if lid > 0 and lid not in seen:
                    seen.add(lid)
                    ids.append(lid)
        if not ids:
            messages.warning(request, "Nessun dipendente selezionato.")
            return redirect("anagrafica:qualifica_sessione_create")

        with transaction.atomic():
            sess = QualificaSessione.objects.create(
                tipo=tipo, data_conseguimento=data_cons, data_scadenza=data_scad,
                ente=ente, note=note, created_by=request.user,
            )
            scad_eff = sess.scadenza_effettiva
            for lid in ids:
                _helpers._upsert_dipendente_qualifica(
                    lid, tipo, data_cons, scad_eff, user=request.user, sessione=sess,
                )
        messages.success(
            request,
            f'Sessione «{tipo.nome}» del {data_cons:%d/%m/%Y}: {len(ids)} qualifiche registrate/rinnovate.',
        )
        return redirect("anagrafica:qualifica_sessione_detail", sessione_id=sess.id)

    # ---- Pagina unica (GET) — form + candidati caricati dinamicamente ----
    # Se arriva ?tipo=<id> (da scadenzario / dettaglio qualifica / matrice) la
    # tabella candidati è renderizzata subito lato server (deep-link no-JS);
    # altrimenti si popola via HTMX al cambio del tipo nel select.
    pre_tipo = None
    pre_tipo_id = (request.GET.get("tipo") or "").strip()
    if pre_tipo_id.isdigit():
        pre_tipo = TipoQualifica.objects.filter(pk=int(pre_tipo_id), is_active=True).first()
    candidati = _build_candidati_qualifica(pre_tipo, oggi) if pre_tipo else []
    n_pre = sum(1 for c in candidati if c["preselect"])
    return render(request, "anagrafica/pages/qualifica_sessione_create.html", {
        "tipi": tipi, "oggi": oggi,
        "pre_tipo": pre_tipo, "candidati": candidati, "n_pre": n_pre,
        "dipendenti_picker": _helpers._dipendenti_picker_rows(),
    })


@login_required
def qualifica_sessione_candidati(request):
    """Partial HTMX: tabella dei candidati (chi detiene già la qualifica, con
    stato di rinnovo) per il tipo selezionato. Popola dinamicamente la pagina di
    creazione sessione senza ricaricarla."""
    if not _helpers._qualifiche_can_edit(request):
        return HttpResponse(status=403)
    from django.utils import timezone as _tz
    raw = (request.GET.get("tipo") or request.GET.get("tipo_id") or "").strip()
    tipo = None
    if raw.isdigit():
        tipo = TipoQualifica.objects.filter(pk=int(raw), is_active=True).first()
    candidati = _build_candidati_qualifica(tipo, _tz.localdate()) if tipo else []
    n_pre = sum(1 for c in candidati if c["preselect"])
    return render(request, "anagrafica/pages/_qualifica_candidati.html", {
        "tipo": tipo, "candidati": candidati, "n_pre": n_pre,
    })


@login_required
def qualifica_sessione_detail(request, sessione_id: int):
    sess = get_object_or_404(QualificaSessione.objects.select_related("tipo"), pk=sessione_id)
    nomi = _helpers._build_nomi_map()
    ordine = _helpers._build_ordine_map()
    rows = [
        {"q": q, "nome": nomi.get(q.legacy_anagrafica_id, f"#{q.legacy_anagrafica_id}")}
        for q in sess.qualifiche.all()
    ]
    rows.sort(key=lambda r: ordine.get(r["q"].legacy_anagrafica_id, r["nome"]).casefold())
    is_admin = _helpers._qualifiche_can_edit(request)
    return render(request, "anagrafica/pages/qualifica_sessione_detail.html", {
        "sess": sess,
        "rows": rows,
        "is_admin": is_admin,
        "dipendenti_picker": _helpers._dipendenti_picker_rows() if is_admin else [],
    })


@login_required
@require_POST
def qualifica_sessione_partecipante_add(request, sessione_id: int):
    if not _helpers._qualifiche_can_edit(request):
        messages.error(request, "Permessi insufficienti.")
        return redirect("anagrafica:qualifica_sessione_detail", sessione_id=sessione_id)
    sess = get_object_or_404(QualificaSessione.objects.select_related("tipo"), pk=sessione_id)
    try:
        lid = int(request.POST.get("legacy_id") or 0)
    except (ValueError, TypeError):
        lid = 0
    if lid > 0:
        _helpers._upsert_dipendente_qualifica(
            lid, sess.tipo, sess.data_conseguimento, sess.scadenza_effettiva,
            user=request.user, sessione=sess,
        )
        messages.success(request, "Partecipante aggiunto alla sessione.")
    else:
        messages.error(request, "Dipendente non valido.")
    return redirect("anagrafica:qualifica_sessione_detail", sessione_id=sessione_id)


@login_required
@require_POST
def qualifica_sessione_partecipante_remove(request, sessione_id: int, q_id: int):
    if not _helpers._qualifiche_can_edit(request):
        messages.error(request, "Permessi insufficienti.")
        return redirect("anagrafica:qualifica_sessione_detail", sessione_id=sessione_id)
    q = get_object_or_404(DipendenteQualifica, pk=q_id, sessione_id=sessione_id)
    # Stacca dalla sessione (la qualifica corrente del dipendente resta).
    q.sessione = None
    q.save(update_fields=["sessione"])
    messages.success(request, "Partecipante rimosso dalla sessione (qualifica conservata).")
    return redirect("anagrafica:qualifica_sessione_detail", sessione_id=sessione_id)


@login_required
@require_POST
def qualifica_sessione_delete(request, sessione_id: int):
    if not _helpers._qualifiche_can_edit(request):
        messages.error(request, "Permessi insufficienti.")
        return redirect("anagrafica:qualifica_sessioni_list")
    sess = get_object_or_404(QualificaSessione, pk=sessione_id)
    # SET_NULL: le qualifiche dei dipendenti restano, perdono solo il legame.
    sess.delete()
    messages.success(request, "Sessione eliminata (qualifiche dei dipendenti conservate).")
    return redirect("anagrafica:qualifica_sessioni_list")


@login_required
def qualifica_sessione_report_csv(request, sessione_id: int):
    """Esporta in CSV i partecipanti di una sessione di qualifica/abilitazione."""
    sess = get_object_or_404(QualificaSessione.objects.select_related("tipo"), pk=sessione_id)
    nomi = _helpers._build_nomi_map()
    ordine = _helpers._build_ordine_map()
    rows = sorted(
        sess.qualifiche.all(),
        key=lambda q: ordine.get(q.legacy_anagrafica_id, f"#{q.legacy_anagrafica_id}").casefold(),
    )

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    fname = f"sessione_qualifica_{sess.tipo.nome}_{sess.data_conseguimento:%Y%m%d}.csv".replace(" ", "_")
    response["Content-Disposition"] = f'attachment; filename="{fname}"'
    response.write("﻿")
    writer = safe_csv_writer(response, delimiter=";")
    writer.writerow(["Qualifica", "Ente", "Conseguimento", "Scadenza sessione"])
    writer.writerow([
        sess.tipo.nome, sess.ente or "",
        sess.data_conseguimento.strftime("%d-%m-%Y") if sess.data_conseguimento else "",
        sess.scadenza_effettiva.strftime("%d-%m-%Y") if sess.scadenza_effettiva else "",
    ])
    writer.writerow([])
    writer.writerow(["Dipendente", "ID anagrafica", "Conseguimento", "Scadenza"])
    for q in rows:
        writer.writerow([
            nomi.get(q.legacy_anagrafica_id, f"#{q.legacy_anagrafica_id}"),
            q.legacy_anagrafica_id,
            q.data_conseguimento.strftime("%d-%m-%Y") if q.data_conseguimento else "",
            q.data_scadenza.strftime("%d-%m-%Y") if q.data_scadenza else "",
        ])
    return response


# ---------------------------------------------------------------------------
# DPI catalogo — CRUD inline da anagrafica/impostazioni
# ---------------------------------------------------------------------------

def _dpi_parse_int(value) -> int | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _dpi_validate_image(uploaded) -> str | None:
    if uploaded is None:
        return None
    try:
        from core.upload_mime import validate_extension_and_mime
        validate_extension_and_mime(
            uploaded,
            allowed_extensions={".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"},
            allowed_mimes={"image/jpeg", "image/png", "image/webp", "image/gif", "image/bmp", "image/x-ms-bmp"},
            label=getattr(uploaded, "name", "immagine"),
        )
    except Exception as exc:
        return str(exc)
    return None


@login_required
@require_POST
def dpi_categoria_create(request):
    ok, resp = _helpers._impostazioni_admin_check(request, "dpi")
    if not ok:
        return resp
    from dpi.models import CategoriaDPI, normalizza_icona_dpi
    nome = (request.POST.get("nome") or "").strip()
    if not nome:
        messages.error(request, "Il nome della categoria DPI è obbligatorio.")
        return _helpers._redirect_impostazioni("dpi")
    cat = CategoriaDPI(
        nome=nome,
        descrizione=(request.POST.get("descrizione") or "").strip(),
        icona_emoji=normalizza_icona_dpi(request.POST.get("icona_emoji")),
        vita_utile_giorni=_dpi_parse_int(request.POST.get("vita_utile_giorni")),
        obbligatoria_mansionario=request.POST.get("obbligatoria_mansionario") == "1",
        unita_misura=(request.POST.get("unita_misura") or "pz").strip() or "pz",
        scorta_minima=_dpi_parse_int(request.POST.get("scorta_minima")) or 0,
        is_active=True,
        order_index=_dpi_parse_int(request.POST.get("order_index")) or 0,
    )
    uploaded = request.FILES.get("immagine")
    if uploaded:
        err = _dpi_validate_image(uploaded)
        if err:
            messages.error(request, err)
            return _helpers._redirect_impostazioni("dpi")
        cat.immagine = uploaded
    cat.save()
    messages.success(request, f'Categoria DPI "{nome}" creata.')
    return _helpers._redirect_impostazioni("dpi")


@login_required
@require_POST
def dpi_categoria_edit(request, pk: int):
    ok, resp = _helpers._impostazioni_admin_check(request, "dpi")
    if not ok:
        return resp
    from dpi.models import CategoriaDPI, normalizza_icona_dpi
    cat = get_object_or_404(CategoriaDPI, pk=pk)
    nome = (request.POST.get("nome") or "").strip()
    if not nome:
        messages.error(request, "Il nome della categoria DPI è obbligatorio.")
        return _helpers._redirect_impostazioni("dpi")
    cat.nome = nome
    cat.descrizione = (request.POST.get("descrizione") or "").strip()
    cat.icona_emoji = normalizza_icona_dpi(request.POST.get("icona_emoji"))
    cat.vita_utile_giorni = _dpi_parse_int(request.POST.get("vita_utile_giorni"))
    cat.obbligatoria_mansionario = request.POST.get("obbligatoria_mansionario") == "1"
    cat.unita_misura = (request.POST.get("unita_misura") or "pz").strip() or "pz"
    cat.scorta_minima = _dpi_parse_int(request.POST.get("scorta_minima")) or 0
    cat.is_active = request.POST.get("is_active") == "1"
    cat.order_index = _dpi_parse_int(request.POST.get("order_index")) or 0
    uploaded = request.FILES.get("immagine")
    if uploaded:
        err = _dpi_validate_image(uploaded)
        if err:
            messages.error(request, err)
            return _helpers._redirect_impostazioni("dpi")
        cat.immagine = uploaded
    cat.save()
    messages.success(request, f'Categoria DPI "{cat.nome}" aggiornata.')
    return _helpers._redirect_impostazioni("dpi")


@login_required
@require_POST
def dpi_categoria_delete(request, pk: int):
    ok, resp = _helpers._impostazioni_admin_check(request, "dpi")
    if not ok:
        return resp
    from dpi.models import CategoriaDPI
    cat = get_object_or_404(CategoriaDPI, pk=pk)
    if cat.richieste.exists():
        messages.error(request, f'"{cat.nome}" ha richieste associate — disattivala invece di eliminarla.')
        return _helpers._redirect_impostazioni("dpi")
    nome = cat.nome
    cat.delete()
    messages.success(request, f'Categoria DPI "{nome}" eliminata.')
    return _helpers._redirect_impostazioni("dpi")


@login_required
@require_POST
def dpi_tipo_create(request):
    ok, resp = _helpers._impostazioni_admin_check(request, "dpi")
    if not ok:
        return resp
    from dpi.models import CategoriaDPI, TipoDPI
    categoria_id = (request.POST.get("categoria_id") or "").strip()
    nome = (request.POST.get("nome") or "").strip()
    if not categoria_id or not nome:
        messages.error(request, "Categoria e nome del tipo DPI sono obbligatori.")
        return _helpers._redirect_impostazioni("dpi")
    try:
        categoria = CategoriaDPI.objects.get(pk=int(categoria_id))
    except (CategoriaDPI.DoesNotExist, ValueError):
        messages.error(request, "Categoria DPI non valida.")
        return _helpers._redirect_impostazioni("dpi")
    if TipoDPI.objects.filter(categoria=categoria, nome=nome).exists():
        messages.error(request, f'Esiste già un tipo "{nome}" in questa categoria.')
        return _helpers._redirect_impostazioni("dpi")
    TipoDPI.objects.create(
        categoria=categoria,
        nome=nome,
        descrizione=(request.POST.get("descrizione") or "").strip(),
        ordine=_dpi_parse_int(request.POST.get("ordine")) or 0,
        is_active=True,
    )
    messages.success(request, f'Tipo DPI "{nome}" creato.')
    return _helpers._redirect_impostazioni("dpi")


@login_required
@require_POST
def dpi_tipo_edit(request, pk: int):
    ok, resp = _helpers._impostazioni_admin_check(request, "dpi")
    if not ok:
        return resp
    from dpi.models import TipoDPI
    tipo = get_object_or_404(TipoDPI, pk=pk)
    nome = (request.POST.get("nome") or "").strip()
    if not nome:
        messages.error(request, "Il nome del tipo DPI è obbligatorio.")
        return _helpers._redirect_impostazioni("dpi")
    tipo.nome = nome
    tipo.descrizione = (request.POST.get("descrizione") or "").strip()
    tipo.ordine = _dpi_parse_int(request.POST.get("ordine")) or 0
    tipo.is_active = request.POST.get("is_active") == "1"
    tipo.save()
    messages.success(request, f'Tipo DPI "{tipo.nome}" aggiornato.')
    return _helpers._redirect_impostazioni("dpi")


@login_required
@require_POST
def dpi_tipo_delete(request, pk: int):
    ok, resp = _helpers._impostazioni_admin_check(request, "dpi")
    if not ok:
        return resp
    from dpi.models import TipoDPI
    tipo = get_object_or_404(TipoDPI, pk=pk)
    if tipo.modelli.exists():
        messages.error(request, f'"{tipo.nome}" ha modelli associati — eliminali prima.')
        return _helpers._redirect_impostazioni("dpi")
    nome = tipo.nome
    tipo.delete()
    messages.success(request, f'Tipo DPI "{nome}" eliminato.')
    return _helpers._redirect_impostazioni("dpi")


@login_required
@require_POST
def dpi_modello_create(request):
    ok, resp = _helpers._impostazioni_admin_check(request, "dpi")
    if not ok:
        return resp
    from dpi.models import TipoDPI, ModelloDPI
    tipo_id = (request.POST.get("tipo_id") or "").strip()
    codice = (request.POST.get("codice") or "").strip()
    nome = (request.POST.get("nome") or "").strip()
    if not tipo_id or not codice or not nome:
        messages.error(request, "Tipo, codice e nome del modello DPI sono obbligatori.")
        return _helpers._redirect_impostazioni("dpi")
    try:
        tipo = TipoDPI.objects.select_related("categoria").get(pk=int(tipo_id))
    except (TipoDPI.DoesNotExist, ValueError):
        messages.error(request, "Tipo DPI non valido.")
        return _helpers._redirect_impostazioni("dpi")
    if ModelloDPI.objects.filter(codice=codice).exists():
        messages.error(request, f'Esiste già un modello con codice "{codice}".')
        return _helpers._redirect_impostazioni("dpi")
    modello = ModelloDPI(
        tipo=tipo, codice=codice, nome=nome,
        produttore=(request.POST.get("produttore") or "").strip(),
        descrizione=(request.POST.get("descrizione") or "").strip(),
        vita_utile_giorni=_dpi_parse_int(request.POST.get("vita_utile_giorni")),
        is_active=True,
    )
    uploaded = request.FILES.get("immagine")
    if uploaded:
        err = _dpi_validate_image(uploaded)
        if err:
            messages.error(request, err)
            return _helpers._redirect_impostazioni("dpi")
        modello.immagine = uploaded
    modello.save()
    messages.success(request, f'Modello DPI "{codice}" creato.')
    return _helpers._redirect_impostazioni("dpi")


@login_required
@require_POST
def dpi_modello_edit(request, pk: int):
    ok, resp = _helpers._impostazioni_admin_check(request, "dpi")
    if not ok:
        return resp
    from dpi.models import ModelloDPI
    modello = get_object_or_404(ModelloDPI, pk=pk)
    nome = (request.POST.get("nome") or "").strip()
    if not nome:
        messages.error(request, "Il nome del modello DPI è obbligatorio.")
        return _helpers._redirect_impostazioni("dpi")
    modello.nome = nome
    modello.produttore = (request.POST.get("produttore") or "").strip()
    modello.descrizione = (request.POST.get("descrizione") or "").strip()
    modello.vita_utile_giorni = _dpi_parse_int(request.POST.get("vita_utile_giorni"))
    modello.is_active = request.POST.get("is_active") == "1"
    uploaded = request.FILES.get("immagine")
    if uploaded:
        err = _dpi_validate_image(uploaded)
        if err:
            messages.error(request, err)
            return _helpers._redirect_impostazioni("dpi")
        modello.immagine = uploaded
    modello.save()
    messages.success(request, f'Modello DPI "{modello.codice}" aggiornato.')
    return _helpers._redirect_impostazioni("dpi")


@login_required
@require_POST
def dpi_modello_delete(request, pk: int):
    ok, resp = _helpers._impostazioni_admin_check(request, "dpi")
    if not ok:
        return resp
    from dpi.models import ModelloDPI
    modello = get_object_or_404(ModelloDPI, pk=pk)
    if modello.taglie.exists():
        messages.error(request, f'"{modello.codice}" ha taglie associate — eliminale prima.')
        return _helpers._redirect_impostazioni("dpi")
    codice = modello.codice
    modello.delete()
    messages.success(request, f'Modello DPI "{codice}" eliminato.')
    return _helpers._redirect_impostazioni("dpi")


@login_required
@require_POST
def dpi_taglia_create(request):
    ok, resp = _helpers._impostazioni_admin_check(request, "dpi")
    if not ok:
        return resp
    from dpi.models import ModelloDPI, TagliaDPI as _TagliaDPI
    modello_id = (request.POST.get("modello_id") or "").strip()
    valore = (request.POST.get("valore") or "").strip()
    if not modello_id or not valore:
        messages.error(request, "Modello e valore della taglia DPI sono obbligatori.")
        return _helpers._redirect_impostazioni("dpi")
    try:
        modello = ModelloDPI.objects.get(pk=int(modello_id))
    except (ModelloDPI.DoesNotExist, ValueError):
        messages.error(request, "Modello DPI non valido.")
        return _helpers._redirect_impostazioni("dpi")
    if _TagliaDPI.objects.filter(modello=modello, valore=valore).exists():
        messages.error(request, f'Esiste già la taglia "{valore}" per questo modello.')
        return _helpers._redirect_impostazioni("dpi")
    _TagliaDPI.objects.create(
        modello=modello,
        valore=valore,
        ordine=_dpi_parse_int(request.POST.get("ordine")) or 0,
        is_active=True,
    )
    messages.success(request, f'Taglia DPI "{valore}" creata.')
    return _helpers._redirect_impostazioni("dpi")


@login_required
@require_POST
def dpi_taglia_edit(request, pk: int):
    ok, resp = _helpers._impostazioni_admin_check(request, "dpi")
    if not ok:
        return resp
    from dpi.models import TagliaDPI as _TagliaDPI
    taglia = get_object_or_404(_TagliaDPI, pk=pk)
    valore = (request.POST.get("valore") or "").strip()
    if not valore:
        messages.error(request, "Il valore della taglia DPI è obbligatorio.")
        return _helpers._redirect_impostazioni("dpi")
    taglia.valore = valore
    taglia.ordine = _dpi_parse_int(request.POST.get("ordine")) or 0
    taglia.is_active = request.POST.get("is_active") == "1"
    taglia.save()
    messages.success(request, f'Taglia DPI "{taglia.valore}" aggiornata.')
    return _helpers._redirect_impostazioni("dpi")


@login_required
@require_POST
def dpi_taglia_delete(request, pk: int):
    ok, resp = _helpers._impostazioni_admin_check(request, "dpi")
    if not ok:
        return resp
    from dpi.models import TagliaDPI as _TagliaDPI
    taglia = get_object_or_404(_TagliaDPI, pk=pk)
    valore = taglia.valore
    taglia.delete()
    messages.success(request, f'Taglia DPI "{valore}" eliminata.')
    return _helpers._redirect_impostazioni("dpi")


# ---------------------------------------------------------------------------
# Skill Matrix MOD.187 — validazione abbinamento competenza→asset (F2a, UI)
# ---------------------------------------------------------------------------

@login_required
def skm_match_validazione(request):
    """Specchietto in-portal per abbinare le competenze-macchina MOD.187 agli
    asset **reali** dell'ambiente (dev o prod) e **confermare** il match — è il
    gate F2a, propedeutico all'import baseline.

    Lavora sugli asset live e salva nel catalogo ``CompetenzaSkm``: NON scrive
    baseline (nessuna ``AbilitazioneMacchina``). Le conferme manuali sono
    preservate dalle ri-sincronizzazioni.
    Accesso: ``_check_hr_permission`` (ACL formale in F7).
    """
    from ..acl_bootstrap import PERM_SKM_MANAGE
    if not _check_skm_permission(request, PERM_SKM_MANAGE):
        messages.error(request, "Non hai i permessi per la validazione Skill Matrix.")
        return redirect("anagrafica:index")

    from ..models import CompetenzaSkm
    from ..services.skillmatrix_seed import sincronizza_catalogo

    if request.method == "POST":
        azione = request.POST.get("azione", "")
        if azione == "sincronizza":
            stats = sincronizza_catalogo()
            messages.success(
                request,
                f"Catalogo sincronizzato dagli asset live: {stats['macchine']} macchine "
                f"({stats['esatti']} esatti, {stats['parziali']} parziali, "
                f"{stats['assenti']} assenti; {stats['confermati']} confermati). "
                f"Processi {stats['processi']} (collegati a qualifica {stats['processi_collegati']}).",
            )
            return redirect("anagrafica:skm_match_validazione")

        if azione == "salva":
            from assets.models import Asset
            macchine = list(CompetenzaSkm.objects.filter(tipo=CompetenzaSkm.TIPO_MACCHINA))
            tag_richiesti = {
                (request.POST.get(f"asset_{c.id}") or "").strip()
                for c in macchine
            }
            tag_richiesti.discard("")
            asset_per_tag = {
                a.asset_tag: a for a in Asset.objects.filter(asset_tag__in=tag_richiesti)
            } if tag_richiesti else {}
            n_conf = n_escl = n_aperti = n_err = 0
            for c in macchine:
                dec = request.POST.get(f"decisione_{c.id}", "da_validare")
                tag = (request.POST.get(f"asset_{c.id}") or "").strip()
                if dec == "conferma":
                    asset = asset_per_tag.get(tag)
                    if asset is None:
                        n_err += 1
                        continue
                    c.asset = asset
                    c.match_confermato = True
                    n_conf += 1
                elif dec == "escludi":
                    c.asset = None
                    c.match_confermato = True
                    n_escl += 1
                else:  # da_validare: aggiorna l'asset proposto ma non confermare
                    asset = asset_per_tag.get(tag) if tag else None
                    if asset is not None:
                        c.asset = asset
                    c.match_confermato = False
                    n_aperti += 1
                c.save()
            msg = f"Salvato: {n_conf} confermati, {n_escl} esclusi, {n_aperti} da validare."
            if n_err:
                messages.warning(request, msg + f" {n_err} righe non salvate (asset_tag non valido).")
            else:
                messages.success(request, msg)
            return redirect("anagrafica:skm_match_validazione")

    macchine = list(
        CompetenzaSkm.objects.filter(tipo=CompetenzaSkm.TIPO_MACCHINA)
        .select_related("asset").order_by("competenza_key")
    )

    def _stato(c):
        if c.match_confermato:
            return "confermato" if c.asset_id else "escluso"
        return "da_validare"

    ordine = {"da_validare": 0, "confermato": 1, "escluso": 2}
    righe = sorted(
        ({"c": c, "stato": _stato(c)} for c in macchine),
        key=lambda r: (ordine.get(r["stato"], 9), r["c"].competenza_key),
    )
    n_conf = sum(1 for r in righe if r["stato"] == "confermato")
    n_escl = sum(1 for r in righe if r["stato"] == "escluso")
    n_val = sum(1 for r in righe if r["stato"] == "da_validare")

    # Datalist asset: esclude i tipi palesemente non-macchina per ridurre rumore.
    from assets.models import Asset
    nonmacc = {"PC", "NOTEBOOK", "SERVER", "VM", "FIREWALL", "STAMPANTE", "FONIA", "CCTV"}
    asset_opts = list(
        Asset.objects.exclude(asset_type__in=nonmacc)
        .only("id", "asset_tag", "name").order_by("asset_tag")
    )

    return render(request, "anagrafica/pages/skm_match_validazione.html", {
        "righe": righe,
        "n_tot": len(righe),
        "n_conf": n_conf,
        "n_escl": n_escl,
        "n_val": n_val,
        "catalogo_vuoto": len(righe) == 0,
        "asset_opts": asset_opts,
    })


# ---------------------------------------------------------------------------
# Skill Matrix MOD.187 — matrice persone × macchine (F4)
# ---------------------------------------------------------------------------

@login_required
def skill_matrix_macchina(request):
    """Matrice **persone × macchine** con livelli I/L/U/O (MOD.187).

    Celle = livello (etichetta configurabile); marker ``▲`` sotto livello
    richiesto; tratteggio = rivalutazione arretrata (NON bloccante); barra blu =
    multivoce; punto = continuità monitorata. KPI in testa (prontezza squadra,
    macchine scoperte, rischio uomo-solo, continuità persa) dal resolver F3.
    Tab gemella "Processi qualificati" rimanda alla matrice qualifiche esistente.

    Sola lettura. Accesso: ``_check_hr_permission`` (ACL formale in F7).
    Finché la baseline (F2b) non è importata, la matrice è vuota: la pagina
    mostra comunque struttura e KPI, con rimando alla validazione match (F2a).
    """
    from ..acl_bootstrap import PERM_SKM_VIEW
    if not _check_skm_permission(request, PERM_SKM_VIEW):
        messages.error(request, "Non hai i permessi per la Skill Matrix macchine.")
        return redirect("anagrafica:index")

    from django.utils import timezone
    from ..models import (
        AbilitazioneMacchina, CompetenzaSkm, ContinuitaOperativa, SkillMatrixConfig,
    )
    from ..services import skillmatrix_resolver as resolver

    config = SkillMatrixConfig.get_instance()
    filtro_reparto = (request.GET.get("reparto") or "").strip()
    export_csv = request.GET.get("format") == "csv"
    oggi = timezone.localdate()

    # Colonne = macchine MOD.187 con asset risolto (catalogo F2a).
    comp_all = list(
        CompetenzaSkm.objects
        .filter(tipo=CompetenzaSkm.TIPO_MACCHINA, asset__isnull=False)
        .select_related("asset").order_by("display", "competenza_key")
    )
    reparti = sorted({
        (c.asset.reparto or "").strip() for c in comp_all if (c.asset.reparto or "").strip()
    })
    comp_macchine = [
        c for c in comp_all
        if not filtro_reparto or (c.asset.reparto or "").strip().casefold() == filtro_reparto.casefold()
    ]
    asset_ids = [c.asset_id for c in comp_macchine]

    # Abilitazioni su quelle macchine (vuoto finché non c'è la baseline F2b).
    ab_map: dict[tuple[int, int], AbilitazioneMacchina] = {}
    legacy_ids: set[int] = set()
    if asset_ids:
        for ab in AbilitazioneMacchina.objects.filter(asset_id__in=asset_ids).prefetch_related("voci"):
            ab_map[(ab.legacy_anagrafica_id, ab.asset_id)] = ab
            legacy_ids.add(ab.legacy_anagrafica_id)

    # Nomi dall'anagrafica legacy: solo se servono, fail-safe (la sorgente può
    # non essere disponibile, es. in test) → fallback "ID <n>".
    dip_map: dict[int, dict] = {}
    if legacy_ids:
        try:
            dip_map = {int(r["id"]): r for r in fetch_anagrafica_rows(deduplicate=True) if r.get("id")}
        except Exception:
            logger.warning("Skill Matrix: anagrafica legacy non disponibile, nomi non risolti", exc_info=True)
    soglia_ord = config.soglia_operativa_ordinale

    # Disponibilità per una data scelta (Skill Matrix × assenze): chi è in
    # ferie/malattia/permesso quel giorno. Read-only, fail-safe: se la sorgente
    # assenze non risponde la matrice resta identica (nessun marker).
    import datetime as _dt
    data_str = (request.GET.get("data") or "").strip()
    try:
        data_sel = _dt.date.fromisoformat(data_str) if data_str else oggi
    except ValueError:
        data_sel = oggi
    disp_map: dict[int, list[dict]] = {}
    if legacy_ids:
        try:
            from assenze.availability import disponibilita_per_anagrafica
            disp_map = disponibilita_per_anagrafica(sorted(legacy_ids), data_sel, data_sel)
        except Exception:
            logger.warning("Skill Matrix: disponibilità assenze non risolta", exc_info=True)

    righe: list[dict] = []
    for lid in legacy_ids:
        dip = dip_map.get(lid, {})
        celle = []
        for c in comp_macchine:
            ab = ab_map.get((lid, c.asset_id))
            if ab is None:
                celle.append({"vuota": True})
                continue
            celle.append({
                "vuota": False,
                "livello": ab.livello,
                "etichetta": config.etichetta(ab.livello),
                "operativa": ab.is_operativa(soglia_ord),
                "sotto": ab.sotto_livello_richiesto,
                "arretrata": bool(ab.prossima_revisione and ab.prossima_revisione < oggi),
                "multivoce": bool(ab.voci.all()),
                "sospesa": ab.stato == AbilitazioneMacchina.STATO_SOSPESA,
                "in_lista": ab.in_lista,
            })
        assenze_lid = disp_map.get(lid, [])
        if any(a["stato"] == "confermata" for a in assenze_lid):
            disp_stato = "assente"
        elif any(a["stato"] == "pendente" for a in assenze_lid):
            disp_stato = "da_confermare"
        else:
            disp_stato = "presente"
        righe.append({
            "legacy_id": lid,
            "cognome": str(dip.get("cognome") or f"ID {lid}").strip(),
            "nome": str(dip.get("nome") or "").strip(),
            "reparto": str(dip.get("reparto") or "").strip(),
            "celle": celle,
            "disp_stato": disp_stato,
            "disp_assenze": assenze_lid,
        })
    righe.sort(key=lambda r: (r["cognome"].casefold(), r["nome"].casefold()))

    if export_csv:
        def _disp_csv(r):
            if r["disp_stato"] == "assente":
                tipi = []
                for a in r["disp_assenze"]:
                    if a["stato"] != "confermata":
                        continue
                    t = a["tipo"] + (" (parziale)" if a.get("parziale") else "")
                    if t not in tipi:
                        tipi.append(t)
                return "assente (%s)" % ", ".join(tipi) if tipi else "assente"
            if r["disp_stato"] == "da_confermare":
                return "da confermare"
            return ""

        resp = HttpResponse(content_type=CSV_CONTENT_TYPE)
        resp["Content-Disposition"] = 'attachment; filename="skill_matrix_macchina.csv"'
        resp.write(BOM)  # una volta sola: Excel riconosce l'UTF-8
        writer = safe_csv_writer(resp, delimiter=";")
        disp_col = f"Disponibilità {data_sel.strftime('%d/%m/%Y')}"
        writer.writerow(
            ["Dipendente", "Reparto", disp_col] + [c.display or c.competenza_key for c in comp_macchine]
        )
        for r in righe:
            cells = []
            for cell in r["celle"]:
                cells.append("" if cell["vuota"] else cell["livello"])
            writer.writerow(
                [naming.nome_completo(r["nome"], r["cognome"]), r["reparto"], _disp_csv(r)] + cells
            )
        return resp

    # KPI dal resolver (rispettano il filtro reparto).
    rep = filtro_reparto or None
    prontezza = resolver.prontezza_squadra(rep, config=config)
    n_scoperte = len(resolver.macchine_scoperte(rep))
    n_uomo_solo = sum(
        1 for c in comp_macchine if resolver.kpi_uomo_solo(c.asset, config=config)["a_rischio"]
    )
    n_cont_persa = sum(
        1 for co in ContinuitaOperativa.objects.all()
        if co.stato() == ContinuitaOperativa.STATO_PERSA
    )

    from ..acl_bootstrap import PERM_SKM_MANAGE
    n_assenti = sum(1 for r in righe if r["disp_stato"] == "assente")
    n_da_confermare = sum(1 for r in righe if r["disp_stato"] == "da_confermare")

    # Contatore abilitati operativi per macchina (header colonna, 1.12).
    from ..services import skillmatrix_qualifica as skm_q
    col_counts = skm_q.conta_operativi_per_asset(asset_ids)
    for c in comp_macchine:
        c.operativi_count = col_counts.get(c.asset_id, 0)

    return render(request, "anagrafica/pages/skill_matrix_macchina.html", {
        "macchine": comp_macchine,
        "righe": righe,
        "reparti": reparti,
        "filtro_reparto": filtro_reparto,
        "totale_persone": len(righe),
        "config": config,
        "kpi": {
            "prontezza": prontezza,
            "scoperte": n_scoperte,
            "uomo_solo": n_uomo_solo,
            "continuita_persa": n_cont_persa,
        },
        "matrice_vuota": len(righe) == 0,
        "n_macchine": len(comp_macchine),
        "data_sel": data_sel,
        "n_assenti": n_assenti,
        "n_da_confermare": n_da_confermare,
        "can_manage": _check_skm_permission(request, PERM_SKM_MANAGE),
        "can_impostazioni": impostazioni_o(request, "anagrafica", lambda r: _check_skm_permission(r, PERM_SKM_MANAGE)),
    })


# ---------------------------------------------------------------------------
# Skill Matrix MOD.187 — refresh semestrale CAR (F6)
# ---------------------------------------------------------------------------

@login_required
def skm_refresh(request):
    """Schermata CAR di **refresh** delle abilitazioni del reparto (MOD.187).

    ① Rivaluta le persone in lista sulle mansioni del reparto, macchine e processi
    (conferma / modifica livello / rimuovi); dove la mansione ha competenze il
    livello si ricava dalla valutazione per competenza (Mansionario fase 3).
    ② Aggiunge una persona a una mansione del reparto. ③ Note del CAR per la
    qualità; la campagna si chiude quando il CAR ha finito. Ogni azione scrive uno
    scatto in ``AbilitazioneMacchinaStorico`` e sposta ``prossima_revisione``.

    Accesso: ``anagrafica.skillmatrix.manage``. Merito = CAR; la qualità avvia e
    sollecita (D18). Nessun dato sanitario: solo livelli e nomi di mansione.
    """
    from ..acl_bootstrap import PERM_SKM_MANAGE
    if not _check_skm_permission(request, PERM_SKM_MANAGE):
        messages.error(request, "Non hai i permessi per il refresh Skill Matrix.")
        return redirect("anagrafica:index")

    from urllib.parse import urlencode
    from django.utils import timezone
    from core.audit import log_action
    from ..models import CampagnaRefresh, CompetenzaSkm, LivelloSkm
    from ..services import mansionario_struttura as mstruttura
    from ..services import skillmatrix_refresh as refresh
    from ..services.mansionario_competenze import competenze as competenze_mansione

    reparto = (request.GET.get("reparto") or request.POST.get("reparto") or "").strip()
    reparti = refresh.reparti_con_mansioni()
    mansioni = refresh.mansioni_reparto(reparto) if reparto else []

    if request.method == "POST" and reparto:
        legacy_user = get_legacy_user(request.user)
        car_id = int(legacy_user.id) if legacy_user else None
        camp = refresh.apri_campagna(reparto, avviatore_ruolo=(request.POST.get("avviatore_ruolo") or "").strip())
        decisioni = {}
        for k, v in request.POST.items():
            if k.startswith("azione_"):
                ab_id = k[len("azione_"):]
                decisioni[ab_id] = {"azione": v, "livello": request.POST.get(f"livello_{ab_id}", "")}
        stats = refresh.applica_refresh(reparto=reparto, decisioni=decisioni, campagna=camp,
                                        car_legacy_id=car_id)
        # ② aggiunta (facoltativa): persona + mansione del reparto + livello.
        nl = (request.POST.get("nuovo_legacy") or "").strip()
        nm = (request.POST.get("nuova_mansione") or "").strip()
        nlv = (request.POST.get("nuovo_livello") or "").strip()
        agg = 0
        if nl or nm or nlv:
            mansione = next((m for m in mansioni if str(m.pk) == nm), None)
            if nl.isdigit() and mansione is not None and nlv:
                try:
                    mstruttura.assegna(mansione, legacy_anagrafica_id=int(nl), livello=nlv, user=request.user)
                    agg = 1
                except ValueError as exc:
                    messages.warning(request, f"Aggiunta non riuscita: {exc}")
            else:
                messages.warning(request, "Per aggiungere scegli persona, mansione e livello.")
        # ③ note del CAR per la qualità e chiusura.
        nota = (request.POST.get("nota_car") or "").strip()
        if nota:
            refresh.aggiungi_nota_campagna(camp, nota, autore=request.user.get_full_name() or request.user.get_username())
        chiusa = request.POST.get("chiudi_campagna") == "1"
        if chiusa:
            refresh.chiudi_campagna(camp)
        log_action(request, "skm_refresh", "anagrafica", {
            "reparto": reparto, "campagna": camp.pk, **{k: stats[k] for k in ("confermate", "modificate", "rimosse")},
            "aggiunte": agg, "nota": bool(nota), "chiusa": chiusa,
        })
        messages.success(
            request,
            f"Refresh salvato: {stats['confermate']} confermate, {stats['modificate']} modificate, "
            f"{stats['rimosse']} rimosse" + (f", {agg} aggiunta" if agg else "")
            + (". Campagna chiusa." if chiusa else "."),
        )
        return redirect(f"{reverse('anagrafica:skm_refresh')}?{urlencode({'reparto': reparto})}")

    oggi = timezone.localdate()
    abil = list(refresh.abilitazioni_reparto(reparto)) if reparto else []
    dip_rows = []
    try:
        dip_rows = fetch_anagrafica_rows(deduplicate=True)
    except Exception:
        logger.warning("Skill Matrix refresh: anagrafica legacy non disponibile", exc_info=True)
    dip_map = {int(r["id"]): r for r in dip_rows if r.get("id")}

    def _nome(lid):
        d = dip_map.get(lid, {})
        return naming.nome_completo(d.get("nome"), d.get("cognome")) or f"ID {lid}"

    con_competenze = {m.pk for m in mansioni if competenze_mansione(m).exists()}
    righe = [{
        "ab": a, "nome": _nome(a.legacy_anagrafica_id),
        "mansione": a.competenza.nome if a.competenza_id else (a.asset.name if a.asset_id else "—"),
        "per_competenze": a.competenza_id in con_competenze,
        "arretrata": bool(a.prossima_revisione and a.prossima_revisione < oggi),
    } for a in abil]
    campagna = (
        CampagnaRefresh.objects.filter(reparto=reparto, stato=CampagnaRefresh.STATO_APERTA).first()
        if reparto else None
    )
    persone_opts = sorted(
        ({"id": int(r["id"]), "nome": naming.nome_completo(r.get("nome"), r.get("cognome"))}
         for r in dip_rows if r.get("attivo", True) and r.get("id")),
        key=lambda c: c["nome"].casefold(),
    ) if reparto else []

    return render(request, "anagrafica/pages/skm_refresh.html", {
        "reparto": reparto,
        "reparti": reparti,
        "righe": righe,
        "mansioni_reparto": [{"id": m.pk, "label": m.nome + (" (processo)" if m.tipo == CompetenzaSkm.TIPO_PROCESSO else "")}
                             for m in mansioni if m.attiva],
        "persone_opts": persone_opts,
        "campagna": campagna,
        "coerenza": refresh.coerenza_rischio_reparto(reparto) if reparto else None,
        "arretrati": sum(1 for r in righe if r["arretrata"]),
        "livelli": LivelloSkm.choices,
        "totale": len(righe),
    })


@login_required
def skm_scadenzario(request):
    """Scadenzario abilitazioni macchina per reparto (MOD.187).

    Mostra, per reparto, la prossima revisione, gli arretrati (non bloccanti) e lo
    stato campagna. La qualità "dà il via" al refresh (apre la campagna e avvisa il CAR:
    in-app + email) e può sollecitarlo; il merito della rivalutazione resta al CAR.
    Accesso: ``anagrafica.skillmatrix.manage``.
    """
    from ..acl_bootstrap import PERM_SKM_MANAGE
    if not _check_skm_permission(request, PERM_SKM_MANAGE):
        messages.error(request, "Non hai i permessi per lo scadenzario Skill Matrix.")
        return redirect("anagrafica:index")

    from django.utils import timezone
    from ..services import skillmatrix_refresh as refresh

    if request.method == "POST" and request.POST.get("azione") == "avvia":
        reparto = (request.POST.get("reparto") or "").strip()
        if reparto:
            legacy_user = get_legacy_user(request.user)
            _, created = refresh.avvia_refresh(
                reparto=reparto, avviatore_ruolo="Qualità",
                avviatore_legacy_id=int(legacy_user.id) if legacy_user else None)
            if created:
                messages.success(request, f"Refresh avviato per «{reparto}»: il caporeparto è stato avvisato.")
            else:
                messages.info(request, f"Il reparto «{reparto}» ha già una campagna di refresh aperta.")
        return redirect("anagrafica:skm_scadenzario")

    if request.method == "POST" and request.POST.get("azione") == "sollecita":
        reparto = (request.POST.get("reparto") or "").strip()
        if refresh.sollecita_car(reparto):
            messages.success(request, f"Sollecito inviato al caporeparto di «{reparto}».")
        else:
            messages.info(request, f"Il reparto «{reparto}» non ha una campagna di refresh aperta.")
        return redirect("anagrafica:skm_scadenzario")

    oggi = timezone.localdate()
    tutte = refresh.scadenzario_reparti(oggi=oggi)
    kpi = {
        "reparti_scaduti": sum(1 for r in tutte if r["stato"] == "scaduto"),
        "abil_scadute": sum(r["n_scadute"] for r in tutte),
        "campagne_aperte": sum(1 for r in tutte if r["campagna_aperta"]),
    }

    filtro_stato = (request.GET.get("stato") or "").strip()
    righe = [r for r in tutte if r["stato"] == filtro_stato] if filtro_stato in ("scaduto", "in_arrivo") else tutte

    if request.GET.get("format") == "csv":
        resp = HttpResponse(content_type=CSV_CONTENT_TYPE)
        resp["Content-Disposition"] = 'attachment; filename="scadenzario_abilitazioni.csv"'
        resp.write(BOM)  # una volta sola: Excel riconosce l'UTF-8
        w = safe_csv_writer(resp, delimiter=";")
        w.writerow(["Reparto", "Prossima revisione", "Totali", "Scadute", "In arrivo", "Stato", "Campagna aperta"])
        for r in righe:
            w.writerow([
                r["reparto"],
                r["prossima_revisione"].strftime("%d/%m/%Y") if r["prossima_revisione"] else "",
                r["n_totali"], r["n_scadute"], r["n_in_arrivo"], r["stato"],
                "Sì" if r["campagna_aperta"] else "No",
            ])
        return resp

    return render(request, "anagrafica/pages/skm_scadenzario.html", {
        "oggi": oggi, "righe": righe, "kpi": kpi, "filtro_stato": filtro_stato,
        "totale": len(righe),
    })


@login_required
def skm_copertura(request):
    """Verifica **copertura minima** (AS/EN 9100): soglie configurate vs abilitati
    operativi disponibili, con evidenza dei gap. Riuso del resolver skill matrix
    per gli asset e delle abilitazioni MPQ attive per i processi. Sola lettura;
    le soglie si gestiscono da admin. Accesso: ``anagrafica.skillmatrix.view``.
    """
    from ..acl_bootstrap import PERM_SKM_VIEW
    if not _check_skm_permission(request, PERM_SKM_VIEW):
        messages.error(request, "Non hai i permessi per la Skill Matrix.")
        return redirect("anagrafica:index")

    from ..services import skillmatrix_copertura as cov
    righe = cov.valuta_copertura()
    kpi = {
        "totali": len(righe),
        "scoperte": sum(1 for r in righe if r["coperta"] is False),
        "gap_totale": sum((r["gap"] or 0) for r in righe),
        "non_valutabili": sum(1 for r in righe if r["coperta"] is None),
    }
    return render(request, "anagrafica/pages/skm_copertura.html", {
        "righe": righe, "kpi": kpi,
    })


@login_required
def skm_impostazioni(request):
    """Gestione del singleton ``SkillMatrixConfig`` (parametri Skill Matrix MOD.187).

    Governa "operativo" (soglia livello, CAR come riserva), il rischio uomo-solo,
    le cadenze continuità/refresh e le etichette della scala. Sola configurazione,
    nessun dato personale. Accesso: ``anagrafica.skillmatrix.manage``.
    """
    from ..acl_bootstrap import PERM_SKM_MANAGE
    if not impostazioni_o(request, "anagrafica", lambda r: _check_skm_permission(r, PERM_SKM_MANAGE)):
        messages.error(request, "Non hai i permessi per gestire la configurazione Skill Matrix.")
        return redirect("anagrafica:index")

    from ..forms import SkillMatrixConfigForm
    from ..models import SkillMatrixConfig

    config = SkillMatrixConfig.get_instance()
    if request.method == "POST":
        form = SkillMatrixConfigForm(request.POST, instance=config)
        if form.is_valid():
            form.save()
            messages.success(request, "Configurazione Skill Matrix aggiornata.")
            return redirect("anagrafica:skm_impostazioni")
        messages.error(request, "Controlla i campi: la configurazione non è stata salvata.")
    else:
        form = SkillMatrixConfigForm(instance=config)

    return render(request, "anagrafica/pages/skill_matrix_impostazioni.html", {
        "form": form,
        "config": config,
    })
