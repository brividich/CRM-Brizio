"""Export tabellari delle liste «Qualifiche / MPQ / Skill matrix» di anagrafica.

Le spec sono registrate all'import del modulo (vedi `anagrafica/exports.py`).

Coperte qui:
  - ``qualifiche``            → /anagrafica/qualifiche/            (catalogo TipoQualifica)
  - ``qualifiche_scadenzario``→ /anagrafica/qualifiche/scadenzario/
  - ``qualifica_sessioni``    → /anagrafica/qualifiche/sessioni/
  - ``matrice_competenze``    → /anagrafica/sicurezza/matrice/
  - ``mpq_clienti``           → /anagrafica/mod128/clienti/

L'export MOD.128 "replica-Word" (`anagrafica/mpq_export.py`) resta separato: copre
la *vista processi qualificati* in .docx, non le liste qui sotto.

GDPR: solo colonne già visibili nelle pagine elenco corrispondenti; il gate ACL è
sempre quello della lista di origine (`acl_gate`).
"""
from __future__ import annotations

from django.http import HttpRequest

from anagrafica.exports import ExportSpec, acl_gate, register  # noqa: F401


def _fmt_date(value) -> str:
    return value.strftime("%d-%m-%Y") if value else ""


def _si_no(value) -> str:
    return "Sì" if value else "No"


# ── Catalogo qualifiche/abilitazioni ─────────────────────────────────────────
# Rispecchia `views.qualifiche_list`: unico filtro di querystring = `categoria`
# (le tab della pagina). Colonne = tabella "catalogo per categoria" a schermo
# (nome + corso collegato, durata validità, n. assegnazioni, stato).

def _qualifiche_rows(request: HttpRequest, scope: str) -> list[dict]:
    from django.db.models import Count

    from anagrafica.models import TipoQualifica

    valid_cats = {c for c, _ in TipoQualifica.CATEGORIA_CHOICES}
    cat_filter = (request.GET.get("categoria") or "").strip().upper()
    if cat_filter not in valid_cats:
        cat_filter = ""

    tipi = (
        TipoQualifica.objects.annotate(n_assegnazioni=Count("assegnazioni"))
        .prefetch_related("corsi")
        .order_by("categoria", "nome")
    )
    if scope == "filtered" and cat_filter:
        tipi = tipi.filter(categoria=cat_filter)

    rows: list[dict] = []
    for t in tipi:
        corsi = [c.titolo for c in t.corsi.all()]
        rows.append({
            "nome": t.nome or "",
            "categoria": t.get_categoria_display(),
            "durata": f"{t.durata_mesi} mesi" if t.durata_mesi else "Nessuna scadenza",
            "corsi": ", ".join(corsi),
            "n_assegnazioni": t.n_assegnazioni,
            "stato": "Attiva" if t.is_active else "Inattiva",
        })
    return rows


def _qualifiche_filters(request: HttpRequest) -> str:
    from anagrafica.models import TipoQualifica

    labels = dict(TipoQualifica.CATEGORIA_CHOICES)
    cat = (request.GET.get("categoria") or "").strip().upper()
    return f"Categoria: {labels[cat]}" if cat in labels else ""


register(ExportSpec(
    key="qualifiche",
    title="Catalogo qualifiche / abilitazioni",
    sheet_title="Qualifiche",
    columns=[
        ("Qualifica", "nome"),
        ("Categoria", "categoria"),
        ("Durata validità", "durata"),
        ("Corsi che la rilasciano", "corsi"),
        ("Assegnazioni", "n_assegnazioni"),
        ("Stato", "stato"),
    ],
    dataset=_qualifiche_rows,
    filters_label=_qualifiche_filters,
    permission=acl_gate("/anagrafica/qualifiche/"),
))


# ── Scadenzario qualifiche ───────────────────────────────────────────────────
# Rispecchia `views.qualifiche_scadenzario`: filtri `stato` (""|scaduta|30|60|
# valide|tutte), `categoria`, `tipo` (id), `reparto`. Il default (`stato` vuoto)
# NON è "tutto": è «da gestire» = scadute + in scadenza ≤60gg. Con `scope=full`
# si esportano invece tutte le assegnazioni. Colonne = quelle dell'export CSV già
# presente nella pagina (stesso set di campi, tutti a schermo o già esportabili).

def _scadenzario_qs(request: HttpRequest, scope: str):
    from datetime import timedelta

    from django.db.models import Q
    from django.utils import timezone as _tz

    from anagrafica.models import DipendenteQualifica, TipoQualifica

    oggi = _tz.localdate()
    soglia_30 = oggi + timedelta(days=30)
    soglia_60 = oggi + timedelta(days=60)

    filtro_stato = (request.GET.get("stato") or "").strip()
    filtro_cat = (request.GET.get("categoria") or "").strip().upper()
    filtro_tipo = (request.GET.get("tipo") or "").strip()
    valid_cats = {c for c, _ in TipoQualifica.CATEGORIA_CHOICES}
    if filtro_cat not in valid_cats:
        filtro_cat = ""

    qs = DipendenteQualifica.objects.select_related("tipo")
    if scope == "filtered":
        if filtro_cat:
            qs = qs.filter(tipo__categoria=filtro_cat)
        if filtro_tipo.isdigit():
            qs = qs.filter(tipo_id=int(filtro_tipo))
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
        else:  # default della pagina: scadute + ≤60gg
            qs = qs.filter(data_scadenza__isnull=False, data_scadenza__lte=soglia_60)
    return qs.order_by("data_scadenza", "tipo__nome"), oggi, soglia_30, soglia_60


def _scadenzario_rows(request: HttpRequest, scope: str) -> list[dict]:
    from core.legacy_anagrafica import fetch_anagrafica_rows

    # Stato RAG dalla stessa fonte unica usata dalla pagina.
    from anagrafica.views import _build_nomi_map, _classifica_scadenza_qualifica

    qs, oggi, soglia_30, soglia_60 = _scadenzario_qs(request, scope)

    try:
        dip_rows = fetch_anagrafica_rows(deduplicate=True)
    except Exception:
        dip_rows = []
    dip_map = {int(r["id"]): r for r in dip_rows if r.get("id")}
    nomi = _build_nomi_map()

    filtro_reparto = (request.GET.get("reparto") or "").strip()
    filtered = scope == "filtered"

    rows: list[dict] = []
    for q in qs:
        dip = dip_map.get(q.legacy_anagrafica_id, {})
        reparto = str(dip.get("reparto") or "").strip()
        if filtered and filtro_reparto and reparto.casefold() != filtro_reparto.casefold():
            continue
        _stato_code, stato_label = _classifica_scadenza_qualifica(
            q.data_scadenza, oggi, soglia_30, soglia_60
        )
        rows.append({
            "dipendente": nomi.get(q.legacy_anagrafica_id, f"#{q.legacy_anagrafica_id}"),
            "reparto": reparto,
            "qualifica": q.tipo.nome,
            "categoria": q.tipo.get_categoria_display(),
            "numero": q.numero or "",
            "livello": q.livello or "",
            "ente": q.ente or "",
            "conseguimento": _fmt_date(q.data_conseguimento),
            "scadenza": _fmt_date(q.data_scadenza),
            "giorni": (q.data_scadenza - oggi).days if q.data_scadenza else "",
            "stato": stato_label,
            "evidenza": _si_no(bool(q.documento)),
            "verificata": _si_no(q.verificata),
        })
    return rows


def _scadenzario_filters(request: HttpRequest) -> str:
    from anagrafica.models import TipoQualifica

    stato_labels = {
        "": "Da gestire (scadute + ≤60gg)",
        "scaduta": "Solo scadute",
        "30": "In scadenza ≤30gg",
        "60": "In scadenza ≤60gg",
        "valide": "Solo valide",
        "tutte": "Tutte",
    }
    parts: list[str] = []
    stato = (request.GET.get("stato") or "").strip()
    parts.append(f"Stato: {stato_labels.get(stato, stato_labels[''])}")

    cat_labels = dict(TipoQualifica.CATEGORIA_CHOICES)
    cat = (request.GET.get("categoria") or "").strip().upper()
    if cat in cat_labels:
        parts.append(f"Categoria: {cat_labels[cat]}")

    tipo = (request.GET.get("tipo") or "").strip()
    if tipo.isdigit():
        nome = TipoQualifica.objects.filter(pk=int(tipo)).values_list("nome", flat=True).first()
        if nome:
            parts.append(f"Qualifica: {nome}")

    reparto = (request.GET.get("reparto") or "").strip()
    if reparto:
        parts.append(f"Reparto: {reparto}")
    return " · ".join(parts)


register(ExportSpec(
    key="qualifiche_scadenzario",
    title="Scadenzario qualifiche",
    sheet_title="Scadenzario",
    columns=[
        ("Dipendente", "dipendente"),
        ("Reparto", "reparto"),
        ("Qualifica", "qualifica"),
        ("Categoria", "categoria"),
        ("N°", "numero"),
        ("Livello", "livello"),
        ("Ente", "ente"),
        ("Conseguimento", "conseguimento"),
        ("Scadenza", "scadenza"),
        ("Giorni", "giorni"),
        ("Stato", "stato"),
        ("Evidenza", "evidenza"),
        ("Verificata", "verificata"),
    ],
    dataset=_scadenzario_rows,
    filters_label=_scadenzario_filters,
    permission=acl_gate("/anagrafica/qualifiche/scadenzario/"),
))


# ── Sessioni di rinnovo qualifiche ───────────────────────────────────────────
# Rispecchia `views.qualifica_sessioni_list`: filtri `tipo` (id) e `q` (ricerca
# su nome qualifica / ente). Colonne = tabella a schermo.

def _sessioni_qs(request: HttpRequest, scope: str):
    from django.db.models import Count, Q

    from anagrafica.models import QualificaSessione

    qs = QualificaSessione.objects.select_related("tipo").annotate(n_part=Count("qualifiche"))
    if scope == "filtered":
        filtro_tipo = (request.GET.get("tipo") or "").strip()
        q_text = (request.GET.get("q") or "").strip()
        if filtro_tipo.isdigit():
            qs = qs.filter(tipo_id=int(filtro_tipo))
        if q_text:
            qs = qs.filter(Q(tipo__nome__icontains=q_text) | Q(ente__icontains=q_text))
    return qs.order_by("-data_conseguimento", "-id")


def _sessioni_rows(request: HttpRequest, scope: str) -> list[dict]:
    rows: list[dict] = []
    for s in _sessioni_qs(request, scope):
        rows.append({
            "data": _fmt_date(s.data_conseguimento),
            "qualifica": s.tipo.nome,
            "ente": s.ente or "",
            "partecipanti": s.n_part,
            "scadenza": _fmt_date(s.scadenza_effettiva),
        })
    return rows


def _sessioni_filters(request: HttpRequest) -> str:
    from anagrafica.models import TipoQualifica

    parts: list[str] = []
    tipo = (request.GET.get("tipo") or "").strip()
    if tipo.isdigit():
        nome = TipoQualifica.objects.filter(pk=int(tipo)).values_list("nome", flat=True).first()
        if nome:
            parts.append(f"Qualifica: {nome}")
    q_text = (request.GET.get("q") or "").strip()
    if q_text:
        parts.append(f'Ricerca: "{q_text}"')
    return " · ".join(parts)


register(ExportSpec(
    key="qualifica_sessioni",
    title="Sessioni di rinnovo qualifiche",
    sheet_title="Sessioni",
    columns=[
        ("Data", "data"),
        ("Qualifica", "qualifica"),
        ("Ente", "ente"),
        ("Partecipanti", "partecipanti"),
        ("Scadenza", "scadenza"),
    ],
    dataset=_sessioni_rows,
    filters_label=_sessioni_filters,
    permission=acl_gate("/anagrafica/qualifiche/sessioni/"),
))


# ── Matrice competenze (skill matrix) ────────────────────────────────────────
# Rispecchia `views.matrice_competenze`: filtri `reparto` e `categoria`; righe =
# dipendenti ATTIVI, colonne a schermo = una per TipoQualifica con almeno
# un'assegnazione.
#
# SCELTA DI APPIATTIMENTO (documentata): `ExportSpec.columns` è statico, mentre le
# colonne della matrice sono dinamiche (decine di competenze) e renderebbero il PDF
# illeggibile. L'export è quindi una tabella piatta con **una riga per dipendente**
# e le colonne principali: conteggi per stato (valide / in scadenza ≤60gg / scadute
# / non possedute) + l'elenco nominale delle competenze per i tre stati che contano
# per l'audit ISO 45001 (valide, in scadenza, scadute; con la data di scadenza dove
# presente). Le "non possedute" restano come conteggio: elencarle significherebbe
# ripetere quasi tutto il catalogo su ogni riga. Nessun dato in più rispetto alla
# matrice a schermo — solo una diversa disposizione delle stesse celle.

def _matrice_rows(request: HttpRequest, scope: str) -> list[dict]:
    from datetime import timedelta

    from django.db.models import Count
    from django.utils import timezone as _tz

    from core.legacy_anagrafica import ensure_anagrafica_schema, fetch_anagrafica_rows

    from anagrafica.models import DipendenteQualifica, TipoQualifica

    ensure_anagrafica_schema()

    valid_cats = {c for c, _ in TipoQualifica.CATEGORIA_CHOICES}
    cat_filter = (request.GET.get("categoria") or "").strip().upper()
    if cat_filter not in valid_cats:
        cat_filter = ""
    filtro_reparto = (request.GET.get("reparto") or "").strip()
    filtered = scope == "filtered"

    oggi = _tz.localdate()
    soglia = oggi + timedelta(days=60)

    dip_rows = [r for r in fetch_anagrafica_rows(deduplicate=True) if r.get("attivo")]
    dip_map = {int(r["id"]): r for r in dip_rows if r.get("id")}
    legacy_ids = list(dip_map.keys())

    tipi = list(
        TipoQualifica.objects.annotate(_n=Count("assegnazioni"))
        .filter(_n__gt=0).order_by("categoria", "nome")
    )
    if filtered and cat_filter:
        tipi = [t for t in tipi if t.categoria == cat_filter]
    tipo_ids = [t.id for t in tipi]

    q_map: dict[tuple[int, int], DipendenteQualifica] = {}
    for q in DipendenteQualifica.objects.filter(
        legacy_anagrafica_id__in=legacy_ids, tipo_id__in=tipo_ids
    ):
        q_map[(q.legacy_anagrafica_id, q.tipo_id)] = q

    def _stato(q):
        if q is None:
            return "mancante"
        if q.data_scadenza is None:
            return "valido"
        if q.data_scadenza < oggi:
            return "scaduto"
        if q.data_scadenza <= soglia:
            return "in_scadenza"
        return "valido"

    rows: list[dict] = []
    for lid, dip in dip_map.items():
        reparto = str(dip.get("reparto") or "").strip()
        if filtered and filtro_reparto and reparto.casefold() != filtro_reparto.casefold():
            continue
        buckets: dict[str, list[str]] = {"valido": [], "in_scadenza": [], "scaduto": [], "mancante": []}
        for t in tipi:
            q = q_map.get((lid, t.id))
            stato = _stato(q)
            etichetta = t.nome
            if q is not None and q.data_scadenza:
                etichetta = f"{t.nome} ({_fmt_date(q.data_scadenza)})"
            buckets[stato].append(etichetta)

        cognome = str(dip.get("cognome") or f"ID {lid}").strip()
        nome = str(dip.get("nome") or "").strip()
        rows.append({
            "_sort": (cognome.casefold(), nome.casefold()),
            "dipendente": f"{cognome} {nome}".strip(),
            "reparto": reparto,
            "n_valide": len(buckets["valido"]),
            "n_in_scadenza": len(buckets["in_scadenza"]),
            "n_scadute": len(buckets["scaduto"]),
            "n_mancanti": len(buckets["mancante"]),
            "valide": ", ".join(buckets["valido"]),
            "in_scadenza": ", ".join(buckets["in_scadenza"]),
            "scadute": ", ".join(buckets["scaduto"]),
        })
    rows.sort(key=lambda r: r["_sort"])
    for r in rows:
        r.pop("_sort", None)
    return rows


def _matrice_filters(request: HttpRequest) -> str:
    from anagrafica.models import TipoQualifica

    parts: list[str] = []
    reparto = (request.GET.get("reparto") or "").strip()
    if reparto:
        parts.append(f"Reparto: {reparto}")
    labels = dict(TipoQualifica.CATEGORIA_CHOICES)
    cat = (request.GET.get("categoria") or "").strip().upper()
    if cat in labels:
        parts.append(f"Categoria: {labels[cat]}")
    return " · ".join(parts)


register(ExportSpec(
    key="matrice_competenze",
    title="Matrice competenze (dipendenti × abilitazioni)",
    sheet_title="Matrice competenze",
    columns=[
        ("Dipendente", "dipendente"),
        ("Reparto", "reparto"),
        ("Valide", "n_valide"),
        ("In scadenza ≤60gg", "n_in_scadenza"),
        ("Scadute", "n_scadute"),
        ("Non possedute", "n_mancanti"),
        ("Competenze valide", "valide"),
        ("Competenze in scadenza", "in_scadenza"),
        ("Competenze scadute", "scadute"),
    ],
    dataset=_matrice_rows,
    filters_label=_matrice_filters,
    permission=acl_gate("/anagrafica/sicurezza/matrice/"),
))


# ── Clienti / enti qualificanti (MOD.128) ────────────────────────────────────
# Rispecchia `views_mpq.mpq_cliente_list`: nessun filtro di querystring (lista
# completa ordinata per tipo/nome). Colonne = tabella a schermo.

def _mpq_clienti_rows(request: HttpRequest, scope: str) -> list[dict]:
    from anagrafica.models_mpq import ClienteQualificante

    rows: list[dict] = []
    for c in ClienteQualificante.objects.select_related("certificatore").order_by("tipo", "nome"):
        rows.append({
            "nome": c.nome or "",
            "tipo": c.get_tipo_display(),
            "codice": c.codice or "",
            "certificatore": c.certificatore.nome if c.certificatore else "",
            "attivo": _si_no(c.is_active),
        })
    return rows


register(ExportSpec(
    key="mpq_clienti",
    title="Clienti / enti qualificanti (MOD.128)",
    sheet_title="Clienti MPQ",
    columns=[
        ("Nome", "nome"),
        ("Tipo", "tipo"),
        ("Codice", "codice"),
        ("Certificatore", "certificatore"),
        ("Attivo", "attivo"),
    ],
    dataset=_mpq_clienti_rows,
    filters_label=lambda request: "",
    permission=acl_gate("/anagrafica/mod128/clienti/"),
))
