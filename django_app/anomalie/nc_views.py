"""Sezione «Non conformità» del modulo anomalie: lista, scheda NC per OP, PDF.

Permessi (tutti lato server):
- **vedere** una NC = chi vede le anomalie dell'OP, oppure chi ha il permesso
  ``anomalie.nc.gestione``;
- **compilare** le sezioni = chi modifica le anomalie dell'OP (capocommessa/CAR,
  «Modifica tutto») oppure chi gestisce le NC;
- **chiudere / riaprire** = secondo l'opzione del modulo (``nc_service``).
"""
from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from uuid import uuid4

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import FileResponse, Http404, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from core.acl_v2 import request_has_permission_code
from core.audit import log_action
from core.legacy_utils import get_legacy_user, is_legacy_admin
from core.upload_mime import UploadMimeValidationError, safe_filename, validate_extension_and_mime

from . import nc_service
from .acl_bootstrap import PERM_ANOMALIE_NC
from .quality_models import AnomaliaNC as NC
from .quality_models import AnomaliaNCAllegato, AnomaliaNCAzione

logger = logging.getLogger(__name__)

ISHIKAWA = {
    "manodopera": "Manodopera",
    "metodo": "Metodo",
    "macchina": "Macchina",
    "materiale": "Materiale",
    "misura": "Misura",
    "ambiente": "Ambiente",
}
ALLEGATI_EXT = {".pdf", ".jpg", ".jpeg", ".png", ".docx", ".xlsx"}
ALLEGATI_MIME = {
    "application/pdf", "image/jpeg", "image/png", "application/zip",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
ALLEGATI_MAX = 20 * 1024 * 1024
LISTA_MAX = 300


# ── Permessi ───────────────────────────────────────────────────────────────


def _gestore(request) -> bool:
    user = request.user
    if getattr(user, "is_superuser", False):
        return True
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(user)
    if legacy_user and is_legacy_admin(legacy_user):
        return True
    try:
        return bool(request_has_permission_code(request, PERM_ANOMALIE_NC))
    except Exception:
        return False


def _permessi(request, nc, *, gestore: bool | None = None) -> dict:
    from . import views as av

    gestore = _gestore(request) if gestore is None else gestore
    vede = gestore or av._can_view_anomalie_for_op(request, nc.op_titolo)
    modifica = gestore or av._can_edit_anomalie_for_op(request, nc.op_titolo)
    try:
        ruoli = set(av._op_role_codes_for_current_user(request, nc.op_titolo))
    except Exception:
        ruoli = set()
    chiude = nc_service.puo_chiudere(gestore=gestore, capocommessa="CC" in ruoli, modifica_op=modifica)
    return {"vede": vede, "modifica": modifica, "chiude": chiude, "gestore": gestore, "ruoli": ruoli}


def _mie(request, nc) -> bool:
    """La NC riguarda l'utente: e' capocommessa/CAR dell'OP o ha azioni assegnate."""
    from . import views as av

    norms = av._current_user_name_norms(request)
    for campo in (nc.capocommessa, nc.car):
        for token in av._split_people_tokens(campo):
            if av._normalize_identity_text(token) in norms:
                return True
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    if legacy_user:
        return any(a.responsabile_legacy_id == legacy_user.id and a.aperta for a in nc.azioni.all())
    return False


# ── Lista ──────────────────────────────────────────────────────────────────


@login_required
def nc_lista(request):
    gestore = _gestore(request)
    stato = str(request.GET.get("stato") or "aperte").strip().upper()
    q = str(request.GET.get("q") or "").strip()
    solo_mie = request.GET.get("mie") == "1"
    solo_scadute = request.GET.get("scadute") == "1"

    from django.db.models import Count
    qs = NC.objects.annotate(n_schede=Count("schede")).prefetch_related("azioni").order_by("-id")
    if q:
        from django.db.models import Q
        qs = qs.filter(Q(op_titolo__icontains=q) | Q(part_number__icontains=q) | Q(protocollo__icontains=q))
    visibili = []
    for nc in qs[:LISTA_MAX * 3]:
        if gestore or _permessi(request, nc, gestore=False)["vede"]:
            visibili.append(nc)
        if len(visibili) >= LISTA_MAX:
            break

    oggi = timezone.localdate()
    conteggi = {k: 0 for k, _ in NC.Stato.choices}
    for nc in visibili:
        conteggi[nc.stato] = conteggi.get(nc.stato, 0) + 1
        azioni = [a for a in nc.azioni.all() if a.aperta]
        nc.n_azioni_aperte = len(azioni)
        nc.n_azioni_scadute = sum(1 for a in azioni if a.scadenza and a.scadenza < oggi)

    righe = visibili
    if stato == "APERTE":
        righe = [n for n in righe if n.stato != NC.Stato.CHIUSA]
    elif stato in conteggi:
        righe = [n for n in righe if n.stato == stato]
    if solo_scadute:
        righe = [n for n in righe if n.n_azioni_scadute]
    if solo_mie:
        righe = [n for n in righe if _mie(request, n)]

    return render(request, "anomalie/pages/nc_lista.html", {
        "righe": righe,
        "stati": NC.Stato.choices,
        "conteggi": conteggi,
        "n_aperte": sum(v for k, v in conteggi.items() if k != NC.Stato.CHIUSA),
        "filtro": {"stato": stato, "q": q, "mie": solo_mie, "scadute": solo_scadute},
        "troncata": len(visibili) >= LISTA_MAX,
        "gestore": gestore,
    })


# ── Dettaglio ──────────────────────────────────────────────────────────────


def _data_o_none(raw):
    raw = str(raw or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _testo(request, key: str, max_len: int = 5000) -> str:
    return str(request.POST.get(key) or "").strip()[:max_len]


def _nome(request) -> str:
    return (request.user.get_full_name() or request.user.username or "")[:150]


def _passi(nc) -> list[dict]:
    ordine = [k for k, _ in NC.Stato.choices]
    idx = ordine.index(nc.stato) if nc.stato in ordine else 0
    return [{"label": label, "stato": "done" if i < idx else ("current" if i == idx else "todo")}
            for i, (_, label) in enumerate(NC.Stato.choices)]


@login_required
def nc_dettaglio(request, pk: int):
    nc = get_object_or_404(NC.objects.select_related("precedente", "chiusa_da"), pk=pk)
    perm = _permessi(request, nc)
    if not perm["vede"]:
        return HttpResponseForbidden("Permesso negato")

    if request.method == "POST":
        return _nc_post(request, nc, perm)

    righe = nc_service.anomalie_della_nc(nc)
    nc_service.ricalcola_stato(nc, righe)
    if not (nc.capocommessa or nc.car):
        nc_service.riallinea_responsabili(nc)
    perche = list(nc.analisi_perche or []) + [""] * 5
    return render(request, "anomalie/pages/nc_dettaglio.html", {
        "nc": nc,
        "perm": perm,
        "righe": righe,
        "contenimento_cc": nc_service.contenimento_capocommessa(righe),
        "passi": _passi(nc),
        "perche": perche[:5],
        "ishikawa": [(k, label, (nc.analisi_ishikawa or {}).get(k, "")) for k, label in ISHIKAWA.items()],
        "metodi": NC.MetodoAnalisi.choices,
        "esiti": NC.Esito.choices,
        "azioni": list(nc.azioni.all()),
        "azione_tipi": AnomaliaNCAzione.Tipo.choices,
        "azione_stati": AnomaliaNCAzione.Stato.choices,
        "responsabili": nc_service.responsabili_proposti(nc) if perm["modifica"] else [],
        "allegati": list(nc.allegati.select_related("uploaded_by")),
        "sezioni_allegato": AnomaliaNCAllegato.Sezione.choices,
        "eventi": list(nc.eventi.all()[:40]),
        "ricadute": list(nc.ricadute.all()),
        "oggi": timezone.localdate(),
        "gestione_url": f"{reverse('gestione_anomalie_page')}?op={nc.op_titolo}",
    })


def _nc_post(request, nc, perm):
    action = str(request.POST.get("action") or "").strip()
    ancora = {"contenimento": "contenimento", "analisi": "analisi", "verifica": "verifica",
              "azione_nuova": "azioni", "azione_aggiorna": "azioni", "allegato": "allegati"}.get(action, "")
    torna = redirect(reverse("anomalie_nc_dettaglio", args=[nc.pk]) + (f"#{ancora}" if ancora else ""))

    if action in ("chiudi", "riapri"):
        if not perm["chiude"]:
            return HttpResponseForbidden("Non puoi chiudere o riaprire questa NC")
        if action == "chiudi" and not nc.is_chiusa:
            nc_service.chiudi(nc, user=request.user, note=_testo(request, "note_chiusura"))
            messages.success(request, f"{nc.protocollo} chiusa.")
        elif action == "riapri" and nc.is_chiusa:
            nc_service.riapri(nc, user=request.user, motivo=_testo(request, "motivo", 300))
            messages.success(request, f"{nc.protocollo} riaperta.")
        _log(request, nc, action)
        _impara(nc, action, request.user)
        return torna

    if not perm["modifica"]:
        return HttpResponseForbidden("Permesso negato: non puoi modificare questa NC")
    if nc.is_chiusa:
        messages.error(request, "NC chiusa: per modificarla va prima riaperta.")
        return torna

    with transaction.atomic():
        if action == "contenimento":
            nc.contenimento = _testo(request, "contenimento")
            nc.contenimento_data = _data_o_none(request.POST.get("contenimento_data"))
            nc.contenimento_da = _testo(request, "contenimento_da", 150) or (_nome(request) if nc.contenimento else "")
            nc.updated_by = request.user
            nc.save()
            nc_service.registra_evento(nc, "contenimento", "Contenimento aggiornato", request.user)
        elif action == "analisi":
            metodo = str(request.POST.get("analisi_metodo") or "").strip().upper()
            nc.analisi_metodo = metodo if metodo in dict(NC.MetodoAnalisi.choices) else ""
            nc.analisi_perche = [_testo(request, f"perche_{i}", 1000) for i in range(1, 6)]
            nc.analisi_ishikawa = {k: _testo(request, f"ishikawa_{k}", 1000) for k in ISHIKAWA}
            nc.analisi_riferimento = _testo(request, "analisi_riferimento", 300)
            nc.causa_radice = _testo(request, "causa_radice")
            nc.analisi_data = _data_o_none(request.POST.get("analisi_data"))
            nc.analisi_da = _testo(request, "analisi_da", 150) or (_nome(request) if nc.causa_radice else "")
            nc.updated_by = request.user
            nc.save()
            nc_service.registra_evento(nc, "analisi", "Analisi delle cause aggiornata", request.user)
        elif action == "azione_nuova":
            descrizione = _testo(request, "descrizione")
            if not descrizione:
                messages.error(request, "Descrivi l'azione.")
                return torna
            resp_id, resp_nome = _responsabile(request, nc)
            tipo = str(request.POST.get("tipo") or "").upper()
            a = AnomaliaNCAzione.objects.create(
                nc=nc, descrizione=descrizione,
                tipo=tipo if tipo in dict(AnomaliaNCAzione.Tipo.choices) else AnomaliaNCAzione.Tipo.CORRETTIVA,
                responsabile_legacy_id=resp_id, responsabile_nome=resp_nome,
                scadenza=_data_o_none(request.POST.get("scadenza")), created_by=request.user,
            )
            nc_service.registra_evento(
                nc, "azione", f"Nuova azione: {a.descrizione[:200]}" + (f" → {resp_nome}" if resp_nome else ""), request.user)
        elif action == "azione_aggiorna":
            a = get_object_or_404(AnomaliaNCAzione, pk=int(request.POST.get("azione_id") or 0), nc=nc)
            stato = str(request.POST.get("stato") or "").upper()
            if stato in dict(AnomaliaNCAzione.Stato.choices) and stato != a.stato:
                a.stato = stato
                a.completata_il = timezone.localdate() if stato == AnomaliaNCAzione.Stato.FATTA else None
                nc_service.registra_evento(
                    nc, "azione", f"Azione «{a.descrizione[:120]}»: {a.get_stato_display()}", request.user)
            a.esito = _testo(request, "esito")
            if "scadenza" in request.POST:
                a.scadenza = _data_o_none(request.POST.get("scadenza"))
                a.promemoria_il = None
            a.save()
        elif action == "verifica":
            nc.verifica_prevista = _data_o_none(request.POST.get("verifica_prevista"))
            nc.verifica_data = _data_o_none(request.POST.get("verifica_data"))
            esito = str(request.POST.get("verifica_esito") or "").upper()
            nc.verifica_esito = esito if esito in dict(NC.Esito.choices) else ""
            nc.verifica_note = _testo(request, "verifica_note")
            nc.verifica_da = _testo(request, "verifica_da", 150) or (_nome(request) if nc.verifica_esito else "")
            if nc.verifica_esito and not nc.verifica_data:
                nc.verifica_data = timezone.localdate()
            nc.updated_by = request.user
            nc.save()
            nc_service.registra_evento(
                nc, "verifica", "Verifica di efficacia: " + (nc.get_verifica_esito_display() if nc.verifica_esito else "aggiornata"),
                request.user)
            if nc.verifica_esito == NC.Esito.EFFICACE and perm["chiude"]:
                nc_service.chiudi(nc, user=request.user, note="Verifica di efficacia positiva")
                messages.success(request, f"Verifica positiva: {nc.protocollo} chiusa.")
        elif action == "allegato":
            _salva_allegato(request, nc)
        else:
            messages.error(request, "Azione non riconosciuta.")
            return torna
        if not nc.is_chiusa:
            nc_service.ricalcola_stato(nc)
    _log(request, nc, action)
    _impara(nc, action, request.user)
    if action in ("contenimento", "analisi", "azione_nuova", "azione_aggiorna") or (
            action == "verifica" and not nc.is_chiusa):
        messages.success(request, "Salvato.")
    return torna


def _impara(nc, action: str, user) -> None:
    """Registra cosa e' stato salvato rispetto alla proposta del copilota (se ce n'era una)."""
    try:
        from . import ai_nc

        if action == "analisi":
            ai_nc.registra_esito_analisi(nc, user)
        elif action in ("verifica", "chiudi"):
            ai_nc.registra_esito_azioni(nc, user)
    except Exception:  # noqa: BLE001 - l'apprendimento non deve mai bloccare il salvataggio
        logger.exception("Apprendimento copilota NC non registrato")


@login_required
def nc_copilota(request, pk: int):
    """Proposta AI di analisi e azioni, con le NC simili e il loro esito. Non salva nulla."""
    if request.method != "POST":
        return HttpResponse(status=405)
    nc = get_object_or_404(NC.objects.select_related("precedente"), pk=pk)
    perm = _permessi(request, nc)
    if not perm["modifica"]:
        return HttpResponseForbidden("Permesso negato")
    from .ai_nc import proponi_analisi_nc

    proposta = proponi_analisi_nc(nc, user=request.user)
    log_action(request, "nc_copilota", "anomalie", {
        "nc": nc.protocollo, "simili": len(proposta["simili"]), "azioni": len(proposta["azioni"]),
        "ai_disponibile": proposta["ai_disponibile"],
    })
    return render(request, "anomalie/partials/nc_copilota.html", {"p": proposta, "nc": nc})


def _responsabile(request, nc) -> tuple[int | None, str]:
    raw = str(request.POST.get("responsabile") or "").strip()
    if not raw.isdigit():
        return None, _testo(request, "responsabile_nome", 200)
    uid = int(raw)
    for r in nc_service.responsabili_proposti(nc):
        if r["id"] == uid:
            return uid, r["nome"][:200]
    return None, ""


def _log(request, nc, action: str) -> None:
    try:
        log_action(request, f"anomalia_nc_{action}", "anomalie", {"nc": nc.protocollo, "op": nc.op_titolo})
    except Exception:
        pass


# ── Allegati ───────────────────────────────────────────────────────────────


def _cartella_nc(nc) -> Path:
    from .views import _anomalie_attachments_root
    return _anomalie_attachments_root() / "nc" / str(nc.pk)


def _salva_allegato(request, nc) -> None:
    f = request.FILES.get("file")
    if f is None:
        messages.error(request, "Nessun file selezionato.")
        return
    try:
        mime = validate_extension_and_mime(
            f, allowed_extensions=ALLEGATI_EXT, allowed_mimes=ALLEGATI_MIME,
            max_bytes=ALLEGATI_MAX, label="Allegato", allow_empty=False,
        )
    except UploadMimeValidationError as exc:
        messages.error(request, str(exc))
        return
    nome = safe_filename(f.name) or "allegato"
    cartella = _cartella_nc(nc)
    cartella.mkdir(parents=True, exist_ok=True)
    file_id = f"{uuid4().hex}__{nome}"
    with (cartella / file_id).open("wb") as out:
        for chunk in f.chunks():
            out.write(chunk)
    sezione = str(request.POST.get("sezione") or "").upper()
    AnomaliaNCAllegato.objects.create(
        nc=nc, nome=nome[:255], file_rel=f"nc/{nc.pk}/{file_id}", size=int(f.size or 0), mime=mime[:100],
        sezione=sezione if sezione in dict(AnomaliaNCAllegato.Sezione.choices) else AnomaliaNCAllegato.Sezione.ALTRO,
        uploaded_by=request.user,
    )
    nc_service.registra_evento(nc, "allegato", f"Allegato caricato: {nome[:200]}", request.user)
    messages.success(request, f"Allegato «{nome}» caricato.")


@login_required
def nc_allegato(request, pk: int, allegato_id: int):
    nc = get_object_or_404(NC, pk=pk)
    if not _permessi(request, nc)["vede"]:
        return HttpResponseForbidden("Permesso negato")
    allegato = get_object_or_404(AnomaliaNCAllegato, pk=allegato_id, nc=nc)
    from .views import _anomalie_attachments_root

    root = _anomalie_attachments_root().resolve()
    path = (root / allegato.file_rel).resolve()
    if root not in path.parents or not path.is_file():
        raise Http404("Allegato non disponibile")
    inline = allegato.mime in ("application/pdf", "image/jpeg", "image/png")
    return FileResponse(path.open("rb"), as_attachment=not inline, filename=allegato.nome,
                        content_type=allegato.mime or "application/octet-stream")


# ── PDF ────────────────────────────────────────────────────────────────────


@login_required
def nc_pdf(request, pk: int):
    nc = get_object_or_404(NC.objects.select_related("precedente", "chiusa_da"), pk=pk)
    if not _permessi(request, nc)["vede"]:
        return HttpResponseForbidden("Permesso negato")
    from .services.nc_pdf import build_nc_pdf_bytes

    pdf = build_nc_pdf_bytes(nc, nc_service.anomalie_della_nc(nc), ishikawa_labels=ISHIKAWA)
    _log(request, nc, "pdf")
    resp = HttpResponse(pdf, content_type="application/pdf")
    resp["Content-Disposition"] = f'inline; filename="{nc.protocollo}.pdf"'
    return resp
