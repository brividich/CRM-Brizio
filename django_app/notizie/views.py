from __future__ import annotations

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
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_POST

from admin_portale.decorators import legacy_admin_or_acl_required
from core.csv_export import CSV_CONTENT_TYPE, bom_first, safe_csv_writer
from core.upload_mime import safe_filename
from core.acl import check_permesso, user_can_modulo_action
from core.audit import log_action
from core.legacy_utils import get_legacy_user, is_legacy_admin, legacy_auth_enabled
from core.models import AuditLog
from core.module_branding import get_module_branding_context, handle_module_branding_post

from .forms import (
    NOTIZIE_ALLEGATO_EXTENSIONS,
    NotiziaAllegatoForm,
    NotiziaAllegatoFormSet,
    NotiziaAudienceFormSet,
    NotiziaForm,
)
from .models import (
    NotiziaAudience,
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
    from core.permessi import puo_fare, sistema_ruoli_attivo

    if sistema_ruoli_attivo():
        # Ruoli: chi gestisce le notizie (HR, Sicurezza), non il nome del ruolo legacy.
        return puo_fare(request, "notizie", "gestire")
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


def _can_manage_notizie_settings(request) -> bool:
    legacy_user = getattr(request, "legacy_user", None) or get_legacy_user(request.user)
    return bool(
        getattr(request.user, "is_superuser", False)
        or (legacy_user and is_legacy_admin(legacy_user))
        or user_can_modulo_action(request, "notizie", "admin_notizie")
    )


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
    for n in qs.prefetch_related("audience", "allegati"):
        if is_visible_to_user(n, legacy_role_id):
            result.append(n)
    return result


class _Echo:
    def write(self, value):
        return value


def _csv_streaming_response(rows_iter, headers: list[str], filename: str) -> StreamingHttpResponse:
    writer = safe_csv_writer(_Echo())

    def stream():
        yield writer.writerow(headers)
        for row in rows_iter:
            yield writer.writerow(row)

    resp = StreamingHttpResponse(bom_first(stream()), content_type=CSV_CONTENT_TYPE)
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
                # Permessi salvati ma cache non invalidata: l'utente continua a
                # vedere i vecchi finche' la cache non scade.
                logger.exception("Notizie: invalidazione della cache permessi legacy fallita")
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


def _audience_maps() -> tuple[set[int], dict[int, set[int]]]:
    """Utenti legacy noti e mappa ruolo -> utenti, base dei destinatari di ogni notizia."""
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
    return all_user_ids, role_users_map


def _dashboard_rows(notizie: list[Notizia]) -> list[dict]:
    all_user_ids, role_users_map = _audience_maps()
    roles_index = _legacy_roles_index()
    rows = []
    for notizia in notizie:
        target_user_ids = _target_legacy_user_ids(notizia, all_user_ids, role_users_map)
        stats = _compliance_breakdown(notizia, target_user_ids)
        target_count = len(target_user_ids)
        pending_count = target_count - stats[COMPLIANCE_CONFORME]
        completion_rate = round((stats[COMPLIANCE_CONFORME] / target_count) * 100, 1) if target_count else 0.0
        completion_rate_int = max(0, min(100, int(round(completion_rate))))
        audience_ids = [int(a.legacy_role_id) for a in notizia.audience.all()]
        audience_labels = [f"{role_id} - {roles_index.get(role_id, 'Ruolo')}" for role_id in audience_ids]

        rows.append(
            {
                "notizia": notizia,
                "stats": stats,
                "target_count": target_count,
                "pending_count": pending_count,
                "completion_rate": completion_rate,
                "completion_rate_int": completion_rate_int,
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
    selected_role_ids: set[int] | None = None,
    nuovi_allegati_errori: list[str] | None = None,
) -> dict:
    roles_index = _legacy_roles_index()
    if selected_role_ids is None:
        selected_role_ids = (
            {int(a.legacy_role_id) for a in notizia.audience.all()} if notizia.pk else set()
        )
    roles = [
        {"id": role_id, "name": role_name, "selected": role_id in selected_role_ids}
        for role_id, role_name in roles_index.items()
    ]
    # Ruoli in audience che non esistono piu' nell'elenco: restano visibili e
    # selezionati, altrimenti un salvataggio li toglierebbe senza che l'utente lo veda.
    for role_id in sorted(selected_role_ids - set(roles_index)):
        roles.append({"id": role_id, "name": f"Ruolo {role_id}", "selected": True})
    return {
        "page_title": "Nuova notizia" if is_create else f"Modifica notizia #{notizia.id}",
        "notizia": notizia,
        "form": form,
        "audience_formset": audience_formset,
        "allegati_formset": allegati_formset,
        "roles": roles,
        "roles_selected_count": sum(1 for r in roles if r["selected"]),
        "nuovi_allegati_errori": nuovi_allegati_errori or [],
        "accept_allegati": ",".join(sorted(NOTIZIE_ALLEGATO_EXTENSIONS)),
        "is_create": is_create,
    }


def _posted_role_ids(request) -> set[int]:
    ids: set[int] = set()
    for raw in request.POST.getlist("audience_roles"):
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if value > 0:
            ids.add(value)
    return ids


def _validate_nuovi_allegati(request) -> tuple[list[NotiziaAllegatoForm], list[str]]:
    """Valida i file del riquadro «trascina qui» con le stesse regole delle righe allegato."""
    forms_ok: list[NotiziaAllegatoForm] = []
    errori: list[str] = []
    for upload in request.FILES.getlist("nuovi_allegati"):
        nome = (safe_filename(getattr(upload, "name", "")) or "allegato")[:300]
        f = NotiziaAllegatoForm(data={"nome_file": nome, "url_esterno": ""}, files={"file": upload})
        if f.is_valid():
            forms_ok.append(f)
        else:
            for err in f.non_field_errors() or [e for errs in f.errors.values() for e in errs]:
                err = str(err)
                errori.append(err if nome in err else f"{nome}: {err}")
    return forms_ok, errori


def _render_dashboard_form(request, notizia: Notizia, *, is_create: bool):
    selected_role_ids: set[int] | None = None
    nuovi_errori: list[str] = []
    if request.method == "POST":
        save_and_publish = request.POST.get("save_and_publish") == "1"
        form = NotiziaForm(request.POST, instance=notizia)
        # La pagina invia i ruoli come caselle (audience_picker=1); il formset per ID
        # resta per compatibilita' con i client che postano ancora le righe.
        use_picker = request.POST.get("audience_picker") == "1"
        audience_formset = NotiziaAudienceFormSet(
            None if use_picker else request.POST, instance=notizia, prefix="audience"
        )
        if use_picker:
            selected_role_ids = _posted_role_ids(request)
        allegati_formset = NotiziaAllegatoFormSet(
            request.POST,
            request.FILES,
            instance=notizia,
            prefix="allegati",
        )
        nuovi_forms, nuovi_errori = _validate_nuovi_allegati(request)

        audience_ok = use_picker or audience_formset.is_valid()
        if form.is_valid() and audience_ok and allegati_formset.is_valid() and not nuovi_errori:
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

                if use_picker:
                    obj.audience.exclude(legacy_role_id__in=selected_role_ids).delete()
                    esistenti = set(obj.audience.values_list("legacy_role_id", flat=True))
                    NotiziaAudience.objects.bulk_create(
                        NotiziaAudience(notizia=obj, legacy_role_id=role_id)
                        for role_id in sorted(selected_role_ids - esistenti)
                    )
                else:
                    audience_formset.instance = obj
                    audience_formset.save()

                allegati_formset.instance = obj
                allegati_formset.save()

                for nuovo in nuovi_forms:
                    allegato = nuovo.save(commit=False)
                    allegato.notizia = obj
                    allegato.save()

                obj.hash_versione = compute_hash_versione(obj)
                obj.save(update_fields=["hash_versione"])

                if save_and_publish:
                    prima_pubblicazione = bool(obj.pubblicato_il is None and obj.versione <= 1)
                    pubblica_notizia(obj, prima_pubblicazione=prima_pubblicazione)

            _invalidate_mandatory_cache_for_all_profiles()

            if is_create:
                if save_and_publish:
                    log_action(request, "notizia_creata_pubblicata" if is_create else "notizia_ripubblicata", "notizie", {"notizia_id": obj.pk, "titolo": obj.titolo})
                    messages.success(request, "Notizia creata e pubblicata.")
                else:
                    log_action(request, "notizia_creata" if is_create else "notizia_modificata", "notizie", {"notizia_id": obj.pk, "titolo": obj.titolo, "stato": obj.stato})
                    messages.success(request, "Notizia creata in bozza.")
            elif was_published:
                if save_and_publish:
                    log_action(request, "notizia_ripubblicata", "notizie", {"notizia_id": obj.pk, "titolo": obj.titolo})
                    messages.success(request, "Notizia aggiornata e ripubblicata con nuova versione.")
                else:
                    log_action(request, "notizia_riportata_bozza", "notizie", {"notizia_id": obj.pk, "titolo": obj.titolo})
                    messages.success(
                        request,
                        "Notizia aggiornata e riportata in bozza. Pubblica per rendere attiva la nuova versione.",
                    )
            else:
                if save_and_publish:
                    log_action(request, "notizia_pubblicata", "notizie", {"notizia_id": obj.pk, "titolo": obj.titolo})
                    messages.success(request, "Notizia salvata e pubblicata.")
                else:
                    log_action(request, "notizia_modificata", "notizie", {"notizia_id": obj.pk, "titolo": obj.titolo, "stato": obj.stato})
                    messages.success(request, "Notizia aggiornata.")

            return redirect(reverse("notizie_dashboard_edit", args=[obj.id]))
    else:
        form = NotiziaForm(instance=notizia)
        audience_formset = NotiziaAudienceFormSet(instance=notizia, prefix="audience")
        allegati_formset = NotiziaAllegatoFormSet(instance=notizia, prefix="allegati")

    return render(
        request,
        "notizie/pages/dashboard_form.html",
        _dashboard_form_context(
            request,
            notizia,
            form,
            audience_formset,
            allegati_formset,
            is_create,
            selected_role_ids=selected_role_ids,
            nuovi_allegati_errori=nuovi_errori,
        ),
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
    query = request.GET.get("q", "").strip()

    notizie_visibili = _notizie_visibili(legacy_role_id)
    if query:
        q_low = query.lower()
        notizie_visibili = [
            n for n in notizie_visibili if q_low in n.titolo.lower() or q_low in n.corpo.lower()
        ]

    all_items = []
    for n in notizie_visibili:
        compliance = get_compliance_status(n, legacy_user_id) if legacy_user_id else COMPLIANCE_NON_LETTO
        allegati = list(n.allegati.all())
        all_items.append({
            "notizia": n,
            "compliance": compliance,
            "allegati_count": len(allegati),
            "pdf_count": sum(1 for a in allegati if a.is_pdf),
        })

    news_stats = {
        "total": len(all_items),
        "filtered": 0,
        "obbligatorie": sum(1 for item in all_items if item["notizia"].obbligatoria),
        "obbligatorie_pendenti": sum(
            1
            for item in all_items
            if item["notizia"].obbligatoria and item["compliance"] != COMPLIANCE_CONFORME
        ),
        "non_lette": sum(1 for item in all_items if item["compliance"] == COMPLIANCE_NON_LETTO),
        "aperte": sum(1 for item in all_items if item["compliance"] == COMPLIANCE_APERTO),
        "non_conformi": sum(1 for item in all_items if item["compliance"] == COMPLIANCE_NON_CONFORME),
        "confermate": sum(1 for item in all_items if item["compliance"] == COMPLIANCE_CONFORME),
    }

    items = []
    for item in all_items:
        if solo_obbligatorie and not item["notizia"].obbligatoria:
            continue
        if filtro_stato and item["compliance"] != filtro_stato:
            continue
        items.append(item)
    news_stats["filtered"] = len(items)

    return render(request, "notizie/pages/lista.html", {
        "page_title": "Notizie",
        "items": items,
        "news_stats": news_stats,
        "solo_obbligatorie": solo_obbligatorie,
        "filtro_stato": filtro_stato,
        "query": query,
        "can_manage_notizie": _can_manage_notizie_dashboard(request),
        "can_gestione_admin": _can_manage_notizie_settings(request),
    })


@login_required
def dashboard(request):
    if not _can_manage_notizie_dashboard(request):
        return _forbidden_response(request)

    can_edit_dashboard_acl = _is_admin_or_hr(request)
    can_manage_settings = _can_manage_notizie_settings(request)
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

    from django.db.models import Count

    notizie_qs = Notizia.objects.prefetch_related("audience").annotate(
        n_allegati=Count("allegati", distinct=True)
    ).order_by("-updated_at", "-created_at")

    if query:
        notizie_qs = notizie_qs.filter(Q(titolo__icontains=query) | Q(corpo__icontains=query))

    # I contatori delle schede contano la ricerca ma non lo stato scelto: ogni
    # scheda mostra quante notizie trovi cliccandola.
    stato_counts = dict(
        Notizia.objects.filter(pk__in=notizie_qs.values("pk"))
        .order_by()
        .values_list("stato")
        .annotate(n=Count("id"))
        .values_list("stato", "n")
    )
    bozza_count = stato_counts.get(STATO_BOZZA, 0)
    pubblicata_count = stato_counts.get(STATO_PUBBLICATA, 0)
    archiviata_count = stato_counts.get(STATO_ARCHIVIATA, 0)

    if filtro_stato in _VALID_STATO_FILTERS:
        notizie_qs = notizie_qs.filter(stato=filtro_stato)

    notizie = list(notizie_qs[:250])
    rows = _dashboard_rows(notizie)

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
            "totale_count": bozza_count + pubblicata_count + archiviata_count,
            "obbligatorie_pendenti": obbligatorie_pendenti,
            "filtro_stato": filtro_stato,
            "query": query,
            "can_edit_dashboard_acl": can_edit_dashboard_acl,
            "can_gestione_admin": can_manage_settings,
            "can_report": _is_admin_or_hr(request),
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
    log_action(request, "notizia_pubblicata" if prima_pubblicazione else "notizia_ripubblicata", "notizie", {"notizia_id": notizia.pk, "titolo": notizia.titolo, "versione": notizia.versione})
    messages.success(
        request,
        "Notizia pubblicata." if prima_pubblicazione else "Notizia ripubblicata con nuova versione.",
    )
    from core.redirects import safe_next

    return redirect(safe_next(request, request.POST.get("next"), reverse("notizie_dashboard")))


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
        log_action(request, "notizia_archiviata", "notizie", {"notizia_id": notizia.pk, "titolo": notizia.titolo})
        messages.success(request, "Notizia archiviata.")
    else:
        messages.info(request, "La notizia era gia archiviata.")
    from core.redirects import safe_next

    return redirect(safe_next(request, request.POST.get("next"), reverse("notizie_dashboard")))


@login_required
@ensure_csrf_cookie
def dettaglio(request, notizia_id: int):
    legacy_role_id = _get_legacy_role_id(request)
    legacy_user_id = _get_legacy_user_id(request)

    notizia = get_object_or_404(Notizia, pk=notizia_id, stato=STATO_PUBBLICATA)

    if not is_visible_to_user(notizia, legacy_role_id):
        return HttpResponseForbidden("Notizia non disponibile.")

    allegati = list(notizia.allegati.all())
    anteprime = [a for a in allegati if a.ha_anteprima]

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
        "anteprima_iniziale": anteprime[0] if anteprime else None,
        "compliance": compliance,
        "lettura": lettura,
        "conferma_token": _build_conferma_token(notizia, legacy_user_id),
    })


_ANTEPRIMA_CONTENT_TYPES = {
    "pdf": "application/pdf",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "gif": "image/gif",
    "webp": "image/webp",
}


@login_required
@xframe_options_sameorigin
def allegato_download(request, allegato_id: int):
    """Download di un allegato: chi vede la notizia pubblicata, oppure chi gestisce le notizie.

    Con ``?anteprima=1`` PDF e immagini si aprono nel browser (inline, incorniciabili
    solo dalle pagine del portale); gli altri tipi restano sempre in download.
    """
    import mimetypes
    import os

    from django.http import FileResponse, Http404

    from .models import NotiziaAllegato

    allegato = get_object_or_404(NotiziaAllegato.objects.select_related("notizia"), pk=allegato_id)
    notizia = allegato.notizia
    can_manage = _can_manage_notizie_dashboard(request)
    if not can_manage:
        if notizia.stato != STATO_PUBBLICATA or not is_visible_to_user(notizia, _get_legacy_role_id(request)):
            return HttpResponseForbidden("Allegato non disponibile.")
    if not allegato.file or not allegato.file.name:
        raise Http404("Allegato senza file.")
    try:
        handle = allegato.file.storage.open(allegato.file.name, "rb")
    except FileNotFoundError:
        raise Http404("File non trovato.")

    filename = os.path.basename(allegato.file.name)
    inline_type = _ANTEPRIMA_CONTENT_TYPES.get(allegato.estensione) if request.GET.get("anteprima") == "1" else None
    if inline_type:
        response = FileResponse(handle, as_attachment=False, filename=filename, content_type=inline_type)
    else:
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        response = FileResponse(handle, as_attachment=True, filename=filename, content_type=content_type)
    response["Cache-Control"] = "private, no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


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


# ---------------------------------------------------------------------------
# Report letture: una riga per persona e notizia
# ---------------------------------------------------------------------------

REPORT_STATI = [
    (COMPLIANCE_NON_LETTO, "Non letta"),
    (COMPLIANCE_NON_CONFORME, "Da riconfermare"),
    (COMPLIANCE_APERTO, "Da confermare"),
    (COMPLIANCE_CONFORME, "Confermata"),
]
REPORT_STATO_LABEL = dict(REPORT_STATI)
_REPORT_STATO_ORDINE = {key: idx for idx, (key, _label) in enumerate(REPORT_STATI)}
_REPORT_PAGE_SIZE = 100


def _report_people_index() -> dict[int, dict]:
    """legacy_user_id -> nome e ruolo, per mostrare persone e non numeri."""
    try:
        from core.models import Profile

        profiles = Profile.objects.values(
            "legacy_user_id", "legacy_ruolo", "user__first_name", "user__last_name", "user__username"
        )
        index: dict[int, dict] = {}
        for p in profiles:
            nome = f"{p['user__first_name'] or ''} {p['user__last_name'] or ''}".strip() or (p["user__username"] or "")
            index[int(p["legacy_user_id"])] = {"nome": nome, "ruolo": p["legacy_ruolo"] or ""}
        return index
    except Exception:
        return {}


def _stato_persona(notizia: Notizia, letture: list[NotiziaLettura]) -> tuple[str, NotiziaLettura | None]:
    """Stato di una persona su una notizia e lettura da mostrare.

    Stessa regola di `_compliance_breakdown`: conta solo la versione corrente;
    chi ha letto solo versioni vecchie deve riconfermare.
    """
    correnti = [lettura for lettura in letture if lettura.versione_letta == notizia.versione]
    if correnti:
        scelta = next((lettura for lettura in correnti if lettura.ack_at), correnti[0])
        if scelta.ack_at:
            return COMPLIANCE_CONFORME, scelta
        if scelta.opened_at:
            return COMPLIANCE_APERTO, scelta
        return COMPLIANCE_NON_LETTO, scelta
    if letture:
        return COMPLIANCE_NON_CONFORME, max(letture, key=lambda lettura: lettura.versione_letta)
    return COMPLIANCE_NON_LETTO, None


def _parse_iso_date(raw: str):
    from datetime import date

    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _report_dataset(request) -> dict:
    """Righe del report (pagina e CSV) con gli stessi filtri."""
    params = request.GET
    notizia_raw = params.get("notizia_id", "").strip()
    filtro_stato = params.get("stato", "").strip()
    if filtro_stato not in REPORT_STATO_LABEL:
        filtro_stato = ""
    q = params.get("q", "").strip()
    da_raw = params.get("da", "").strip()
    a_raw = params.get("a", "").strip()
    da = _parse_iso_date(da_raw)
    a = _parse_iso_date(a_raw)

    notizia_sel = None
    if notizia_raw.isdigit():
        notizia_sel = Notizia.objects.filter(pk=int(notizia_raw)).prefetch_related("audience").first()

    letture_qs = NotiziaLettura.objects.select_related("notizia")
    if notizia_sel is not None:
        letture_qs = letture_qs.filter(notizia=notizia_sel)

    gruppi: dict[tuple[int, int], list[NotiziaLettura]] = {}
    notizie_map: dict[int, Notizia] = {}
    for lettura in letture_qs:
        key = (lettura.notizia_id, int(lettura.legacy_user_id))
        gruppi.setdefault(key, []).append(lettura)
        notizie_map[lettura.notizia_id] = lettura.notizia

    if notizia_sel is not None:
        # Con una notizia scelta compaiono anche i destinatari che non l'hanno mai aperta.
        all_user_ids, role_users_map = _audience_maps()
        for user_id in _target_legacy_user_ids(notizia_sel, all_user_ids, role_users_map):
            gruppi.setdefault((notizia_sel.pk, user_id), [])
        notizie_map[notizia_sel.pk] = notizia_sel

    persone = _report_people_index()
    q_low = q.lower()
    rows: list[dict] = []
    for (notizia_id, user_id), letture in gruppi.items():
        notizia = notizie_map[notizia_id]
        stato, lettura = _stato_persona(notizia, letture)
        persona = persone.get(user_id, {"nome": "", "ruolo": ""})
        if q_low and q_low not in f"{persona['nome']} {persona['ruolo']} {notizia.titolo} {user_id}".lower():
            continue
        if da or a:
            ack = lettura.ack_at if lettura else None
            if ack is None:
                continue
            giorno = timezone.localtime(ack).date() if timezone.is_aware(ack) else ack.date()
            if (da and giorno < da) or (a and giorno > a):
                continue
        rows.append({
            "user_id": user_id,
            "nome": persona["nome"],
            "ruolo": persona["ruolo"],
            "notizia": notizia,
            "stato": stato,
            "stato_label": REPORT_STATO_LABEL[stato],
            "lettura": lettura,
        })

    counts = {key: 0 for key in REPORT_STATO_LABEL}
    for row in rows:
        counts[row["stato"]] += 1
    totale = len(rows)
    if filtro_stato:
        rows = [row for row in rows if row["stato"] == filtro_stato]
    rows.sort(key=lambda r: (
        r["notizia"].titolo.lower(),
        r["notizia"].pk,
        _REPORT_STATO_ORDINE[r["stato"]],
        (r["nome"] or "~").lower(),
        r["user_id"],
    ))
    return {
        "rows": rows,
        "counts": counts,
        "totale": totale,
        "notizia_sel": notizia_sel,
        "filtro_notizia_id": str(notizia_sel.pk) if notizia_sel else "",
        "filtro_stato": filtro_stato,
        "filtro_q": q,
        "filtro_da": da_raw if da else "",
        "filtro_a": a_raw if a else "",
    }


def _conformita_obbligatorie() -> dict:
    """Conferme della versione corrente sui destinatari delle obbligatorie pubblicate."""
    righe = _dashboard_rows(list(
        Notizia.objects.filter(stato=STATO_PUBBLICATA, obbligatoria=True).prefetch_related("audience")
    ))
    dovute = sum(r["target_count"] for r in righe)
    conformi = sum(r["stats"][COMPLIANCE_CONFORME] for r in righe)
    tasso = round(conformi * 100 / dovute, 1) if dovute else 0
    return {"n_notizie": len(righe), "dovute": dovute, "conformi": conformi, "tasso": tasso}


def _querystring(request, **override) -> str:
    params = request.GET.copy()
    params.pop("page", None)
    for key, value in override.items():
        if value in (None, ""):
            params.pop(key, None)
        else:
            params[key] = value
    return params.urlencode()


@login_required
def report(request):
    if not _is_admin_or_hr(request):
        return _forbidden_response(request)

    from django.core.paginator import Paginator

    data = _report_dataset(request)
    page = Paginator(data["rows"], _REPORT_PAGE_SIZE).get_page(request.GET.get("page"))
    stato_tabs = [{
        "key": "",
        "label": "Tutti",
        "count": data["totale"],
        "qs": _querystring(request, stato=None),
        "active": not data["filtro_stato"],
    }]
    for key, label in REPORT_STATI:
        stato_tabs.append({
            "key": key,
            "label": label,
            "count": data["counts"][key],
            "qs": _querystring(request, stato=key),
            "active": data["filtro_stato"] == key,
        })

    return render(request, "notizie/pages/report.html", {
        "page_title": "Report letture",
        **data,
        "page": page,
        "stato_tabs": stato_tabs,
        "qs_corrente": _querystring(request),
        "notizie_qs": Notizia.objects.exclude(stato=STATO_BOZZA).order_by("-pubblicato_il", "-id"),
        "conformita": _conformita_obbligatorie(),
        "filtri_attivi": bool(data["filtro_q"] or data["filtro_da"] or data["filtro_a"]),
    })


@login_required
def report_csv(request):
    if not _is_admin_or_hr(request):
        return HttpResponseForbidden("Accesso negato.")

    data = _report_dataset(request)
    headers = [
        "Persona", "Ruolo", "Utente ID", "Notizia", "Stato", "Versione letta",
        "Versione corrente", "Impronta versione letta", "Aperta il", "Confermata il",
    ]

    def _fmt(dt):
        if not dt:
            return ""
        return (timezone.localtime(dt) if timezone.is_aware(dt) else dt).strftime("%Y-%m-%d %H:%M")

    def rows():
        for row in data["rows"]:
            lettura = row["lettura"]
            yield [
                row["nome"],
                row["ruolo"],
                row["user_id"],
                row["notizia"].titolo,
                row["stato_label"],
                lettura.versione_letta if lettura else "",
                row["notizia"].versione,
                lettura.hash_versione_letta if lettura else "",
                _fmt(lettura.opened_at) if lettura else "",
                _fmt(lettura.ack_at) if lettura else "",
            ]

    return _csv_streaming_response(rows(), headers, "report_notizie.csv")


# ---------------------------------------------------------------------------
# Impostazioni
# ---------------------------------------------------------------------------

_IMPOSTAZIONI_TABS = ("permessi", "aspetto", "registro")
_REGISTRO_PAGE_SIZE = 50
_REGISTRO_MAX = 2000
_AZIONI_LABEL = {
    "notizia_creata": "Creata (bozza)",
    "notizia_creata_pubblicata": "Creata e pubblicata",
    "notizia_modificata": "Modificata",
    "notizia_pubblicata": "Pubblicata",
    "notizia_ripubblicata": "Ripubblicata",
    "notizia_riportata_bozza": "Riportata in bozza",
    "notizia_archiviata": "Archiviata",
    "save_module_branding": "Aspetto del modulo salvato",
    "remove_module_branding_logo": "Logo del modulo rimosso",
}


def _azione_label(azione: str) -> str:
    return _AZIONI_LABEL.get(azione) or (azione or "").replace("_", " ").capitalize()


def _registro_righe(entries) -> list[dict]:
    righe = []
    for entry in entries:
        dettaglio = entry.dettaglio if isinstance(entry.dettaglio, dict) else {}
        notizia_id = dettaglio.get("notizia_id")
        extra = []
        if dettaglio.get("versione"):
            extra.append(f"versione {dettaglio['versione']}")
        if dettaglio.get("stato"):
            extra.append(str(dettaglio["stato"]))
        righe.append({
            "entry": entry,
            "azione_label": _azione_label(entry.azione),
            "notizia_id": notizia_id if isinstance(notizia_id, int) else None,
            "titolo": str(dettaglio.get("titolo") or ""),
            "extra": ", ".join(extra),
        })
    return righe


@legacy_admin_or_acl_required("notizie", "gestione_admin")
def gestione_admin(request):
    """Impostazioni del modulo: permessi della gestione, aspetto, registro attività."""
    from django.core.paginator import Paginator

    tab = request.GET.get("tab", "").strip()
    if tab == "record":
        # L'elenco delle notizie sta solo nella Gestione notizie.
        params = {}
        if request.GET.get("q", "").strip():
            params["q"] = request.GET["q"].strip()
        if request.GET.get("filter_stato", "").strip() in _VALID_STATO_FILTERS:
            params["stato"] = request.GET["filter_stato"].strip()
        target = reverse("notizie_dashboard")
        if params:
            from urllib.parse import urlencode

            target += "?" + urlencode(params)
        return redirect(target)
    if tab == "log":
        tab = "registro"
    if tab not in _IMPOSTAZIONI_TABS:
        tab = "permessi"
    can_edit_dashboard_acl = _is_admin_or_hr(request)

    if request.method == "POST":
        branding_response = handle_module_branding_post(
            request,
            module_key="notizie",
            redirect_to=request.get_full_path() or reverse("notizie_gestione_admin"),
            audit_module="notizie",
            fallback_label="Notizie",
        )
        if branding_response is not None:
            return branding_response

        if request.POST.get("action") == "save_dashboard_acl":
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
            return redirect(request.get_full_path() or reverse("notizie_gestione_admin"))

    context = {
        "page_title": "Impostazioni notizie",
        "tab": tab,
        "can_edit_dashboard_acl": can_edit_dashboard_acl,
        "can_report": can_edit_dashboard_acl,
        "can_dashboard": _can_manage_notizie_dashboard(request),
    }

    if tab == "permessi":
        roles = _dashboard_acl_roles()
        context["dashboard_acl_roles"] = roles
        context["dashboard_acl_enabled"] = sum(1 for role in roles if role.get("enabled"))
    elif tab == "aspetto":
        context.update(get_module_branding_context("notizie", fallback_label="Notizie"))
        context["branding_compact"] = True
    else:
        azione = request.GET.get("azione", "").strip()
        q = request.GET.get("q", "").strip()
        base_qs = AuditLog.objects.filter(modulo="notizie")
        azioni_presenti = sorted(
            {a for a in base_qs.order_by().values_list("azione", flat=True).distinct() if a},
            key=_azione_label,
        )
        log_qs = base_qs.order_by("-created_at")
        if azione:
            log_qs = log_qs.filter(azione=azione)
        righe = _registro_righe(log_qs[:_REGISTRO_MAX])
        if q:
            q_low = q.lower()
            righe = [
                r for r in righe
                if q_low in f"{r['entry'].utente_display} {r['titolo']} {r['azione_label']}".lower()
            ]
        registro_page = Paginator(righe, _REGISTRO_PAGE_SIZE).get_page(request.GET.get("page"))
        ids_pagina = {r["notizia_id"] for r in registro_page.object_list if r["notizia_id"]}
        esistenti = set(Notizia.objects.filter(pk__in=ids_pagina).values_list("pk", flat=True)) if ids_pagina else set()
        for r in registro_page.object_list:
            r["notizia_esiste"] = r["notizia_id"] in esistenti
        context.update({
            "registro_page": registro_page,
            "registro_azioni": [(a, _azione_label(a)) for a in azioni_presenti],
            "registro_azione": azione,
            "registro_q": q,
            "registro_qs": _querystring(request),
        })

    return render(request, "notizie/pages/gestione_admin.html", context)
