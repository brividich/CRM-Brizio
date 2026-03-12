from __future__ import annotations

import csv
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponseForbidden, HttpResponseNotAllowed, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from admin_portale.decorators import legacy_admin_required
from core.acl import check_permesso, user_can_modulo_action
from core.audit import log_action
from core.legacy_utils import get_legacy_user, is_legacy_admin, legacy_auth_enabled
from core.models import AuditLog

from .forms import NotiziaAllegatoFormSet, NotiziaAudienceFormSet, NotiziaForm
from .models import (
    COMPLIANCE_APERTO,
    COMPLIANCE_CONFORME,
    COMPLIANCE_NON_LETTO,
    COMPLIANCE_NON_CONFORME,
    STATO_ARCHIVIATA,
    STATO_BOZZA,
    STATO_PUBBLICATA,
    Notizia,
    NotiziaLettura,
    compute_hash_versione,
    get_compliance_status,
    get_or_create_lettura,
    is_visible_to_user,
    pubblica_notizia,
)
from .mandatory_middleware import invalidate_pending_mandatory_cache

logger = logging.getLogger(__name__)

_REPORT_ALLOWED_RUOLI = {"admin", "hr"}

_VALID_STATO_FILTERS = {STATO_BOZZA, STATO_PUBBLICATA, STATO_ARCHIVIATA}
_CONFERMA_TOKEN_SALT = "notizie.conferma"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_legacy_user_id(request) -> int | None:
    legacy_user = getattr(request, "legacy_user", None)
    if legacy_user is not None:
        return int(legacy_user.id)
    try:
        from core.models import Profile
        profile = Profile.objects.filter(user=request.user).first()
        if profile and profile.legacy_user_id:
            return int(profile.legacy_user_id)
    except Exception:
        pass
    return None


def _get_legacy_role_id(request) -> int | None:
    legacy_user = getattr(request, "legacy_user", None)
    if legacy_user is not None:
        return legacy_user.ruolo_id
    try:
        from core.models import Profile
        profile = Profile.objects.filter(user=request.user).first()
        if profile:
            return profile.legacy_ruolo_id
    except Exception:
        pass
    return None


def _is_admin_or_hr(request) -> bool:
    if getattr(request.user, "is_superuser", False):
        return True
    legacy_user = getattr(request, "legacy_user", None)
    if legacy_user is not None:
        if is_legacy_admin(legacy_user):
            return True
        return str(legacy_user.ruolo or "").strip().lower() in _REPORT_ALLOWED_RUOLI
    try:
        from core.models import Profile
        profile = Profile.objects.filter(user=request.user).first()
        if profile:
            ruolo = str(profile.legacy_ruolo or "").strip().lower()
            return ruolo in (_REPORT_ALLOWED_RUOLI | {"admin"})
    except Exception:
        pass
    return False


def _can_manage_notizie_dashboard(request) -> bool:
    """Controlla accesso dashboard notizie.

    In produzione (ACL legacy attiva): usa il permesso ACL sul path dashboard.
    In fallback (ACL legacy disattivata): usa admin/hr.
    """
    if getattr(request.user, "is_superuser", False):
        return True

    if legacy_auth_enabled():
        legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
        if not legacy_user:
            return False
        return bool(check_permesso(legacy_user, reverse("notizie_dashboard")))

    return _is_admin_or_hr(request)


def _build_conferma_token(notizia: Notizia, legacy_user_id: int | None) -> str:
    if legacy_user_id is None:
        return ""
    return signing.dumps(
        {
            "uid": int(legacy_user_id),
            "nid": int(notizia.id),
            "ver": int(notizia.versione),
            "hash": str(notizia.hash_versione or compute_hash_versione(notizia)),
        },
        salt=_CONFERMA_TOKEN_SALT,
    )


def _has_valid_conferma_token(token: str, notizia: Notizia, legacy_user_id: int | None) -> bool:
    if not token or legacy_user_id is None:
        return False
    try:
        payload = signing.loads(token, salt=_CONFERMA_TOKEN_SALT, max_age=86400)
    except signing.BadSignature:
        return False
    except signing.SignatureExpired:
        return False

    expected_hash = str(notizia.hash_versione or compute_hash_versione(notizia))
    return (
        int(payload.get("uid", -1)) == int(legacy_user_id)
        and int(payload.get("nid", -1)) == int(notizia.id)
        and int(payload.get("ver", -1)) == int(notizia.versione)
        and str(payload.get("hash", "")) == expected_hash
    )


def _notizie_visibili(legacy_role_id: int | None):
    """Restituisce QS delle notizie pubblicate visibili al ruolo dato."""
    qs = Notizia.objects.filter(stato=STATO_PUBBLICATA)
    result = []
    for n in qs.prefetch_related("audience"):
        if is_visible_to_user(n, legacy_role_id):
            result.append(n)
    return result


class _Echo:
    def write(self, value):
        return value


def _csv_streaming_response(rows_iter, headers: list[str], filename: str) -> StreamingHttpResponse:
    writer = csv.writer(_Echo())

    def stream():
        yield writer.writerow(headers)
        for row in rows_iter:
            yield writer.writerow(row)

    resp = StreamingHttpResponse(stream(), content_type="text/csv; charset=utf-8-sig")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


def _forbidden_response(request):
    return render(request, "core/pages/forbidden.html", {"page_title": "Accesso negato"}, status=403)


def _legacy_roles_index() -> dict[int, str]:
    roles: dict[int, str] = {}
    try:
        from core.legacy_models import Ruolo

        for ruolo in Ruolo.objects.all().order_by("nome"):
            try:
                ruolo_id = int(ruolo.id)
            except (TypeError, ValueError):
                continue
            roles[ruolo_id] = (str(ruolo.nome or "").strip() or f"Ruolo {ruolo_id}")[:100]
    except Exception:
        pass

    if roles:
        return roles

    try:
        from core.models import Profile

        for role_id, role_name in Profile.objects.exclude(legacy_ruolo_id__isnull=True).values_list(
            "legacy_ruolo_id", "legacy_ruolo"
        ):
            if role_id is None:
                continue
            role_id_int = int(role_id)
            if role_id_int in roles:
                continue
            roles[role_id_int] = (str(role_name or "").strip() or f"Ruolo {role_id_int}")[:100]
    except Exception:
        pass

    return dict(sorted(roles.items(), key=lambda item: (str(item[1]).lower(), item[0])))


def _permesso_allows_view(perm) -> bool:
    if perm is None:
        return False
    can_view = getattr(perm, "can_view", None)
    consentito = getattr(perm, "consentito", None)
    return bool(can_view) or (can_view is None and bool(consentito))


def _dashboard_acl_roles() -> list[dict]:
    rows: list[dict] = []
    try:
        from core.legacy_models import Permesso, Ruolo

        for ruolo in Ruolo.objects.all().order_by("nome"):
            ruolo_id = int(ruolo.id)
            perm = (
                Permesso.objects.filter(
                    ruolo_id=ruolo_id,
                    modulo__iexact="notizie",
                    azione__iexact="notizie_dashboard",
                )
                .order_by("-id")
                .first()
            )
            rows.append(
                {
                    "role_id": ruolo_id,
                    "role_name": str(ruolo.nome or "").strip() or f"Ruolo {ruolo_id}",
                    "enabled": _permesso_allows_view(perm),
                }
            )
    except Exception:
        return []
    return rows


def _save_dashboard_acl_roles(selected_role_ids: set[int]) -> tuple[int, int]:
    updated = 0
    total = 0
    try:
        from core.legacy_cache import bump_legacy_cache_version
        from core.legacy_models import Permesso, Ruolo

        with transaction.atomic():
            for ruolo in Ruolo.objects.all().order_by("nome"):
                role_id = int(ruolo.id)
                total += 1

                perm = (
                    Permesso.objects.filter(
                        ruolo_id=role_id,
                        modulo__iexact="notizie",
                        azione__iexact="notizie_dashboard",
                    )
                    .order_by("-id")
                    .first()
                )
                should_enable = role_id in selected_role_ids

                if perm is None:
                    Permesso.objects.create(
                        ruolo_id=role_id,
                        modulo="notizie",
                        azione="notizie_dashboard",
                        can_view=1 if should_enable else 0,
                        consentito=1 if should_enable else 0,
                        can_edit=0,
                        can_delete=0,
                        can_approve=0,
                    )
                    updated += 1
                    continue

                if _permesso_allows_view(perm) == should_enable:
                    continue

                perm.can_view = 1 if should_enable else 0
                fields = ["can_view"]
                if hasattr(perm, "consentito"):
                    perm.consentito = perm.can_view
                    fields.append("consentito")
                perm.save(update_fields=fields)
                updated += 1

        if updated:
            try:
                bump_legacy_cache_version()
            except Exception:
                pass
    except Exception:
        return 0, 0

    return total, updated


def _invalidate_mandatory_cache_for_all_profiles() -> None:
    try:
        from core.models import Profile

        user_ids = Profile.objects.exclude(legacy_user_id__isnull=True).values_list("legacy_user_id", flat=True)
        for legacy_user_id in user_ids:
            if legacy_user_id is None:
                continue
            invalidate_pending_mandatory_cache(int(legacy_user_id))
    except Exception:
        return


def _target_legacy_user_ids(
    notizia: Notizia,
    all_user_ids: set[int],
    role_users_map: dict[int, set[int]],
) -> set[int]:
    audience_ids = [int(a.legacy_role_id) for a in notizia.audience.all()]
    if not audience_ids:
        return set(all_user_ids)

    target_ids: set[int] = set()
    for role_id in audience_ids:
        target_ids.update(role_users_map.get(role_id, set()))
    return target_ids


def _compliance_breakdown(notizia: Notizia, target_user_ids: set[int]) -> dict[str, int]:
    stats = {
        COMPLIANCE_CONFORME: 0,
        COMPLIANCE_APERTO: 0,
        COMPLIANCE_NON_CONFORME: 0,
        COMPLIANCE_NON_LETTO: 0,
    }
    if not target_user_ids:
        return stats

    letture = list(
        NotiziaLettura.objects.filter(notizia=notizia, legacy_user_id__in=target_user_ids).only(
            "legacy_user_id", "versione_letta", "opened_at", "ack_at"
        )
    )

    latest_version_map: dict[int, NotiziaLettura] = {}
    any_read_users: set[int] = set()

    for lettura in letture:
        user_id = int(lettura.legacy_user_id)
        any_read_users.add(user_id)
        if lettura.versione_letta != notizia.versione:
            continue
        current = latest_version_map.get(user_id)
        if current is None:
            latest_version_map[user_id] = lettura
            continue
        if not current.ack_at and lettura.ack_at:
            latest_version_map[user_id] = lettura

    for user_id in target_user_ids:
        current = latest_version_map.get(user_id)
        if current is not None:
            if current.ack_at:
                stats[COMPLIANCE_CONFORME] += 1
            elif current.opened_at:
                stats[COMPLIANCE_APERTO] += 1
            else:
                stats[COMPLIANCE_NON_LETTO] += 1
            continue

        if user_id in any_read_users:
            stats[COMPLIANCE_NON_CONFORME] += 1
        else:
            stats[COMPLIANCE_NON_LETTO] += 1

    return stats


def _dashboard_rows(notizie: list[Notizia]) -> list[dict]:
    try:
        from core.models import Profile

        profiles = list(
            Profile.objects.exclude(legacy_user_id__isnull=True).values("legacy_user_id", "legacy_ruolo_id")
        )
    except Exception:
        profiles = []

    all_user_ids: set[int] = set()
    role_users_map: dict[int, set[int]] = {}
    for profile in profiles:
        legacy_user_id = profile.get("legacy_user_id")
        if legacy_user_id is None:
            continue
        user_id = int(legacy_user_id)
        all_user_ids.add(user_id)

        role_id = profile.get("legacy_ruolo_id")
        if role_id is None:
            continue
        role_id_int = int(role_id)
        role_users_map.setdefault(role_id_int, set()).add(user_id)

    roles_index = _legacy_roles_index()
    rows = []
    for notizia in notizie:
        target_user_ids = _target_legacy_user_ids(notizia, all_user_ids, role_users_map)
        stats = _compliance_breakdown(notizia, target_user_ids)
        target_count = len(target_user_ids)
        pending_count = target_count - stats[COMPLIANCE_CONFORME]
        completion_rate = round((stats[COMPLIANCE_CONFORME] / target_count) * 100, 1) if target_count else 0.0
        audience_ids = [int(a.legacy_role_id) for a in notizia.audience.all()]
        audience_labels = [f"{role_id} - {roles_index.get(role_id, 'Ruolo')}" for role_id in audience_ids]

        rows.append(
            {
                "notizia": notizia,
                "stats": stats,
                "target_count": target_count,
                "pending_count": pending_count,
                "completion_rate": completion_rate,
                "audience_ids": audience_ids,
                "audience_labels": audience_labels,
            }
        )
    return rows


def _dashboard_form_context(
    request,
    notizia: Notizia,
    form: NotiziaForm,
    audience_formset: NotiziaAudienceFormSet,
    allegati_formset: NotiziaAllegatoFormSet,
    is_create: bool,
) -> dict:
    roles_index = _legacy_roles_index()
    return {
        "page_title": "Nuova notizia" if is_create else f"Modifica notizia #{notizia.id}",
        "notizia": notizia,
        "form": form,
        "audience_formset": audience_formset,
        "allegati_formset": allegati_formset,
        "roles_hint": [{"id": role_id, "name": role_name} for role_id, role_name in roles_index.items()],
        "is_create": is_create,
    }


def _render_dashboard_form(request, notizia: Notizia, *, is_create: bool):
    if request.method == "POST":
        save_and_publish = request.POST.get("save_and_publish") == "1"
        form = NotiziaForm(request.POST, instance=notizia)
        audience_formset = NotiziaAudienceFormSet(request.POST, instance=notizia, prefix="audience")
        allegati_formset = NotiziaAllegatoFormSet(
            request.POST,
            request.FILES,
            instance=notizia,
            prefix="allegati",
        )

        if form.is_valid() and audience_formset.is_valid() and allegati_formset.is_valid():
            was_published = (notizia.pk is not None and notizia.stato == STATO_PUBBLICATA)

            with transaction.atomic():
                obj = form.save(commit=False)
                if not obj.pk:
                    obj.creato_da = obj.creato_da or request.user
                    obj.stato = STATO_BOZZA
                elif was_published:
                    # Evita modifiche in-place su versione gia pubblicata.
                    obj.stato = STATO_BOZZA
                obj.save()

                audience_formset.instance = obj
                audience_formset.save()

                allegati_formset.instance = obj
                allegati_formset.save()

                obj.hash_versione = compute_hash_versione(obj)
                obj.save(update_fields=["hash_versione"])

                if save_and_publish:
                    prima_pubblicazione = bool(obj.pubblicato_il is None and obj.versione <= 1)
                    pubblica_notizia(obj, prima_pubblicazione=prima_pubblicazione)

            _invalidate_mandatory_cache_for_all_profiles()

            if is_create:
                if save_and_publish:
                    messages.success(request, "Notizia creata e pubblicata.")
                else:
                    messages.success(request, "Notizia creata in bozza.")
            elif was_published:
                if save_and_publish:
                    messages.success(request, "Notizia aggiornata e ripubblicata con nuova versione.")
                else:
                    messages.success(
                        request,
                        "Notizia aggiornata e riportata in bozza. Pubblica per rendere attiva la nuova versione.",
                    )
            else:
                if save_and_publish:
                    messages.success(request, "Notizia salvata e pubblicata.")
                else:
                    messages.success(request, "Notizia aggiornata.")

            return redirect(reverse("notizie_dashboard_edit", args=[obj.id]))
    else:
        form = NotiziaForm(instance=notizia)
        audience_formset = NotiziaAudienceFormSet(instance=notizia, prefix="audience")
        allegati_formset = NotiziaAllegatoFormSet(instance=notizia, prefix="allegati")

    return render(
        request,
        "notizie/pages/dashboard_form.html",
        _dashboard_form_context(request, notizia, form, audience_formset, allegati_formset, is_create),
    )


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

@login_required
def lista(request):
    legacy_role_id = _get_legacy_role_id(request)
    legacy_user_id = _get_legacy_user_id(request)

    solo_obbligatorie = request.GET.get("solo_obbligatorie") == "1"
    filtro_stato = request.GET.get("stato", "").strip()

    notizie_visibili = _notizie_visibili(legacy_role_id)

    if solo_obbligatorie:
        notizie_visibili = [n for n in notizie_visibili if n.obbligatoria]

    items = []
    for n in notizie_visibili:
        compliance = get_compliance_status(n, legacy_user_id) if legacy_user_id else COMPLIANCE_NON_LETTO
        if filtro_stato and compliance != filtro_stato:
            continue
        items.append({"notizia": n, "compliance": compliance})

    return render(request, "notizie/pages/lista.html", {
        "page_title": "Notizie",
        "items": items,
        "solo_obbligatorie": solo_obbligatorie,
        "filtro_stato": filtro_stato,
        "can_manage_notizie": _can_manage_notizie_dashboard(request),
    })


@login_required
def dashboard(request):
    if not _can_manage_notizie_dashboard(request):
        return _forbidden_response(request)

    can_edit_dashboard_acl = _is_admin_or_hr(request)
    if request.method == "POST" and request.POST.get("action") == "save_dashboard_acl":
        if not can_edit_dashboard_acl:
            return _forbidden_response(request)

        selected_role_ids: set[int] = set()
        for raw in request.POST.getlist("role_ids"):
            try:
                selected_role_ids.add(int(raw))
            except (TypeError, ValueError):
                continue

        total, updated = _save_dashboard_acl_roles(selected_role_ids)
        if total == 0 and updated == 0:
            messages.error(
                request,
                "Impossibile aggiornare i permessi ruoli da questa istanza (tabella legacy non disponibile).",
            )
        else:
            messages.success(
                request,
                f"Permessi dashboard notizie aggiornati su {updated} ruoli (totale ruoli: {total}).",
            )
        return redirect(reverse("notizie_dashboard"))

    filtro_stato = request.GET.get("stato", "").strip().lower()
    query = request.GET.get("q", "").strip()

    notizie_qs = Notizia.objects.prefetch_related("audience").order_by("-updated_at", "-created_at")

    if filtro_stato in _VALID_STATO_FILTERS:
        notizie_qs = notizie_qs.filter(stato=filtro_stato)

    if query:
        notizie_qs = notizie_qs.filter(Q(titolo__icontains=query) | Q(corpo__icontains=query))

    notizie = list(notizie_qs[:250])
    rows = _dashboard_rows(notizie)

    bozza_count = sum(1 for r in rows if r["notizia"].stato == STATO_BOZZA)
    pubblicata_count = sum(1 for r in rows if r["notizia"].stato == STATO_PUBBLICATA)
    archiviata_count = sum(1 for r in rows if r["notizia"].stato == STATO_ARCHIVIATA)
    obbligatorie_pendenti = sum(
        r["pending_count"]
        for r in rows
        if r["notizia"].obbligatoria and r["notizia"].stato == STATO_PUBBLICATA
    )

    return render(
        request,
        "notizie/pages/dashboard.html",
        {
            "page_title": "Dashboard notizie",
            "rows": rows,
            "bozza_count": bozza_count,
            "pubblicata_count": pubblicata_count,
            "archiviata_count": archiviata_count,
            "obbligatorie_pendenti": obbligatorie_pendenti,
            "filtro_stato": filtro_stato,
            "query": query,
            "can_edit_dashboard_acl": can_edit_dashboard_acl,
            "can_gestione_admin": user_can_modulo_action(request, "notizie", "admin_notizie"),
            "dashboard_acl_roles": _dashboard_acl_roles(),
        },
    )


@login_required
def dashboard_create(request):
    if not _can_manage_notizie_dashboard(request):
        return _forbidden_response(request)

    notizia = Notizia(creato_da=request.user)
    return _render_dashboard_form(request, notizia, is_create=True)


@login_required
def dashboard_edit(request, notizia_id: int):
    if not _can_manage_notizie_dashboard(request):
        return _forbidden_response(request)

    notizia = get_object_or_404(Notizia, pk=notizia_id)
    return _render_dashboard_form(request, notizia, is_create=False)


@login_required
@require_POST
def dashboard_publish(request, notizia_id: int):
    if not _can_manage_notizie_dashboard(request):
        return _forbidden_response(request)

    notizia = get_object_or_404(Notizia, pk=notizia_id)
    prima_pubblicazione = bool(notizia.pubblicato_il is None and notizia.versione <= 1)

    with transaction.atomic():
        pubblica_notizia(notizia, prima_pubblicazione=prima_pubblicazione)

    _invalidate_mandatory_cache_for_all_profiles()
    messages.success(
        request,
        "Notizia pubblicata." if prima_pubblicazione else "Notizia ripubblicata con nuova versione.",
    )
    return redirect(request.POST.get("next") or reverse("notizie_dashboard"))


@login_required
@require_POST
def dashboard_archive(request, notizia_id: int):
    if not _can_manage_notizie_dashboard(request):
        return _forbidden_response(request)

    notizia = get_object_or_404(Notizia, pk=notizia_id)
    if notizia.stato != STATO_ARCHIVIATA:
        notizia.stato = STATO_ARCHIVIATA
        notizia.save(update_fields=["stato"])
        _invalidate_mandatory_cache_for_all_profiles()
        messages.success(request, "Notizia archiviata.")
    else:
        messages.info(request, "La notizia era gia archiviata.")
    return redirect(request.POST.get("next") or reverse("notizie_dashboard"))


@login_required
@ensure_csrf_cookie
def dettaglio(request, notizia_id: int):
    legacy_role_id = _get_legacy_role_id(request)
    legacy_user_id = _get_legacy_user_id(request)

    notizia = get_object_or_404(Notizia, pk=notizia_id, stato=STATO_PUBBLICATA)

    if not is_visible_to_user(notizia, legacy_role_id):
        return HttpResponseForbidden("Notizia non disponibile.")

    allegati = list(notizia.allegati.all())

    lettura = None
    compliance = COMPLIANCE_NON_LETTO
    if legacy_user_id:
        lettura = get_or_create_lettura(notizia, legacy_user_id)
        if not lettura.opened_at:
            lettura.opened_at = timezone.now()
            lettura.save(update_fields=["opened_at"])
        compliance = get_compliance_status(notizia, legacy_user_id)

    return render(request, "notizie/pages/dettaglio.html", {
        "page_title": notizia.titolo,
        "notizia": notizia,
        "allegati": allegati,
        "compliance": compliance,
        "lettura": lettura,
        "conferma_token": _build_conferma_token(notizia, legacy_user_id),
    })


@login_required
def conferma(request, notizia_id: int):
    if request.method not in {"GET", "POST"}:
        return HttpResponseNotAllowed(["GET", "POST"])

    legacy_user_id = _get_legacy_user_id(request)
    legacy_role_id = _get_legacy_role_id(request)

    notizia = get_object_or_404(Notizia, pk=notizia_id, stato=STATO_PUBBLICATA)

    if not is_visible_to_user(notizia, legacy_role_id):
        return HttpResponseForbidden("Notizia non disponibile.")

    if legacy_user_id is None:
        return HttpResponseForbidden("Utente legacy non trovato.")

    if request.method == "GET":
        token = str(request.GET.get("token") or "").strip()
        if not _has_valid_conferma_token(token, notizia, legacy_user_id):
            return HttpResponseForbidden("Token conferma non valido.")

    lettura = get_or_create_lettura(notizia, legacy_user_id)

    if not lettura.ack_at:
        now = timezone.now()
        lettura.ack_at = now
        if not lettura.opened_at:
            lettura.opened_at = now
        lettura.hash_versione_letta = notizia.hash_versione or compute_hash_versione(notizia)
        lettura.save(update_fields=["ack_at", "opened_at", "hash_versione_letta"])

        logger.info(
            "presa_visione user_id=%s news_id=%s versione=%s hash=%s",
            legacy_user_id,
            notizia.id,
            notizia.versione,
            lettura.hash_versione_letta,
        )

        invalidate_pending_mandatory_cache(legacy_user_id)

    # Se ci sono altre obbligatorie pendenti, vai alla pagina obbligatorie.
    from .mandatory_middleware import _has_pending_mandatory
    if notizia.obbligatoria and _has_pending_mandatory(legacy_user_id, force_check=True):
        return redirect(reverse("notizie_obbligatorie"))

    return redirect(reverse("notizie_dettaglio", args=[notizia_id]))


@login_required
@ensure_csrf_cookie
def obbligatorie(request):
    """Pagina safe: elenca notizie obbligatorie non ancora confermate."""
    legacy_role_id = _get_legacy_role_id(request)
    legacy_user_id = _get_legacy_user_id(request)

    pendenti = []
    for n in _notizie_visibili(legacy_role_id):
        if not n.obbligatoria:
            continue
        if legacy_user_id is None:
            pendenti.append(n)
            continue
        compliance = get_compliance_status(n, legacy_user_id)
        if compliance != COMPLIANCE_CONFORME:
            pendenti.append(n)

    return render(request, "notizie/pages/obbligatorie.html", {
        "page_title": "Comunicazioni obbligatorie",
        "pendenti": pendenti,
    })


@login_required
def report(request):
    if not _is_admin_or_hr(request):
        return _forbidden_response(request)

    notizia_id = request.GET.get("notizia_id", "").strip()
    filtro_stato = request.GET.get("stato", "").strip()
    da = request.GET.get("da", "").strip()
    a = request.GET.get("a", "").strip()

    notizie_qs = Notizia.objects.all().order_by("-pubblicato_il")
    letture_qs = NotiziaLettura.objects.select_related("notizia").order_by(
        "notizia__titolo", "legacy_user_id", "-versione_letta"
    )

    if notizia_id:
        try:
            letture_qs = letture_qs.filter(notizia_id=int(notizia_id))
        except ValueError:
            pass

    rows = []
    for lettura in letture_qs:
        notizia = lettura.notizia
        compliance = get_compliance_status(notizia, lettura.legacy_user_id)
        if filtro_stato and compliance != filtro_stato:
            continue
        if da:
            try:
                from datetime import date
                cutoff = date.fromisoformat(da)
                if lettura.ack_at and lettura.ack_at.date() < cutoff:
                    continue
            except ValueError:
                pass
        if a:
            try:
                from datetime import date
                cutoff = date.fromisoformat(a)
                if lettura.ack_at and lettura.ack_at.date() > cutoff:
                    continue
            except ValueError:
                pass
        rows.append({
            "lettura": lettura,
            "notizia": notizia,
            "compliance": compliance,
        })

    return render(request, "notizie/pages/report.html", {
        "page_title": "Report letture notizie",
        "rows": rows,
        "notizie_qs": notizie_qs,
        "filtro_notizia_id": notizia_id,
        "filtro_stato": filtro_stato,
        "filtro_da": da,
        "filtro_a": a,
    })


@login_required
def report_csv(request):
    if not _is_admin_or_hr(request):
        return HttpResponseForbidden("Accesso negato.")

    notizia_id = request.GET.get("notizia_id", "").strip()
    filtro_stato = request.GET.get("stato", "").strip()
    da = request.GET.get("da", "").strip()
    a = request.GET.get("a", "").strip()

    letture_qs = NotiziaLettura.objects.select_related("notizia").order_by(
        "notizia__titolo", "legacy_user_id", "-versione_letta"
    )
    if notizia_id:
        try:
            letture_qs = letture_qs.filter(notizia_id=int(notizia_id))
        except ValueError:
            pass

    headers = ["Utente ID", "Notizia", "Versione letta", "Versione corrente", "Hash versione", "Stato", "Data apertura", "Data conferma"]

    def rows():
        for lettura in letture_qs:
            notizia = lettura.notizia
            compliance = get_compliance_status(notizia, lettura.legacy_user_id)
            if filtro_stato and compliance != filtro_stato:
                continue
            if da:
                try:
                    from datetime import date
                    cutoff = date.fromisoformat(da)
                    if lettura.ack_at and lettura.ack_at.date() < cutoff:
                        continue
                except ValueError:
                    pass
            if a:
                try:
                    from datetime import date
                    cutoff = date.fromisoformat(a)
                    if lettura.ack_at and lettura.ack_at.date() > cutoff:
                        continue
                except ValueError:
                    pass
            yield [
                lettura.legacy_user_id,
                notizia.titolo,
                lettura.versione_letta,
                notizia.versione,
                lettura.hash_versione_letta,
                compliance,
                lettura.opened_at.strftime("%Y-%m-%d %H:%M") if lettura.opened_at else "",
                lettura.ack_at.strftime("%Y-%m-%d %H:%M") if lettura.ack_at else "",
            ]

    return _csv_streaming_response(rows(), headers, "report_notizie.csv")


@legacy_admin_required
def gestione_admin(request):
    """Pagina di gestione interna Notizie — accesso solo admin."""
    from django.core.paginator import Paginator
    from django.db.models import Count

    tab = request.GET.get("tab", "riepilogo")

    # --- Statistiche ---
    total = Notizia.objects.count()
    bozze = Notizia.objects.filter(stato=STATO_BOZZA).count()
    pubblicate = Notizia.objects.filter(stato=STATO_PUBBLICATA).count()
    archiviate = Notizia.objects.filter(stato=STATO_ARCHIVIATA).count()
    obbligatorie = Notizia.objects.filter(stato=STATO_PUBBLICATA, obbligatoria=True).count()
    totale_letture = NotiziaLettura.objects.count()
    totale_conformi = NotiziaLettura.objects.filter(ack_at__isnull=False).count()
    tasso_conformita = round(totale_conformi * 100 / totale_letture, 1) if totale_letture else 0

    # --- Record: notizie con conteggio letture ---
    q = request.GET.get("q", "").strip()
    filter_stato = request.GET.get("filter_stato", "").strip()
    notizie_qs = Notizia.objects.annotate(
        n_letture=Count("letture", distinct=True),
        n_conformi=Count("letture__id", filter=Q(letture__ack_at__isnull=False), distinct=True),
    ).order_by("-pubblicato_il", "-created_at")
    if q:
        notizie_qs = notizie_qs.filter(Q(titolo__icontains=q))
    if filter_stato:
        notizie_qs = notizie_qs.filter(stato=filter_stato)
    notizie_page = Paginator(notizie_qs, 50).get_page(request.GET.get("page"))

    # --- Log ---
    audit_entries = AuditLog.objects.filter(modulo="notizie").order_by("-created_at")[:100]

    stati = [
        (STATO_BOZZA, "Bozza"),
        (STATO_PUBBLICATA, "Pubblicata"),
        (STATO_ARCHIVIATA, "Archiviata"),
    ]

    return render(
        request,
        "notizie/pages/gestione_admin.html",
        {
            "page_title": "Gestione Notizie",
            "tab": tab,
            # stats
            "total": total,
            "bozze": bozze,
            "pubblicate": pubblicate,
            "archiviate": archiviate,
            "obbligatorie_attive": obbligatorie,
            "totale_letture": totale_letture,
            "totale_conformi": totale_conformi,
            "tasso_conformita": tasso_conformita,
            # records
            "notizie_page": notizie_page,
            "q": q,
            "filter_stato": filter_stato,
            "stati": stati,
            # log
            "audit_entries": audit_entries,
        },
    )
