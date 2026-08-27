"""Export tabellari delle liste «Formazione» di anagrafica.

Le spec sono registrate all'import del modulo (vedi `anagrafica/exports.py`).

Ogni spec replica *fedelmente* filtri (nomi dei parametri GET e semantica) e
colonne visibili della pagina elenco corrispondente in `anagrafica/views.py`.
Nessun campo non mostrato a schermo viene esportato (dati HR → minimizzazione).
"""
from __future__ import annotations

from django.http import HttpRequest

from anagrafica.exports import ExportSpec, acl_gate, register  # noqa: F401


def _d(value) -> str:
    """Data in formato d-m-Y (come a schermo); stringa vuota se assente."""
    return value.strftime("%d-%m-%Y") if value else ""


def _si_no(value: bool) -> str:
    return "Si" if value else "No"


# ── Corsi ─────────────────────────────────────────────────────────────────────
# Filtri di `views.formazione_corsi_list`: q (titolo|codice), piano, stato,
# obbligatorio (1 = solo obbligatori, 0 = solo facoltativi).

def _formazione_corsi_qs(request: HttpRequest, scope: str):
    from django.db.models import Q

    from anagrafica.models import TrainingCourse

    qs = TrainingCourse.objects.select_related("piano").all()
    if scope == "filtered":
        filtro_piano = (request.GET.get("piano") or "").strip()
        filtro_stato = (request.GET.get("stato") or "").strip()
        filtro_obbligatorio = (request.GET.get("obbligatorio") or "").strip()
        q_search = (request.GET.get("q") or "").strip()
        if filtro_piano:
            try:
                qs = qs.filter(piano_id=int(filtro_piano))
            except (TypeError, ValueError):
                pass
        if filtro_stato:
            qs = qs.filter(stato=filtro_stato)
        if filtro_obbligatorio == "1":
            qs = qs.filter(obbligatorio=True)
        elif filtro_obbligatorio == "0":
            qs = qs.filter(obbligatorio=False)
        if q_search:
            qs = qs.filter(Q(titolo__icontains=q_search) | Q(codice__icontains=q_search))
    return qs.order_by("piano__nome", "titolo")


def _formazione_corsi_rows(request: HttpRequest, scope: str) -> list[dict]:
    rows: list[dict] = []
    for c in _formazione_corsi_qs(request, scope):
        rows.append({
            "codice": c.codice or "",
            "titolo": c.titolo or "",
            "piano": c.piano.nome if c.piano_id else "",
            "stato": c.get_stato_display(),
            "durata_ore": c.durata_ore_teorica,
            "validita": c.validita_mesi if c.validita_mesi else "una tantum",
            "obbligatorio": _si_no(c.obbligatorio),
        })
    return rows


def _formazione_corsi_filters(request: HttpRequest) -> str:
    from anagrafica.models import TrainingCourse, TrainingPlan

    parts: list[str] = []
    q_search = (request.GET.get("q") or "").strip()
    if q_search:
        parts.append(f'Ricerca: "{q_search}"')
    filtro_piano = (request.GET.get("piano") or "").strip()
    if filtro_piano:
        piano = TrainingPlan.objects.filter(pk=filtro_piano).first() if filtro_piano.isdigit() else None
        parts.append(f"Piano: {piano.nome if piano else filtro_piano}")
    filtro_stato = (request.GET.get("stato") or "").strip()
    labels = dict(TrainingCourse.STATO_CHOICES)
    if filtro_stato in labels:
        parts.append(f"Stato: {labels[filtro_stato]}")
    filtro_obbligatorio = (request.GET.get("obbligatorio") or "").strip()
    if filtro_obbligatorio == "1":
        parts.append("Solo obbligatori")
    elif filtro_obbligatorio == "0":
        parts.append("Solo facoltativi")
    return " · ".join(parts)


register(ExportSpec(
    key="formazione_corsi",
    title="Corsi formativi",
    sheet_title="Corsi",
    columns=[
        ("Codice", "codice"),
        ("Titolo", "titolo"),
        ("Piano", "piano"),
        ("Stato", "stato"),
        ("Durata (h)", "durata_ore"),
        ("Validità (mesi)", "validita"),
        ("Obbligatorio", "obbligatorio"),
    ],
    dataset=_formazione_corsi_rows,
    filters_label=_formazione_corsi_filters,
    permission=acl_gate("/anagrafica/formazione/corsi/"),
))


# ── Sessioni ──────────────────────────────────────────────────────────────────
# Filtri di `views.formazione_sessioni_list`: q (codice_sessione|corso.titolo|sede),
# corso, stato, anno (anno di data_inizio).

def _formazione_sessioni_qs(request: HttpRequest, scope: str):
    from django.db.models import Q

    from anagrafica.models import TrainingSession

    qs = TrainingSession.objects.select_related("corso", "corso__piano", "docente").all()
    if scope == "filtered":
        filtro_corso = (request.GET.get("corso") or "").strip()
        filtro_stato = (request.GET.get("stato") or "").strip()
        filtro_anno = (request.GET.get("anno") or "").strip()
        q_search = (request.GET.get("q") or "").strip()
        if filtro_corso:
            try:
                qs = qs.filter(corso_id=int(filtro_corso))
            except (TypeError, ValueError):
                pass
        if filtro_stato:
            qs = qs.filter(stato=filtro_stato)
        if filtro_anno:
            try:
                qs = qs.filter(data_inizio__year=int(filtro_anno))
            except (TypeError, ValueError):
                pass
        if q_search:
            qs = qs.filter(
                Q(codice_sessione__icontains=q_search)
                | Q(corso__titolo__icontains=q_search)
                | Q(sede__icontains=q_search)
            )
    return qs.order_by("-data_inizio")


def _formazione_sessioni_rows(request: HttpRequest, scope: str) -> list[dict]:
    rows: list[dict] = []
    for s in _formazione_sessioni_qs(request, scope):
        docente = (s.docente_nome or "").strip() or (s.docente.nome if s.docente_id else "")
        rows.append({
            "codice": s.codice_sessione or "",
            "corso": s.corso.titolo if s.corso_id else "",
            "piano": s.corso.piano.nome if (s.corso_id and s.corso.piano_id) else "",
            "inizio": _d(s.data_inizio),
            "fine": _d(s.data_fine),
            "stato": s.get_stato_display(),
            "modalita": s.get_modalita_display(),
            "docente": docente,
        })
    return rows


def _formazione_sessioni_filters(request: HttpRequest) -> str:
    from anagrafica.models import TrainingCourse, TrainingSession

    parts: list[str] = []
    q_search = (request.GET.get("q") or "").strip()
    if q_search:
        parts.append(f'Ricerca: "{q_search}"')
    filtro_corso = (request.GET.get("corso") or "").strip()
    if filtro_corso:
        corso = TrainingCourse.objects.filter(pk=filtro_corso).first() if filtro_corso.isdigit() else None
        parts.append(f"Corso: {corso.titolo if corso else filtro_corso}")
    filtro_stato = (request.GET.get("stato") or "").strip()
    labels = dict(TrainingSession.STATO_CHOICES)
    if filtro_stato in labels:
        parts.append(f"Stato: {labels[filtro_stato]}")
    filtro_anno = (request.GET.get("anno") or "").strip()
    if filtro_anno:
        parts.append(f"Anno: {filtro_anno}")
    return " · ".join(parts)


register(ExportSpec(
    key="formazione_sessioni",
    title="Sessioni formative",
    sheet_title="Sessioni",
    columns=[
        ("Codice", "codice"),
        ("Corso", "corso"),
        ("Piano", "piano"),
        ("Inizio", "inizio"),
        ("Fine", "fine"),
        ("Stato", "stato"),
        ("Modalità", "modalita"),
        ("Docente", "docente"),
    ],
    dataset=_formazione_sessioni_rows,
    filters_label=_formazione_sessioni_filters,
    permission=acl_gate("/anagrafica/formazione/sessioni/"),
))


# ── Piani formativi ───────────────────────────────────────────────────────────
# Filtri di `views.formazione_piani_list`: stato, categoria.

def _formazione_piani_rows(request: HttpRequest, scope: str) -> list[dict]:
    from django.db.models import Count

    from anagrafica.models import TrainingPlan

    qs = TrainingPlan.objects.all()
    if scope == "filtered":
        filtro_stato = (request.GET.get("stato") or "").strip()
        filtro_cat = (request.GET.get("categoria") or "").strip()
        if filtro_stato:
            qs = qs.filter(stato=filtro_stato)
        if filtro_cat:
            qs = qs.filter(categoria=filtro_cat)

    rows: list[dict] = []
    for p in qs.order_by("nome").annotate(n_corsi=Count("corsi")):
        rows.append({
            "codice": p.codice or "",
            "nome": p.nome or "",
            "categoria": p.get_categoria_display(),
            "stato": p.get_stato_display(),
            "n_corsi": p.n_corsi,
            "provider": _si_no(p.provider_esterno),
        })
    return rows


def _formazione_piani_filters(request: HttpRequest) -> str:
    from anagrafica.models import TrainingPlan

    parts: list[str] = []
    filtro_stato = (request.GET.get("stato") or "").strip()
    stati = dict(TrainingPlan.STATO_CHOICES)
    if filtro_stato in stati:
        parts.append(f"Stato: {stati[filtro_stato]}")
    filtro_cat = (request.GET.get("categoria") or "").strip()
    categorie = dict(TrainingPlan.CATEGORIA_CHOICES)
    if filtro_cat in categorie:
        parts.append(f"Categoria: {categorie[filtro_cat]}")
    return " · ".join(parts)


register(ExportSpec(
    key="formazione_piani",
    title="Piani formativi",
    sheet_title="Piani",
    columns=[
        ("Codice", "codice"),
        ("Nome", "nome"),
        ("Categoria", "categoria"),
        ("Stato", "stato"),
        ("Corsi", "n_corsi"),
        ("Provider esterno", "provider"),
    ],
    dataset=_formazione_piani_rows,
    filters_label=_formazione_piani_filters,
    permission=acl_gate("/anagrafica/formazione/piani/"),
))


# ── Docenti / Formatori ───────────────────────────────────────────────────────
# Filtri di `views.formazione_istruttori_list`: q (nome|ragione_sociale|azienda),
# tipo, azienda (id o "NESSUNA").
# Email/telefono sono già visibili a schermo (contatti professionali del docente).

def _formazione_istruttori_rows(request: HttpRequest, scope: str) -> list[dict]:
    from django.db.models import Q

    from anagrafica.models import TrainingInstructor

    qs = TrainingInstructor.objects.select_related("azienda")
    if scope == "filtered":
        filtro_tipo = (request.GET.get("tipo") or "").strip()
        q_search = (request.GET.get("q") or "").strip()
        filtro_azienda = (request.GET.get("azienda") or "").strip()
        if filtro_tipo:
            qs = qs.filter(tipo=filtro_tipo)
        if q_search:
            qs = qs.filter(
                Q(nome__icontains=q_search)
                | Q(ragione_sociale__icontains=q_search)
                | Q(azienda__nome__icontains=q_search)
            )
        if filtro_azienda == "NESSUNA":
            qs = qs.filter(azienda__isnull=True)
        elif filtro_azienda.isdigit():
            qs = qs.filter(azienda_id=int(filtro_azienda))

    rows: list[dict] = []
    for i in qs.order_by("nome"):
        rows.append({
            "nome": i.nome or "",
            "tipo": i.get_tipo_display(),
            "azienda": i.azienda.nome if i.azienda_id else "",
            "ragione_sociale": i.ragione_sociale or "",
            "email": i.email or "",
            "telefono": i.telefono or "",
            "attivo": _si_no(i.is_active),
        })
    return rows


def _formazione_istruttori_filters(request: HttpRequest) -> str:
    from anagrafica.models import TrainingInstructor

    parts: list[str] = []
    q_search = (request.GET.get("q") or "").strip()
    if q_search:
        parts.append(f'Ricerca: "{q_search}"')
    filtro_tipo = (request.GET.get("tipo") or "").strip()
    labels = dict(TrainingInstructor.TIPO_CHOICES)
    if filtro_tipo in labels:
        parts.append(f"Tipo: {labels[filtro_tipo]}")
    filtro_azienda = (request.GET.get("azienda") or "").strip()
    if filtro_azienda == "NESSUNA":
        parts.append("Azienda formativa: nessuna")
    elif filtro_azienda.isdigit():
        from anagrafica.models import TrainingProvider

        az = TrainingProvider.objects.filter(pk=int(filtro_azienda)).first()
        if az:
            parts.append(f"Azienda formativa: {az.nome}")
    return " · ".join(parts)


register(ExportSpec(
    key="formazione_istruttori",
    title="Docenti / Formatori",
    sheet_title="Docenti",
    columns=[
        ("Nome", "nome"),
        ("Tipo", "tipo"),
        ("Azienda formativa", "azienda"),
        ("Ragione sociale (libera)", "ragione_sociale"),
        ("Email", "email"),
        ("Telefono", "telefono"),
        ("Attivo", "attivo"),
    ],
    dataset=_formazione_istruttori_rows,
    filters_label=_formazione_istruttori_filters,
    permission=acl_gate("/anagrafica/formazione/istruttori/"),
))


# ── Scadenzario formazione ────────────────────────────────────────────────────
# Filtri di `views.formazione_scadenzario`: stato, corso, q (nome dipendente).
# Senza `stato` la lista mostra solo scaduti / in scadenza / mai frequentati:
# lo scope "filtered" replica questo default, lo scope "full" esporta tutto.

def _nomi_dipendenti() -> dict[int, str]:
    """{legacy_anagrafica_id: 'Cognome Nome'} — come `views._build_nomi_map`."""
    nomi: dict[int, str] = {}
    try:
        from core.legacy_models import AnagraficaDipendente

        for r in AnagraficaDipendente.objects.values("id", "cognome", "nome"):
            try:
                lid = int(r.get("id") or 0)
            except (TypeError, ValueError):
                continue
            cognome = (r.get("cognome") or "").strip()
            nome = (r.get("nome") or "").strip()
            nomi[lid] = f"{cognome} {nome}".strip() or f"#{lid}"
    except Exception:  # tabella legacy non disponibile: si degrada su "#id"
        return {}
    return nomi


def _formazione_scadenzario_rows(request: HttpRequest, scope: str) -> list[dict]:
    from anagrafica.models import TrainingDeadline

    qs = (
        TrainingDeadline.objects
        .select_related("corso", "corso__piano")
        .order_by("stato_scadenza", "data_scadenza", "legacy_anagrafica_id")
    )
    nomi_map = _nomi_dipendenti()

    if scope == "filtered":
        filtro_stato = (request.GET.get("stato") or "").strip()
        filtro_corso = (request.GET.get("corso") or "").strip()
        filtro_q = (request.GET.get("q") or "").strip()
        if filtro_stato:
            qs = qs.filter(stato_scadenza=filtro_stato)
        else:
            qs = qs.filter(
                stato_scadenza__in=["SCADUTO", "IN_SCADENZA_30", "IN_SCADENZA_90", "MAI_FREQUENTATO"]
            )
        if filtro_corso:
            try:
                qs = qs.filter(corso_id=int(filtro_corso))
            except (TypeError, ValueError):
                pass
        if filtro_q:
            q_lower = filtro_q.lower()
            matched = [lid for lid, nome in nomi_map.items() if q_lower in nome.lower()]
            qs = qs.filter(legacy_anagrafica_id__in=matched)

    rows: list[dict] = []
    for s in qs:
        corso = s.corso
        rows.append({
            "dipendente": nomi_map.get(s.legacy_anagrafica_id, f"#{s.legacy_anagrafica_id}"),
            "corso": f"[{corso.codice}] {corso.titolo}" if corso else "",
            "piano": corso.piano.nome if (corso and corso.piano_id) else "",
            "scadenza": _d(s.data_scadenza),
            "stato": s.get_stato_scadenza_display(),
            "obbligatorio": _si_no(s.is_required),
        })
    return rows


def _formazione_scadenzario_filters(request: HttpRequest) -> str:
    from anagrafica.models import TrainingCourse, TrainingDeadline

    parts: list[str] = []
    filtro_stato = (request.GET.get("stato") or "").strip()
    labels = dict(TrainingDeadline.STATO_SCADENZA_CHOICES)
    if filtro_stato in labels:
        parts.append(f"Stato: {labels[filtro_stato]}")
    else:
        parts.append("Scaduti + in scadenza + mai frequentati")
    filtro_corso = (request.GET.get("corso") or "").strip()
    if filtro_corso:
        corso = TrainingCourse.objects.filter(pk=filtro_corso).first() if filtro_corso.isdigit() else None
        parts.append(f"Corso: {corso.codice if corso else filtro_corso}")
    filtro_q = (request.GET.get("q") or "").strip()
    if filtro_q:
        parts.append(f'Ricerca: "{filtro_q}"')
    return " · ".join(parts)


register(ExportSpec(
    key="formazione_scadenzario",
    title="Scadenzario formazione",
    sheet_title="Scadenzario",
    columns=[
        ("Dipendente", "dipendente"),
        ("Corso", "corso"),
        ("Piano", "piano"),
        ("Scadenza", "scadenza"),
        ("Stato", "stato"),
        ("Obbligatorio", "obbligatorio"),
    ],
    dataset=_formazione_scadenzario_rows,
    filters_label=_formazione_scadenzario_filters,
    permission=acl_gate("/anagrafica/formazione/scadenzario/"),
))


# ── Fattori di rischio ────────────────────────────────────────────────────────
# `views.fattori_rischio_list` non ha filtri GET: la lista è completa.

def _fattori_rischio_rows(request: HttpRequest, scope: str) -> list[dict]:
    from django.db.models import Count

    from anagrafica.models import FattoreRischio

    qs = (
        FattoreRischio.objects
        .annotate(
            n_categorie=Count("categorie_corso", distinct=True),
            n_esposizioni=Count("esposizioni", distinct=True),
        )
        .order_by("categoria", "nome")
    )
    rows: list[dict] = []
    for f in qs:
        rows.append({
            "codice": f.codice or "",
            "nome": f.nome or "",
            "categoria": f.get_categoria_display(),
            "period_form": f.periodicita_formazione_mesi or "",
            "period_sorv": f.periodicita_sorveglianza_mesi or "",
            "req_form": _si_no(f.richiede_formazione),
            "req_med": _si_no(f.richiede_visita_medica),
            "req_dpi": _si_no(f.richiede_dpi),
            "n_categorie": f.n_categorie,
            "n_esposizioni": f.n_esposizioni,
            "attivo": _si_no(f.is_active),
        })
    return rows


register(ExportSpec(
    key="fattori_rischio",
    title="Fattori di rischio",
    sheet_title="Fattori rischio",
    columns=[
        ("Codice", "codice"),
        ("Nome", "nome"),
        ("Categoria", "categoria"),
        ("Formazione (mesi)", "period_form"),
        ("Sorveglianza (mesi)", "period_sorv"),
        ("Richiede formazione", "req_form"),
        ("Richiede visita medica", "req_med"),
        ("Richiede DPI", "req_dpi"),
        ("Categorie collegate", "n_categorie"),
        ("Esposizioni", "n_esposizioni"),
        ("Attivo", "attivo"),
    ],
    dataset=_fattori_rischio_rows,
    permission=acl_gate("/anagrafica/formazione/rischi/fattori/"),
))


# ── Categorie corso ───────────────────────────────────────────────────────────
# `views.categorie_corso_list` non ha filtri GET: la lista è completa.

def _categorie_corso_rows(request: HttpRequest, scope: str) -> list[dict]:
    from django.db.models import Count

    from anagrafica.models import CategoriaCorso

    qs = (
        CategoriaCorso.objects
        .prefetch_related("fattori_rischio")
        .annotate(n_corsi=Count("corsi", distinct=True))
        .order_by("nome")
    )
    rows: list[dict] = []
    for c in qs:
        rows.append({
            "codice": c.codice or "",
            "nome": c.nome or "",
            "descrizione": c.descrizione or "",
            "fattori": ", ".join(f.codice for f in c.fattori_rischio.all()),
            "n_corsi": c.n_corsi,
            "attivo": _si_no(c.is_active),
        })
    return rows


register(ExportSpec(
    key="categorie_corso",
    title="Categorie corso",
    sheet_title="Categorie corso",
    columns=[
        ("Codice", "codice"),
        ("Nome", "nome"),
        ("Descrizione", "descrizione"),
        ("Fattori collegati", "fattori"),
        ("Corsi", "n_corsi"),
        ("Attivo", "attivo"),
    ],
    dataset=_categorie_corso_rows,
    permission=acl_gate("/anagrafica/formazione/rischi/categorie/"),
))


# ── Esposizioni a rischio ─────────────────────────────────────────────────────
# `views.esposizioni_rischio_list` non ha filtri GET: la lista è completa.

def _esposizioni_rischio_rows(request: HttpRequest, scope: str) -> list[dict]:
    from anagrafica.models import EsposizioneRischio

    qs = (
        EsposizioneRischio.objects
        .select_related("fattore", "mansione", "area")
        .order_by("fattore__categoria", "fattore__nome", "mansione__nome", "area__nome")
    )
    rows: list[dict] = []
    for e in qs:
        rows.append({
            "fattore": f"[{e.fattore.codice}] {e.fattore.nome}" if e.fattore_id else "",
            "categoria": e.fattore.get_categoria_display() if e.fattore_id else "",
            "mansione": e.mansione.nome if e.mansione_id else "",
            "area": e.area.nome if e.area_id else "",
            "note": e.note or "",
            "attivo": _si_no(e.is_active),
        })
    return rows


register(ExportSpec(
    key="esposizioni_rischio",
    title="Esposizioni a rischio",
    sheet_title="Esposizioni",
    columns=[
        ("Fattore", "fattore"),
        ("Categoria fattore", "categoria"),
        ("Mansione", "mansione"),
        ("Area", "area"),
        ("Note", "note"),
        ("Attivo", "attivo"),
    ],
    dataset=_esposizioni_rischio_rows,
    permission=acl_gate("/anagrafica/formazione/rischi/esposizioni/"),
))
