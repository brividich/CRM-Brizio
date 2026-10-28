"""
Rentri — Registro Rifiuti RENTRI
Il registro del portale fa fede; la lista SharePoint è una copia (``sharepoint.py``).
Le scritture passano da ``servizi.py`` (validazione, consolidamento, annullamento).
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from django.contrib import messages

from core.acl_v2 import request_has_permission_code
from core.csv_export import safe_csv_writer
from core.audit import log_action, storico_leggibile, storico_oggetto
from core.contact_people import parse_contact_people, primary_contact, serialize_contact_people
from core.legacy_utils import get_legacy_user, is_legacy_admin
from core.module_branding import get_module_branding_context, handle_module_branding_post
from core.upload_mime import validate_filename, validate_extension_and_mime, UploadMimeValidationError

from .acl_bootstrap import PERM_RENTRI_MANAGE
from .catena import indice_per_id, risali_a_carichi, split_rif_op
from .importazione import (  # noqa: F401 - _parse_csv_rows resta importabile da qui
    ImportAnnullato,
    _parse_csv_rows,
    importa_righe,
)
from .servizi import ErroreRegistro, annulla, consolida, salva_movimento, segna_trasmesso, fotografia
from .sharepoint import _graph_configured, pull as sharepoint_pull
from .validazione import quantita_da_testo
from core.upload_limits import DOCUMENT_MAX_BYTES

logger = logging.getLogger(__name__)


_RENTRI_CSV_MAX_BYTES = 5 * 1024 * 1024


def _validate_rentri_csv(uploaded_file):
    """Valida un upload CSV import RENTRI: nome, estensione, dimensione."""
    try:
        filename = validate_filename(getattr(uploaded_file, "name", ""), label="CSV")
    except UploadMimeValidationError as exc:
        return str(exc)
    if not filename.lower().endswith(".csv"):
        return f"{filename}: formato non consentito. Attesa estensione .csv."
    size = int(getattr(uploaded_file, "size", 0) or 0)
    if size <= 0:
        return f"{filename}: file vuoto."
    if size > _RENTRI_CSV_MAX_BYTES:
        return f"{filename}: supera il limite di 5 MB."
    return None


_ALLEGATO_MAX_BYTES = DOCUMENT_MAX_BYTES
_ALLEGATO_ALLOWED_EXTENSIONS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".jpg", ".jpeg", ".png", ".webp"}
_ALLEGATO_ALLOWED_MIMES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "image/jpeg",
    "image/png",
    "image/webp",
}


def _validate_rentri_allegato(uploaded_file):
    """Valida l'allegato di un carico: nome, estensione, dimensione, MIME reale."""
    try:
        validate_extension_and_mime(
            uploaded_file,
            allowed_extensions=_ALLEGATO_ALLOWED_EXTENSIONS,
            allowed_mimes=_ALLEGATO_ALLOWED_MIMES,
            max_bytes=_ALLEGATO_MAX_BYTES,
            label="Allegato",
            allow_empty=False,
        )
    except UploadMimeValidationError as exc:
        return str(exc)
    return None

from .models import RegistroRifiuti, RentriImpostazioni
from core.permessi.impostazioni import impostazioni_o

# ── Request parsing helpers ───────────────────────────────────────────────────


def _parse_json_body(request) -> dict:
    """Estrae il payload della richiesta: JSON per fetch normali, POST per multipart (allegato)."""
    if request.content_type.startswith("multipart/form-data"):
        return request.POST.dict()
    try:
        return json.loads(request.body)
    except Exception:
        return {}


def _get_username(request) -> str:
    if request.user and request.user.is_authenticated:
        return request.user.get_full_name() or request.user.username
    return ""


def _can_manage_rentri(request) -> bool:
    """SEC-PREPROD-02 (M3): gate scrittura registro RENTRI (dato a valenza legale).

    Consentito a superuser, amministratori legacy e ai ruoli con il grant
    canonico `rentri.registro.manage` (concedibile da /admin-portale/acl-canonico/,
    additivo e fail-closed); gli altri utenti con accesso al modulo restano in
    sola lettura.
    """
    if getattr(request.user, "is_superuser", False):
        return True
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    if legacy_user and is_legacy_admin(legacy_user):
        return True
    return request_has_permission_code(request, PERM_RENTRI_MANAGE)


def _require_rentri_manager(request):
    """Ritorna una JsonResponse 403 se l'utente non puo' gestire il registro, altrimenti None."""
    if _can_manage_rentri(request):
        return None
    return JsonResponse(
        {"ok": False, "error": "Permessi insufficienti per modificare il registro RENTRI."},
        status=403,
    )


def _as_bool_field(v) -> bool:
    """Interpreta booleani sia da JSON (bool nativo) sia da multipart/form-data (stringa)."""
    if isinstance(v, bool):
        return v
    return str(v or "").strip().lower() in {"1", "true", "yes", "on", "si"}


def _populate_registro(registro: RegistroRifiuti, data: dict, tipo: str) -> list[str]:
    """Copia nel movimento i campi del modulo; ritorna gli errori di formato.

    Le regole di validità (CER, quantità, collegamenti, giacenza) stanno in
    ``validazione.py``. Il numero di registrazione non arriva mai dal modulo:
    lo assegna il portale e non cambia più.
    """
    errors = []

    data_val = str(data.get("data") or "").strip()
    if not data_val:
        errors.append("Il campo Data è obbligatorio.")
    else:
        try:
            registro.data = datetime.fromisoformat(data_val).date()
        except ValueError:
            errors.append("Formato data non valido.")

    registro.tipo = tipo
    registro.rif_op = ", ".join(split_rif_op(data.get("rif_op")))[:200]
    registro.codice = " ".join(str(data.get("codice") or "").split())[:100]

    for campo, etichetta in (("quantita", "Quantità"), ("rettifica_scarico", "Rettifica scarico")):
        try:
            setattr(registro, campo, quantita_da_testo(data.get(campo)))
        except ValueError:
            errors.append(f"{etichetta} non valida.")

    if "unita" in data:
        registro.unita = str(data.get("unita") or "").strip()[:3]
    registro.carico_scarico = tipo
    registro.rentri_si_no = _as_bool_field(data.get("rentri_si_no"))
    registro.note_rentri = str(data.get("note_rentri") or "").strip()
    registro.pericolosita = str(data.get("pericolosita") or "").strip()[:100]
    registro.arrivo_fir = str(data.get("arrivo_fir") or "").strip()[:200]
    return errors


# ── Helpers wizard (step-by-step): codici CER e catena Rif.Op ─────────────────


# Alias storico: la catena vive in ``catena.py``.
_split_rif_op = split_rif_op


def _codici_esistenti(q: str = "") -> list[str]:
    """Codici CER già usati in almeno una registrazione (per lo step di ricerca)."""
    qs = RegistroRifiuti.objects.attivi().exclude(codice="")
    if q:
        qs = qs.filter(codice__icontains=q)
    return sorted(set(qs.values_list("codice", flat=True)))[:50]


def _candidati_rif_op(tipo: str, codice: str) -> list[dict]:
    """Ritorna i record "genitori" disponibili per lo step Rif.Op del tipo richiesto.

    - O: carichi (C) del CER indicato senza alcuna evoluzione (nessun O/M/R li referenzia
      ancora nel proprio rif_op) — come richiesto per lo scarico originale.
    - M: scarichi originali (O) del CER indicato senza uno scarico effettivo già collegato.
    - R: scarichi effettivi (M) del CER indicato senza una rettifica già collegata.

    Il wizard salva nel nuovo movimento l'``id_registrazione`` del genitore
    scelto (catena ``C ← O ← M ← R``, risalita da ``catena.risali_a_carichi``).
    Un genitore è "già collegato" se un movimento valido del tipo richiesto ne
    cita l'id, oppure (forma dello storico) ne ripete lo stesso ``rif_op``.
    Gli annullati non contano. Stesse regole del controllo lato server in
    ``validazione.py``.
    """
    codice = (codice or "").strip()
    tipo = (tipo or "").strip().upper()
    if not codice or tipo not in ("O", "M", "R"):
        return []

    attivi = RegistroRifiuti.objects.attivi()
    source_tipo = {"O": "C", "M": "O", "R": "M"}[tipo]
    source_qs = attivi.filter(tipo=source_tipo, codice=codice).order_by("data", "id_registrazione")

    if source_tipo == "C":
        referenced: set[str] = set()
        for raw in attivi.filter(tipo__in=["O", "M", "R"]).values_list("rif_op", flat=True):
            referenced.update(split_rif_op(raw))
        candidates = [r for r in source_qs if r.id_registrazione not in referenced]
        return [
            {
                "id_registrazione": r.id_registrazione,
                "data": r.data.strftime("%d/%m/%Y") if r.data else "",
                "quantita": float(r.quantita) if r.quantita is not None else None,
                "rif_op": r.id_registrazione,
                "carichi": [r.id_registrazione],
            }
            for r in candidates
        ]

    citati: set[str] = set()
    used_rif_op: set[str] = set()
    for raw in attivi.filter(tipo=tipo).values_list("rif_op", flat=True):
        if str(raw or "").strip():
            citati.update(split_rif_op(raw))
            used_rif_op.add(", ".join(split_rif_op(raw)))
    candidates = [
        r for r in source_qs
        if str(r.rif_op or "").strip()
        and r.id_registrazione not in citati
        and ", ".join(split_rif_op(r.rif_op)) not in used_rif_op
    ]
    return [
        {
            "id_registrazione": r.id_registrazione,
            "data": r.data.strftime("%d/%m/%Y") if r.data else "",
            "quantita": float(r.quantita) if r.quantita is not None else None,
            "rif_op": r.rif_op,
            "carichi": split_rif_op(r.rif_op),
        }
        for r in candidates
    ]


@login_required
def api_codici_cer(request):
    q = request.GET.get("q", "").strip()
    return JsonResponse({"ok": True, "codici": _codici_esistenti(q)})


@login_required
def api_candidati_rif_op(request):
    tipo = request.GET.get("tipo", "")
    codice = request.GET.get("codice", "")
    return JsonResponse({"ok": True, "candidati": _candidati_rif_op(tipo, codice)})


# ── Views ─────────────────────────────────────────────────────────────────────


@login_required
def menu(request):
    return render(request, "rentri/pages/menu.html")


def _risposta_errore(exc: ErroreRegistro) -> JsonResponse:
    return JsonResponse({"ok": False, "error": "; ".join(exc.errori), "errori": exc.errori}, status=exc.stato_http)


def _salva_da_richiesta(request, registro: RegistroRifiuti, tipo: str, *, prima: dict | None) -> JsonResponse:
    """Parte comune di inserimento e modifica: modulo → validazione → salvataggio."""
    if prima is not None and registro.bloccato:
        return _risposta_errore(ErroreRegistro(
            "Registrazione consolidata o annullata: non si modifica. "
            "Per correggerla registra una rettifica (R) o annullala.",
            stato_http=409,
        ))
    data = _parse_json_body(request)
    errors = _populate_registro(registro, data, tipo)

    # Allegato: scheda del carico o formulario (FIR) degli scarichi.
    allegato = request.FILES.get("allegato") if tipo in ("C", "O", "M") else None
    if allegato is not None:
        err = _validate_rentri_allegato(allegato)
        if err:
            errors.append(err)

    if errors:
        return JsonResponse({"ok": False, "error": "; ".join(errors), "errori": errors}, status=400)

    if allegato is not None:
        registro.allegato = allegato

    try:
        salva_movimento(request, registro, prima=prima)
    except ErroreRegistro as exc:
        return _risposta_errore(exc)
    except Exception:  # noqa: BLE001 - il dettaglio va solo nel log
        logger.exception("RENTRI: salvataggio fallito (movimento %s)", registro.pk)
        return JsonResponse(
            {"ok": False, "error": "Errore interno durante il salvataggio: la registrazione non è stata scritta."},
            status=500,
        )

    return JsonResponse({
        "ok": True,
        "id": registro.pk,
        "id_registrazione": registro.id_registrazione,
        "avviso_sync": registro.sync_errore or "",
    })


def _handle_form(request, tipo: str, template: str):
    """Generic handler for C/O/M/R form pages."""
    if request.method == "GET":
        return render(request, template, {"tipo": tipo, "unita_choices": RegistroRifiuti.UNITA_CHOICES})

    denied = _require_rentri_manager(request)
    if denied is not None:
        return denied
    registro = RegistroRifiuti()
    registro.inserito_da = _get_username(request)
    registro.origine = "portale"
    return _salva_da_richiesta(request, registro, tipo, prima=None)


@login_required
def carico(request):
    return _handle_form(request, "C", "rentri/pages/carico.html")


@login_required
def scarico_originale(request):
    return _handle_form(request, "O", "rentri/pages/scarico_originale.html")


@login_required
def scarico_effettivo(request):
    return _handle_form(request, "M", "rentri/pages/scarico_effettivo.html")


@login_required
def rettifica_scarico(request):
    return _handle_form(request, "R", "rentri/pages/rettifica_scarico.html")


_ORM_ORDER = {"O": 0, "R": 1, "M": 2}

# Alias storico: la risalita vive in ``catena.py``.
_risali_a_carichi = risali_a_carichi


def _build_families(records: list) -> list[dict]:
    """
    Raggruppa le registrazioni in famiglie: ogni famiglia ha uno o più C (carichi)
    e i relativi O/R/M collegati tramite il campo rif_op (anche indirettamente,
    quando il riferimento passa dal genitore invece che dal carico).

    Famiglie che condividono anche un solo carico vengono fuse (union-find), così
    uno scarico a riferimento multiplo non spezza la catena degli altri.

    Ogni famiglia riporta lo stato: è **chiusa** quando il ciclo è concluso, cioè
    quando ha almeno un carico (C) e almeno uno scarico effettivo (M). Le famiglie
    chiuse vengono in fondo all'elenco.
    """
    by_id = indice_per_id(records)

    c_map: dict[str, object] = {}
    ops: list = []
    for r in records:
        if r.tipo == "C":
            # In caso di id duplicati vince il primo (i record arrivano ordinati per data).
            c_map.setdefault(str(r.id_registrazione or "").strip(), r)
        else:
            ops.append(r)

    # ── Union-find sugli id dei carichi ───────────────────────────────────────
    parent: dict[str, str] = {cid: cid for cid in c_map}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    op_carichi: list[tuple] = []
    for op in ops:
        cids = [c for c in _risali_a_carichi(op.rif_op or "", by_id) if c in c_map]
        op_carichi.append((op, cids))
        for cid in cids[1:]:
            union(cids[0], cid)

    # ── Composizione delle famiglie ───────────────────────────────────────────
    gruppi: dict[str, dict] = {}
    for cid, c_rec in c_map.items():
        root = find(cid)
        gruppi.setdefault(root, {"carichi": [], "operazioni": []})["carichi"].append(c_rec)

    orfane: dict[str, list] = {}
    for op, cids in op_carichi:
        if cids:
            gruppi[find(cids[0])]["operazioni"].append(op)
        else:
            orfane.setdefault(str(op.rif_op or "").strip(), []).append(op)

    families: list[dict] = [
        _family_payload(
            sorted(g["carichi"], key=lambda r: (r.data or date.min, r.id_registrazione or "")),
            sorted(g["operazioni"], key=lambda r: (r.data or date.min, _ORM_ORDER.get(r.tipo, 9))),
        )
        for g in gruppi.values()
    ]

    # O/M/R il cui riferimento non porta a nessun carico del queryset corrente.
    for ops_list in orfane.values():
        families.append(_family_payload(
            [],
            sorted(ops_list, key=lambda r: (r.data or date.min, _ORM_ORDER.get(r.tipo, 9))),
        ))

    # Le famiglie chiuse vanno in fondo; dentro ogni blocco si ordina per data.
    families.sort(key=lambda f: (f["chiusa"], f["data_inizio"] or date.min, f["id_ancora"]))
    return families


def _family_payload(carichi: list, operazioni: list) -> dict:
    """Costruisce la famiglia con i metadati usati dall'elenco (stato, CER, date)."""
    righe = carichi + operazioni
    tipi = {r.tipo for r in righe}
    date_note = [r.data for r in righe if r.data]
    codici = sorted({(r.codice or "").strip() for r in righe if (r.codice or "").strip()})
    ancora = carichi[0] if carichi else (operazioni[0] if operazioni else None)
    return {
        "carichi": carichi,
        "operazioni": operazioni,
        "tipi": [t for t in ("C", "O", "R", "M") if t in tipi],
        "chiusa": bool(carichi) and "M" in tipi,
        "codice": codici[0] if len(codici) == 1 else " / ".join(codici),
        "n_record": len(righe),
        "data_inizio": min(date_note) if date_note else None,
        "data_fine": max(date_note) if date_note else None,
        "id_ancora": (ancora.id_registrazione or "") if ancora is not None else "",
    }


_SORT_FIELDS = {
    "data": "data",
    "tipo": "tipo",
    "id_reg": "id_registrazione",
    "codice": "codice",
    "quantita": "quantita",
    "inserito_da": "inserito_da",
}

_GROUP_FIELDS = {
    "codice": ("codice", lambda r: r.codice or "—"),
    "tipo": ("tipo", lambda r: r.tipo),
    "anno": ("data__year", lambda r: str(r.data.year) if r.data else "—"),
    "inserito_da": ("inserito_da", lambda r: r.inserito_da or "—"),
}


@login_required
def elenco(request):
    q_annullati = request.GET.get("annullati", "") == "1"
    qs = RegistroRifiuti.objects.all() if q_annullati else RegistroRifiuti.objects.attivi()

    q_tipo   = request.GET.get("tipo",  "").strip()
    q_search = request.GET.get("q",     "").strip()
    q_anno   = request.GET.get("anno",  "").strip()
    q_sort   = request.GET.get("sort",  "").strip()
    q_dir    = request.GET.get("dir",   "desc").strip()
    q_group  = request.GET.get("group", "").strip()
    q_view   = request.GET.get("view",  "famiglie").strip()  # default: vista famiglie
    q_stato  = request.GET.get("stato", "").strip()          # aperte | chiuse (solo vista famiglie)

    if q_tipo in ("C", "O", "M", "R"):
        qs = qs.filter(tipo=q_tipo)
    if q_search:
        qs = qs.filter(codice__icontains=q_search) | qs.filter(rif_op__icontains=q_search)
    if q_anno:
        try:
            qs = qs.filter(data__year=int(q_anno))
        except ValueError:
            pass

    ctx = {
        "q_tipo": q_tipo,
        "q_search": q_search,
        "q_anno": q_anno,
        "q_sort": q_sort,
        "q_dir": q_dir,
        "q_group": q_group,
        "q_view": q_view,
        "q_stato": q_stato,
        "q_annullati": q_annullati,
        "n_annullati": RegistroRifiuti.objects.filter(annullato=True).count(),
        "can_manage": _can_manage_rentri(request),
    }

    # ── Vista famiglie (default) ───────────────────────────────────────────────
    if q_view == "famiglie" and not q_group:
        # Carica tutti i record del filtro corrente, ordinati per data
        # La famiglia viene costruita in Python tramite rif_op
        records = list(qs.order_by("data", "id_registrazione"))
        families = _build_families(records)
        ctx["n_chiuse"] = sum(1 for f in families if f["chiusa"])
        ctx["n_aperte"] = len(families) - ctx["n_chiuse"]
        if q_stato == "aperte":
            families = [f for f in families if not f["chiusa"]]
        elif q_stato == "chiuse":
            families = [f for f in families if f["chiusa"]]
        ctx["families"] = families
        ctx["total"] = sum(len(f["carichi"]) + len(f["operazioni"]) for f in families)
        return render(request, "rentri/pages/elenco.html", ctx)

    # ── Vista lista con sort/group ─────────────────────────────────────────────
    if q_sort in _SORT_FIELDS:
        order_field = _SORT_FIELDS[q_sort]
        qs = qs.order_by(order_field if q_dir == "asc" else f"-{order_field}", "id")
    else:
        qs = qs.order_by("-data", "-id")
        q_sort = "data"
        q_dir = "desc"
        ctx["q_sort"] = q_sort
        ctx["q_dir"] = q_dir

    # Raggruppamento — nessuna paginazione
    if q_group in _GROUP_FIELDS:
        order_db, key_fn = _GROUP_FIELDS[q_group]
        if q_sort in _SORT_FIELDS and q_sort != q_group:
            prefix = "" if q_dir == "asc" else "-"
            qs = qs.order_by(order_db, f"{prefix}{_SORT_FIELDS[q_sort]}", "id")
        else:
            qs = qs.order_by(order_db, "-data", "id")

        records = list(qs)
        groups = []
        current_key = None
        current_group: list = []
        for r in records:
            k = key_fn(r)
            if k != current_key:
                if current_group:
                    groups.append({"key": current_key, "rows": current_group})
                current_key = k
                current_group = [r]
            else:
                current_group.append(r)
        if current_group:
            groups.append({"key": current_key, "rows": current_group})

        ctx["groups"] = groups
        ctx["total"] = len(records)
        return render(request, "rentri/pages/elenco.html", ctx)

    # Vista flat paginata
    paginator = Paginator(qs, 50)
    ctx["page_obj"] = paginator.get_page(request.GET.get("page"))
    return render(request, "rentri/pages/elenco.html", ctx)


def _scadenzario_rows(qs, today) -> list[dict]:
    rows = []
    for r in qs:
        giorni = (today - r.data).days if r.data else None
        rows.append({
            "pk": r.pk,
            "data": r.data,
            "tipo": r.tipo,
            "tipo_label": r.get_tipo_display(),
            "id_registrazione": r.id_registrazione,
            "codice": r.codice,
            "quantita": r.quantita,
            "giorni": giorni,
            "note": r.note_rentri,
            "salva": r.salva,
        })
    return rows


def _scadenzario_buckets(today) -> list[dict]:
    """Costruisce gli adempimenti aperti del registro RENTRI.

    - FIR mancante: scarichi (O/M) senza riferimento al Formulario (arrivo_fir vuoto).
      La rettifica R corregge uno scarico che ha già il suo formulario.
    - Da comunicare: movimenti consolidati (salva=True) non ancora marcati come trasmessi.
    - Bozze: registrazioni non ancora consolidate.

    Gli annullati non sono adempimenti aperti.
    """
    attivi = RegistroRifiuti.objects.attivi()
    fir_qs = attivi.filter(tipo__in=["O", "M"], arrivo_fir="").order_by("data", "id")
    comunicare_qs = attivi.filter(rentri_si_no=False, salva=True).order_by("data", "id")
    bozze_qs = attivi.filter(salva=False).order_by("data", "id")

    return [
        {
            "key": "fir",
            "label": "FIR mancante",
            "desc": "Scarichi (O/M) senza riferimento al Formulario di Identificazione Rifiuti.",
            "tone": "danger",
            "rows": _scadenzario_rows(fir_qs, today),
        },
        {
            "key": "comunicare",
            "label": "Da comunicare a RENTRI",
            "desc": "Movimenti consolidati ma non ancora marcati come trasmessi a RENTRI.",
            "tone": "warning",
            "rows": _scadenzario_rows(comunicare_qs, today),
        },
        {
            "key": "bozze",
            "label": "Bozze da consolidare",
            "desc": "Registrazioni non ancora consolidate: finché sono bozze si possono modificare.",
            "tone": "info",
            "rows": _scadenzario_rows(bozze_qs, today),
        },
    ]


def _scadenzario_csv(today, sections):
    from django.http import HttpResponse

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="rentri_scadenzario_{today.strftime("%Y%m%d")}.csv"'
    )
    response.write("﻿")  # BOM per apertura corretta in Excel
    writer = safe_csv_writer(response, delimiter=";")
    writer.writerow([
        "Adempimento", "Data", "ID Registrazione", "Tipo",
        "Codice EER", "Quantita", "Giorni di giacenza", "Note",
    ])
    for section in sections:
        for r in section["rows"]:
            writer.writerow([
                section["label"],
                r["data"].strftime("%d/%m/%Y") if r["data"] else "",
                r["id_registrazione"],
                r["tipo_label"],
                r["codice"],
                r["quantita"] if r["quantita"] is not None else "",
                r["giorni"] if r["giorni"] is not None else "",
                r["note"],
            ])
    return response


@login_required
def scadenzario(request):
    """Scadenzario adempimenti RENTRI: FIR mancanti, da comunicare, bozze.

    Sola lettura (login). Export CSV con ?export=csv. Il PDF del registro
    completo resta su `rentri_export_pdf`.
    """
    today = timezone.localdate()
    sections = _scadenzario_buckets(today)

    if request.GET.get("export") == "csv":
        return _scadenzario_csv(today, sections)

    total = sum(len(s["rows"]) for s in sections)
    return render(request, "rentri/pages/scadenzario.html", {
        "sections": sections,
        "total": total,
        "today": today,
        "can_manage": _can_manage_rentri(request),
    })


def _giacenze_csv(rows, today, soglie):
    from django.http import HttpResponse

    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = (
        f'attachment; filename="rentri_giacenze_{today.strftime("%Y%m%d")}.csv"'
    )
    response.write("﻿")  # BOM per apertura corretta in Excel
    writer = safe_csv_writer(response, delimiter=";")
    writer.writerow([
        "Codice EER", "Pericoloso", "Carichi", "Scarichi",
        "Entrate", "Uscite", "Giacenza", "Unità", "Primo carico",
        "Carico più vecchio aperto", "Giorni in deposito", "Stato",
    ])
    stato_label = {
        "rosso": "Oltre soglia",
        "giallo": "In avvicinamento",
        "verde": "Regolare",
        "chiuso": "Azzerata",
    }
    for g, tono in rows:
        writer.writerow([
            g.codice,
            "Sì" if g.pericoloso else "",
            g.n_carichi,
            g.n_scarichi,
            g.entrate,
            g.uscite,
            g.giacenza,
            g.unita,
            g.primo_carico.strftime("%d/%m/%Y") if g.primo_carico else "",
            g.carico_aperto.strftime("%d/%m/%Y") if g.carico_aperto else "",
            g.giorni_giacenza if g.giorni_giacenza is not None else "",
            stato_label.get(tono, tono),
        ])
    return response


@login_required
def giacenze(request):
    """Giacenze rifiuti per CER + semaforo deposito temporaneo (sola lettura).

    Aggrega carichi/scarichi per codice EER e segnala le giacenze aperte che si
    avvicinano o superano il limite di deposito temporaneo. Export CSV con
    ?export=csv. Le soglie sono configurabili (vedi `rentri.giacenze`).
    """
    from .giacenze import criterio_quantitativo, giacenze_per_cer, soglie_deposito

    today = timezone.localdate()
    soglie = soglie_deposito()

    q_search = request.GET.get("q", "").strip()
    q_allerta = request.GET.get("allerta", "") == "1"
    q_pericolosi = request.GET.get("pericolosi", "") == "1"
    q_aperte = request.GET.get("aperte", "1") != "0"  # default: solo giacenze aperte

    _TONO_ORDER = {"rosso": 0, "giallo": 1, "verde": 2, "chiuso": 3}
    rows = []
    tutte = giacenze_per_cer()
    criterio = criterio_quantitativo(tutte, soglie)
    for g in tutte:
        tono = g.tono(soglie)
        if q_aperte and not g.aperta:
            continue
        if q_allerta and tono not in ("rosso", "giallo"):
            continue
        if q_pericolosi and not g.pericoloso:
            continue
        if q_search and q_search.lower() not in g.codice.lower():
            continue
        rows.append((g, tono))

    rows.sort(key=lambda rt: (_TONO_ORDER.get(rt[1], 9), -(rt[0].giorni_giacenza or 0)))

    if request.GET.get("export") == "csv":
        return _giacenze_csv(rows, today, soglie)

    n_allerta = sum(1 for _, t in rows if t in ("rosso", "giallo"))
    n_oltre = sum(1 for _, t in rows if t == "rosso")
    return render(request, "rentri/pages/giacenze.html", {
        "rows": rows,
        "today": today,
        "soglie": soglie,
        "totale": len(rows),
        "n_allerta": n_allerta,
        "n_oltre": n_oltre,
        "criterio": criterio,
        "q_search": q_search,
        "q_allerta": q_allerta,
        "q_pericolosi": q_pericolosi,
        "q_aperte": q_aperte,
        "can_manage": _can_manage_rentri(request),
    })


_TEMPLATE_TIPO = {
    "C": "rentri/pages/carico.html",
    "O": "rentri/pages/scarico_originale.html",
    "M": "rentri/pages/scarico_effettivo.html",
    "R": "rentri/pages/rettifica_scarico.html",
}


@login_required
def modifica(request, pk: int):
    registro = get_object_or_404(RegistroRifiuti, pk=pk)

    if request.method == "GET":
        if registro.bloccato:
            # Consolidata o annullata: niente modulo, solo la scheda in lettura.
            return redirect("rentri_dettaglio", pk=registro.pk)
        template = _TEMPLATE_TIPO.get(registro.tipo, "rentri/pages/carico.html")
        return render(request, template, {
            "registro": registro, "edit_mode": True, "unita_choices": RegistroRifiuti.UNITA_CHOICES,
        })

    denied = _require_rentri_manager(request)
    if denied is not None:
        return denied
    return _salva_da_richiesta(request, registro, registro.tipo, prima=fotografia(registro))


@login_required
def dettaglio(request, pk: int):
    """Scheda di un movimento: dati, collegamenti, storico, azioni."""
    from .servizi import figli_attivi

    registro = get_object_or_404(RegistroRifiuti, pk=pk)
    genitori = list(
        RegistroRifiuti.objects.filter(id_registrazione__in=split_rif_op(registro.rif_op)).order_by("data", "id")
    )
    voci = storico_oggetto(registro)
    return render(request, "rentri/pages/dettaglio.html", {
        "registro": registro,
        "genitori": genitori,
        "figli": figli_attivi(registro),
        "storico": storico_leggibile(voci),
        "can_manage": _can_manage_rentri(request),
    })


def _azione_registro(request, pk: int, fn):
    """Esegue un'azione di pagina (consolida/annulla/trasmesso) e torna alla scheda."""
    denied = _require_rentri_manager(request)
    if denied is not None:
        return denied
    registro = get_object_or_404(RegistroRifiuti, pk=pk)
    try:
        esito = fn(registro)
    except ErroreRegistro as exc:
        messages.error(request, " ".join(exc.errori))
    else:
        messages.success(request, esito)
        if registro.sync_errore:
            messages.warning(request, f"Registrazione salvata, ma la copia su SharePoint non è allineata: {registro.sync_errore}")
    prossima = request.POST.get("next", "")
    if prossima.startswith("/rentri/") and "//" not in prossima:
        return redirect(prossima)
    return redirect("rentri_dettaglio", pk=pk)


@login_required
@require_POST
def consolida_view(request, pk: int):
    def _fai(registro):
        consolida(request, registro, _get_username(request))
        return f"{registro.id_registrazione} consolidata: da ora si corregge solo con una rettifica o annullandola."
    return _azione_registro(request, pk, _fai)


@login_required
@require_POST
def trasmesso_view(request, pk: int):
    trasmesso = request.POST.get("trasmesso", "1") == "1"

    def _fai(registro):
        segna_trasmesso(request, registro, trasmesso)
        stato = "trasmessa a RENTRI" if trasmesso else "da trasmettere a RENTRI"
        return f"{registro.id_registrazione} segnata come {stato}."
    return _azione_registro(request, pk, _fai)


@login_required
@require_POST
def annulla_view(request, pk: int):
    def _fai(registro):
        annulla(request, registro, request.POST.get("motivo", ""), _get_username(request))
        return f"{registro.id_registrazione} annullata: resta a registro, barrata, e non conta più."
    return _azione_registro(request, pk, _fai)


@login_required
@require_POST
def elimina(request, pk: int):
    """Compatibilità: un movimento non si elimina più, si annulla con un motivo (JSON)."""
    denied = _require_rentri_manager(request)
    if denied is not None:
        return denied
    registro = get_object_or_404(RegistroRifiuti, pk=pk)
    data = _parse_json_body(request) if request.body else {}
    motivo = request.POST.get("motivo") or data.get("motivo") or ""
    try:
        annulla(request, registro, motivo, _get_username(request))
    except ErroreRegistro as exc:
        return _risposta_errore(exc)
    return JsonResponse({"ok": True, "annullato": True})


@login_required
def verifica(request):
    """Verifica di coerenza del registro (sola lettura), export CSV con ?export=csv."""
    from .verifica import verifica_registro, verifica_csv

    sezioni = verifica_registro()
    if request.GET.get("export") == "csv":
        return verifica_csv(sezioni)
    return render(request, "rentri/pages/verifica.html", {
        "sezioni": sezioni,
        "totale": sum(len(s["righe"]) for s in sezioni),
        "today": timezone.localdate(),
    })


@login_required
@require_POST
def import_preview(request):
    """POST: riceve un file CSV e restituisce un'anteprima JSON senza scrivere sul DB."""
    csv_file = request.FILES.get("csv_file")
    if not csv_file:
        return JsonResponse({"ok": False, "error": "Nessun file selezionato"}, status=400)
    err = _validate_rentri_csv(csv_file)
    if err:
        return JsonResponse({"ok": False, "error": err}, status=400)
    try:
        content = csv_file.read().decode("utf-8-sig")
    except Exception:
        return JsonResponse({"ok": False, "error": "Errore lettura file CSV (atteso UTF-8)."}, status=400)

    rows, errors = _parse_csv_rows(content)
    nuovi = sum(1 for r in rows if not r["esiste"])

    return JsonResponse({
        "ok": True,
        "rows": rows,
        "errors": errors,
        "totale": len(rows),
        "nuovi": nuovi,
        "skip": len(rows) - nuovi,
    })


@login_required
@require_POST
def import_confirm(request):
    """POST: importa effettivamente il CSV nel DB."""
    denied = _require_rentri_manager(request)
    if denied is not None:
        return denied
    csv_file = request.FILES.get("csv_file")
    if not csv_file:
        return JsonResponse({"ok": False, "error": "Nessun file"}, status=400)
    err = _validate_rentri_csv(csv_file)
    if err:
        return JsonResponse({"ok": False, "error": err}, status=400)
    try:
        content = csv_file.read().decode("utf-8-sig")
    except Exception:
        return JsonResponse({"ok": False, "error": "Errore lettura file CSV (atteso UTF-8)."}, status=400)

    rows, parse_errors = _parse_csv_rows(content)
    if parse_errors:
        return JsonResponse({
            "ok": False,
            "error": "Il file ha righe non valide: correggile e riprova. Non è stato importato nulla.",
            "created": 0, "skipped": 0, "errors": parse_errors,
        }, status=400)
    try:
        esito = importa_righe(rows, utente=_get_username(request))
    except ImportAnnullato as exc:
        return JsonResponse({
            "ok": False,
            "error": "Import annullato: alcune righe non si sono potute scrivere. Non è stato importato nulla.",
            "created": 0, "skipped": 0, "errors": exc.errori,
        }, status=400)
    log_action(request, "rentri_import_csv", "rentri", {
        "file": getattr(csv_file, "name", "")[:120],
        "creati": esito["created"], "saltati": esito["skipped"], "avvisi": len(esito["avvisi"]),
    })
    return JsonResponse({
        "ok": True,
        "created": esito["created"],
        "skipped": esito["skipped"],
        "errors": esito["avvisi"],
    })


@login_required
def export_pdf(request):
    """GET: genera ed invia un PDF con le registrazioni RENTRI."""
    from io import BytesIO

    from django.http import HttpResponse
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm, mm
    from reportlab.platypus import Paragraph, Table, TableStyle

    from core.pdf import (
        FOOTER_HEIGHT, HEADER_HEIGHT, PdfTheme,
        header_footer_callback, make_document,
    )

    # ── filtri ────────────────────────────────────────────────────────────────
    q_tipo = request.GET.get("tipo", "").strip()
    q_search = request.GET.get("q", "").strip()
    q_anno = request.GET.get("anno", "").strip()

    qs = RegistroRifiuti.objects.all()
    if q_tipo in ("C", "O", "M", "R"):
        qs = qs.filter(tipo=q_tipo)
    if q_search:
        qs = qs.filter(codice__icontains=q_search) | qs.filter(rif_op__icontains=q_search)
    if q_anno:
        try:
            qs = qs.filter(data__year=int(q_anno))
        except ValueError:
            pass

    records = list(qs.order_by("data", "id"))

    # ── tema condiviso + palette dominio ──────────────────────────────────────
    theme = PdfTheme.from_branding()
    COL_GRID = theme.c_border()

    # Colori semantici per tipo di registrazione: NON sono branding, ma
    # codifica di dominio del registro → restano locali.
    TIPO_BG = {
        "C": "#dbeafe",
        "O": "#fed7aa",
        "M": "#d9f99d",
        "R": "#fef08a",
    }
    TIPO_FG = {
        "C": "#1e40af",
        "O": "#9a3412",
        "M": "#166534",
        "R": "#854d0e",
    }
    TIPO_LABEL = {
        "C": "Carico",
        "O": "Scarico orig.",
        "M": "Scarico eff.",
        "R": "Rettifica",
    }

    MARGIN = 1.5 * cm
    # Spazio extra sotto l'header standard per ospitare la legenda dei tipi.
    LEGEND_BAND = 1.4 * cm

    # ── filtri stringa per footer ─────────────────────────────────────────────
    filter_parts = []
    if q_tipo:
        filter_parts.append(f"Tipo: {TIPO_LABEL.get(q_tipo, q_tipo)}")
    if q_anno:
        filter_parts.append(f"Anno: {q_anno}")
    if q_search:
        filter_parts.append(f"Ricerca: {q_search}")
    filters_str = " | ".join(filter_parts) if filter_parts else "Tutte le registrazioni"
    n_records = len(records)

    # ── callback: header/footer standard + legenda/filtri di dominio ──────────
    _base_draw = header_footer_callback(
        theme,
        title="RENTRI",
        subtitle=f"Registro Elettronico Nazionale Tracciabilità Rifiuti  ·  {n_records} registrazioni",
    )

    def _draw_page(canv, doc):
        _base_draw(canv, doc)
        canv.saveState()
        page_w, page_h = doc.pagesize
        right = page_w - MARGIN

        # legenda colori tipo, appena sotto l'header standard
        legend_items = [
            ("C", "Carico"),
            ("O", "Scarico originario"),
            ("M", "Scarico effettivo"),
            ("R", "Rettifica"),
        ]
        lx = MARGIN
        ly = page_h - HEADER_HEIGHT - 0.2 * cm
        dot_r = 3
        canv.setFont("Helvetica", 6.5)
        for tipo, label in legend_items:
            canv.setFillColor(colors.HexColor(TIPO_BG[tipo]))
            canv.circle(lx + dot_r, ly + dot_r, dot_r, fill=1, stroke=0)
            canv.setFillColor(colors.HexColor(TIPO_FG[tipo]))
            canv.drawString(lx + dot_r * 2 + 3, ly + 1, f"{tipo} – {label}")
            lx += 4.8 * cm

        canv.setStrokeColor(COL_GRID)
        canv.setLineWidth(0.3)
        canv.line(MARGIN, ly - 0.45 * cm, right, ly - 0.45 * cm)

        # filtri applicati nel footer (sopra la riga standard)
        canv.setFillColor(theme.c_muted())
        canv.setFont("Helvetica", 6.5)
        canv.drawString(MARGIN, FOOTER_HEIGHT - 1.5 * mm, filters_str)

        canv.restoreState()

    # ── documento ─────────────────────────────────────────────────────────────
    buffer = BytesIO()
    doc = make_document(
        buffer,
        title="Registro RENTRI",
        landscape=True,
        left_margin=MARGIN,
        right_margin=MARGIN,
        top_margin=HEADER_HEIGHT + LEGEND_BAND,
    )

    # ── stili ─────────────────────────────────────────────────────────────────
    # Font ridotti rispetto allo stylesheet condiviso: il registro è una tabella
    # densa in landscape e necessita di celle compatte.
    cell_s = ParagraphStyle("cell", fontName="Helvetica", fontSize=7, leading=9, wordWrap="CJK")
    cell_r = ParagraphStyle("cell_r", parent=cell_s, alignment=2)  # right-align numeri
    hdr_s  = ParagraphStyle(
        "hdr", fontName="Helvetica-Bold", fontSize=8, leading=10,
        textColor=colors.white, alignment=1,
    )

    def _tipo_cell(tipo):
        label = f"<b>{tipo}</b> {TIPO_LABEL.get(tipo, '')}"
        fg = TIPO_FG.get(tipo, "#333333")
        s = ParagraphStyle(
            f"tipo_{tipo}", fontName="Helvetica", fontSize=7, leading=9,
            textColor=colors.HexColor(fg), alignment=1,
        )
        return Paragraph(label, s)

    # ── dati tabella ──────────────────────────────────────────────────────────
    COL_W = [2.0*cm, 3.0*cm, 3.0*cm, 7.4*cm, 1.9*cm, 1.9*cm, 5.2*cm, 2.3*cm]

    header_row = [
        Paragraph("Data", hdr_s),
        Paragraph("ID Reg.", hdr_s),
        Paragraph("Tipo", hdr_s),
        Paragraph("Codice EER", hdr_s),
        Paragraph("Qtà", hdr_s),
        Paragraph("Rettifica", hdr_s),
        Paragraph("Note / FIR", hdr_s),
        Paragraph("Inserito da", hdr_s),
    ]
    table_data = [header_row]
    for r in records:
        note_fir = r.note_rentri or r.arrivo_fir or ""
        if r.annullato:
            note_fir = f"ANNULLATO: {r.motivo_annullamento}"
        table_data.append([
            Paragraph(r.data.strftime("%d-%m-%Y") if r.data else "", cell_s),
            Paragraph(r.id_registrazione or "", cell_s),
            _tipo_cell(r.tipo),
            Paragraph((r.codice or "")[:80], cell_s),
            Paragraph(str(r.quantita) if r.quantita is not None else "", cell_r),
            Paragraph(str(r.rettifica_scarico) if r.rettifica_scarico is not None else "", cell_r),
            Paragraph(note_fir[:70], cell_s),
            Paragraph((r.inserito_da or "")[:22], cell_s),
        ])

    table = Table(table_data, colWidths=COL_W, repeatRows=1)
    ts = TableStyle([
        ("BACKGROUND",    (0, 0), (-1, 0),  theme.c_primary()),
        ("LINEBELOW",     (0, 0), (-1, 0),  1.5,  theme.c_primary_mid()),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, theme.c_row_alt()]),
        ("GRID",          (0, 0), (-1, -1), 0.25, COL_GRID),
        ("LINEBEFORE",    (0, 0), (-1, -1), 0,    colors.white),   # annulla bordo sinistro
        ("LINEAFTER",     (-1, 0),(-1, -1), 0,    colors.white),   # annulla bordo destro
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING",   (0, 0), (-1, -1), 5),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 5),
    ])
    for i, r in enumerate(records, start=1):
        bg = TIPO_BG.get(r.tipo)
        if bg:
            ts.add("BACKGROUND", (2, i), (2, i), colors.HexColor(bg))
        if r.annullato:
            ts.add("TEXTCOLOR", (0, i), (-1, i), colors.HexColor("#94a3b8"))
    table.setStyle(ts)

    doc.build([table], onFirstPage=_draw_page, onLaterPages=_draw_page)

    buffer.seek(0)
    anno_str = q_anno or timezone.localdate().strftime("%Y")
    filename = f"rentri_{anno_str}_{timezone.localdate().strftime('%Y%m%d')}.pdf"
    response = HttpResponse(buffer.read(), content_type="application/pdf")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@login_required
@require_POST
def api_sync_pull(request):
    """Pull all items from SharePoint and upsert locally."""
    denied = _require_rentri_manager(request)
    if denied is not None:
        return denied
    if not _graph_configured():
        return JsonResponse({"ok": False, "error": "Configurazione Graph non disponibile."}, status=503)

    try:
        esito = sharepoint_pull(_get_username(request))
    except Exception:  # noqa: BLE001 - rete/token/risposta: dettaglio nel log
        logger.exception("RENTRI: lettura SharePoint fallita")
        return JsonResponse({"ok": False, "error": "SharePoint non raggiungibile o risposta non valida."}, status=502)
    log_action(request, "rentri_sync_pull", "rentri", esito)
    return JsonResponse({"ok": True, **esito})


@login_required
def impostazioni(request):
    """Impostazioni modulo Rentri — superuser, admin legacy o grant canonico."""
    if not impostazioni_o(request, "rentri", _can_manage_rentri):
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden()

    cfg = RentriImpostazioni.get_singleton()

    if request.method == "POST":
        branding_response = handle_module_branding_post(
            request,
            module_key="rentri",
            redirect_to="rentri_impostazioni",
            audit_module="rentri",
            fallback_label="RENTRI",
        )
        if branding_response is not None:
            return branding_response
        responsabili = parse_contact_people(request.POST.get("responsabili_raw", ""))
        primary = primary_contact(responsabili)
        cfg.codice_iscrizione_rentri = request.POST.get("codice_iscrizione_rentri", "").strip()
        cfg.ragione_sociale = request.POST.get("ragione_sociale", "").strip()
        cfg.responsabili = responsabili
        cfg.responsabile_nome = primary["nome"]
        cfg.responsabile_email = primary["email"]
        cfg.note_generali = request.POST.get("note_generali", "").strip()
        cfg.save()
        log_action(request, "modifica", "rentri", "Aggiornate impostazioni Rentri")
        messages.success(request, "Impostazioni salvate.")
        return redirect("rentri_impostazioni")

    return render(
        request,
        "rentri/pages/impostazioni.html",
        {
            "cfg": cfg,
            "responsabili_raw": serialize_contact_people(
                cfg.responsabili,
                fallback_name=cfg.responsabile_nome,
                fallback_email=cfg.responsabile_email,
            ),
            **get_module_branding_context("rentri", fallback_label="RENTRI"),
        },
    )
