import json
import re

from django.core.management.base import BaseCommand, CommandError
from django.test import RequestFactory

from rest_framework.test import APIRequestFactory, force_authenticate

from security.api import AddonsSummaryApiView, SecurityAddonDetailApiView
from security.api_configuration import ConfigurationOverviewApiView, ConfigurationSourcesApiView
from security.management.commands.seed_security_uat_demo import (
    DEMO_CODE_PREFIX,
    DEMO_MAILBOX_SOURCES,
    DEMO_RAW_BODY_MARKER,
    DEMO_SOURCE_NAME_PREFIX,
    DEMO_SUBJECT_PREFIX,
)
from security.models import SecurityMailboxMessage, SecurityMailboxSource
from security.views import admin_mailbox_source_detail


UNSAFE_SUMMARY_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"password\s*[:=]",
        r"client_secret\s*[:=]",
        r"api[_ -]?key\s*[:=]",
        r"token\s*[:=]",
        r"bearer\s+[a-z0-9._-]{12,}",
        r"sk-[a-z0-9]{12,}",
    )
]


class _SmokeUser:
    is_authenticated = True
    is_staff = True
    is_superuser = True

    def has_perm(self, permission):
        return True


class Command(BaseCommand):
    help = "Run synthetic UAT/demo smoke checks without external calls."

    def handle(self, *args, **options):
        checks = []

        overview_payload = None
        sources_payload = None
        addons_payload = None

        overview_ok, overview_detail, overview_payload = self._check_api_view(
            "Configuration overview API",
            ConfigurationOverviewApiView,
            "/security/api/configuration/overview/",
            lambda payload: payload.get("monitored_sources_count", 0) >= len(DEMO_MAILBOX_SOURCES),
        )
        checks.append((overview_ok, overview_detail))

        sources_ok, sources_detail, sources_payload = self._check_api_view(
            "Configuration sources API",
            ConfigurationSourcesApiView,
            "/security/api/configuration/sources/",
            self._sources_include_demo_codes,
        )
        checks.append((sources_ok, sources_detail))

        checks.append(self._check_demo_sources())
        checks.append(self._check_mailbox_source_page())

        addons_ok, addons_detail, addons_payload = self._check_api_view(
            "Module workspace aggregation API",
            AddonsSummaryApiView,
            "/security/api/addons/summary/",
            self._addons_have_required_modules,
        )
        checks.append((addons_ok, addons_detail))

        checks.append(self._check_addon_details())
        checks.append(self._check_pipeline_summaries())
        checks.append(self._check_api_safety(overview_payload, sources_payload, addons_payload))

        failures = [detail for ok, detail in checks if not ok]
        for ok, detail in checks:
            prefix = "PASS" if ok else "FAIL"
            self.stdout.write(f"{prefix}: {detail}")

        passed = len(checks) - len(failures)
        self.stdout.write(f"Summary: {passed}/{len(checks)} checks passed.")

        if failures:
            self.stdout.write("Next steps:")
            self.stdout.write("- Run: python manage.py seed_security_uat_demo")
            self.stdout.write("- Then rerun: python manage.py security_uat_smoke_check")
            self.stdout.write("- If a page check still fails, verify login/staff permissions and URL routing.")
            raise CommandError("UAT smoke check failed.")

    def _check_demo_sources(self):
        expected_codes = {source["code"] for source in DEMO_MAILBOX_SOURCES}
        found_codes = set(
            SecurityMailboxSource.objects.filter(code__startswith=DEMO_CODE_PREFIX).values_list("code", flat=True)
        )
        missing = sorted(expected_codes - found_codes)
        if missing:
            return False, f"Demo mailbox sources missing: {', '.join(missing)}"
        return True, "Demo mailbox sources exist"

    def _check_mailbox_source_page(self):
        first_code = DEMO_MAILBOX_SOURCES[0]["code"]
        request = RequestFactory().get(f"/security/admin/mailbox-sources/{first_code}/")
        request.user = _SmokeUser()
        response = admin_mailbox_source_detail(request, first_code)
        body = response.content.decode("utf-8", errors="ignore")
        if response.status_code != 200:
            return False, f"Mailbox source SSR page returned HTTP {response.status_code}"
        if DEMO_SOURCE_NAME_PREFIX not in body:
            return False, "Mailbox source SSR page rendered without UAT marker"
        return True, "Mailbox source SSR page renders"

    def _check_addon_details(self):
        required = ["watchguard", "microsoft_defender", "backup_nas"]
        for code in required:
            response = self._api_response(SecurityAddonDetailApiView, f"/api/security/addons/{code}/", code=code)
            if response.status_code != 200:
                return False, f"Addon detail API for {code} returned HTTP {response.status_code}"
            payload = response.data
            if not isinstance(payload.get("runtime_sources", []), list):
                return False, f"Addon detail API for {code} did not aggregate runtime sources"
        return True, "Module addon detail APIs aggregate related data"

    def _check_pipeline_summaries(self):
        messages = SecurityMailboxMessage.objects.filter(
            source__name__startswith=DEMO_SOURCE_NAME_PREFIX,
            subject__startswith=DEMO_SUBJECT_PREFIX,
        )
        if messages.count() < len(DEMO_MAILBOX_SOURCES):
            return False, "Demo mailbox messages are missing"
        for message in messages:
            summary_text = json.dumps(message.pipeline_result, sort_keys=True)
            if DEMO_RAW_BODY_MARKER in summary_text:
                return False, f"Pipeline summary exposes raw body marker for message {message.id}"
            if '"body"' in summary_text or '"raw_payload"' in summary_text:
                return False, f"Pipeline summary contains raw-content fields for message {message.id}"
            if self._contains_unsafe_summary_text(summary_text):
                return False, f"Pipeline summary contains secret-like text for message {message.id}"
        return True, "Pipeline result summaries are compact and safe"

    def _check_api_safety(self, *payloads):
        combined = json.dumps([payload for payload in payloads if payload is not None], sort_keys=True)
        if DEMO_RAW_BODY_MARKER in combined:
            return False, "API summaries expose raw synthetic body text"
        if self._contains_unsafe_summary_text(combined):
            return False, "API summaries expose secret-like strings"
        return True, "API summaries do not expose raw bodies or secret-like strings"

    def _check_api_view(self, label, view_class, path, validator):
        response = self._api_response(view_class, path)
        if response.status_code != 200:
            return False, f"{label} returned HTTP {response.status_code}", None
        payload = response.data
        if not validator(payload):
            return False, f"{label} payload is not coherent for UAT demo data", payload
        return True, f"{label} is coherent", payload

    def _api_response(self, view_class, path, **kwargs):
        request = APIRequestFactory().get(path)
        force_authenticate(request, user=_SmokeUser())
        return view_class.as_view()(request, **kwargs)

    def _sources_include_demo_codes(self, payload):
        if not isinstance(payload, list):
            return False
        found_codes = {item.get("code") for item in payload}
        return {source["code"] for source in DEMO_MAILBOX_SOURCES}.issubset(found_codes)

    def _addons_have_required_modules(self, payload):
        modules = payload.get("modules") if isinstance(payload, dict) else None
        if not isinstance(modules, list):
            return False
        codes = {module.get("code") for module in modules}
        return {"watchguard", "microsoft_defender", "backup_nas"}.issubset(codes)

    def _contains_unsafe_summary_text(self, text):
        return any(pattern.search(text) for pattern in UNSAFE_SUMMARY_PATTERNS)
