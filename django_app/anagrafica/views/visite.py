"""Viste anagrafica — Sorveglianza sanitaria: visite mediche, referti, libretto, sicurezza, conformità.

Spacchettamento di ``anagrafica/views.py`` (18/10/2026): le funzioni condivise stanno in
``_helpers`` e si chiamano ``_helpers.nome`` così i test patchano un solo punto.
"""
from __future__ import annotations

import logging
from datetime import timedelta as _timedelta
from datetime import date
from pathlib import Path

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.http import (
    HttpResponse, HttpResponseForbidden, JsonResponse,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
# Alias esplicito: in questo file `timezone` è già importato dentro varie
# funzioni (come `tz`/`_tz`) e `datetime.timezone` è un'altra cosa ancora.
from django.utils import timezone as django_timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_http_methods, require_POST

from django.contrib.auth.decorators import login_required
from core import naming
from core.csv_export import BOM, CSV_CONTENT_TYPE, safe_csv_writer
from core.legacy_anagrafica import (
    ensure_anagrafica_schema,
    fetch_anagrafica_rows,
)
from core.legacy_models import AnagraficaDipendente
from core.legacy_utils import get_legacy_user

from ..forms import (
    VisitaMedicaForm,
)
from ..models import (
    DURATA_VISITA_MAX_MESI,
    DipendenteAnagraficaAziendale,
    DipendenteAnagraficaCivile,
    DipendenteQualifica,
    DipendenteRuoloOperativo,
    DocumentoDipendente,
    Mansione,
    RuoloOperativo,
    TipoQualifica,
    TipoVisitaMedica,
    VisitaMedica,
)
from ..services.visite import (
    completa_referti_visite,
    ultime_visite_correnti_ids,
)
from ..services import conformita as conformita_service
from ..acl_bootstrap import (
    PERM_VISITE_DELETE,
)
from core.upload_limits import DOCUMENT_MAX_BYTES, DOCUMENT_MAX_MB


from . import _helpers  # noqa: E402

logger = logging.getLogger(__name__)


def _visite_mediche_panel_ctx(request) -> dict:
    """Contesto del pannello «Tipi di visita medica» di Impostazioni.

    Ricalcolato ad ogni azione (create/edit/delete/bulk) per il partial HTMX,
    indipendente dal contesto — molto più ampio — della vista ``impostazioni``.
    """
    from datetime import timedelta

    from django.db.models import Case as _VmCase, When as _VmWhen
    from django.utils import timezone as tz

    tipi_visita = list(
        TipoVisitaMedica.objects
        .annotate(n_visite=Count("visite"))
        .prefetch_related("ruoli_operativi", "mansioni_richiedenti")
        .order_by(_VmCase(_VmWhen(categoria="", then=1), default=0), "categoria", "nome")
    )
    categorie_visita = sorted({t.categoria for t in tipi_visita if t.categoria})
    soglia = tz.localdate() + timedelta(days=60)
    scadenze_vm_count = VisitaMedica.objects.filter(
        data_scadenza__isnull=False, data_scadenza__lte=soglia
    ).count()
    return {
        "is_admin": _helpers._is_anagrafica_admin(request),
        "tipi_visita": tipi_visita,
        "categorie_visita": categorie_visita,
        "scadenze_vm_count": scadenze_vm_count,
        "mansioni": list(Mansione.objects.all().order_by("nome")),
        "ruoli_operativi": list(RuoloOperativo.objects.order_by("nome")),
    }


def _visite_mediche_response(request):
    """Esito di un'azione sul catalogo visite mediche: partial HTMX (il resto
    della pagina Impostazioni non ricarica) se il form è arrivato via HTMX,
    altrimenti il redirect classico di sempre (form senza JS)."""
    if request.headers.get("HX-Request"):
        return render(
            request, "anagrafica/partials/_visite_mediche_panel_wrapper.html",
            _visite_mediche_panel_ctx(request),
        )
    return _helpers._redirect_impostazioni("visite-mediche")


def _fascia_eta_tipo_visita(post) -> tuple[int | None, int | None, str]:
    """(eta_minima, eta_massima, errore) dai campi del form; vuoto = nessun limite."""
    valori = []
    for campo in ("eta_minima", "eta_massima"):
        raw = (post.get(campo) or "").strip()
        if not raw:
            valori.append(None)
            continue
        try:
            valore = int(raw)
        except ValueError:
            return None, None, "Età non valida: un numero di anni da 0 a 120."
        if not 0 <= valore <= 120:
            return None, None, "Età non valida: un numero di anni da 0 a 120."
        valori.append(valore)
    minima, massima = valori
    if minima is not None and massima is not None and minima > massima:
        return None, None, "Fascia d'età non valida: «età da» supera «età fino a»."
    return minima, massima, ""


def _durata_tipo_visita(raw) -> int | None:
    """Periodicità in mesi da 0 (nessuna scadenza) a DURATA_VISITA_MAX_MESI; None se non valida.
    Prima un valore sbagliato diventava 12 in silenzio, cambiando tutte le scadenze."""
    raw = (raw or "").strip()
    if not raw:
        return 12
    try:
        durata = int(raw)
    except ValueError:
        return None
    return durata if 0 <= durata <= DURATA_VISITA_MAX_MESI else None


@login_required
@require_POST
def tipo_visita_medica_create(request):
    ok, resp = _helpers._impostazioni_admin_check(request, "visite-mediche")
    if not ok:
        return _visite_mediche_response(request) if request.headers.get("HX-Request") else resp
    nome = (request.POST.get("nome") or "").strip()[:150]
    if not nome:
        messages.error(request, "Il nome della visita è obbligatorio.")
        return _visite_mediche_response(request)
    durata_mesi = _durata_tipo_visita(request.POST.get("durata_mesi"))
    if durata_mesi is None:
        messages.error(request, f"Periodicità non valida: un numero di mesi da 0 a {DURATA_VISITA_MAX_MESI}.")
        return _visite_mediche_response(request)
    eta_minima, eta_massima, errore_eta = _fascia_eta_tipo_visita(request.POST)
    if errore_eta:
        messages.error(request, errore_eta)
        return _visite_mediche_response(request)
    tv, created = TipoVisitaMedica.objects.get_or_create(
        nome__iexact=nome,
        defaults={
            "nome": nome,
            "durata_mesi": durata_mesi,
            "eta_minima": eta_minima,
            "eta_massima": eta_massima,
            "obbligatoria": request.POST.get("obbligatoria") == "1",
            "descrizione": (request.POST.get("descrizione") or "").strip(),
            "categoria": (request.POST.get("categoria") or "").strip()[:100],
        },
    )
    if created:
        ruolo_ids = [int(x) for x in request.POST.getlist("ruolo_ids") if str(x).isdigit()]
        if ruolo_ids:
            tv.ruoli_operativi.set(ruolo_ids)
        mansione_ids = [int(x) for x in request.POST.getlist("mansione_ids") if str(x).isdigit()]
        if mansione_ids:
            tv.mansioni_richiedenti.set(mansione_ids)
        messages.success(request, f'Tipo visita "{nome}" creato.')
    else:
        messages.warning(request, f'Esiste già un tipo visita con il nome "{nome}".')
    return _visite_mediche_response(request)


@login_required
@require_POST
def tipo_visita_medica_edit(request, tipo_id: int):
    ok, resp = _helpers._impostazioni_admin_check(request, "visite-mediche")
    if not ok:
        return _visite_mediche_response(request) if request.headers.get("HX-Request") else resp
    tipo = get_object_or_404(TipoVisitaMedica, pk=tipo_id)
    nome = (request.POST.get("nome") or "").strip()[:150]
    if not nome:
        messages.error(request, "Il nome della visita è obbligatorio.")
        return _visite_mediche_response(request)
    durata_mesi = _durata_tipo_visita(request.POST.get("durata_mesi"))
    if durata_mesi is None:
        messages.error(request, f"Periodicità non valida: un numero di mesi da 0 a {DURATA_VISITA_MAX_MESI}.")
        return _visite_mediche_response(request)
    eta_minima, eta_massima, errore_eta = _fascia_eta_tipo_visita(request.POST)
    if errore_eta:
        messages.error(request, errore_eta)
        return _visite_mediche_response(request)
    tipo.nome = nome
    tipo.durata_mesi = durata_mesi
    tipo.eta_minima = eta_minima
    tipo.eta_massima = eta_massima
    tipo.obbligatoria = request.POST.get("obbligatoria") == "1"
    tipo.descrizione = (request.POST.get("descrizione") or "").strip()
    tipo.categoria = (request.POST.get("categoria") or "").strip()[:100]
    tipo.is_active = request.POST.get("is_active") == "1"
    tipo.save()
    ruolo_ids = [int(x) for x in request.POST.getlist("ruolo_ids") if str(x).isdigit()]
    tipo.ruoli_operativi.set(ruolo_ids)
    mansione_ids = [int(x) for x in request.POST.getlist("mansione_ids") if str(x).isdigit()]
    tipo.mansioni_richiedenti.set(mansione_ids)
    messages.success(request, f'Tipo visita "{tipo.nome}" aggiornato.')
    return _visite_mediche_response(request)


@login_required
@require_POST
def tipo_visita_medica_delete(request, tipo_id: int):
    ok, resp = _helpers._impostazioni_admin_check(request, "visite-mediche")
    if not ok:
        return _visite_mediche_response(request) if request.headers.get("HX-Request") else resp
    tipo = get_object_or_404(TipoVisitaMedica, pk=tipo_id)
    n_uso = tipo.visite.count()
    if n_uso:
        if tipo.is_active:
            tipo.is_active = False
            tipo.save(update_fields=["is_active"])
            messages.warning(request, f'"{tipo.nome}" è in uso ({n_uso} visite registrate): disattivato (non eliminato) per preservare lo storico. Puoi riattivarlo dalla modifica.')
        else:
            messages.error(request, f'"{tipo.nome}" ha {n_uso} visite registrate: non eliminabile (già disattivo).')
        return _visite_mediche_response(request)
    nome = tipo.nome
    tipo.delete()
    messages.success(request, f'Tipo visita "{nome}" eliminato.')
    return _visite_mediche_response(request)


@login_required
@require_POST
def tipo_visita_medica_bulk_edit(request):
    """Applica in blocco categoria/obbligatorietà/stato attivo ai tipi visita
    selezionati (checkbox della lista). Ogni campo lasciato vuoto/"non
    modificare" non viene toccato sui record selezionati."""
    ok, resp = _helpers._impostazioni_admin_check(request, "visite-mediche")
    if not ok:
        return _visite_mediche_response(request) if request.headers.get("HX-Request") else resp

    ids = [int(x) for x in request.POST.getlist("ids") if str(x).isdigit()]
    if not ids:
        messages.error(request, "Nessun tipo visita selezionato.")
        return _visite_mediche_response(request)

    campi: dict = {}
    categoria = (request.POST.get("categoria") or "").strip()
    if categoria:
        campi["categoria"] = categoria[:100]
    obbligatoria = (request.POST.get("obbligatoria") or "").strip()
    if obbligatoria in ("0", "1"):
        campi["obbligatoria"] = obbligatoria == "1"
    is_active = (request.POST.get("is_active") or "").strip()
    if is_active in ("0", "1"):
        campi["is_active"] = is_active == "1"

    if not campi:
        messages.error(request, "Scegli almeno un campo da modificare in blocco.")
        return _visite_mediche_response(request)

    aggiornati = TipoVisitaMedica.objects.filter(pk__in=ids).update(**campi)
    # update() salta i segnali post_save: categoria, obbligatorietà e stato attivo
    # cambiano le visite dovute e la famiglia, quindi il ricalcolo va chiesto qui.
    from ..services.scadenze import ricalcola_dopo_commit
    ricalcola_dopo_commit(None)
    messages.success(
        request,
        f'{aggiornati} tipi visita aggiornati in blocco ({", ".join(campi)}).',
    )
    return _visite_mediche_response(request)


def _audit_consultazione_visita(request, visita: VisitaMedica) -> None:
    """Traccia chi consulta un dato sanitario (GDPR art. 9), al più una riga
    all'ora per utente e visita, per non annegare l'audit nei refresh."""
    try:
        from django.core.cache import cache

        from core.audit import log_action

        if cache.add(f"anagrafica:visita_vista:{request.user.pk}:{visita.pk}", 1, 3600):
            log_action(
                request, "VISITA_MEDICA_VISUALIZZATA", "anagrafica",
                {"visita_id": visita.pk, "dipendente_id": visita.legacy_anagrafica_id},
                oggetto=visita,
            )
    except Exception:
        logger.warning("Audit consultazione visita %s fallito", visita.pk, exc_info=True)


@login_required
def visita_medica_dettaglio(request, v_id: int):
    """Scheda HTML della singola visita, con i medesimi gate della sezione sanitaria."""
    if not _helpers._can_view_visite_mediche(request):
        return HttpResponseForbidden("Non hai i permessi per visualizzare le visite mediche.")

    visita = get_object_or_404(
        VisitaMedica.objects.select_related(
            "tipo", "sessione", "referto_documento", "referto_documento_secondario",
            "created_by", "updated_by",
        ),
        pk=v_id,
    )
    _audit_consultazione_visita(request, visita)
    completa_referti_visite([visita])
    if visita.referto_documento_secondario_id and all(
        documento.pk != visita.referto_documento_secondario_id
        for documento in visita.referti_documenti
    ):
        visita.referti_documenti.append(visita.referto_documento_secondario)
    dipendente_nome = f"Dipendente #{visita.legacy_anagrafica_id}"
    try:
        persona = AnagraficaDipendente.objects.filter(id=visita.legacy_anagrafica_id).values(
            "nome", "cognome"
        ).first()
        if persona:
            dipendente_nome = naming.nome_completo(
                persona.get("nome"), persona.get("cognome")
            ) or dipendente_nome
    except Exception:
        logger.exception("Errore lookup dipendente per visita %s", v_id)

    # Scadenza secondo il tipo della visita fatta: se diversa da quella salvata, la
    # scheda spiega l'anticipo (ricalcolo prudente, services.scadenze.ricalcola_visite).
    durata = visita.tipo.durata_mesi or 0
    scadenza_tipo = _helpers._add_months(visita.data_svolgimento, durata) if durata > 0 else None
    return render(request, "anagrafica/pages/visita_medica_dettaglio.html", {
        "visita": visita,
        "scadenza_tipo": scadenza_tipo,
        "scadenza_anticipata": bool(not visita.scadenza_medico and scadenza_tipo and visita.data_scadenza
                                    and visita.data_scadenza < scadenza_tipo),
        "dipendente_nome": dipendente_nome,
        "form": VisitaMedicaForm(instance=visita),
        "can_edit_visite": _helpers._can_edit_visite_mediche(request),
        "can_delete_visite": _helpers._has_canonical_grant(request, PERM_VISITE_DELETE),
    })


@login_required
@require_POST
def visita_medica_superata(request, v_id: int):
    """Segna (o ripristina) una visita come superata: esce dallo scadenziario
    ma resta nello storico e nel libretto. Motivo obbligatorio + audit."""
    if not _helpers._can_edit_visite_mediche(request):
        return HttpResponseForbidden("Non hai i permessi per modificare le visite mediche.")

    from django.utils import timezone as _tz
    from core.audit import log_action

    visita = get_object_or_404(VisitaMedica.objects.select_related("tipo"), pk=v_id)
    ripristina = request.POST.get("azione") == "ripristina"
    motivo = (request.POST.get("motivo") or "").strip()
    if not ripristina and (not motivo or len(motivo) > 500):
        messages.error(request, "Indica perché la visita è superata (massimo 500 caratteri).")
        return redirect(f"{reverse('anagrafica:visita_medica_dettaglio', args=[v_id])}#superata")

    dettaglio = {
        "visita_id": visita.pk,
        "dipendente_id": visita.legacy_anagrafica_id,
        "tipo_visita": visita.tipo.nome,
        "data_svolgimento": visita.data_svolgimento.isoformat(),
    }
    if ripristina and VisitaMedica.objects.filter(
        legacy_anagrafica_id=visita.legacy_anagrafica_id, tipo_id=visita.tipo_id,
        data_svolgimento=visita.data_svolgimento, superata_il__isnull=True,
    ).exclude(pk=visita.pk).exists():
        messages.error(
            request,
            "Non ripristinabile: c'è già una visita attiva dello stesso tipo e della stessa "
            "data per questo dipendente. Segna prima quella come superata, se è lei il doppione.",
        )
        return redirect("anagrafica:visita_medica_dettaglio", v_id=v_id)
    if ripristina:
        dettaglio["motivo_precedente"] = visita.superata_motivo
        visita.superata_il = None
        visita.superata_da = None
        visita.superata_motivo = ""
        azione, testo = "VISITA_MEDICA_RIPRISTINATA", "Visita ripristinata nello scadenziario."
    else:
        dettaglio["motivo"] = motivo
        visita.superata_il = _tz.now()
        visita.superata_da = request.user
        visita.superata_motivo = motivo
        azione, testo = "VISITA_MEDICA_SUPERATA", "Visita segnata come superata: non compare più nello scadenziario."
    visita.updated_by = request.user
    try:
        with transaction.atomic():
            visita.save(update_fields=[
                "superata_il", "superata_da", "superata_motivo", "updated_by", "updated_at",
            ])
    except IntegrityError:
        messages.error(request, "Non ripristinabile: esiste già una visita attiva dello stesso tipo e data.")
        return redirect("anagrafica:visita_medica_dettaglio", v_id=v_id)
    log_action(request, azione, "anagrafica", dettaglio, oggetto=visita)
    messages.success(request, testo)
    return redirect("anagrafica:visita_medica_dettaglio", v_id=v_id)


@login_required
@require_http_methods(["GET", "POST"])
def visita_medica_elimina(request, v_id: int):
    """Rimuove una visita errata solo dopo conferma, ACL e audit atomico."""
    if not _helpers._can_view_visite_mediche(request) or not _helpers._has_canonical_grant(request, PERM_VISITE_DELETE):
        return HttpResponseForbidden("Non hai i permessi per eliminare visite mediche.")

    visita = get_object_or_404(VisitaMedica.objects.select_related("tipo"), pk=v_id)
    def referti_collegati(v, *, lock=False):
        """Include FK storiche e documenti con riferimento generico alla visita."""
        documenti = DocumentoDipendente.objects.filter(
            oggetto_riferimento_tipo="anagrafica.visitamedica",
            oggetto_riferimento_id=v.pk,
        )
        if lock:
            documenti = documenti.select_for_update()
        documenti_ids = list(documenti.values_list("pk", flat=True))
        referti_ids = sorted(set(documenti_ids) | {
            pk for pk in (v.referto_documento_id, v.referto_documento_secondario_id) if pk
        })
        return documenti, referti_ids

    motivo = (request.POST.get("motivo") or "").strip() if request.method == "POST" else ""
    if request.method == "POST":
        if not motivo or len(motivo) > 1000:
            messages.error(request, "Inserisci una motivazione (massimo 1000 caratteri).")
        else:
            from core.audit import _get_client_ip
            from core.impersonation import display_name_for_user
            from core.models import AuditLog

            try:
                with transaction.atomic():
                    visita = VisitaMedica.objects.select_for_update().select_related("tipo").get(pk=v_id)
                    documenti_collegati, referti_ids = referti_collegati(visita, lock=True)
                    legacy_user = get_legacy_user(request.user)
                    actor_legacy = getattr(request, "impersonator_legacy_user", None) or legacy_user
                    AuditLog.objects.create(
                        legacy_user_id=getattr(actor_legacy, "id", None),
                        utente_display=display_name_for_user(
                            django_user=getattr(request, "impersonator_user", None) or request.user,
                            legacy_user=actor_legacy,
                        ),
                        azione="VISITA_MEDICA_ELIMINATA",
                        modulo="anagrafica",
                        dettaglio={
                            "motivo": motivo,
                            "visita_id": visita.pk,
                            "dipendente_id": visita.legacy_anagrafica_id,
                            "tipo_visita": visita.tipo.nome,
                            "data_svolgimento": visita.data_svolgimento.isoformat(),
                            "data_scadenza": visita.data_scadenza.isoformat() if visita.data_scadenza else None,
                            "referti_conservati_ids": referti_ids,
                        },
                        ip_address=_get_client_ip(request),
                        oggetto_tipo="anagrafica.visitamedica",
                        oggetto_id=str(visita.pk),
                    )
                    documenti_collegati.update(
                        oggetto_riferimento_tipo="", oggetto_riferimento_id=None
                    )
                    visita.delete()
            except Exception:
                logger.exception("Eliminazione visita %s fallita", v_id)
                messages.error(request, "Eliminazione non riuscita: la visita è rimasta registrata.")
            else:
                messages.success(request, "Visita eliminata e motivazione registrata nell'audit. I referti restano nel fascicolo del dipendente.")
                return redirect("anagrafica:visite_mediche_dashboard")

    _, referti_ids = referti_collegati(visita)
    return render(request, "anagrafica/pages/visita_medica_elimina.html", {
        "visita": visita,
        "motivo": motivo,
        "referti_count": len(referti_ids),
    })


# ---------------------------------------------------------------------------
# Gestione del singolo referto di visita medica
# ---------------------------------------------------------------------------
RIFERIMENTO_VISITA_MEDICA = "anagrafica.visitamedica"


def _visita_del_referto(doc: DocumentoDipendente) -> VisitaMedica | None:
    """La visita a cui il referto e' agganciato, per riferimento o per FK.

    Il riferimento generico (``oggetto_riferimento_*``) e' la fonte primaria:
    e' cio' che l'import e il form usano. Le FK sulla visita restano un
    secondo canale, perche' i referti storici possono avere solo quelle.
    """
    if doc.oggetto_riferimento_tipo == RIFERIMENTO_VISITA_MEDICA and doc.oggetto_riferimento_id:
        visita = (
            VisitaMedica.objects.select_related("tipo")
            .filter(pk=doc.oggetto_riferimento_id)
            .first()
        )
        if visita is not None:
            return visita
    return (
        VisitaMedica.objects.select_related("tipo")
        .filter(Q(referto_documento_id=doc.pk) | Q(referto_documento_secondario_id=doc.pk))
        .first()
    )


def _nome_dipendente_legacy(legacy_id: int) -> str:
    """Nome e cognome dal legacy, con fallback all'id: mai una pagina senza titolo."""
    fallback = f"Dipendente #{legacy_id}"
    try:
        persona = (
            AnagraficaDipendente.objects.filter(id=legacy_id)
            .values("nome", "cognome")
            .first()
        )
    except Exception:
        logger.exception("Errore lookup dipendente #%s", legacy_id)
        return fallback
    if not persona:
        return fallback
    return naming.nome_completo(persona.get("nome"), persona.get("cognome")) or fallback


def _accessi_referto(doc: DocumentoDipendente, limit: int = 100) -> list:
    """Chi ha aperto QUESTO referto, dal piu' recente.

    Due sorgenti, perche' l'audit del download ha iniziato ad agganciare il
    record solo da questa versione: le voci nuove si trovano per
    ``oggetto_tipo``/``oggetto_id``, quelle storiche solo dal testo del
    dettaglio, filtrato in Python per non dipendere dalle lookup JSON (il
    backend SQL Server non le supporta in modo uniforme).
    """
    from core.models import AuditLog

    azione = "DOCUMENTO_DIPENDENTE_DOWNLOAD"
    voci = list(
        AuditLog.objects.filter(
            azione=azione,
            oggetto_tipo=DocumentoDipendente._meta.label_lower,
            oggetto_id=str(doc.pk),
        ).order_by("-created_at")[:limit]
    )
    try:
        atteso = f"documento #{doc.pk} "
        storiche = (
            AuditLog.objects.filter(azione=azione, modulo="anagrafica", oggetto_id="")
            .order_by("-created_at")[:500]
        )
        for voce in storiche:
            dettaglio = voce.dettaglio or {}
            testo = dettaglio.get("dettaglio", "") if isinstance(dettaglio, dict) else dettaglio
            if atteso in str(testo):
                voci.append(voce)
    except Exception:
        logger.warning("Ricerca accessi storici referto %s fallita", doc.pk, exc_info=True)
    voci.sort(key=lambda v: v.created_at, reverse=True)
    return voci[:limit]


def _audit_referto(request, azione: str, doc: DocumentoDipendente, dettaglio: dict) -> None:
    """Audit agganciato al record del referto: alimenta storico e accessi."""
    try:
        from core.audit import log_action
        log_action(request, azione, "anagrafica", dettaglio, oggetto=doc)
    except Exception:
        logger.warning("Audit %s fallito per referto %s", azione, doc.pk, exc_info=True)


@login_required
@require_http_methods(["GET", "POST"])
def referto_gestione(request, doc_id: int):
    """Scheda di gestione di un singolo referto: metadati, file, aggancio, accessi.

    Il referto e' un dato sanitario: la lettura passa dal permesso delle visite
    mediche, l'eliminazione da ``anagrafica.visite.delete`` con motivazione
    obbligatoria. Ogni azione scrive una voce di audit agganciata al record,
    cosi' la scheda stessa e' il registro di cosa e' stato fatto e di chi ha
    aperto il file.
    """
    if not _helpers._can_view_referti(request):
        return HttpResponseForbidden("Non hai i permessi per gestire i referti sanitari.")

    doc = get_object_or_404(
        DocumentoDipendente.objects.select_related("created_by", "cartella"),
        pk=doc_id,
        tipo=DocumentoDipendente.Tipo.VISITA_MEDICA_REFERTO,
    )
    if doc.cartella_id and doc.cartella.solo_admin and not _helpers._can_view_documenti_riservati(request):
        return HttpResponseForbidden("Referto in cartella riservata.")

    can_delete = _helpers._has_canonical_grant(request, PERM_VISITE_DELETE)
    azione = (request.POST.get("azione") or "").strip() if request.method == "POST" else ""
    motivo = (request.POST.get("motivo") or "").strip() if request.method == "POST" else ""

    if request.method == "POST":
        visita = _visita_del_referto(doc)

        if azione == "metadati":
            descrizione = (request.POST.get("descrizione") or "").strip()[:300]
            nome_originale = (request.POST.get("nome_originale") or "").strip()[:255]
            retention_raw = (request.POST.get("retention_until") or "").strip()
            retention = parse_date(retention_raw) if retention_raw else None
            if retention_raw and retention is None:
                messages.error(request, "Data di conservazione non valida.")
            elif not nome_originale:
                messages.error(request, "Il nome del file è obbligatorio.")
            else:
                prima = {
                    "descrizione": doc.descrizione,
                    "nome_originale": doc.nome_originale,
                    "retention_until": doc.retention_until.isoformat() if doc.retention_until else None,
                }
                doc.descrizione = descrizione
                doc.nome_originale = nome_originale
                doc.retention_until = retention
                doc.save(update_fields=["descrizione", "nome_originale", "retention_until"])
                _audit_referto(request, "REFERTO_MODIFICATO", doc, {
                    "prima": prima,
                    "dopo": {
                        "descrizione": doc.descrizione,
                        "nome_originale": doc.nome_originale,
                        "retention_until": doc.retention_until.isoformat() if doc.retention_until else None,
                    },
                    "motivo": motivo[:1000],
                    "visita_id": visita.pk if visita else None,
                    "dipendente_id": doc.legacy_anagrafica_id,
                })
                messages.success(request, "Dati del referto aggiornati.")
                return redirect("anagrafica:referto_gestione", doc_id=doc.pk)

        elif azione == "sostituisci":
            uploaded = request.FILES.get("file")
            if not uploaded:
                messages.error(request, "Seleziona il file del nuovo referto.")
            else:
                suffix = Path(uploaded.name or "").suffix.lower()
                if suffix not in _helpers._ALLOWED_DOC_EXTENSIONS:
                    messages.error(
                        request,
                        f"Formato non consentito ({suffix}). Ammessi: PDF, DOC, DOCX, "
                        "XLS, XLSX, JPG, PNG, WEBP.",
                    )
                elif uploaded.size > _MAX_DOC_SIZE:
                    messages.error(
                        request,
                        f"File troppo grande ({uploaded.size // (1024 * 1024)} MB). Limite: {DOCUMENT_MAX_MB} MB.",
                    )
                else:
                    try:
                        # SEC (audit A8): libmagic sul contenuto, fail-closed; mai il
                        # tipo dichiarato dal browser. (``sniff_mime`` non esiste in
                        # core.upload_mime: l'import falliva sempre e si ripiegava
                        # sul Content-Type del client.)
                        from core.upload_mime import sniff_upload_mime
                        mime = sniff_upload_mime(uploaded)
                    except Exception:
                        mime = ""
                    if mime not in _ALLOWED_DOC_MIMES:
                        messages.error(request, "Tipo di file non consentito (contenuto non valido).")
                    else:
                        prima = {
                            "nome_originale": doc.nome_originale,
                            "dimensione_bytes": doc.dimensione_bytes,
                            "tipo_mime": doc.tipo_mime,
                        }
                        vecchio_storage = doc.file.storage if doc.file else None
                        vecchio_nome = doc.file.name if doc.file else ""
                        doc.file.save(uploaded.name, uploaded, save=False)
                        doc.nome_originale = uploaded.name[:255]
                        doc.tipo_mime = mime
                        doc.dimensione_bytes = uploaded.size
                        doc.save(update_fields=[
                            "file", "nome_originale", "tipo_mime", "dimensione_bytes",
                        ])
                        if vecchio_storage and vecchio_nome and vecchio_nome != doc.file.name:
                            try:
                                if vecchio_storage.exists(vecchio_nome):
                                    vecchio_storage.delete(vecchio_nome)
                            except Exception:
                                logger.warning(
                                    "File precedente del referto %s non rimosso",
                                    doc.pk, exc_info=True,
                                )
                        _audit_referto(request, "REFERTO_SOSTITUITO", doc, {
                            "prima": prima,
                            "dopo": {
                                "nome_originale": doc.nome_originale,
                                "dimensione_bytes": doc.dimensione_bytes,
                                "tipo_mime": doc.tipo_mime,
                            },
                            "motivo": motivo[:1000],
                            "visita_id": visita.pk if visita else None,
                            "dipendente_id": doc.legacy_anagrafica_id,
                        })
                        messages.success(
                            request,
                            "Referto sostituito: il file precedente è stato rimosso.",
                        )
                        return redirect("anagrafica:referto_gestione", doc_id=doc.pk)

        elif azione in {"principale", "secondario"}:
            if visita is None:
                messages.error(request, "Il referto non è collegato a nessuna visita.")
            else:
                campo = "referto_documento" if azione == "principale" else "referto_documento_secondario"
                altro = "referto_documento_secondario" if azione == "principale" else "referto_documento"
                aggiorna = [campo, "updated_at", "updated_by"]
                setattr(visita, campo, doc)
                if getattr(visita, f"{altro}_id", None) == doc.pk:
                    setattr(visita, altro, None)
                    aggiorna.append(altro)
                visita.updated_by = request.user
                doc.oggetto_riferimento_tipo = RIFERIMENTO_VISITA_MEDICA
                doc.oggetto_riferimento_id = visita.pk
                doc.save(update_fields=["oggetto_riferimento_tipo", "oggetto_riferimento_id"])
                visita.save(update_fields=aggiorna)
                _audit_referto(request, "REFERTO_RUOLO_CAMBIATO", doc, {
                    "ruolo": azione,
                    "motivo": motivo[:1000],
                    "visita_id": visita.pk,
                    "dipendente_id": doc.legacy_anagrafica_id,
                })
                messages.success(
                    request,
                    "Referto impostato come principale." if azione == "principale"
                    else "Referto impostato come secondario.",
                )
                return redirect("anagrafica:referto_gestione", doc_id=doc.pk)

        elif azione == "scollega":
            if not motivo:
                messages.error(request, "Indica il motivo dello scollegamento.")
            else:
                visita_id = visita.pk if visita else None
                with transaction.atomic():
                    if visita is not None:
                        aggiorna = ["updated_at", "updated_by"]
                        if visita.referto_documento_id == doc.pk:
                            visita.referto_documento = None
                            aggiorna.append("referto_documento")
                        if visita.referto_documento_secondario_id == doc.pk:
                            visita.referto_documento_secondario = None
                            aggiorna.append("referto_documento_secondario")
                        visita.updated_by = request.user
                        visita.save(update_fields=aggiorna)
                    doc.oggetto_riferimento_tipo = ""
                    doc.oggetto_riferimento_id = None
                    doc.save(update_fields=["oggetto_riferimento_tipo", "oggetto_riferimento_id"])
                _audit_referto(request, "REFERTO_SCOLLEGATO", doc, {
                    "motivo": motivo[:1000],
                    "visita_id": visita_id,
                    "dipendente_id": doc.legacy_anagrafica_id,
                })
                messages.success(
                    request,
                    "Referto scollegato dalla visita: resta nel fascicolo del dipendente.",
                )
                return redirect("anagrafica:referto_gestione", doc_id=doc.pk)

        elif azione == "elimina":
            if not can_delete:
                return HttpResponseForbidden("Non hai i permessi per eliminare referti sanitari.")
            if not motivo or len(motivo) > 1000:
                messages.error(request, "Inserisci una motivazione (massimo 1000 caratteri).")
            else:
                legacy_id = doc.legacy_anagrafica_id
                visita_id = visita.pk if visita else None
                try:
                    with transaction.atomic():
                        bloccato = (
                            DocumentoDipendente.objects.select_for_update()
                            .get(pk=doc.pk)
                        )
                        if visita is not None:
                            aggiorna = ["updated_at", "updated_by"]
                            if visita.referto_documento_id == bloccato.pk:
                                visita.referto_documento = None
                                aggiorna.append("referto_documento")
                            if visita.referto_documento_secondario_id == bloccato.pk:
                                visita.referto_documento_secondario = None
                                aggiorna.append("referto_documento_secondario")
                            visita.updated_by = request.user
                            visita.save(update_fields=aggiorna)
                        _audit_referto(request, "REFERTO_ELIMINATO", bloccato, {
                            "motivo": motivo,
                            "nome_originale": bloccato.nome_originale,
                            "dimensione_bytes": bloccato.dimensione_bytes,
                            "visita_id": visita_id,
                            "dipendente_id": legacy_id,
                        })
                        bloccato.delete()
                except Exception:
                    logger.exception("Eliminazione referto %s fallita", doc.pk)
                    messages.error(
                        request, "Eliminazione non riuscita: il referto è rimasto in archivio.",
                    )
                else:
                    messages.success(request, "Referto eliminato e motivazione registrata nell'audit.")
                    if visita_id:
                        return redirect("anagrafica:visita_medica_dettaglio", v_id=visita_id)
                    return redirect("anagrafica:dipendente_detail", legacy_id=legacy_id)
        else:
            messages.error(request, "Azione non riconosciuta.")

    from core.audit import storico_oggetto

    visita = _visita_del_referto(doc)
    ruolo = ""
    if visita is not None:
        if visita.referto_documento_id == doc.pk:
            ruolo = "principale"
        elif visita.referto_documento_secondario_id == doc.pk:
            ruolo = "secondario"
    accessi = _accessi_referto(doc)
    return render(request, "anagrafica/pages/referto_gestione.html", {
        "doc": doc,
        "visita": visita,
        "ruolo": ruolo,
        "dipendente_nome": _nome_dipendente_legacy(doc.legacy_anagrafica_id),
        "accessi": accessi,
        "accessi_count": len(accessi),
        "storico": storico_oggetto(doc, limit=60),
        "can_delete_referto": can_delete,
        "motivo": motivo,
    })


# ---------------------------------------------------------------------------
# Upload manuale documento dipendente
# ---------------------------------------------------------------------------

_ALLOWED_DOC_MIMES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "image/jpeg",
    "image/png",
    "image/webp",
}
_MAX_DOC_SIZE = DOCUMENT_MAX_BYTES


@login_required
def visite_mediche_dashboard(request):
    """Dashboard globale visite mediche.

    Mostra (gating su ``_can_view_visite_mediche``):
    - contatori: scadute / in scadenza / valide / mancanti aggregati sull'azienda
    - tabella "scadute o in scadenza" con dettaglio dipendente
    - tabella "ultime visite registrate"
    - elenco tipologie attive con counter di dipendenti coperti vs richiesti
    """
    if not _helpers._can_view_visite_mediche(request):
        messages.error(request, "Non hai i permessi per visualizzare le visite mediche.")
        return redirect("anagrafica:index")

    import calendar as _calendar
    from django.utils import timezone as _tz

    oggi = _tz.localdate()
    soglia_avviso = oggi + _timedelta(days=60)

    # Filtro mese dalla query string (?scad=mese_corrente | prossimo_mese | tutti)
    filtro_scad = request.GET.get("scad", "").strip()

    # Map legacy_id -> "Cognome Nome" da AnagraficaDipendente (lookup unico)
    nomi_map = _helpers._build_nomi_map()

    # Fonte unica "visite correnti" (l'ultima per dipendente+tipo): le righe
    # storiche superate non contano più come scadute/in scadenza.
    correnti_qs = VisitaMedica.objects.filter(id__in=ultime_visite_correnti_ids())

    # KPI globali (sulle visite correnti dell'intero dataset, non filtrato per mese)
    kpi_scadute = correnti_qs.filter(
        data_scadenza__isnull=False, data_scadenza__lt=oggi
    ).count()
    kpi_in_scad = correnti_qs.filter(
        data_scadenza__isnull=False, data_scadenza__range=[oggi, soglia_avviso]
    ).count()
    kpi_visite_totali = VisitaMedica.objects.count()

    _MESI_ITA = ["", "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
                 "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre"]

    # Ultime visite registrate (globale, 30 più recenti)
    ultime_visite = list(
        VisitaMedica.objects
        .select_related("tipo", "referto_documento")
        .order_by("-data_svolgimento", "-id")[:30]
    )
    completa_referti_visite(ultime_visite)
    for v in ultime_visite:
        v.dipendente_nome = nomi_map.get(v.legacy_anagrafica_id, f"#{v.legacy_anagrafica_id}")
        if v.data_svolgimento:
            v.mese_label = f"{_MESI_ITA[v.data_svolgimento.month]} {v.data_svolgimento.year}"
        else:
            v.mese_label = "Data non disponibile"

    # Scadute o in scadenza — con filtro mese opzionale
    if filtro_scad == "mese_corrente":
        _, last_day_n = _calendar.monthrange(oggi.year, oggi.month)
        _range_start = oggi.replace(day=1)
        _range_end = oggi.replace(day=last_day_n)
        scad_qs = correnti_qs.filter(
            data_scadenza__isnull=False,
            data_scadenza__range=[_range_start, _range_end],
        )
    elif filtro_scad == "prossimo_mese":
        pm_y = oggi.year + 1 if oggi.month == 12 else oggi.year
        pm_m = 1 if oggi.month == 12 else oggi.month + 1
        _, last_day_n = _calendar.monthrange(pm_y, pm_m)
        _range_start = date(pm_y, pm_m, 1)
        _range_end = date(pm_y, pm_m, last_day_n)
        scad_qs = correnti_qs.filter(
            data_scadenza__isnull=False,
            data_scadenza__range=[_range_start, _range_end],
        )
    else:
        filtro_scad = "tutti"
        scad_qs = correnti_qs.filter(
            data_scadenza__isnull=False, data_scadenza__lte=soglia_avviso
        )

    scad_o_in_scad = list(scad_qs.select_related("tipo").order_by("data_scadenza"))
    for v in scad_o_in_scad:
        v.dipendente_nome = nomi_map.get(v.legacy_anagrafica_id, f"#{v.legacy_anagrafica_id}")
        v.giorni_a_scadenza = (v.data_scadenza - oggi).days if v.data_scadenza else None
        if v.data_scadenza:
            v.mese_label = f"{_MESI_ITA[v.data_scadenza.month]} {v.data_scadenza.year}"
        else:
            v.mese_label = "Senza scadenza"

    # Pre-aggrega conteggi DB per tipo (evita N query nel loop) — solo visite correnti
    _valide_per_tipo = {
        row["tipo_id"]: row["n"]
        for row in correnti_qs
        .filter(data_scadenza__gte=oggi)
        .order_by()
        .values("tipo_id")
        .annotate(n=Count("legacy_anagrafica_id", distinct=True))
    }
    _scadute_per_tipo = {
        row["tipo_id"]: row["n"]
        for row in correnti_qs
        .filter(data_scadenza__lt=oggi)
        .order_by()
        .values("tipo_id")
        .annotate(n=Count("legacy_anagrafica_id", distinct=True))
    }

    # Tipologie con copertura ruoli + conteggi reali DB
    tipi_attivi_qs = TipoVisitaMedica.objects.filter(is_active=True).prefetch_related("ruoli_operativi")
    tipologie_stats = []
    for t in tipi_attivi_qs:
        ruoli_ids = list(t.ruoli_operativi.values_list("id", flat=True))
        if ruoli_ids:
            legacy_ids_richiesti = set(
                DipendenteRuoloOperativo.objects
                .filter(ruolo_id__in=ruoli_ids)
                .exclude(legacy_anagrafica_id__in=DipendenteAnagraficaAziendale.objects.filter(
                    data_cessazione__isnull=False,
                ).values("legacy_anagrafica_id"))
                .values_list("legacy_anagrafica_id", flat=True)
            )
        else:
            legacy_ids_richiesti = set()
        legacy_ids_coperti = set(
            correnti_qs
            .filter(tipo=t, data_scadenza__gte=oggi)
            .values_list("legacy_anagrafica_id", flat=True)
        )
        mancanti = legacy_ids_richiesti - legacy_ids_coperti
        # Richiesti che non hanno nessuna visita di questo tipo (né valida né scaduta).
        senza_visita = legacy_ids_richiesti - set(
            correnti_qs.filter(tipo=t).values_list("legacy_anagrafica_id", flat=True)
        ) if legacy_ids_richiesti else set()
        tipologie_stats.append({
            "tipo": t,
            "ha_ruoli": bool(ruoli_ids),
            "richiesti": len(legacy_ids_richiesti),
            "coperti": len(legacy_ids_richiesti & legacy_ids_coperti),
            "mancanti": len(mancanti),
            "senza_visita": len(senza_visita),
            "valide_db": _valide_per_tipo.get(t.pk, 0),
            "scadute_db": _scadute_per_tipo.get(t.pk, 0),
        })

    kpi_tipi_attivi = tipi_attivi_qs.count()

    # Sessioni per tipo (latest per dipendente): usate nel pannello dettaglio interattivo
    from collections import defaultdict as _defaultdict
    _all_tipo_ids = [row["tipo"].pk for row in tipologie_stats]
    if _all_tipo_ids:
        _latest_sessions_bulk = list(
            correnti_qs
            .filter(tipo_id__in=_all_tipo_ids)
            .select_related("tipo")
            .order_by("tipo_id", "legacy_anagrafica_id")
        )
        _soglia_avviso = oggi + _timedelta(days=60)
        _sessions_by_tipo: dict = _defaultdict(list)
        for _v in _latest_sessions_bulk:
            _v.dipendente_nome = nomi_map.get(_v.legacy_anagrafica_id, f"#{_v.legacy_anagrafica_id}")
            _v.giorni_a_scadenza = (_v.data_scadenza - oggi).days if _v.data_scadenza else None
            _sessions_by_tipo[_v.tipo_id].append(_v)

        def _session_sort_key(_v):
            if not _v.data_scadenza:
                return (3, "")
            if _v.data_scadenza < oggi:
                return (0, str(_v.data_scadenza))
            if _v.data_scadenza <= _soglia_avviso:
                return (1, str(_v.data_scadenza))
            return (2, str(_v.data_scadenza))

        for row in tipologie_stats:
            sessioni = sorted(_sessions_by_tipo.get(row["tipo"].pk, []), key=_session_sort_key)
            row["sessioni"] = sessioni
            row["n_scadute"] = sum(1 for s in sessioni if s.data_scadenza and s.giorni_a_scadenza is not None and s.giorni_a_scadenza < 0)
            row["n_in_scadenza"] = sum(1 for s in sessioni if s.data_scadenza and s.giorni_a_scadenza is not None and 0 <= s.giorni_a_scadenza <= 60)
            row["n_valide"] = sum(1 for s in sessioni if s.data_scadenza and s.giorni_a_scadenza is not None and s.giorni_a_scadenza > 60)
    else:
        for row in tipologie_stats:
            row["sessioni"] = []
            row["n_scadute"] = 0
            row["n_in_scadenza"] = 0
            row["n_valide"] = 0

    # Stile C: una scheda per tipo di visita (solo conteggi, nessun esito).
    from ..models import VisitaSessione
    from ..models_sorveglianza import RefertoIntakeRiga
    from ..services import sezioni_c
    copertura_visite = sezioni_c.griglia(
        id="fmd-visite", titolo="Copertura per tipologia", icona="i-pill",
        aside="Persone con l'ultima visita del tipo · clic per il dettaglio",
        schede=sezioni_c.schede_visite(tipologie_stats),
        filtri=[("", "Tutti"), ("obbligatoria", "Obbligatorie"), ("facoltativa", "Facoltative")]
        if any(not row["tipo"].obbligatoria for row in tipologie_stats) else [],
        ordini=[("gap", "Prima le meno coperte"), ("az", "A–Z")],
        legenda=[("ok", "in regola"), ("s90", "≤60g"), ("ko", "scaduta"), ("mai", "senza visita (ruolo operativo)")],
        vuoto_titolo="Nessuna visita da mostrare",
        vuoto_testo="Le schede compaiono quando ci sono visite registrate o ruoli operativi collegati ai tipi.",
    )
    kpi_referti = RefertoIntakeRiga.objects.filter(esito=RefertoIntakeRiga.ESITO_DA_RIVEDERE).count()
    kpi_senza_visita = sum(row.get("senza_visita", 0) for row in tipologie_stats)
    ultime_sessioni = list(
        VisitaSessione.objects.annotate(n_visite=Count("visite")).order_by("-data_svolgimento", "-id")[:5]
    )
    aree = sezioni_c.aree_visibili(request, [
        sezioni_c.Area("anagrafica:visite_mediche_sessioni", "Sessioni di visita", "Proposte di rinnovo e giornate", icona="i-calendar"),
        sezioni_c.Area("anagrafica:referti_coda", "Referti da rivedere", "Letture da confermare", icona="i-doc"),
        sezioni_c.Area("anagrafica:referti_registro", "Registro referti", "Tutti i referti acquisiti", icona="i-clipboard"),
        sezioni_c.Area("anagrafica:libretto_sanitario_generale", "Libretto sanitario", "Per persona", icona="i-book"),
        sezioni_c.Area("anagrafica:impostazioni", "Tipi di visita", "Catalogo e periodicità", "tab=visite-mediche", icona="i-gear"),
    ])

    return render(request, "anagrafica/pages/visite_mediche_dashboard.html", {
        "oggi": oggi,
        "copertura_visite": copertura_visite,
        "kpi_referti": kpi_referti,
        "kpi_senza_visita": kpi_senza_visita,
        "ultime_sessioni": ultime_sessioni,
        "aree": aree,
        "soglia_avviso": oggi + _timedelta(days=60),
        "kpi_scadute": kpi_scadute,
        "kpi_in_scad": kpi_in_scad,
        "kpi_totali": kpi_visite_totali,
        "kpi_tipi_attivi": kpi_tipi_attivi,
        "ultime_visite": ultime_visite,
        "scad_o_in_scad": scad_o_in_scad,
        "tipologie_stats": tipologie_stats,
        "can_manage": _helpers._can_edit_visite_mediche(request),
        "can_delete_visite": _helpers._has_canonical_grant(request, PERM_VISITE_DELETE),
        "can_edit_visite": _helpers._can_edit_visite_mediche(request),
        "filtro_scad": filtro_scad,
    })


def _requisiti_tipo_visita(tipo: TipoVisitaMedica) -> dict:
    """Chi è tenuto alla visita ``tipo`` e da dove nasce l'obbligo.

    Ritorna ``{"da_ruoli": set, "da_processi": set, "ha_vincoli": bool}``.
    ``ha_vincoli`` = il tipo ha ruoli operativi o processi MOD.128 COLLEGATI
    in configurazione (anche se nessuna persona li possiede): governa il
    fallback storico e la valutazione di pertinenza. Cessati NON filtrati qui.
    """
    ruolo_ids = list(tipo.ruoli_operativi.values_list("id", flat=True))
    da_ruoli: set[int] = set()
    if ruolo_ids:
        da_ruoli = set(
            DipendenteRuoloOperativo.objects
            .filter(ruolo_id__in=ruolo_ids)
            .values_list("legacy_anagrafica_id", flat=True)
        )
    da_processi: set[int] = set()
    ha_processi = False
    try:
        from ..models_mpq import AbilitazioneProcesso
        ha_processi = tipo.processi_richiedenti.exists()
        if ha_processi:
            da_processi = set(
                AbilitazioneProcesso.objects
                .filter(
                    stato=AbilitazioneProcesso.STATO_ATTIVA,
                    processo__visite_richieste=tipo,
                )
                .exclude(legacy_anagrafica_id=0)
                .values_list("legacy_anagrafica_id", flat=True)
            )
    except Exception:
        logger.warning(
            "Lookup requisiti MOD.128 per tipo visita %s fallito", tipo.pk, exc_info=True,
        )
    return {
        "da_ruoli": da_ruoli,
        "da_processi": da_processi,
        "ha_vincoli": bool(ruolo_ids) or ha_processi,
    }


def _build_candidati_sessione(tipo: TipoVisitaMedica, oggi) -> list[dict]:
    """Dipendenti candidati per una sessione di visita del tipo dato.

    Il tipo è "consono" quando è richiesto dai ruoli operativi del dipendente
    o da un processo MOD.128 a cui è abilitato; se il tipo non ha vincoli
    configurati si propone chi ha quel tipo nello storico (stato calcolato
    sull'ultima visita). Cessati sempre esclusi.

    Candidato = ultima visita del tipo scaduta, in scadenza entro 90 giorni,
    oppure mai effettuata (solo pool ruoli/processi). Un'ultima visita senza
    scadenza (durata 0) è valida per sempre: non viene riproposta.
    """
    soglia = oggi + _timedelta(days=90)
    cessati = _helpers._cessati_legacy_ids()
    req = _requisiti_tipo_visita(tipo)
    da_ruoli, da_processi = req["da_ruoli"], req["da_processi"]

    if req["ha_vincoli"]:
        pool_ids = (da_ruoli | da_processi) - cessati
    else:
        # Tipo non collegato a ruoli/processi: si propone chi ha quel tipo
        # nello storico, non tutta l'azienda.
        pool_ids = set(
            VisitaMedica.objects
            .filter(tipo=tipo)
            .values_list("legacy_anagrafica_id", flat=True)
        ) - cessati

    if not pool_ids:
        return []

    # Ultima visita del tipo per ogni candidato (spareggio: pk più alto).
    ultima_per_id: dict[int, VisitaMedica] = {}
    for v in (
        VisitaMedica.objects
        .filter(tipo=tipo, legacy_anagrafica_id__in=pool_ids)
        .select_related("tipo")
        .order_by("legacy_anagrafica_id", "-data_svolgimento", "-pk")
    ):
        if v.legacy_anagrafica_id not in ultima_per_id:
            ultima_per_id[v.legacy_anagrafica_id] = v

    nomi_map = _helpers._build_nomi_map()

    candidati = []
    for lid in pool_ids:
        ultima = ultima_per_id.get(lid)
        if ultima is None:
            status = "mai_effettuata"
            giorni = None
        elif ultima.data_scadenza is None:
            continue  # valida senza scadenza: non riproporre
        elif ultima.data_scadenza < oggi:
            status = "scaduta"
            giorni = (ultima.data_scadenza - oggi).days
        elif ultima.data_scadenza <= soglia:
            status = "in_scadenza"
            giorni = (ultima.data_scadenza - oggi).days
        else:
            continue  # ancora valida oltre la soglia dei 90 giorni

        if lid in da_ruoli:
            origine = "ruolo"
        elif lid in da_processi:
            origine = "processo"
        else:
            origine = "storico"

        candidati.append({
            "legacy_id": lid,
            "nome": nomi_map.get(lid, f"#{lid}"),
            "ultima_visita": ultima,
            "data_scadenza": ultima.data_scadenza if ultima else None,
            "status": status,
            "giorni_a_scadenza": giorni,
            "origine": origine,
        })

    # Ordine: in_scadenza → scaduta → mai_effettuata; poi alfabetico per nome
    _status_order = {"in_scadenza": 0, "scaduta": 1, "mai_effettuata": 2}
    ordine_map = _helpers._build_ordine_map()
    candidati.sort(key=lambda c: (
        _status_order.get(c["status"], 9),
        ordine_map.get(c["legacy_id"], c["nome"]),
    ))
    return candidati


def _build_candidati_giornata(oggi, tipo_id=None) -> list[dict]:
    """Righe candidate per una "giornata visite" multi-tipo: per ogni tipo di
    visita attivo (o solo ``tipo_id`` se dato) prende i candidati "consoni" da
    ``_build_candidati_sessione`` e li appiattisce in righe ``(persona, tipo)``.
    Chi ha più tipi dovuti compare in più righe (= più visite nel giorno)."""
    if tipo_id:
        tipi = list(TipoVisitaMedica.objects.filter(pk=tipo_id, is_active=True))
    else:
        tipi = list(TipoVisitaMedica.objects.filter(is_active=True).order_by("nome"))

    righe: list[dict] = []
    for tipo in tipi:
        for c in _build_candidati_sessione(tipo, oggi):
            righe.append({
                **c,
                "tipo": tipo,
                "preselect": c["status"] in ("scaduta", "in_scadenza"),
            })
    _status_order = {"in_scadenza": 0, "scaduta": 1, "mai_effettuata": 2}
    ordine_map = _helpers._build_ordine_map()
    righe.sort(key=lambda r: (
        _status_order.get(r["status"], 9),
        ordine_map.get(r["legacy_id"], r["nome"]).casefold(),
        r["tipo"].nome,
    ))
    return righe


# ---------------------------------------------------------------------------
# View: registrazione nuova sessione batch visite mediche
# ---------------------------------------------------------------------------

@login_required
def visite_mediche_nuova_sessione(request):
    """Registrazione batch di visite mediche per un tipo e una data.

    Step 1 (GET / POST step=1): selezione tipo visita, data, medico competente.
    Step 2 (POST step=2): tabella dipendenti candidati con esito per ognuno → salva.
    """
    if not _helpers._can_edit_visite_mediche(request):
        messages.error(request, "Non hai i permessi per registrare le visite mediche.")
        return redirect("anagrafica:visite_mediche_dashboard")

    from django.utils import timezone as _tz

    oggi = _tz.localdate()
    tipi_attivi = list(TipoVisitaMedica.objects.filter(is_active=True).order_by("nome"))

    # ---- POST: salva la giornata (sessione + visite multi-tipo) -----------
    if request.method == "POST":
        data_str = request.POST.get("data_svolgimento", "").strip()
        medico = request.POST.get("medico_competente", "").strip()
        luogo = request.POST.get("luogo", "").strip()
        note_sess = request.POST.get("note", "").strip()

        try:
            data_svolgimento = date.fromisoformat(data_str)
        except (ValueError, TypeError):
            messages.error(request, "Data non valida.")
            return redirect("anagrafica:visite_mediche_nuova_sessione")
        if data_svolgimento > oggi:
            messages.error(request, "La data di svolgimento non può essere nel futuro.")
            return redirect("anagrafica:visite_mediche_nuova_sessione")

        # Righe selezionate: campo sel_<legacy>_<tipo> presente.
        selezioni: list[tuple[int, int]] = []
        for key in request.POST.keys():
            if not key.startswith("sel_"):
                continue
            parts = key.split("_")
            if len(parts) != 3:
                continue
            try:
                selezioni.append((int(parts[1]), int(parts[2])))
            except (ValueError, TypeError):
                continue
        if not selezioni:
            messages.warning(request, "Nessuna visita selezionata.")
            return redirect("anagrafica:visite_mediche_nuova_sessione")

        from ..models import VisitaSessione
        from ..services.visite import (
            dipendenti_esistenti, errore_data_visita, errore_esito_note, famiglia_tipo, visita_doppia,
        )
        # Solo id presenti in anagrafica: le chiavi del POST non sono una fonte attendibile.
        esistenti = dipendenti_esistenti({lid for lid, _ in selezioni})
        sess = VisitaSessione.objects.create(
            data_svolgimento=data_svolgimento, medico_competente=medico,
            luogo=luogo, note=note_sess, created_by=request.user,
        )

        tipi_cache: dict[int, TipoVisitaMedica] = {}
        creati = 0
        doppioni = 0
        errori = []
        registrate: set[tuple[int, str]] = set()  # (persona, famiglia) già salvate in questo invio
        for legacy_id, tipo_id in selezioni:
            tipo = tipi_cache.get(tipo_id)
            if tipo is None:
                tipo = TipoVisitaMedica.objects.filter(pk=tipo_id, is_active=True).first()
                tipi_cache[tipo_id] = tipo
            if tipo is None:
                continue
            etichetta = f"#{legacy_id} {tipo.nome}"
            if legacy_id not in esistenti:
                errori.append(f"{etichetta} (dipendente inesistente)")
                continue
            esito = request.POST.get(f"esito_{legacy_id}_{tipo_id}", VisitaMedica.Esito.IDONEO)
            if esito not in VisitaMedica.Esito.values:
                esito = VisitaMedica.Esito.IDONEO
            prescrizioni = request.POST.get(f"prescrizioni_{legacy_id}_{tipo_id}", "").strip()
            note = request.POST.get(f"note_{legacy_id}_{tipo_id}", "").strip()
            # Stesse regole del form singolo: la giornata non è una scorciatoia.
            if errore_esito_note(esito, note):
                errori.append(f"{etichetta} (con limitazioni servono le note che le descrivono)")
                continue
            errore_data = errore_data_visita(legacy_id, data_svolgimento)
            if errore_data:
                errori.append(f"{etichetta} ({errore_data})")
                continue
            chiave = (legacy_id, famiglia_tipo(tipo))
            if chiave in registrate or visita_doppia(legacy_id, tipo, data_svolgimento):
                doppioni += 1
                continue
            referto_file = request.FILES.get(f"referto_{legacy_id}_{tipo_id}")
            if referto_file:
                from ..services.referti_file import UploadMimeValidationError, valida_referto
                try:
                    valida_referto(referto_file)
                except UploadMimeValidationError:
                    # Referto non ammesso: la visita non si registra senza il suo referto.
                    errori.append(f"{etichetta} (referto non ammesso: solo PDF/PNG/JPEG)")
                    continue
            file_salvati: list = []
            try:
                # Riga per riga: visita e referto insieme, o nessuno dei due.
                with transaction.atomic():
                    visita = VisitaMedica.objects.create(
                        legacy_anagrafica_id=legacy_id, tipo=tipo,
                        data_svolgimento=data_svolgimento, esito=esito,
                        prescrizioni=prescrizioni, note=note, medico_competente=medico,
                        sessione=sess, created_by=request.user, updated_by=request.user,
                    )
                    if referto_file:
                        _helpers._salva_referto_visita(request, visita, referto_file, file_salvati)
                registrate.add(chiave)
                creati += 1
            except IntegrityError:
                _helpers._elimina_file_salvati(file_salvati)
                doppioni += 1
            except Exception:
                _helpers._elimina_file_salvati(file_salvati)
                logger.exception("Errore creazione VisitaMedica giornata legacy=%s tipo=%s", legacy_id, tipo_id)
                errori.append(etichetta)

        if creati == 0:
            sess.delete()  # nessuna visita creata: non lasciare sessioni vuote

        try:
            from core.audit import log_action
            log_action(
                request, "VISITA_MEDICA_BATCH_CREATA", "anagrafica",
                {
                    "sessione_id": sess.pk if creati else None,
                    "data_svolgimento": data_svolgimento.isoformat(),
                    "creati": creati, "doppioni": doppioni, "errori": len(errori),
                },
            )
        except Exception:
            logger.warning("Audit VISITA_MEDICA_BATCH_CREATA fallito", exc_info=True)

        if errori:
            messages.warning(request, f"{creati} visite registrate. Non registrate: {'; '.join(errori)}.")
            if creati == 0:
                return redirect("anagrafica:visite_mediche_nuova_sessione")
        elif creati == 0:
            messages.info(request, "Nessuna visita registrata (tutte già presenti in pari data).")
            return redirect("anagrafica:visite_mediche_nuova_sessione")
        else:
            msg = f"Giornata del {data_svolgimento.strftime('%d-%m-%Y')}: {creati} visite registrate."
            if doppioni:
                msg += f" {doppioni} già presenti in pari data: saltate."
            messages.success(request, msg)
        return redirect("anagrafica:visite_mediche_sessione_detail", sessione_id=sess.pk)

    # ---- GET: pagina Giornata visite (reattiva) --------------------------
    pre_tipo_id = (request.GET.get("tipo") or "").strip()
    tipo_pre = None
    if pre_tipo_id.isdigit():
        tipo_pre = TipoVisitaMedica.objects.filter(pk=int(pre_tipo_id), is_active=True).first()
    righe = (
        _build_candidati_giornata(oggi, tipo_id=(tipo_pre.pk if tipo_pre else None))
        if (tipo_pre or request.GET.get("all")) else []
    )
    medici_precedenti = list(
        VisitaMedica.objects.exclude(medico_competente="")
        .order_by("medico_competente").values_list("medico_competente", flat=True).distinct()[:20]
    )
    return render(request, "anagrafica/pages/visite_mediche_nuova_sessione.html", {
        "tipi_attivi": tipi_attivi,
        "tipo_pre": tipo_pre,
        "righe": righe,
        "n_pre": sum(1 for r in righe if r["preselect"]),
        "oggi": oggi,
        "esiti": VisitaMedica.Esito.choices,
        "esito_default": VisitaMedica.Esito.IDONEO,
        "medici_precedenti": medici_precedenti,
    })


# ---------------------------------------------------------------------------
# API: ricerca live dipendente per aggiunta manuale in sessione
# ---------------------------------------------------------------------------

@login_required
def visite_mediche_api_cerca_dipendente(request):
    """Ricerca live dipendenti per il popup '+Aggiungi dipendente' nella sessione.

    GET ?q=QUERY&exclude=ID1,ID2,...&tipo_id=N
    Ritorna JSON {results: [{legacy_id, nome, pertinente}, ...]}.

    ``pertinente`` = il tipo è richiesto al dipendente da ruoli operativi o
    processi MOD.128; se il tipo non ha vincoli configurati la pertinenza non
    è valutabile e vale sempre ``true``. I cessati non compaiono mai.
    """
    if not _helpers._can_view_visite_mediche(request):
        return JsonResponse({"error": "Forbidden"}, status=403)

    q = request.GET.get("q", "").strip()
    if len(q) < 2:
        return JsonResponse({"results": []})

    exclude_ids: set[int] = set()
    for s in request.GET.get("exclude", "").split(","):
        try:
            exclude_ids.add(int(s.strip()))
        except (ValueError, TypeError):
            pass
    exclude_ids |= _helpers._cessati_legacy_ids()

    pertinenti: set[int] | None = None
    tipo_id_raw = request.GET.get("tipo_id", "").strip()
    if tipo_id_raw:
        try:
            tipo = TipoVisitaMedica.objects.get(pk=int(tipo_id_raw))
        except (TipoVisitaMedica.DoesNotExist, ValueError, TypeError):
            tipo = None
        if tipo is not None:
            req = _requisiti_tipo_visita(tipo)
            if req["ha_vincoli"]:
                pertinenti = req["da_ruoli"] | req["da_processi"]

    qs = (
        AnagraficaDipendente.objects
        .filter(Q(cognome__icontains=q) | Q(nome__icontains=q) | naming.q_persona(q, "nome", "cognome"))
        .exclude(id__in=exclude_ids)
        .order_by("cognome", "nome")[:25]
    )
    results = []
    for d in qs:
        cog = (getattr(d, "cognome", "") or "").strip()
        nom = (getattr(d, "nome", "") or "").strip()
        results.append({
            "legacy_id": d.id,
            "nome": f"{cog} {nom}".strip() or f"#{d.id}",
            "pertinente": True if pertinenti is None else (d.id in pertinenti),
        })
    return JsonResponse({"results": results})


@login_required
def visite_mediche_candidati(request):
    """Partial HTMX: righe candidate della giornata per il tipo selezionato
    (o tutti i tipi se ``tipo`` assente). Popola la tabella senza reload."""
    if not _helpers._can_view_visite_mediche(request):
        return HttpResponse(status=403)
    from django.utils import timezone as _tz
    raw = (request.GET.get("tipo") or "").strip()
    tipo_id = int(raw) if raw.isdigit() else None
    righe = _build_candidati_giornata(_tz.localdate(), tipo_id=tipo_id)
    return render(request, "anagrafica/partials/_visite_candidati.html", {
        "righe": righe,
        "esiti": VisitaMedica.Esito.choices,
        "esito_default": VisitaMedica.Esito.IDONEO,
        "n_pre": sum(1 for r in righe if r["preselect"]),
    })


# ---------------------------------------------------------------------------
# Sessioni visite (VisitaSessione): hub proposte, dettaglio, aggiungi, elimina
# ---------------------------------------------------------------------------

@login_required
def visite_mediche_sessioni(request):
    """Hub: proposte di rinnovo per tipo (da rinnovare = ultima visita corrente
    scaduta/in scadenza) + elenco delle giornate salvate."""
    if not _helpers._can_view_visite_mediche(request):
        messages.error(request, "Non hai i permessi per le visite mediche.")
        return redirect("anagrafica:index")
    from django.utils import timezone as _tz
    from ..models import VisitaSessione
    oggi = _tz.localdate()
    soglia = oggi + _timedelta(days=60)
    correnti = VisitaMedica.objects.filter(id__in=ultime_visite_correnti_ids())
    proposte = []
    for t in TipoVisitaMedica.objects.filter(is_active=True).order_by("nome"):
        n_scad = correnti.filter(tipo=t, data_scadenza__lt=oggi).count()
        n_insc = correnti.filter(tipo=t, data_scadenza__gte=oggi, data_scadenza__lte=soglia).count()
        if n_scad or n_insc:
            proposte.append({"tipo": t, "n_scadute": n_scad, "n_in_scadenza": n_insc})
    sessioni = list(
        VisitaSessione.objects.annotate(n_visite=Count("visite")).order_by("-data_svolgimento", "-id")[:50]
    )
    return render(request, "anagrafica/pages/visite_mediche_sessioni.html", {
        "proposte": proposte, "sessioni": sessioni, "oggi": oggi,
        "tot_da_rinnovare": sum(p["n_scadute"] + p["n_in_scadenza"] for p in proposte),
        "can_edit_visite": _helpers._can_edit_visite_mediche(request),
    })


@login_required
def visite_mediche_sessione_detail(request, sessione_id: int):
    if not _helpers._can_view_visite_mediche(request):
        messages.error(request, "Non hai i permessi per le visite mediche.")
        return redirect("anagrafica:index")
    from ..models import VisitaSessione
    sess = get_object_or_404(VisitaSessione, pk=sessione_id)
    nomi = _helpers._build_nomi_map()
    visite = list(sess.visite.select_related("tipo").order_by("tipo__nome"))
    for v in visite:
        v.dipendente_nome = nomi.get(v.legacy_anagrafica_id, f"#{v.legacy_anagrafica_id}")
    _, is_admin = _helpers._ensure_admin(request)
    return render(request, "anagrafica/pages/visite_mediche_sessione_detail.html", {
        "sess": sess, "visite": visite, "is_admin": is_admin,
        "can_edit_visite": _helpers._can_edit_visite_mediche(request),
        "tipi_attivi": list(TipoVisitaMedica.objects.filter(is_active=True).order_by("nome")),
        "esiti": VisitaMedica.Esito.choices, "esito_default": VisitaMedica.Esito.IDONEO,
    })


@login_required
@require_POST
def visite_mediche_sessione_partecipante_add(request, sessione_id: int):
    from ..services.visite import dipendenti_esistenti, errore_data_visita, errore_esito_note, visita_doppia

    torna = redirect("anagrafica:visite_mediche_sessione_detail", sessione_id=sessione_id)
    if not _helpers._can_edit_visite_mediche(request):
        messages.error(request, "Permessi insufficienti.")
        return torna
    from ..models import VisitaSessione
    sess = get_object_or_404(VisitaSessione, pk=sessione_id)
    try:
        legacy_id = int(request.POST.get("legacy_id") or 0)
        tipo = TipoVisitaMedica.objects.get(pk=request.POST.get("tipo_id"), is_active=True)
    except (ValueError, TypeError, TipoVisitaMedica.DoesNotExist):
        messages.error(request, "Dipendente o tipo non validi.")
        return torna
    if legacy_id <= 0 or not dipendenti_esistenti([legacy_id]):
        messages.error(request, "Dipendente non trovato: scegli una persona dalla ricerca.")
        return torna
    esito = request.POST.get("esito", VisitaMedica.Esito.IDONEO)
    if esito not in VisitaMedica.Esito.values:
        esito = VisitaMedica.Esito.IDONEO
    note = (request.POST.get("note") or "").strip()
    errore = errore_esito_note(esito, note) or errore_data_visita(legacy_id, sess.data_svolgimento)
    if errore:
        messages.error(request, errore)
        return torna
    if visita_doppia(legacy_id, tipo, sess.data_svolgimento):
        messages.warning(request, "Visita già presente in pari data (stessa famiglia): non aggiunta.")
        return torna
    try:
        with transaction.atomic():
            visita = VisitaMedica.objects.create(
                legacy_anagrafica_id=legacy_id, tipo=tipo, data_svolgimento=sess.data_svolgimento,
                esito=esito, note=note, medico_competente=sess.medico_competente, sessione=sess,
                created_by=request.user, updated_by=request.user,
            )
    except IntegrityError:
        messages.warning(request, "Visita già presente in pari data: non aggiunta.")
        return torna
    try:
        from core.audit import log_action
        log_action(
            request, "VISITA_MEDICA_CREATA", "anagrafica",
            {"visita_id": visita.pk, "dipendente_id": legacy_id, "tipo_visita": tipo.nome,
             "data_svolgimento": sess.data_svolgimento.isoformat(), "esito": esito,
             "sessione_id": sess.pk},
            oggetto=visita,
        )
    except Exception:
        logger.warning("Audit VISITA_MEDICA_CREATA (giornata) fallito", exc_info=True)
    messages.success(request, "Partecipante aggiunto alla giornata.")
    return torna


@login_required
@require_POST
def visite_mediche_sessione_delete(request, sessione_id: int):
    if not _helpers._can_view_visite_mediche(request):
        messages.error(request, "Permessi insufficienti.")
        return redirect("anagrafica:visite_mediche_sessioni")
    _, is_admin = _helpers._ensure_admin(request)
    if not is_admin:
        messages.error(request, "Solo gli amministratori possono eliminare una giornata.")
        return redirect("anagrafica:visite_mediche_sessione_detail", sessione_id=sessione_id)
    from ..models import VisitaSessione
    sess = get_object_or_404(VisitaSessione, pk=sessione_id)
    dettaglio = {
        "sessione_id": sess.pk, "data_svolgimento": sess.data_svolgimento.isoformat(),
        "medico_competente": sess.medico_competente,
        "visite_conservate_ids": list(sess.visite.values_list("pk", flat=True)),
    }
    sess.delete()  # SET_NULL: le visite restano
    try:
        from core.audit import log_action
        log_action(request, "VISITA_SESSIONE_ELIMINATA", "anagrafica", dettaglio,
                   oggetto_tipo="anagrafica.visitasessione", oggetto_id=str(dettaglio["sessione_id"]))
    except Exception:
        logger.warning("Audit VISITA_SESSIONE_ELIMINATA fallito", exc_info=True)
    messages.success(request, "Giornata eliminata (le visite registrate sono conservate).")
    return redirect("anagrafica:visite_mediche_sessioni")


# ---------------------------------------------------------------------------
# Export Excel: copertura per tipologia e visite in scadenza
# ---------------------------------------------------------------------------

def _audit_export_visite(request, export: str, righe: int) -> None:
    """Un export di dati sanitari esce dal portale: chi, cosa, con quali filtri."""
    try:
        from core.audit import log_action
        log_action(request, "VISITE_MEDICHE_EXPORT", "anagrafica", {
            "export": export, "righe": max(0, int(righe)),
            "filtri": {k: request.GET.getlist(k) for k in request.GET},
        })
    except Exception:
        logger.warning("Audit export visite %s fallito", export, exc_info=True)


@login_required
def visite_mediche_export_scadenze(request):
    """Scarica le visite scadute/in scadenza come file .xlsx.

    Accetta ?scad=mese_corrente | prossimo_mese (default: tutti ≤60g).
    """
    if not _helpers._can_view_visite_mediche(request):
        return HttpResponse(status=403)

    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment
    except ImportError:
        return HttpResponse("openpyxl non installato.", status=500)

    from core.excel_export import append_row

    import calendar as _cal
    from django.utils import timezone as _tz

    oggi = _tz.localdate()
    filtro = request.GET.get("scad", "tutti").strip()
    correnti_ids = ultime_visite_correnti_ids()

    if filtro == "mese_corrente":
        _, ld = _cal.monthrange(oggi.year, oggi.month)
        qs = VisitaMedica.objects.filter(
            id__in=correnti_ids,
            data_scadenza__isnull=False,
            data_scadenza__range=[oggi.replace(day=1), oggi.replace(day=ld)],
        )
        label = f"mese_corrente_{oggi.strftime('%Y%m')}"
    elif filtro == "prossimo_mese":
        pm_y = oggi.year + 1 if oggi.month == 12 else oggi.year
        pm_m = 1 if oggi.month == 12 else oggi.month + 1
        _, ld = _cal.monthrange(pm_y, pm_m)
        qs = VisitaMedica.objects.filter(
            id__in=correnti_ids,
            data_scadenza__isnull=False,
            data_scadenza__range=[date(pm_y, pm_m, 1), date(pm_y, pm_m, ld)],
        )
        label = f"prossimo_mese_{pm_y}{pm_m:02d}"
    else:
        qs = VisitaMedica.objects.filter(
            id__in=correnti_ids,
            data_scadenza__isnull=False, data_scadenza__lte=oggi + _timedelta(days=60)
        )
        label = "scadenze_60gg"

    qs = qs.select_related("tipo").order_by("data_scadenza")
    nomi_map = _helpers._build_nomi_map()

    # CF lookup
    cf_map: dict[int, str] = dict(
        DipendenteAnagraficaCivile.objects
        .exclude(codice_fiscale="")
        .values_list("legacy_anagrafica_id", "codice_fiscale")
    )

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Scadenze"

    # Le prescrizioni sono dato sanitario: escono solo a chi apre anche i referti.
    con_prescrizioni = _helpers._can_view_referti(request)
    header = ["Dipendente", "Codice Fiscale", "Tipo visita", "Data svolgimento",
              "Data scadenza", "Giorni a scadenza", "Esito"]
    if con_prescrizioni:
        header.append("Prescrizioni")
    append_row(ws, header)
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="E2E8F0")

    for v in qs:
        nome = nomi_map.get(v.legacy_anagrafica_id, f"#{v.legacy_anagrafica_id}")
        cf = cf_map.get(v.legacy_anagrafica_id, "")
        giorni = (v.data_scadenza - oggi).days if v.data_scadenza else ""
        riga = [
            nome, cf, v.tipo.nome,
            v.data_svolgimento.strftime("%d-%m-%Y") if v.data_svolgimento else "",
            v.data_scadenza.strftime("%d-%m-%Y") if v.data_scadenza else "",
            giorni,
            v.get_esito_display(),
        ]
        if con_prescrizioni:
            riga.append(v.prescrizioni or "")
        append_row(ws, riga)

    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = max(
            len(str(c.value or "")) for c in col
        ) + 4

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = f'attachment; filename="visite_scadenze_{label}.xlsx"'
    _audit_export_visite(request, "scadenze", ws.max_row - 1)
    wb.save(response)
    return response


@login_required
def visite_mediche_export_copertura(request):
    """Scarica la tabella copertura per tipologia come .xlsx."""
    if not _helpers._can_view_visite_mediche(request):
        return HttpResponse(status=403)

    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill
    except ImportError:
        return HttpResponse("openpyxl non installato.", status=500)

    from core.excel_export import append_row

    from django.utils import timezone as _tz

    oggi = _tz.localdate()
    correnti_qs = VisitaMedica.objects.filter(id__in=ultime_visite_correnti_ids())

    _valide_per_tipo = {
        row["tipo_id"]: row["n"]
        for row in correnti_qs
        .filter(data_scadenza__gte=oggi)
        .order_by()
        .values("tipo_id")
        .annotate(n=Count("legacy_anagrafica_id", distinct=True))
    }
    _scadute_per_tipo = {
        row["tipo_id"]: row["n"]
        for row in correnti_qs
        .filter(data_scadenza__lt=oggi)
        .order_by()
        .values("tipo_id")
        .annotate(n=Count("legacy_anagrafica_id", distinct=True))
    }

    tipi = TipoVisitaMedica.objects.filter(is_active=True).prefetch_related("ruoli_operativi")

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Copertura tipologie"

    header = ["Tipologia", "Periodicità (mesi)", "Obbligatoria",
              "Ruoli collegati", "Richiesti (ruoli)", "Coperti (ruoli)", "Mancanti (ruoli)",
              "Valide (DB)", "Scadute (DB)"]
    append_row(ws, header)
    for cell in ws[1]:
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="E2E8F0")

    for t in tipi:
        ruoli_ids = list(t.ruoli_operativi.values_list("id", flat=True))
        if ruoli_ids:
            legacy_ids_richiesti = set(
                DipendenteRuoloOperativo.objects
                .filter(ruolo_id__in=ruoli_ids)
                .exclude(legacy_anagrafica_id__in=DipendenteAnagraficaAziendale.objects.filter(
                    data_cessazione__isnull=False,
                ).values("legacy_anagrafica_id"))
                .values_list("legacy_anagrafica_id", flat=True)
            )
        else:
            legacy_ids_richiesti = set()
        legacy_ids_coperti = set(
            correnti_qs
            .filter(tipo=t, data_scadenza__gte=oggi)
            .values_list("legacy_anagrafica_id", flat=True)
        )
        mancanti = legacy_ids_richiesti - legacy_ids_coperti
        ruoli_nomi = ", ".join(t.ruoli_operativi.values_list("nome", flat=True)) or "—"

        append_row(ws, [
            t.nome, t.durata_mesi, "Sì" if t.obbligatoria else "No",
            ruoli_nomi,
            len(legacy_ids_richiesti),
            len(legacy_ids_richiesti & legacy_ids_coperti),
            len(mancanti),
            _valide_per_tipo.get(t.pk, 0),
            _scadute_per_tipo.get(t.pk, 0),
        ])

    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = max(
            len(str(c.value or "")) for c in col
        ) + 4

    response = HttpResponse(
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    response["Content-Disposition"] = 'attachment; filename="visite_copertura_tipologie.xlsx"'
    _audit_export_visite(request, "copertura", ws.max_row - 1)
    wb.save(response)
    return response


@login_required
def sicurezza_hub(request):
    """Cruscotto "Sicurezza & Idoneità": numeri chiave e collegamenti a tutte le
    sezioni correlate (fattori, esposizioni, mansioni di rischio, conformità,
    catalogo DPI), così le pagine non risultano isolate. Le metriche di idoneità
    (aggregate, non nominative) sono mostrate solo con permesso HR.
    """
    if not _helpers._can_view_formazione(request):
        messages.error(request, "Non hai i permessi per il cruscotto sicurezza.")
        return redirect("anagrafica:index")
    can_hr = _helpers._check_hr_permission(request)

    # Il catalogo Mansione è il catalogo delle mansioni di rischio (spec
    # Mansionario 15/10/2026): si contano le voci attive e quelle ancora senza
    # profilo (né DPI né visite), da completare.
    n_mansioni_rischio = Mansione.objects.filter(is_active=True).count()
    n_mansioni = (
        Mansione.objects.filter(is_active=True, dpi_richiesti__isnull=True, visite_richieste__isnull=True)
        .distinct().count()
    )

    idoneita_kpi = None
    conformita_kpi = None
    stati = None
    if can_hr:
        dip_rows = [r for r in fetch_anagrafica_rows(deduplicate=True) if r.get("attivo")]
        dip_map = {int(r["id"]): r for r in dip_rows if r.get("id")}
        mansioni_per_legacy = {
            lid: str(d.get("mansione") or "").strip()
            for lid, d in dip_map.items() if str(d.get("mansione") or "").strip()
        }
        stati = conformita_service.stato_conformita_batch(
            list(dip_map), mansioni_per_legacy=mansioni_per_legacy
        )
        c = {"ok": 0, "warn": 0, "ko": 0, "na": 0}
        conf = {"ok": 0, "warn": 0, "ko": 0, "na": 0}
        for s in stati.values():
            e = s.get("idoneita", {}).get("esito", "na")
            c[e] = c.get(e, 0) + 1
            k = s.get("complessivo", "na")
            conf[k] = conf.get(k, 0) + 1
        idoneita_kpi = {
            "idonei": c["ok"], "riserve": c["warn"], "non_idonei": c["ko"],
            "valutati": c["ok"] + c["warn"] + c["ko"],
        }
        valutati = conf["ok"] + conf["warn"] + conf["ko"]
        conformita_kpi = {
            "in_regola": conf["ok"], "in_scadenza": conf["warn"], "non_conformi": conf["ko"],
            "valutati": valutati, "perc": round(conf["ok"] * 100 / valutati) if valutati else 0,
        }

    # Stile C: una scheda per mansione di rischio (gruppo omogeneo del DVR).
    from ..services import organigramma_rischio, sezioni_c
    try:
        gruppi = organigramma_rischio.costruisci(can_view_visite=_helpers._can_view_visite_mediche(request))
    except Exception:
        logger.warning("Cruscotto sicurezza: mansioni di rischio non disponibili", exc_info=True)
        gruppi = []
    livelli_scelte = [(k, v.split(" (")[0]) for k, v in Mansione.LIVELLO_RISCHIO_CHOICES]
    presenti = {g.mansione_rischio.livello_rischio for g in gruppi}
    copertura_mansioni = sezioni_c.griglia(
        id="fmd-mansioni-rischio", titolo="Conformità per mansione di rischio", icona="i-alert-tri",
        aside=("Persone del gruppo in regola con tutti gli obblighi · clic per i requisiti" if can_hr
               else "Persone e protocollo di ogni gruppo omogeneo · clic per i requisiti"),
        schede=sezioni_c.schede_mansioni_rischio(gruppi, stati),
        filtri=[("", "Tutte")] + [(k, f"Rischio {v.lower()}") for k, v in livelli_scelte[::-1] if k in presenti]
        + ([("nd", "Senza livello")] if "" in presenti else []),
        etichetta_filtri="Filtra per livello di rischio",
        ordini=[("gap", "Prima le meno conformi" if can_hr else "Ordine DVR"), ("az", "A–Z")],
        legenda=[("ok", "in regola"), ("s30", "obblighi in scadenza"), ("ko", "non conforme"), ("mai", "da completare")] if can_hr else [],
        vuoto_titolo="Nessuna mansione di rischio attiva",
        vuoto_testo="Si definiscono in Mansioni di rischio, dai gruppi omogenei del DVR.",
    )

    cambi_aperti = []
    if can_hr or _helpers._is_anagrafica_admin(request):
        from ..models import AdempimentoCambioMansione
        aperti = list(
            AdempimentoCambioMansione.objects.filter(stato=AdempimentoCambioMansione.STATO_APERTO, attivo=True)
            .order_by("entro_il", "legacy_anagrafica_id")
        )
        per_persona: dict[int, dict] = {}
        oggi = django_timezone.localdate()
        for a in aperti:
            v = per_persona.setdefault(a.legacy_anagrafica_id, {"legacy_id": a.legacy_anagrafica_id, "aperti": 0,
                                                                "ritardo": 0, "entro": a.entro_il, "tipi": []})
            v["aperti"] += 1
            v["ritardo"] += 1 if (a.entro_il and a.entro_il < oggi) else 0
            if a.get_tipo_display() not in v["tipi"]:
                v["tipi"].append(a.get_tipo_display())
        if per_persona:
            nomi = _helpers._build_nomi_map()
            for v in per_persona.values():
                v["nome"] = nomi.get(v["legacy_id"], f"#{v['legacy_id']}")
        cambi_aperti = sorted(per_persona.values(), key=lambda v: (-v["ritardo"], v["entro"] or oggi, v["nome"]))

    aree = sezioni_c.aree_visibili(request, [
        sezioni_c.Area("anagrafica:mansioni_list", "Mansioni di rischio", "Gruppi omogenei del DVR e requisiti", icona="i-alert-tri"),
        sezioni_c.Area("anagrafica:organigramma_mansioni_rischio", "Organigramma rischi", "Chi è esposto, per gruppo", icona="i-users"),
        sezioni_c.Area("anagrafica:conformita_report", "Conformità / Idoneità", "Semaforo e idoneità per dipendente", icona="i-check"),
        sezioni_c.Area("anagrafica:cambi_mansione", "Cambi mansione", "Adempimenti del piano di adeguamento", icona="i-refresh"),
        sezioni_c.Area("anagrafica:scadenzario", "Scadenzario HR", "Qualifiche, visite, formazione, contratti", icona="i-calendar"),
        sezioni_c.Area("anagrafica:visite_mediche_dashboard", "Visite mediche", "Sorveglianza sanitaria", icona="i-pill"),
        sezioni_c.Area("anagrafica:fattori_rischio_list", "Fattori di rischio", "Catalogo", icona="i-clipboard"),
        sezioni_c.Area("anagrafica:esposizioni_rischio_list", "Esposizioni", "Chi è esposto a cosa", icona="i-clipboard"),
        sezioni_c.Area("anagrafica:matrice_competenze", "Matrice competenze", "Dipendenti × abilitazioni per audit ISO", icona="i-grid"),
        sezioni_c.Area("anagrafica:qualifiche_list", "Qualifiche di sicurezza", "Carrellisti, antincendio, BLSD…", "categoria=SICUREZZA", icona="i-cap"),
        sezioni_c.Area("dpi:impostazioni", "Catalogo DPI", "Categorie, tipi, modelli, taglie", icona="i-shield"),
        sezioni_c.Area("anagrafica:formazione_dashboard", "Formazione", "Piani, corsi, sessioni, scadenze", icona="i-book"),
    ])

    return render(request, "anagrafica/pages/sicurezza_hub.html", {
        "can_hr": can_hr,
        "n_mansioni": n_mansioni,
        "n_mansioni_rischio": n_mansioni_rischio,
        "idoneita_kpi": idoneita_kpi,
        "conformita_kpi": conformita_kpi,
        "copertura_mansioni": copertura_mansioni,
        "cambi_aperti": cambi_aperti,
        "n_cambi_aperti": sum(v["aperti"] for v in cambi_aperti),
        "aree": aree,
    })


@login_required
def sicurezza_ricerca(request):
    """Ricerca dell'area Sicurezza & Idoneità: mansioni di rischio, dipendenti
    (idoneità), qualifiche di sicurezza e fattori di rischio. Speculare alla
    ricerca globale formazione, ma con le categorie pertinenti alla safety.
    Gated dallo stesso permesso del cruscotto sicurezza.
    """
    if not _helpers._can_view_formazione(request):
        messages.error(request, "Non hai i permessi per il cruscotto sicurezza.")
        return redirect("anagrafica:index")

    from ..models_rischi import FattoreRischio

    q = (request.GET.get("q") or "").strip()
    risultati: dict[str, list] = {
        "mansioni": [], "dipendenti": [], "qualifiche": [], "fattori": [],
    }
    totale = 0
    if q:
        ql = q.lower()

        from django.db.models import Count as _Count
        risultati["mansioni"] = list(
            Mansione.objects.filter(is_active=True)
            .filter(Q(nome__icontains=q) | Q(descrizione__icontains=q))
            .annotate(n_esposizioni=_Count("esposizioni_rischio", distinct=True))
            .order_by("nome")[:25]
        )
        risultati["qualifiche"] = list(
            TipoQualifica.objects.filter(categoria=TipoQualifica.CAT_SICUREZZA)
            .filter(Q(nome__icontains=q) | Q(descrizione__icontains=q))
            .annotate(n_assegnazioni=_Count("assegnazioni", distinct=True))
            .order_by("nome")[:25]
        )
        risultati["fattori"] = list(
            FattoreRischio.objects.filter(
                Q(nome__icontains=q) | Q(codice__icontains=q) | Q(descrizione__icontains=q)
            ).annotate(n_esposizioni=_Count("esposizioni", distinct=True))
            .order_by("nome")[:25]
        )

        nomi = _helpers._build_nomi_map()
        dip_match = [
            {"legacy_id": lid, "nome": nome}
            for lid, nome in nomi.items() if ql in nome.lower()
        ]
        _ordine = _helpers._build_ordine_map()
        dip_match.sort(key=lambda d: _ordine.get(d["legacy_id"], d["nome"]).casefold())
        risultati["dipendenti"] = dip_match[:25]

        totale = sum(len(v) for v in risultati.values())

    # Ricerca live: su richiesta HTMX rende solo il frammento dei risultati;
    # con ?suggest=1 (casella nella dashboard) rende la tendina compatta.
    if request.headers.get("HX-Request"):
        template = (
            "anagrafica/partials/_safety_search_suggest.html"
            if request.GET.get("suggest")
            else "anagrafica/partials/_safety_search_results.html"
        )
    else:
        template = "anagrafica/pages/sicurezza_ricerca.html"
    return render(request, template, {
        "q": q,
        "risultati": risultati,
        "totale": totale,
    })


@login_required
def sicurezza_wizard(request):
    """Configurazione guidata della "mansione di rischio": passi in ordine, con
    stato (fatto/da fare) calcolato dai dati reali e CTA verso ogni sezione.
    Rende esplicito il flusso e collega le sezioni tra loro."""
    if not _helpers._can_view_formazione(request):
        messages.error(request, "Non hai i permessi per la guida sicurezza.")
        return redirect("anagrafica:index")

    n_mansioni_rischio = (
        Mansione.objects.filter(is_active=True)
        .filter(Q(dpi_richiesti__isnull=False) | Q(visite_richieste__isnull=False)
                | ~Q(livello_rischio=""))
        .distinct().count()
    )
    try:
        from dpi.models import CategoriaDPI
        n_dpi = CategoriaDPI.objects.filter(is_active=True).count()
    except Exception:
        n_dpi = 0
    n_visite = TipoVisitaMedica.objects.filter(is_active=True).count()

    steps = [
        {
            "n": 1, "titolo": "Cataloghi di base",
            "desc": "Verifica che esistano le categorie DPI e le tipologie di visita medica da assegnare alle mansioni.",
            "stato": "ok" if (n_dpi or n_visite) else "todo",
            "info": f"{n_dpi} categorie DPI · {n_visite} tipi visita",
            "url": reverse("dpi:impostazioni"), "cta": "Catalogo DPI",
            "url2": reverse("anagrafica:impostazioni") + "?tab=visite", "cta2": "Tipi visita",
        },
        {
            "n": 2, "titolo": "Requisiti delle mansioni",
            "desc": "Su ogni mansione imposta il livello di rischio e i requisiti (DPI, visite, formazione). Il rischio è dedotto dalla mansione e dai DPI associati.",
            "stato": "ok" if n_mansioni_rischio else "todo",
            "info": f"{n_mansioni_rischio} mansioni di rischio configurate",
            "url": reverse("anagrafica:mansioni_list"), "cta": "Mansioni di rischio",
        },
        {
            "n": 3, "titolo": "Verifica idoneità",
            "desc": "Controlla il semaforo di idoneità di ogni dipendente: requisiti mancanti (avviso) o scaduti (non idoneo). Vedi anche la matrice competenze.",
            "stato": "info",
            "info": "Report trasversale su tutto il personale",
            "url": reverse("anagrafica:conformita_report"), "cta": "Apri conformità",
        },
    ]
    return render(request, "anagrafica/pages/sicurezza_wizard.html", {"steps": steps})


@login_required
def matrice_competenze(request):
    """Matrice **dipendenti × competenze/abilitazioni** (qualifiche) per audit ISO 45001.

    Celle: valido / in scadenza (≤60gg) / scaduto / mancante. Colonne = i
    ``TipoQualifica`` con almeno un'assegnazione (competenze realmente in uso,
    incl. quelle importate dall'ASR). Filtro reparto + export CSV.
    Accesso: ``_check_hr_permission`` (vista trasversale sul personale).
    """
    if not _helpers._check_hr_permission(request):
        messages.error(request, "Non hai i permessi per la matrice competenze.")
        return redirect("anagrafica:index")

    from datetime import timedelta
    from django.utils import timezone
    ensure_anagrafica_schema()
    filtro_reparto = (request.GET.get("reparto") or "").strip()
    export_csv = request.GET.get("format") == "csv"
    valid_cats = {c for c, _ in TipoQualifica.CATEGORIA_CHOICES}
    cat_filter = (request.GET.get("categoria") or "").strip().upper()
    if cat_filter not in valid_cats:
        cat_filter = ""
    oggi = timezone.localdate()
    soglia = oggi + timedelta(days=60)

    dip_rows = [r for r in fetch_anagrafica_rows(deduplicate=True) if r.get("attivo")]
    dip_map = {int(r["id"]): r for r in dip_rows if r.get("id")}
    legacy_ids = list(dip_map.keys())

    # Colonne = TipoQualifica con almeno un'assegnazione; tab per categoria.
    cat_labels = dict(TipoQualifica.CATEGORIA_CHOICES)
    tipi_all = list(
        TipoQualifica.objects.annotate(_n=Count("assegnazioni"))
        .filter(_n__gt=0).order_by("categoria", "nome")
    )
    tabs = [("", "Tutte", len(tipi_all))]
    for cat_code, cat_lbl in TipoQualifica.CATEGORIA_CHOICES:
        n = sum(1 for t in tipi_all if t.categoria == cat_code)
        if n:
            tabs.append((cat_code, cat_lbl, n))
    tipi = [t for t in tipi_all if not cat_filter or t.categoria == cat_filter]
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

    righe: list[dict] = []
    for lid, dip in dip_map.items():
        reparto = str(dip.get("reparto") or "").strip()
        if filtro_reparto and reparto.casefold() != filtro_reparto.casefold():
            continue
        celle = []
        for t in tipi:
            q = q_map.get((lid, t.id))
            celle.append({"stato": _stato(q), "data": q.data_scadenza if q else None})
        righe.append({
            "legacy_id": lid,
            "cognome": str(dip.get("cognome") or f"ID {lid}").strip(),
            "nome": str(dip.get("nome") or "").strip(),
            "reparto": reparto,
            "celle": celle,
        })
    righe.sort(key=lambda r: (r["cognome"].casefold(), r["nome"].casefold()))
    reparti = sorted({r["reparto"] for r in righe if r["reparto"]})

    if export_csv:
        _LAB = {"valido": "OK", "in_scadenza": "In scadenza", "scaduto": "SCADUTO", "mancante": "—"}
        resp = HttpResponse(content_type=CSV_CONTENT_TYPE)
        resp["Content-Disposition"] = 'attachment; filename="matrice_competenze.csv"'
        resp.write(BOM)  # una volta sola: Excel riconosce l'UTF-8
        writer = safe_csv_writer(resp, delimiter=";")
        writer.writerow(["Dipendente", "Reparto"] + [t.nome for t in tipi])
        for r in righe:
            cells = []
            for c in r["celle"]:
                lab = _LAB.get(c["stato"], c["stato"])
                if c["data"]:
                    lab = f"{lab} {c['data']:%d/%m/%Y}"
                cells.append(lab)
            writer.writerow([naming.nome_completo(r["nome"], r["cognome"]), r["reparto"]] + cells)
        return resp

    return render(request, "anagrafica/pages/matrice_competenze.html", {
        "tipi": tipi,
        "righe": righe,
        "reparti": reparti,
        "filtro_reparto": filtro_reparto,
        "totale": len(righe),
        "tabs": tabs,
        "active_categoria": cat_filter,
        "active_categoria_label": cat_labels.get(cat_filter, ""),
    })


@login_required
def conformita_report(request):
    """Elenco conformità di tutti i dipendenti attivi (semaforo per dominio).

    Accesso: ``_check_hr_permission`` (vista trasversale su tutto il personale).
    Filtri reparto/esito complessivo, ordinamento peggiori-prima, export CSV.
    Performance: un'unica chiamata batch (numero di query costante).
    """
    if not _helpers._check_hr_permission(request):
        messages.error(request, "Non hai i permessi per il report conformità.")
        return redirect("anagrafica:index")

    ensure_anagrafica_schema()
    can_view_visite = _helpers._can_view_visite_mediche(request)

    filtro_reparto = (request.GET.get("reparto") or "").strip()
    filtro_esito = (request.GET.get("esito") or "").strip()
    filtro_idoneita = (request.GET.get("idoneita") or "").strip()
    filtro_mansione = (request.GET.get("mansione") or "").strip()
    export_csv = request.GET.get("format") == "csv"

    dip_rows = [r for r in fetch_anagrafica_rows(deduplicate=True) if r.get("attivo")]
    dip_map = {int(r["id"]): r for r in dip_rows if r.get("id")}
    legacy_ids = list(dip_map.keys())

    # Mappa nome mansione → id (per collegare ogni riga alla sua pagina Requisiti).
    mansioni_map = {
        m.nome.casefold(): m.id
        for m in Mansione.objects.filter(is_active=True).only("id", "nome")
    }

    mansioni_per_legacy = {
        lid: str(dip.get("mansione") or "").strip()
        for lid, dip in dip_map.items()
        if str(dip.get("mansione") or "").strip()
    }

    stati = conformita_service.stato_conformita_batch(
        legacy_ids,
        include_visite_dettaglio=can_view_visite,
        mansioni_per_legacy=mansioni_per_legacy,
    )

    _ORDINE_ESITO = {
        conformita_service.ESITO_KO: 0,
        conformita_service.ESITO_WARN: 1,
        conformita_service.ESITO_OK: 2,
        conformita_service.ESITO_NA: 3,
    }
    na = {"esito": conformita_service.ESITO_NA, "dettagli": []}

    righe: list[dict] = []
    for legacy_id, dip in dip_map.items():
        reparto = str(dip.get("reparto") or "").strip()
        if filtro_reparto and reparto.casefold() != filtro_reparto.casefold():
            continue
        mansione_nome = str(dip.get("mansione") or "").strip()
        if filtro_mansione and mansione_nome.casefold() != filtro_mansione.casefold():
            continue
        stato = stati.get(legacy_id, {"complessivo": conformita_service.ESITO_NA})
        complessivo = stato.get("complessivo", conformita_service.ESITO_NA)
        if filtro_esito and complessivo != filtro_esito:
            continue
        idoneita = stato.get("idoneita", {"esito": conformita_service.ESITO_NA})
        if filtro_idoneita and idoneita.get("esito") != filtro_idoneita:
            continue
        righe.append({
            "legacy_id": legacy_id,
            "mansione_id": mansioni_map.get(mansione_nome.casefold()),
            "cognome": str(dip.get("cognome") or f"ID {legacy_id}").strip(),
            "nome": str(dip.get("nome") or "").strip(),
            "reparto": reparto,
            "mansione": str(dip.get("mansione") or "").strip(),
            "complessivo": complessivo,
            "idoneita": idoneita,
            "formazione": stato.get("formazione", na),
            "visite": stato.get("visite", na),
            "qualifiche": stato.get("qualifiche", na),
            "dpi": stato.get("dpi", na),
        })

    righe.sort(key=lambda r: (
        _ORDINE_ESITO.get(r["complessivo"], 9),
        r["cognome"].casefold(),
        r["nome"].casefold(),
    ))

    # KPI
    n_ko = sum(1 for r in righe if r["complessivo"] == conformita_service.ESITO_KO)
    n_warn = sum(1 for r in righe if r["complessivo"] == conformita_service.ESITO_WARN)
    n_ok = sum(1 for r in righe if r["complessivo"] == conformita_service.ESITO_OK)
    n_na = sum(1 for r in righe if r["complessivo"] == conformita_service.ESITO_NA)

    reparti = sorted({r["reparto"] for r in righe if r["reparto"]})

    if export_csv:
        _LABEL = {
            conformita_service.ESITO_OK: "In regola",
            conformita_service.ESITO_WARN: "In scadenza",
            conformita_service.ESITO_KO: "Non conforme",
            conformita_service.ESITO_NA: "Nessun requisito",
        }
        _LABEL_IDN = {
            conformita_service.ESITO_OK: "Idoneo",
            conformita_service.ESITO_WARN: "Idoneo con riserve",
            conformita_service.ESITO_KO: "Non idoneo",
            conformita_service.ESITO_NA: "Non valutabile",
        }
        resp = HttpResponse(content_type=CSV_CONTENT_TYPE)
        resp["Content-Disposition"] = 'attachment; filename="conformita_anagrafica.csv"'
        resp.write(BOM)  # una volta sola: Excel riconosce l'UTF-8
        writer = safe_csv_writer(resp, delimiter=";")
        writer.writerow([
            "Dipendente", "Reparto", "Mansione", "Conformità", "Idoneità mansione",
            "Requisiti da soddisfare", "Formazione", "Visite mediche", "Qualifiche", "DPI",
        ])
        for r in righe:
            idn = r["idoneita"]
            da_soddisfare = "; ".join(list(idn.get("scaduti", [])) + list(idn.get("mancanti", [])))
            writer.writerow([
                naming.nome_completo(r["nome"], r["cognome"]),
                r["reparto"],
                r["mansione"],
                _LABEL.get(r["complessivo"], r["complessivo"]),
                _LABEL_IDN.get(idn.get("esito"), idn.get("esito")),
                da_soddisfare,
                _LABEL.get(r["formazione"]["esito"], r["formazione"]["esito"]),
                _LABEL.get(r["visite"]["esito"], r["visite"]["esito"]),
                _LABEL.get(r["qualifiche"]["esito"], r["qualifiche"]["esito"]),
                _LABEL.get(r["dpi"]["esito"], r["dpi"]["esito"]),
            ])
        return resp

    paginator = Paginator(righe, 50)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(request, "anagrafica/pages/conformita_report.html", {
        "page_obj": page_obj,
        "totale": len(righe),
        "n_ko": n_ko,
        "n_warn": n_warn,
        "n_ok": n_ok,
        "n_na": n_na,
        "reparti": reparti,
        "filtro_reparto": filtro_reparto,
        "filtro_esito": filtro_esito,
        "filtro_idoneita": filtro_idoneita,
        "filtro_mansione": filtro_mansione,
        "can_view_visite": can_view_visite,
    })


# ---------------------------------------------------------------------------
# Libretto sanitario aziendale — quadro generale (tutto il personale)
# ---------------------------------------------------------------------------

@login_required
def libretto_sanitario_generale(request):
    """Resoconto aziendale degli obblighi di mansione, con KPI e filtri.

    Il report Conformità conta le **persone** per semaforo; qui si contano gli
    **adempimenti**, che è l'unità di misura del lavoro da fare (e quella su cui
    si viene sanzionati): per ogni obbligo si sa a chi appartiene, perché è
    dovuto, quando scade e in che stato è. Due letture della stessa lista:

    - ``?vista=persone`` (default): una riga per dipendente, con il verdetto e
      i contatori dei suoi obblighi;
    - ``?vista=requisiti``: una riga per singolo requisito, peggiori in testa —
      la lista di lavoro di RSPP/HR.

    Lista e filtri vengono da ``libretto_sanitario.quadro_generale``, la stessa
    funzione che alimenta gli export PDF/Excel: il documento che si stampa non
    può divergere da quello che si vede.

    Accesso: ``_check_hr_permission`` (vista trasversale su tutto il personale).
    Privacy: il dettaglio delle visite segue ``_can_view_visite_mediche``.
    """
    if not _helpers._check_hr_permission(request):
        messages.error(request, "Non hai i permessi per il libretto sanitario aziendale.")
        return redirect("anagrafica:index")

    ensure_anagrafica_schema()
    from ..services import libretto_sanitario as libretto_service

    vista = "requisiti" if request.GET.get("vista") == "requisiti" else "persone"
    filtri = {
        chiave: (request.GET.get(chiave) or "").strip()
        for chiave in ("reparto", "mansione", "verdetto", "dominio", "stato")
    }

    quadro = libretto_service.quadro_generale(
        [r for r in fetch_anagrafica_rows(deduplicate=True) if r.get("attivo")],
        filtri=filtri,
        include_visite_dettaglio=_helpers._can_view_visite_mediche(request),
        mansioni_map={
            m.nome.casefold(): m.id
            for m in Mansione.objects.filter(is_active=True).only("id", "nome")
        },
    )

    elenco = quadro["adempimenti"] if vista == "requisiti" else quadro["persone"]
    paginator = Paginator(elenco, 50)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(request, "anagrafica/pages/libretto_sanitario_generale.html", {
        "page_obj": page_obj,
        "vista": vista,
        "totale": len(elenco),
        "export_key": (
            "libretto_sanitario_requisiti" if vista == "requisiti"
            else "libretto_sanitario_persone"
        ),
        "filtro_reparto": filtri["reparto"],
        "filtro_mansione": filtri["mansione"],
        "filtro_verdetto": filtri["verdetto"],
        "filtro_dominio": filtri["dominio"],
        "filtro_stato": filtri["stato"],
        "can_view_visite": _helpers._can_view_visite_mediche(request),
        "oggi": django_timezone.localdate(),
        **quadro,
    })
