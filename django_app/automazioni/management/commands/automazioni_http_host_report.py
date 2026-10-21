"""Host di destinazione delle azioni http_request e se sono ammessi (sola lettura).

Da lanciare prima del deploy dell'elenco chiuso degli host esterni (GDPR 21/10/2026):
ogni azione con un host non ammesso andrebbe in errore alla prossima esecuzione.

Uso:
    python manage.py automazioni_http_host_report
"""
from __future__ import annotations

from urllib.parse import urlsplit

from django.conf import settings
from django.core.management.base import BaseCommand

from automazioni.models import AutomationAction
from automazioni.services import _host_matches, http_external_hosts


class Command(BaseCommand):
    help = "Elenca gli host delle azioni http_request e se sono fra quelli ammessi (sola lettura)"

    def handle(self, *args, **options):
        esterni = http_external_hosts()
        interni = list(getattr(settings, "AUTOMATION_HTTP_ALLOWED_HOSTS", []) or [])
        azioni = AutomationAction.objects.filter(action_type="http_request").select_related("rule").order_by("rule_id", "order")
        bloccate = 0
        for azione in azioni:
            url = str((azione.config_json or {}).get("url_template") or "").strip()
            host = (urlsplit(url).hostname or "").strip() if "://" in url else ""
            if not host or "{" in host:
                esito = "DA VERIFICARE (host calcolato a runtime)"
            elif _host_matches(host, interni) or _host_matches(host, esterni):
                esito = "ammesso"
            else:
                esito = "BLOCCATO"
                if azione.is_enabled and azione.rule.is_active:
                    bloccate += 1
            stato = "attiva" if (azione.is_enabled and azione.rule.is_active) else "spenta"
            self.stdout.write(f"regola {azione.rule_id} «{azione.rule}» azione {azione.pk} ({stato}): {host or '?'} -> {esito}")
        if not azioni:
            self.stdout.write("Nessuna azione http_request.")
        self.stdout.write(f"Azioni attive bloccate: {bloccate}. Host esterni ammessi: {', '.join(esterni)}")
