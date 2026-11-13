"""
Rentri — Registro Rifiuti RENTRI
Il registro del portale fa fede; la lista SharePoint è una copia (``sharepoint.py``).
Le scritture passano da ``servizi.py`` (validazione, consolidamento, annullamento).
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
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
from .catena import GENITORI_AMMESSI, indice_per_id, risali_a_carichi, split_rif_op
from .importazione import (  # noqa: F401 - _parse_csv_rows resta importabile da qui
    ImportAnnullato,
    _parse_csv_rows,
    importa_righe,
)
from .servizi import (
    ErroreRegistro,
    annulla,
    anteprima_filo,
    consolida,
    consolida_filo,
    elimina_definitivamente,
    fotografia,
    salva_movimento,
    segna_trasmesso,
)
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

from .models import CatalogoEER, RegistroRifiuti, RentriImpostazioni
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


_FILTRI_SESSIONE = "rentri_filtri"
_PARAMETRI_NON_RICORDATI = ("export", "reset")


def _ricorda_filtri(request, pagina: str):
    """Ogni tabella ricorda i propri filtri nella sessione dell'utente.

    Con parametri nell'indirizzo li salva; senza, riapplica gli ultimi salvati
    (redirect). ``?reset=1`` li dimentica. Gli export non toccano il salvato.
    Ritorna un redirect da restituire, oppure ``None``.
    """
    salvati = dict(request.session.get(_FILTRI_SESSIONE) or {})
    if request.GET.get("reset") == "1":
        if salvati.pop(pagina, None) is not None:
            request.session[_FILTRI_SESSIONE] = salvati
        return redirect(request.path)
    if request.GET.get("export"):
        return None
    parametri = request.GET.copy()
    for k in _PARAMETRI_NON_RICORDATI:
        parametri.pop(k, None)
    testo = parametri.urlencode()
    if testo:
        if salvati.get(pagina) != testo:
            salvati[pagina] = testo
            request.session[_FILTRI_SESSIONE] = salvati
        return None
    if salvati.get(pagina):
        return redirect(f"{request.path}?{salvati[pagina]}")
    return None


def _prossima_rentri(request) -> str:
    """Pagina a cui tornare dopo un'azione: solo percorsi interni del modulo."""
    prossima = request.POST.get("next") or request.GET.get("next") or ""
    return prossima if prossima.startswith("/rentri/") and "//" not in prossima else ""


def _annota_righe(records: list, attivi: list | None = None) -> None:
    """Per le azioni di riga: movimenti collegati (``figli_txt``) e se si può eliminare davvero."""
    if attivi is None:
        attivi = list(RegistroRifiuti.objects.attivi().only("pk", "tipo", "id_registrazione", "rif_op"))
    figli: dict[str, list] = {}
    for r in attivi:
        for rid in split_rif_op(r.rif_op):
            figli.setdefault(rid, []).append(r)
    for r in records:
        mie = [f for f in figli.get((r.id_registrazione or "").strip(), []) if f.pk != r.pk]
        testo = ", ".join(f"{f.tipo} {f.id_registrazione}" for f in mie[:6])
        r.figli_txt = testo + ("…" if len(mie) > 6 else "")
        r.eliminabile = not (r.annullato or r.salva or r.rentri_si_no or mie)


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
    """Codici CER già usati (per lo step di ricerca): uno per CER, con il testo più usato.

    Lo storico scrive «12.01.01 Sfridi Ferro Kg», il portale «12 01 01»: per le sei
    cifre sono lo stesso codice e qui compaiono una volta sola.
    """
    from collections import Counter

    from .fili import chiave

    testi: dict[str, Counter] = {}
    for c in RegistroRifiuti.objects.attivi().exclude(codice="").values_list("codice", flat=True):
        testi.setdefault(chiave(c), Counter())[" ".join(c.split())] += 1
    codici = {t.most_common(1)[0][0] for t in testi.values()}
    if q:
        # «1501» trova «15 01 06» e «15.01.06»: il confronto ignora spazi, punti e maiuscole.
        ago = re.sub(r"[\s.\-]", "", q).lower()
        codici = {c for c in codici if ago in re.sub(r"[\s.\-]", "", c).lower()}
    return sorted(codici)[:50]


def _candidati_rif_op(tipo: str, codice: str, *, tutti: bool = False, escludi_pk=None) -> list[dict]:
    """Movimenti collegabili per lo step «Collegato a»: un filo per carico (vedi ``fili.py``).

    Il codice si confronta per le sei cifre del CER, così «12 01 01» trova anche i
    carichi scritti «12.01.01 Sfridi Ferro Kg». Stesse regole della validazione.
    """
    from .fili import fili_del_codice
    from .giacenze import soglie_deposito

    voci = fili_del_codice(codice, tipo, tutti=tutti, escludi_pk=escludi_pk)
    oggi = timezone.localdate()
    soglie = soglie_deposito()
    for v in voci:
        v["giorni"] = None
        v["tono"] = ""
        if v.get("tipo") == "C" and not v.get("gia_collegato") and v.get("carico_data"):
            giorni = (oggi - datetime.strptime(v["carico_data"], "%d/%m/%Y").date()).days
            v["giorni"] = giorni
            v["tono"] = "rosso" if giorni >= soglie["giorni_max"] else ("giallo" if giorni >= soglie["giorni_warn"] else "")
            v["giorni_max"] = soglie["giorni_max"]
    # In cima i carichi vicini o oltre il limite del deposito temporaneo, dal più vecchio.
    urgenti = sorted((v for v in voci if v["tono"]), key=lambda v: -v["giorni"])
    return urgenti + [v for v in voci if not v["tono"]]


@login_required
def api_codici_cer(request):
    from .catalogo import cerca

    q = request.GET.get("q", "").strip()
    usati = _codici_esistenti(q)
    # Dal catalogo EER solo le voci non già tra i codici usati (per nome o per cifre).
    gia = {" ".join(c.split()) for c in usati}
    catalogo = [c for c in cerca(q) if c["codice"] not in gia]
    return JsonResponse({"ok": True, "codici": usati, "catalogo": catalogo})


def _unita_usate(k: str) -> list[list]:
    """Unità con cui è registrato il codice, dalla più usata: [[unità, movimenti], ...]."""
    from collections import Counter

    from .giacenze import chiave_codice

    conta = Counter(
        u for c, u in RegistroRifiuti.objects.attivi().exclude(unita="").values_list("codice", "unita")
        if chiave_codice(c) == k
    )
    return [[u, n] for u, n in conta.most_common()]


@login_required
def api_cer_info(request):
    """Cosa si sa di un codice: confronto col catalogo EER, giacenza, valori dell'ultimo movimento."""
    from .catalogo import confronta
    from .giacenze import chiave_codice, giacenza_di

    codice = " ".join(request.GET.get("codice", "").split())
    if not codice:
        return JsonResponse({"ok": True, "catalogo": {"stato": "vuoto"}})
    chiave = chiave_codice(codice)
    ultimo = next(
        (r for r in RegistroRifiuti.objects.attivi().exclude(codice="").order_by("-data", "-id")
         .only("codice", "unita", "pericolosita", "tipo")[:500]
         if chiave_codice(r.codice) == chiave),
        None,
    )
    unita = ""
    pericolosita = ""
    if ultimo is not None:
        unita = ultimo.unita
        carico = next(
            (r for r in RegistroRifiuti.objects.attivi().filter(tipo="C").exclude(pericolosita="")
             .order_by("-data", "-id").only("codice", "pericolosita")[:500]
             if chiave_codice(r.codice) == chiave),
            None,
        )
        pericolosita = carico.pericolosita if carico else ""
    return JsonResponse({
        "ok": True,
        "catalogo": confronta(codice),
        "usato": ultimo is not None,
        "unita": unita,
        "unita_usate": _unita_usate(chiave),
        "pericolosita": pericolosita,
        "giacenza": format(giacenza_di(codice), "f") if ultimo is not None else None,
    })


@login_required
def api_candidati_rif_op(request):
    tipo = request.GET.get("tipo", "")
    codice = request.GET.get("codice", "")
    tutti = request.GET.get("tutti", "") == "1"
    escludi = request.GET.get("escludi", "")
    return JsonResponse({
        "ok": True,
        "candidati": _candidati_rif_op(tipo, codice, tutti=tutti, escludi_pk=int(escludi) if escludi.isdigit() else None),
    })


@login_required
@require_POST
def api_leggi_fir(request):
    """Legge il formulario caricato e propone i campi dello scarico. Non salva il file."""
    from core.lettura_documenti import DocumentoNonLeggibile

    from .lettura_fir import leggi_fir

    denied = _require_rentri_manager(request)
    if denied is not None:
        return denied
    f = request.FILES.get("file")
    if not f:
        return JsonResponse({"ok": False, "error": "Scegli il file del formulario."}, status=400)
    errore = _validate_rentri_allegato(f)
    if errore:
        return JsonResponse({"ok": False, "error": errore}, status=400)
    f.seek(0)
    tipo = request.POST.get("tipo", "O") if request.POST.get("tipo") in ("O", "M") else "O"
    try:
        esito = leggi_fir(f.read(), tipo=tipo)
    except DocumentoNonLeggibile as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    return JsonResponse({"ok": True, **esito})


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


# Testi del form unico dei movimenti (rentri/pages/movimento_form.html), per tipo.
_FORM_TIPO = {
    "C": {
        "lettera": "C", "titolo": "Carico", "titolo_breve": "Carico",
        "sottotitolo": "Il rifiuto viene prodotto e messo nel deposito temporaneo.",
        "rif_tipo": "", "rif_help": "",
    },
    "O": {
        "lettera": "O", "titolo": "Scarico originale", "titolo_breve": "Scarico originale",
        "sottotitolo": "Il rifiuto parte con il formulario: quantità stimata.",
        "rif_tipo": "C",
        "rif_help": "I carichi di questo codice CER con un residuo in deposito. Il collegamento è facoltativo.",
    },
    "M": {
        "lettera": "M", "titolo": "Scarico effettivo", "titolo_breve": "Scarico effettivo",
        "sottotitolo": "La quantità vera pesata dal destinatario, con il FIR di ritorno.",
        "rif_tipo": "O",
        "rif_help": "I carichi usciti di questo codice CER senza scarico effettivo: si collega lo scarico originale (O). Facoltativo.",
    },
    "R": {
        "lettera": "R", "titolo": "Rettifica scarico", "titolo_breve": "Rettifica",
        "sottotitolo": "Correzione di uno scarico effettivo già registrato, positiva o negativa.",
        "rif_tipo": "M",
        "rif_help": "I carichi di questo codice CER con uno scarico effettivo (M) da rettificare. Facoltativo.",
    },
}




def _num(v) -> str:
    return "" if v is None else format(v, "f")


def _valori_iniziali(request, tipo: str, registro=None) -> tuple[dict, str]:
    """Valori del modulo e, per i nuovi, da dove arrivano (testo per l'utente).

    - modifica: i dati del movimento;
    - ``?da=<pk>``: il movimento da cui nasce (Scarica / Registra effettivo /
      Rettifica dalla scheda): codice, unità, collegamento e quantità;
    - ``?duplica=<pk>``: stesso tipo, stesso codice, unità e pericolosità;
    - ``?codice=``: solo il codice (dalle Giacenze).
    """
    oggi = timezone.localdate().isoformat()
    if registro is not None:
        return {
            "data": registro.data.isoformat() if registro.data else "",
            "codice": registro.codice, "quantita": _num(registro.quantita), "unita": registro.unita,
            "rettifica": _num(registro.rettifica_scarico), "pericolosita": registro.pericolosita,
            "arrivo_fir": registro.arrivo_fir, "note_rentri": registro.note_rentri,
            "rentri_si_no": registro.rentri_si_no, "rif_op": split_rif_op(registro.rif_op),
            "allegato": bool(registro.allegato),
        }, ""
    v = {"data": oggi, "codice": "", "quantita": "", "unita": "", "rettifica": "", "pericolosita": "",
         "arrivo_fir": "", "note_rentri": "", "rentri_si_no": False, "rif_op": [], "allegato": False}
    origine = ""
    attivi = RegistroRifiuti.objects.attivi()
    da, dup = request.GET.get("da", ""), request.GET.get("duplica", "")
    if da.isdigit():
        g = attivi.filter(pk=int(da), tipo__in=GENITORI_AMMESSI.get(tipo, ())).first()
        if g is not None:
            v.update(codice=g.codice, unita=g.unita, rif_op=[g.id_registrazione])
            if tipo in ("O", "M") and g.quantita is not None:
                v["quantita"] = _num(g.quantita)
            origine = f"Compilato da {g.get_tipo_display()} {g.id_registrazione}: controlla quantità e data."
    elif dup.isdigit():
        g = attivi.filter(pk=int(dup), tipo=tipo).first()
        if g is not None:
            v.update(codice=g.codice, unita=g.unita, pericolosita=g.pericolosita)
            origine = f"Copia di {g.id_registrazione}: stesso codice e unità, data di oggi."
    elif request.GET.get("codice", "").strip():
        v["codice"] = " ".join(request.GET["codice"].split())[:100]
    return v, origine


def _render_form(request, tipo: str, registro=None):
    valori, origine = _valori_iniziali(request, tipo, registro)
    return render(request, "rentri/pages/movimento_form.html", {
        "tipo": tipo,
        "cfg": _FORM_TIPO[tipo],
        "registro": registro,
        "edit_mode": registro is not None,
        "v": valori,
        "origine": origine,
        "unita_choices": RegistroRifiuti.UNITA_CHOICES,
        "fir_leggibile": tipo in ("O", "M") and _can_manage_rentri(request),
    })


def _handle_form(request, tipo: str):
    """Pagina e salvataggio di un nuovo movimento C/O/M/R."""
    if request.method == "GET":
        return _render_form(request, tipo)

    denied = _require_rentri_manager(request)
    if denied is not None:
        return denied
    registro = RegistroRifiuti()
    registro.inserito_da = _get_username(request)
    legacy = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    registro.inserito_da_legacy_id = getattr(legacy, "id", None)
    registro.origine = "portale"
    return _salva_da_richiesta(request, registro, tipo, prima=None)


@login_required
def carico(request):
    return _handle_form(request, "C")


@login_required
def scarico_originale(request):
    return _handle_form(request, "O")


@login_required
def scarico_effettivo(request):
    return _handle_form(request, "M")


@login_required
def rettifica_scarico(request):
    return _handle_form(request, "R")


_ORM_ORDER = {"O": 0, "R": 1, "M": 2}

# Alias storico: la risalita vive in ``catena.py``.
_risali_a_carichi = risali_a_carichi


def _build_families(records: list, analisi=None, annullati: dict | None = None) -> list[dict]:
    """
    Raggruppa le registrazioni in famiglie (fili): ogni famiglia ha uno o più C
    (carichi) e i relativi O/R/M collegati tramite il campo rif_op (anche
    indirettamente, quando il riferimento passa dal genitore invece che dal carico).

    Famiglie che condividono anche un solo carico vengono fuse (union-find), così
    uno scarico a riferimento multiplo non spezza la catena degli altri.

    Lo stato viene dal conto del filo (``fili.py``): **in deposito** finché un
    carico ha un residuo, **manca lo scarico effettivo** quando è uscito senza M,
    **chiusa** quando è uscito ed è arrivato lo scarico effettivo. Le famiglie
    chiuse vengono in fondo all'elenco.
    """
    from .fili import analizza

    if analisi is None:
        analisi = analizza(records)
    annullati = annullati or {}
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
            analisi, annullati,
        )
        for g in gruppi.values()
    ]

    # O/M/R il cui riferimento non porta a nessun carico del queryset corrente.
    for ops_list in orfane.values():
        families.append(_family_payload(
            [],
            sorted(ops_list, key=lambda r: (r.data or date.min, _ORM_ORDER.get(r.tipo, 9))),
            analisi, annullati,
        ))

    # Le famiglie chiuse vanno in fondo; dentro ogni blocco si ordina per data.
    families.sort(key=lambda f: (f["chiusa"], f["data_inizio"] or date.min, f["id_ancora"]))
    return families


_STATI_FAMIGLIA = {
    "deposito": "IN DEPOSITO",
    "attesa_m": "MANCA SCARICO EFFETTIVO",
    "chiusa": "CHIUSA",
    "senza_carico": "SENZA CARICO",
}


def _family_payload(carichi: list, operazioni: list, analisi=None, annullati: dict | None = None) -> dict:
    """Costruisce la famiglia con i metadati usati dall'elenco (stato, CER, residuo, date)."""
    from collections import Counter
    from decimal import Decimal

    from .fili import EPS, chiave

    righe = carichi + operazioni
    tipi = {r.tipo for r in righe}
    date_note = [r.data for r in righe if r.data]
    codici = sorted({(r.codice or "").strip() for r in righe if (r.codice or "").strip()})
    ancora = carichi[0] if carichi else (operazioni[0] if operazioni else None)
    residuo = Decimal(0)
    if analisi is not None:
        residuo = sum((analisi.residuo.get(c.pk, Decimal(0)) for c in carichi if not c.annullato), Decimal(0))
    if not carichi:
        stato = "senza_carico"
    elif residuo > EPS:
        stato = "deposito"
    elif "M" in tipi:
        stato = "chiusa"
    else:
        stato = "attesa_m"
    annullati = annullati or {}
    scollegati = sorted({rid for r in operazioni for rid in split_rif_op(r.rif_op) if rid in annullati})
    testi = Counter(" ".join(r.codice.split()) for r in righe if (r.codice or "").strip())
    cer_label = testi.most_common(1)[0][0] if testi else ""
    cerca = [_STATI_FAMIGLIA[stato], *scollegati]
    for r in righe:
        cerca += [r.id_registrazione, r.rif_op, r.codice, r.arrivo_fir, r.inserito_da, r.note_rentri]
        if r.data:
            cerca += [r.data.strftime("%d-%m-%Y"), r.data.strftime("%d/%m/%Y")]
    return {
        "cerca": " ".join(" ".join(str(x).split()) for x in cerca if x).lower(),
        "cer_keys": " ".join(sorted({chiave(r.codice) for r in righe if chiave(r.codice)})),
        "hp": list(dict.fromkeys(h for c in carichi for h in c.classi_hp)),
        "carichi": carichi,
        "operazioni": operazioni,
        "tipi": [t for t in ("C", "O", "R", "M") if t in tipi],
        "chiusa": stato == "chiusa",
        "stato": stato,
        "stato_label": _STATI_FAMIGLIA[stato],
        "residuo": residuo,
        "unita": next((c.unita for c in carichi if c.unita), ""),
        "scollegati": scollegati,
        "codice": codici[0] if len(codici) == 1 else " / ".join(codici),
        "cer_key": chiave(cer_label) if cer_label else "",
        "cer_label": cer_label,
        "n_record": len(righe),
        "data_inizio": min(date_note) if date_note else None,
        "data_fine": max(date_note) if date_note else None,
        "id_ancora": (ancora.id_registrazione or "") if ancora is not None else "",
    }


def _raggruppa_per_codice(families: list[dict]) -> list[dict]:
    """Famiglie raggruppate per CER (sei cifre), in ordine di codice."""
    gruppi: dict[str, dict] = {}
    for f in families:
        k = f["cer_key"] or "—"
        g = gruppi.setdefault(k, {"key": k, "label": f["cer_label"] or "— senza codice —", "families": [], "n_record": 0})
        g["families"].append(f)
        g["n_record"] += f["n_record"]
    return sorted(gruppi.values(), key=lambda g: g["key"])


_FILTRI_STATO = {
    "aperte": lambda f: not f["chiusa"],
    "chiuse": lambda f: f["chiusa"],
    "deposito": lambda f: f["stato"] == "deposito",
    "attesa_m": lambda f: f["stato"] == "attesa_m",
    "senza_carico": lambda f: f["stato"] == "senza_carico",
    "scollegati": lambda f: bool(f["scollegati"]),
}


def _codici_filtro() -> list[dict]:
    """CER presenti nel registro per il filtro «Codice»: sei cifre + testo più usato."""
    from collections import Counter

    from .fili import chiave

    testi: dict[str, Counter] = {}
    for c in RegistroRifiuti.objects.exclude(codice="").values_list("codice", flat=True):
        k = chiave(c)
        if k:
            testi.setdefault(k, Counter())[" ".join(c.split())] += 1
    return [{"key": k, "label": t.most_common(1)[0][0]} for k, t in sorted(testi.items())]


_CAMPI_FILTRO = ("tipo", "q", "anno", "dal", "al", "cer", "trasmesso", "consolidato", "pericolosi")


def cifre_cer(testo: str) -> str:
    """Le cifre di una ricerca che è un codice CER, anche parziale («12.01», «12 01 01», «120101»).

    Vuoto se il testo non è un codice: lettere, più di sei cifre o un numero di
    registrazione («2025/1862») si cercano come testo.
    """
    t = (testo or "").strip()
    if not t or not re.fullmatch(r"\d{2}(?:[\s.\-]?\d{2}){0,2}\*?", t):
        return ""
    return re.sub(r"\D", "", t)


def _filtra_registro(get, *, annullati: bool):
    """Queryset e valori dei filtri comuni a elenco ed export PDF."""
    from django.db.models import Q

    from .fili import chiave

    qs = RegistroRifiuti.objects.all() if annullati else RegistroRifiuti.objects.attivi()
    f = {k: (get.get(k, "") or "").strip() for k in _CAMPI_FILTRO}
    if f["tipo"] in ("C", "O", "M", "R"):
        qs = qs.filter(tipo=f["tipo"])
    if f["q"]:
        testo = Q()
        for parola in f["q"].split():
            testo &= (
                Q(codice__icontains=parola) | Q(rif_op__icontains=parola) | Q(id_registrazione__icontains=parola)
                | Q(arrivo_fir__icontains=parola) | Q(note_rentri__icontains=parola) | Q(inserito_da__icontains=parola)
            )
        cifre = cifre_cer(f["q"])
        if cifre:
            per_codice = [pk for pk, c in qs.values_list("pk", "codice") if chiave(c).startswith(cifre)]
            # «12» o «12 01»: solo il codice. Da quattro cifre vale anche come testo («1862» = 2025/1862).
            solo_cifre = f["q"].strip().isdigit() and len(cifre) >= 4
            qs = qs.filter((testo | Q(pk__in=per_codice)) if solo_cifre else Q(pk__in=per_codice))
        else:
            qs = qs.filter(testo)
    if f["anno"].isdigit():
        qs = qs.filter(data__year=int(f["anno"]))
    for campo, lookup in (("dal", "data__gte"), ("al", "data__lte")):
        if not f[campo]:
            continue
        try:
            qs = qs.filter(**{lookup: date.fromisoformat(f[campo])})
        except ValueError:
            f[campo] = ""
    if f["trasmesso"] in ("si", "no"):
        qs = qs.filter(rentri_si_no=f["trasmesso"] == "si")
    if f["consolidato"] in ("si", "no"):
        qs = qs.filter(salva=f["consolidato"] == "si")
    if f["cer"] or f["pericolosi"] == "1":
        righe = list(qs.values_list("pk", "codice", "pericolosita", "tipo"))
        pericolosi = {chiave(c) for _pk, c, p, t in righe if "*" in c or (t == "C" and (p or "").strip())}
        tenuti = [
            pk for pk, c, _p, _t in righe
            if (not f["cer"] or chiave(c) == f["cer"]) and (f["pericolosi"] != "1" or chiave(c) in pericolosi)
        ]
        qs = qs.filter(pk__in=tenuti)
    return qs, f


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
    from .fili import analizza

    ricordati = _ricorda_filtri(request, "elenco")
    if ricordati is not None:
        return ricordati
    q_annullati = request.GET.get("annullati", "") == "1"
    qs, filtri = _filtra_registro(request.GET, annullati=q_annullati)

    q_tipo   = filtri["tipo"]
    q_search = filtri["q"]
    q_anno   = filtri["anno"]
    q_sort   = request.GET.get("sort",  "").strip()
    q_dir    = request.GET.get("dir",   "desc").strip()
    q_group  = request.GET.get("group", "").strip()
    q_view   = request.GET.get("view",  "famiglie").strip()  # default: vista famiglie
    q_stato  = request.GET.get("stato", "").strip()          # vedi _FILTRI_STATO (solo vista famiglie)

    # Parametri dei filtri da riportare nei link (ordinamento, viste, pagine).
    from urllib.parse import urlencode

    filtri_qs = urlencode({k: v for k, v in filtri.items() if v})
    if q_annullati:
        filtri_qs += ("&" if filtri_qs else "") + "annullati=1"

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
        "f": filtri,
        "filtri_qs": filtri_qs,
        "filtri_attivi": any(filtri.values()) or bool(q_group or q_stato or q_annullati),
        "codici_filtro": _codici_filtro(),
        "n_annullati": RegistroRifiuti.objects.filter(annullato=True).count(),
        "can_manage": _can_manage_rentri(request),
    }

    # ── Vista famiglie (default) ───────────────────────────────────────────────
    if q_view == "famiglie" and not q_group:
        # Il conto del filo si fa su tutto il registro valido: il residuo di un
        # carico non dipende dai filtri della pagina.
        records = list(qs.order_by("data", "id_registrazione"))
        attivi = list(RegistroRifiuti.objects.attivi())
        analisi = analizza(attivi)
        _annota_righe(records, attivi)
        annullati = dict(RegistroRifiuti.objects.filter(annullato=True).values_list("id_registrazione", "tipo"))
        families = _build_families(records, analisi, annullati)
        for fam in families:
            vivi = [r for r in fam["carichi"] + fam["operazioni"] if not r.annullato]
            fam["n_vivi"] = len(vivi)
            fam["n_consolidati"] = sum(1 for r in vivi if r.salva)
            fam["ancora_pk"] = vivi[0].pk if vivi else None
        ctx["n_chiuse"] = sum(1 for f in families if f["chiusa"])
        ctx["n_aperte"] = len(families) - ctx["n_chiuse"]
        if q_stato in _FILTRI_STATO:
            families = [f for f in families if _FILTRI_STATO[q_stato](f)]
        ctx["families"] = families
        ctx["fam_aperte"] = [f for f in families if not f["chiusa"]]
        ctx["gruppi_chiuse"] = _raggruppa_per_codice([f for f in families if f["chiusa"]])
        ctx["n_chiuse_vis"] = len(families) - len(ctx["fam_aperte"])
        for i, fam in enumerate(ctx["fam_aperte"], 1):
            fam["fid"] = f"a{i}"
        for gi, grp in enumerate(ctx["gruppi_chiuse"], 1):
            grp["gid"] = str(gi)
            for j, fam in enumerate(grp["families"], 1):
                fam["fid"] = f"g{gi}-{j}"
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
        _annota_righe(records)
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
    pagina = paginator.get_page(request.GET.get("page"))
    pagina.object_list = list(pagina.object_list)
    _annota_righe(pagina.object_list)
    ctx["page_obj"] = pagina
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
            "arrivo_fir": r.arrivo_fir,
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
        "Codice EER", "Quantita", "FIR", "Giorni di giacenza", "Note",
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
                r["arrivo_fir"],
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

    ricordati = _ricorda_filtri(request, "giacenze")
    if ricordati is not None:
        return ricordati
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
        "filtri_attivi": bool(q_search or q_allerta or q_pericolosi or not q_aperte),
        "can_manage": _can_manage_rentri(request),
    })




@login_required
def modifica(request, pk: int):
    registro = get_object_or_404(RegistroRifiuti, pk=pk)

    if request.method == "GET":
        if registro.bloccato:
            # Consolidata o annullata: niente modulo, solo la scheda in lettura.
            return redirect("rentri_dettaglio", pk=registro.pk)
        return _render_form(request, registro.tipo if registro.tipo in _FORM_TIPO else "C", registro)

    denied = _require_rentri_manager(request)
    if denied is not None:
        return denied
    return _salva_da_richiesta(request, registro, registro.tipo, prima=fotografia(registro))


# Il passo successivo della catena dalla scheda: (tipo del figlio, tipi che lo «chiudono», etichetta).
_PROSSIMO = {
    "C": ("O", ("O", "M", "R"), "Scarica (O)", "rentri_scarico_originale"),
    "O": ("M", ("M", "R"), "Registra scarico effettivo (M)", "rentri_scarico_effettivo"),
    "M": ("R", ("R",), "Rettifica (R)", "rentri_rettifica_scarico"),
}


def _prossimo_movimento(registro: RegistroRifiuti, figli: list, filo: list | None = None) -> dict | None:
    """Pulsante «passo successivo» se il movimento non ha ancora il suo seguito.

    Un carico si scarica finché ha un residuo, anche se ha già uno scarico parziale.
    """
    voce = _PROSSIMO.get(registro.tipo)
    if registro.annullato or voce is None:
        return None
    _, chiudono, etichetta, url_name = voce
    if registro.tipo == "C" and filo:
        if filo[0]["stato"] != "deposito":
            return None
    elif any(f.tipo in chiudono for f in figli):
        return None
    return {"etichetta": etichetta, "url": reverse(url_name) + f"?da={registro.pk}"}


def _filo_scheda(registro: RegistroRifiuti) -> list[dict]:
    """Stato del filo dei carichi a cui appartiene il movimento (per la scheda)."""
    from .fili import ETICHETTE_STATO, analizza_codice, stato_filo

    if registro.annullato or not registro.codice:
        return []
    an = analizza_codice(registro.codice)
    if registro.tipo == "C":
        carichi = [registro] if registro.pk in an.residuo else []
    else:
        per_pk = {c.pk: c for lst in an.carichi.values() for c in lst}
        carichi = [per_pk[pk] for pk in an.collegati.get(registro.pk, []) if pk in per_pk]
    out = []
    for c in carichi:
        stato = stato_filo(c, an)
        out.append({"carico": c, "stato": stato, "stato_label": ETICHETTE_STATO[stato], "residuo": an.residuo[c.pk]})
    return out


_URL_TIPO = {"C": "rentri_carico", "O": "rentri_scarico_originale", "M": "rentri_scarico_effettivo", "R": "rentri_rettifica_scarico"}


@login_required
def dettaglio(request, pk: int):
    """Scheda di un movimento: dati, collegamenti, storico, azioni."""
    from .servizi import figli_attivi

    registro = get_object_or_404(RegistroRifiuti, pk=pk)
    genitori = list(
        RegistroRifiuti.objects.filter(id_registrazione__in=split_rif_op(registro.rif_op)).order_by("data", "id")
    )
    voci = storico_oggetto(registro)
    figli = figli_attivi(registro)
    filo = _filo_scheda(registro)
    can_manage = _can_manage_rentri(request)
    bozze_filo = 0
    if can_manage and not registro.annullato:
        _annota_righe([registro])
        anteprima = anteprima_filo(registro)
        bozze_filo = len(anteprima["pronte"]) + len(anteprima["incomplete"])
    return render(request, "rentri/pages/dettaglio.html", {
        "bozze_filo": bozze_filo,
        "registro": registro,
        "genitori": genitori,
        "figli": figli,
        "filo": filo,
        "prossimo": _prossimo_movimento(registro, figli, filo),
        "duplica_url": reverse(_URL_TIPO.get(registro.tipo, "rentri_carico")) + f"?duplica={registro.pk}",
        "storico": storico_leggibile(voci),
        "can_manage": can_manage,
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
        figli = annulla(request, registro, request.POST.get("motivo", ""), _get_username(request))
        testo = f"{registro.id_registrazione} annullata: resta a registro, barrata, e non conta più."
        if figli:
            elenco = ", ".join(f"{f.tipo} {f.id_registrazione}" for f in figli[:6])
            testo += f" Non più collegati (il riferimento resta come traccia): {elenco}."
        return testo
    return _azione_registro(request, pk, _fai)


@login_required
@require_POST
def rimuovi_view(request, pk: int):
    """Dal pulsante cestino delle tabelle: annulla (resta barrata) o elimina definitivamente una bozza."""
    denied = _require_rentri_manager(request)
    if denied is not None:
        return denied
    registro = get_object_or_404(RegistroRifiuti, pk=pk)
    motivo = request.POST.get("motivo", "")
    utente = _get_username(request)
    try:
        if request.POST.get("modo") == "elimina":
            foto = elimina_definitivamente(request, registro, motivo, utente)
            messages.success(
                request,
                f"{foto['id_registrazione']} eliminata definitivamente. Il numero non viene riusato; "
                "dati e motivo restano nel registro delle attività.",
            )
        else:
            figli = annulla(request, registro, motivo, utente)
            testo = f"{registro.id_registrazione} annullata: resta a registro, barrata, e non conta più."
            if figli:
                testo += " Non più collegati (il riferimento resta come traccia): " + ", ".join(
                    f"{f.tipo} {f.id_registrazione}" for f in figli[:6]
                ) + "."
            messages.success(request, testo)
            if registro.sync_errore:
                messages.warning(request, f"La copia su SharePoint non è allineata: {registro.sync_errore}")
    except ErroreRegistro as exc:
        messages.error(request, " ".join(exc.errori))
    prossima = _prossima_rentri(request)
    if prossima.startswith(f"/rentri/{pk}/") and not RegistroRifiuti.objects.filter(pk=pk).exists():
        prossima = ""  # la scheda della riga eliminata non esiste più
    return redirect(prossima or reverse("rentri_elenco"))


@login_required
def consolida_filo_view(request, pk: int):
    """GET: anteprima del filo per il popup. POST: consolida tutte le righe complete del filo."""
    denied = _require_rentri_manager(request)
    if denied is not None:
        return denied
    registro = get_object_or_404(RegistroRifiuti, pk=pk)
    prossima = _prossima_rentri(request)
    if request.method != "POST":
        return render(request, "rentri/components/consolida_filo.html", {
            "registro": registro,
            "anteprima": anteprima_filo(registro),
            "prossima": prossima,
        })
    try:
        esito = consolida_filo(request, registro, _get_username(request))
    except ErroreRegistro as exc:
        messages.error(request, " ".join(exc.errori))
    else:
        fatte = esito["fatte"]
        messages.success(
            request,
            f"Filo consolidato: {len(fatte)} registrazion{'e' if len(fatte) == 1 else 'i'} "
            f"({', '.join(r.id_registrazione for r in fatte[:8])}{'…' if len(fatte) > 8 else ''}).",
        )
        if esito["incomplete"]:
            messages.warning(
                request,
                f"Restano bozze perché incomplete: "
                + "; ".join(f"{r.id_registrazione} ({', '.join(r.mancanti)})" for r in esito["incomplete"][:6]) + ".",
            )
        non_allineate = [r.id_registrazione for r in fatte if r.sync_errore]
        if non_allineate:
            messages.warning(request, f"Copia su SharePoint non allineata per: {', '.join(non_allineate[:8])}.")
    return redirect(prossima or reverse("rentri_dettaglio", args=[pk]))


@login_required
@require_POST
def consolida_bozze_view(request):
    """Consolida in blocco le bozze complete fino alla data indicata (dallo Scadenzario)."""
    from .servizi import consolida_in_blocco

    denied = _require_rentri_manager(request)
    if denied is not None:
        return denied
    try:
        fino_al = date.fromisoformat(request.POST.get("fino_al", ""))
    except ValueError:
        messages.error(request, "Indica una data valida.")
        return redirect("rentri_scadenzario")
    if fino_al > timezone.localdate():
        messages.error(request, "La data non può essere nel futuro.")
        return redirect("rentri_scadenzario")
    esito = consolida_in_blocco(request, fino_al, _get_username(request))
    messages.success(request, f"Consolidate {esito['consolidabili']} registrazioni fino al {fino_al:%d/%m/%Y}.")
    if esito["incomplete"]:
        messages.warning(request, f"{esito['incomplete']} bozze restano da completare (senza data, codice o quantità).")
    return redirect("rentri_scadenzario")


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
    can_manage = _can_manage_rentri(request)
    from .uniforma import proposte

    return render(request, "rentri/pages/verifica.html", {
        "sezioni": sezioni,
        "totale": sum(len(s["righe"]) for s in sezioni),
        "today": timezone.localdate(),
        "can_manage": can_manage,
        "uniforma": proposte() if can_manage else [],
    })


@login_required
@require_POST
def uniforma_codici(request):
    """Scrive un testo unico per i codici scelti nella Verifica (stesse sei cifre, solo la forma)."""
    from .uniforma import TestoNonValido, applica

    denied = _require_rentri_manager(request)
    if denied is not None:
        return denied
    scelte = {
        k: request.POST.get(f"testo_{k}", "")
        for k in request.POST.getlist("codice")
        if re.fullmatch(r"\d{6}", k or "")
    }
    if not scelte:
        messages.warning(request, "Spunta almeno un codice da uniformare.")
        return redirect(reverse("rentri_verifica") + "#uniforma")
    try:
        esito = applica(request, scelte, _get_username(request))
    except TestoNonValido as exc:
        messages.error(request, str(exc))
        return redirect(reverse("rentri_verifica") + "#uniforma")
    messages.success(request, f"Uniformati {esito['codici']} codici: {esito['righe']} registrazioni aggiornate (storico nella scheda di ognuna).")
    return redirect(reverse("rentri_verifica") + "#uniforma")


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


_TIPO_EXPORT = {"C": "Carico", "O": "Scarico originale", "M": "Scarico effettivo", "R": "Rettifica"}
_STATO_EXPORT = {
    "aperte": "Da completare", "chiuse": "Chiuse", "deposito": "In deposito",
    "attesa_m": "Manca scarico effettivo", "senza_carico": "Senza carico",
    "scollegati": "Collegati a un annullato",
}


def _registro_da_esportare(get):
    """Righe, filtri, stato del filo per riga ed etichetta filtri di un export.

    `scope=tutto` = registro completo, annullati compresi (tracciabilità);
    altrimenti gli stessi filtri dell'elenco, stato del filo incluso.
    """
    from .fili import analizza

    tutto = get.get("scope") == "tutto"
    if tutto:
        qs, f = RegistroRifiuti.objects.all(), {k: "" for k in _CAMPI_FILTRO}
        annullati_ok, stato = True, ""
    else:
        annullati_ok = get.get("annullati", "") == "1"
        qs, f = _filtra_registro(get, annullati=annullati_ok)
        stato = (get.get("stato", "") or "").strip()
        if stato not in _FILTRI_STATO:
            stato = ""
    records = list(qs.order_by("data", "id_registrazione", "id"))
    analisi = analizza(list(RegistroRifiuti.objects.attivi()))
    nomi_annullati = dict(RegistroRifiuti.objects.filter(annullato=True).values_list("id_registrazione", "tipo"))
    stati: dict[int, str] = {}
    tenuti: set[int] = set()
    for fam in _build_families(records, analisi, nomi_annullati):
        pks = [r.pk for r in fam["carichi"] + fam["operazioni"]]
        for pk in pks:
            stati[pk] = fam["stato_label"].capitalize()
        if not stato or _FILTRI_STATO[stato](fam):
            tenuti.update(pks)
    if stato:
        records = [r for r in records if r.pk in tenuti]

    parti = []
    if f["tipo"]:
        parti.append(f"Tipo: {_TIPO_EXPORT.get(f['tipo'], f['tipo'])}")
    if f["cer"]:
        parti.append(f"Codice: {f['cer']}")
    if f["anno"]:
        parti.append(f"Anno: {f['anno']}")
    if f["dal"] or f["al"]:
        parti.append(f"Periodo: {f['dal'] or '…'} → {f['al'] or '…'}")
    if f["trasmesso"]:
        parti.append("Trasmessi" if f["trasmesso"] == "si" else "Da trasmettere")
    if f["consolidato"]:
        parti.append("Consolidati" if f["consolidato"] == "si" else "Bozze")
    if f["pericolosi"] == "1":
        parti.append("Solo pericolosi")
    if stato:
        parti.append(f"Filo: {_STATO_EXPORT[stato]}")
    if f["q"]:
        parti.append(f"Ricerca: {f['q']}")
    if parti and not annullati_ok:
        parti.append("senza annullati")
    etichetta = " | ".join(parti) if parti else (
        "Registro completo" if annullati_ok else "Tutte le registrazioni valide"
    )
    return records, f, stati, etichetta


def _numero(v):
    return float(v) if v is not None else None


@login_required
def export_excel(request):
    """GET: registro RENTRI in Excel, completo (`scope=tutto`) o con i filtri dell'elenco."""
    from core.excel_export import make_xlsx_response

    records, f, stati, etichetta = _registro_da_esportare(request.GET)
    righe = [
        [
            r.data, r.id_registrazione, _TIPO_EXPORT.get(r.tipo, r.tipo), " ".join((r.codice or "").split()),
            _numero(r.quantita), _numero(r.rettifica_scarico), r.unita, r.rif_op, r.arrivo_fir,
            stati.get(r.pk, ""), "Sì" if r.salva else "No", "Sì" if r.rentri_si_no else "No",
            (f"Sì — {r.motivo_annullamento}".strip(" —") if r.annullato else ""),
            r.rif_op_storico, r.note_rentri, r.inserito_da,
        ]
        for r in records
    ]
    log_action(request, "rentri_export_excel", "rentri", {"righe": len(righe), "filtri": etichetta})
    oggi = timezone.localdate()
    nome = "completo" if request.GET.get("scope") == "tutto" else (f["anno"] or "filtrato")
    return make_xlsx_response(
        filename=f"rentri_{nome}_{oggi:%Y%m%d}.xlsx",
        columns=[
            "Data", "N. registrazione", "Tipo", "Codice EER", "Quantità", "Rettifica scarico", "Unità",
            "Collegato a", "FIR", "Stato del filo", "Consolidato", "Trasmesso", "Annullato",
            "Collegamenti tolti", "Note", "Inserito da",
        ],
        rows=righe,
        sheet_title="Registro",
        title="Registro RENTRI",
        subtitle=f"{len(righe)} registrazioni",
        filters_label=etichetta,
    )


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

    # ── filtri (gli stessi dell'elenco) ───────────────────────────────────────
    records, _filtri, _stati, filters_str = _registro_da_esportare(request.GET)

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
    anno_str = _filtri["anno"] or timezone.localdate().strftime("%Y")
    filename = f"rentri_{anno_str}_{timezone.localdate().strftime('%Y%m%d')}.pdf"
    log_action(request, "rentri_export_pdf", "rentri", {"righe": n_records, "filtri": filters_str})
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

    if request.method == "POST" and request.POST.get("azione") == "catalogo_eer":
        return _carica_catalogo_eer(request)

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
            "catalogo_voci": CatalogoEER.objects.count(),
            "catalogo_pericolosi": CatalogoEER.objects.filter(pericoloso=True).count(),
            **get_module_branding_context("rentri", fallback_label="RENTRI"),
        },
    )


_CATALOGO_MAX_BYTES = 15 * 1024 * 1024


def _carica_catalogo_eer(request):
    """Sostituisce il catalogo EER col file caricato (HTML/PDF EUR-Lex o CSV)."""
    from .catalogo import leggi_file, sostituisci
    from .management.commands.rentri_catalogo_eer import MIN_VOCI

    f = request.FILES.get("file_catalogo")
    if not f:
        messages.error(request, "Scegli il file del catalogo.")
        return redirect("rentri_impostazioni")
    nome = (f.name or "").lower()
    if not nome.endswith((".html", ".htm", ".pdf", ".csv", ".txt")) or f.size > _CATALOGO_MAX_BYTES:
        messages.error(request, "Il file deve essere HTML, PDF, CSV o TXT e stare sotto i 15 MB.")
        return redirect("rentri_impostazioni")
    voci = leggi_file(nome, f.read())
    if len(voci) < MIN_VOCI:
        messages.error(
            request,
            f"Nel file ho trovato solo {len(voci)} codici: non sembra l'elenco completo (sono circa 840). Catalogo non modificato.",
        )
        return redirect("rentri_impostazioni")
    n = sostituisci(voci)
    log_action(request, "modifica", "rentri", f"Catalogo EER caricato: {n} voci da {f.name}")
    messages.success(request, f"Catalogo EER aggiornato: {n} codici.")
    return redirect("rentri_impostazioni")


def _anno_richiesto(request) -> int:
    testo = (request.GET.get("anno") or "").strip()
    return int(testo) if testo.isdigit() and 2000 <= int(testo) <= 2100 else timezone.localdate().year


@login_required
def registro_cronologico(request):
    """GET: PDF del registro cronologico dell'anno (annullate comprese, «Pagina N di M»)."""
    from django.http import HttpResponse

    from .registro_annuale import _catalogo
    from .registro_annuale import registro_cronologico as righe_anno
    from .stampe import pdf_registro_cronologico

    anno = _anno_richiesto(request)
    righe = righe_anno(anno)
    pdf = pdf_registro_cronologico(anno, righe, RentriImpostazioni.get_singleton(), _catalogo())
    log_action(request, "rentri_registro_cronologico", "rentri", {"anno": anno, "righe": len(righe)})
    response = HttpResponse(pdf, content_type="application/pdf")
    response["Content-Disposition"] = f'inline; filename="registro_cronologico_{anno}.pdf"'
    return response


def _andamento_annuale(anni: list[int], righe_anno: list, anno: int) -> dict:
    """Caricato e scaricato in kg per anno (ultimi sei) e confronto per codice con l'anno prima."""
    from .registro_annuale import riepilogo_anno

    serie = []
    for a in sorted(anni)[-6:]:
        rr = righe_anno if a == anno else riepilogo_anno(a)
        kg = [r for r in rr if r.unita == "kg" and not r.unita_miste]
        serie.append({"anno": a, "caricato": float(sum(r.caricato for r in kg)),
                      "scaricato": float(sum(r.scaricato for r in kg))})
    prima = {r.chiave: r for r in riepilogo_anno(anno - 1)}
    for r in righe_anno:
        p = prima.get(r.chiave)
        r.caricato_prima = p.caricato if p else None
        r.variazione = (
            round(float((r.caricato - p.caricato) / p.caricato * 100))
            if p and p.caricato and r.unita == p.unita else None
        )
    massimo = max([max(s["caricato"], s["scaricato"]) for s in serie] + [0]) or 1
    for s in serie:
        s["h_car"] = round(s["caricato"] / massimo * 100, 1)
        s["h_sca"] = round(s["scaricato"] / massimo * 100, 1)
    return {"serie": serie, "massimo": massimo, "con_dati": any(s["caricato"] or s["scaricato"] for s in serie)}


@login_required
def riepilogo_annuale(request):
    """Riepilogo per codice CER dell'anno (base per il MUD), con export Excel e PDF."""
    from .registro_annuale import anni_disponibili, riepilogo_anno

    ricordati = _ricorda_filtri(request, "riepilogo_annuale")
    if ricordati is not None:
        return ricordati
    anno = _anno_richiesto(request)
    righe = riepilogo_anno(anno)
    formato = request.GET.get("export", "")
    if formato == "xlsx":
        from core.excel_export import make_xlsx_response

        log_action(request, "rentri_riepilogo_excel", "rentri", {"anno": anno, "righe": len(righe)})
        return make_xlsx_response(
            filename=f"rentri_riepilogo_{anno}.xlsx",
            columns=["Codice EER", "Descrizione", "Pericoloso", "Unità", "Giacenza al 1/1", "Caricato", "Scaricato",
                     "Giacenza al 31/12", "N. carichi", "N. scarichi", "Formulari", "Non torna"],
            rows=[
                [rg.codice, rg.descrizione, "Sì" if rg.pericoloso else "No",
                 rg.unita + (" (miste)" if rg.unita_miste else ""), _numero(rg.giacenza_inizio),
                 _numero(rg.caricato), _numero(rg.scaricato), _numero(rg.giacenza_fine), rg.n_carichi,
                 rg.n_scarichi, ", ".join(rg.fir), _numero(rg.differenza) if abs(rg.differenza) > 0.0005 else None]
                for rg in righe
            ],
            sheet_title=f"Riepilogo {anno}",
            title=f"RENTRI — riepilogo annuale {anno}",
            subtitle=f"{len(righe)} codici",
            filters_label="Base per il MUD: giacenze dal conto del filo",
        )
    if formato == "pdf":
        from django.http import HttpResponse

        from .stampe import pdf_riepilogo

        log_action(request, "rentri_riepilogo_pdf", "rentri", {"anno": anno, "righe": len(righe)})
        response = HttpResponse(pdf_riepilogo(anno, righe, RentriImpostazioni.get_singleton()), content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="rentri_riepilogo_{anno}.pdf"'
        return response
    andamento = _andamento_annuale(anni_disponibili(), righe, anno)
    return render(request, "rentri/pages/riepilogo_annuale.html", {
        "andamento": andamento,
        "anno": anno,
        "anni": anni_disponibili(),
        "righe": righe,
        "n_non_torna": sum(1 for rg in righe if abs(rg.differenza) > 0.0005),
        "cfg": RentriImpostazioni.get_singleton(),
    })
