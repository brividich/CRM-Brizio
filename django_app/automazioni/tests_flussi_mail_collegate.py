"""Segnaposto SQL della coda, flussi installati da soli, mail collegate al flusso."""
from datetime import datetime
from unittest.mock import MagicMock, patch

from django.core import mail
from django.core.mail import EmailMessage
from django.test import TestCase, override_settings

from .managed_flows import assicura_installati, catalog, event_flow
from .models import EmailInviata, ManagedFlow


def _cursore_finto():
    cursore = MagicMock()
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursore
    conn.vendor = "microsoft"
    return conn, cursore


class SegnapostoCodaTests(TestCase):
    """mssql-django fa ``sql % ('?', ...)``: con segnaposto ``?`` la query esplodeva."""

    def _formatta_come_mssql(self, sql, params):
        return sql % tuple("?" * len(params))

    def test_schedule_queue_event_usa_percento_s(self):
        from . import services

        conn, cursore = _cursore_finto()
        with patch.object(services, "_queue_table_has_column", return_value=True), \
                patch("django.db.connections", {"default": conn}):
            services._schedule_queue_event(
                source_code="s", source_table="t", source_pk="1", operation_type="insert",
                event_code="e", payload_json="{}", execute_after=datetime(2026, 11, 15, 10, 0),
            )
        sql, params = cursore.execute.call_args[0]
        self.assertNotIn("(?", sql)
        self.assertIn("?", self._formatta_come_mssql(sql, params))

    def test_count_source_usa_percento_s(self):
        from . import services

        conn, cursore = _cursore_finto()
        cursore.fetchone.return_value = (3,)
        with patch("automazioni.source_registry.get_source_definition", return_value={"table_name": "tab"}), \
                patch("automazioni.source_registry.get_source_fields", return_value=[{"name": "a"}, {"name": "d"}]), \
                patch("django.db.connections", {"default": conn}):
            n = services._count_source("x", "a", 1, window_field="d", window_days=7)
        self.assertEqual(n, 3)
        sql, params = cursore.execute.call_args[0]
        self._formatta_come_mssql(sql, params)


class FlussiInstallatiDaSoliTests(TestCase):
    def test_assicura_installati_crea_i_mancanti(self):
        self.assertFalse(ManagedFlow.objects.filter(code="diario_preposto_scheda").exists())
        self.assertGreater(assicura_installati(), 0)
        for codice in ("diario_preposto_scheda", "sicurezza_scheda_segnalazione"):
            self.assertTrue(ManagedFlow.objects.filter(code=codice).exists())
        self.assertEqual(assicura_installati(), 0)
        self.assertEqual(ManagedFlow.objects.count(), len(catalog()))

    def test_non_solleva(self):
        with patch("automazioni.managed_flows.install_flows", side_effect=RuntimeError("db")):
            self.assertEqual(assicura_installati(), 0)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
                   DEFAULT_FROM_EMAIL="noreply@test.local")
class MailCollegateAlFlussoTests(TestCase):
    def setUp(self):
        assicura_installati()
        self.binding = ManagedFlow.objects.select_related("rule").get(code="diario_preposto_scheda")
        self.binding.rule.is_active = True
        self.binding.rule.is_draft = False
        self.binding.rule.save()

    def test_mail_dentro_il_flusso_porta_regola_e_run_log(self):
        @event_flow("diario_preposto_scheda", skipped_result=0)
        def manda():
            return EmailMessage("Scheda prova", "corpo", to=["rspp@example.com"]).send()

        manda()
        self.assertEqual(len(mail.outbox), 1)
        riga = EmailInviata.objects.get(oggetto="Scheda prova")
        self.assertEqual(riga.sorgente, "diario_preposto_scheda")
        self.assertEqual(riga.regola_id, self.binding.rule_id)
        self.assertIsNotNone(riga.run_log_id)

    def test_flussi_per_riga_risale_dalla_sorgente(self):
        from .mail_inviate import flussi_per_riga

        vecchia = EmailInviata.objects.create(origine="modulo", sorgente="diario_preposto_scheda",
                                              destinatari="a@example.com", oggetto="x")
        libera = EmailInviata.objects.create(origine="modulo", sorgente="tickets",
                                             destinatari="a@example.com", oggetto="y")
        righe = list(EmailInviata.objects.select_related("regola").filter(pk__in=[vecchia.pk, libera.pk]))
        flussi_per_riga(righe)
        per_pk = {r.pk: r.flusso for r in righe}
        self.assertEqual(per_pk[vecchia.pk]["rule_id"], self.binding.rule_id)
        self.assertEqual(per_pk[vecchia.pk]["codice"], "diario_preposto_scheda")
        self.assertIsNone(per_pk[libera.pk])


class FlussiNelGruppoDelModuloTests(TestCase):
    def test_schede_sicurezza_nel_gruppo_della_sorgente(self):
        from django.contrib.auth import get_user_model
        from django.urls import reverse

        admin = get_user_model().objects.create_superuser("grp_admin", "grp@example.com", "synthetic")
        self.client.force_login(admin)
        r = self.client.get(reverse("admin_portale:automazioni_rule_list"))
        gruppi = {g["source_code"]: [x.code for x in g["rules"]] for g in r.context["rules_by_source"]}
        self.assertIn("managed-diario_preposto_scheda", gruppi.get("diario_preposto", []))
        self.assertIn("managed-sicurezza_scheda_segnalazione", gruppi.get("rilevazione_incidenti", []))
        self.assertNotIn("managed-diario_preposto", gruppi)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
                   DEFAULT_FROM_EMAIL="noreply@test.local")
class CollegamentoTuttiIPercorsiTests(TestCase):
    def setUp(self):
        assicura_installati()
        for b in ManagedFlow.objects.select_related("rule"):
            b.rule.is_active, b.rule.is_draft = True, False
            b.rule.save(update_fields=["is_active", "is_draft"])

    def _regola(self, codice):
        return ManagedFlow.objects.get(code=codice).rule_id

    def test_ogni_oggetto_censito_riconosce_un_solo_flusso(self):
        import re

        from .mail_inviate import ALTRI_OGGETTI, flusso_da_oggetto
        from .schedules import DIGEST_OGGETTO

        for codice, serie in list(DIGEST_OGGETTO.items()) + list(ALTRI_OGGETTI.items()):
            for testo in serie:
                esempio = re.sub(r"‹[^›]*›", "Reparto A", testo).replace("gg-mm-aaaa", "15-11-2026")
                esempio = re.sub(r"(?<![A-Za-z])N(?![A-Za-z])", "7", esempio)
                self.assertEqual(flusso_da_oggetto(esempio), codice, esempio)
        self.assertEqual(flusso_da_oggetto("Re: una mail qualsiasi"), "")

    def test_send_hub_mail_nel_flusso_tiene_codice_regola_run_log(self):
        from core.email_utils import send_hub_mail

        @event_flow("diario_preposto_scheda", skipped_result=0)
        def manda():
            return send_hub_mail("Scheda hub", "corpo", ["rspp@example.com"], email_type="Diario preposto")

        manda()
        riga = EmailInviata.objects.get(oggetto="Scheda hub")
        self.assertEqual(riga.origine, "hub")
        self.assertEqual(riga.sorgente, "diario_preposto_scheda")
        self.assertEqual(riga.regola_id, self._regola("diario_preposto_scheda"))
        self.assertIsNotNone(riga.run_log_id)

    def test_mail_fuori_flusso_riconosciuta_dall_oggetto(self):
        from core.email_utils import send_hub_mail

        send_hub_mail("[SERVER CRITICO] tls_cert — production", "x", ["it@example.com"], email_type="Monitoraggio")
        riga = EmailInviata.objects.get(oggetto__startswith="[SERVER CRITICO]")
        self.assertEqual(riga.sorgente, "infra_health_alert")
        self.assertEqual(riga.regola_id, self._regola("infra_health_alert"))

    def test_regola_della_coda_non_diventa_automation_queue(self):
        from .managed_flows import _invocation
        from .mail_inviate import registra
        from .models import AutomationRule

        au = AutomationRule.objects.create(code="au-x", name="AU X", source_code="diario_preposto",
                                           operation_type="insert", trigger_scope="all_inserts")
        token = _invocation.set({"code": "automation_queue", "call": None, "used": True,
                                 "rule_id": self._regola("automation_queue"), "run_log_id": None})
        try:
            EmailMessage("Promemoria AU", "x", to=["rspp@example.com"]).send()
            registra(origine="automazione", destinatari=["rspp@example.com"], oggetto="Promemoria AU",
                     sorgente="diario_preposto", record_id=5, regola=au)
        finally:
            _invocation.reset(token)
        riga = EmailInviata.objects.get(oggetto="Promemoria AU")
        self.assertEqual((riga.regola_id, riga.sorgente), (au.pk, "diario_preposto"))
        from .mail_inviate import flussi_per_riga

        righe = list(EmailInviata.objects.select_related("regola").filter(pk=riga.pk))
        flussi_per_riga(righe)
        self.assertEqual(righe[0].flusso["nome"], "AU X")

    def test_righe_vecchie_collegate_e_filtrabili_per_flusso(self):
        from django.contrib.auth import get_user_model
        from django.urls import reverse

        vecchia = EmailInviata.objects.create(
            origine="hub", sorgente="Monitoraggio", destinatari="it@example.com",
            oggetto="[VISITE MEDICHE] 24 scadute + 0 in scadenza - 15-11-2026")
        EmailInviata.objects.create(origine="hub", sorgente="Monitoraggio", destinatari="it@example.com",
                                    oggetto="[Monitoraggio IT] 45 problemi aperti — 15-11-2026")
        admin = get_user_model().objects.create_superuser("lnk_admin", "lnk@example.com", "synthetic")
        self.client.force_login(admin)
        url = reverse("admin_portale:automazioni_mail_inviate")
        r = self.client.get(url)
        righe = {m.pk: m for m in r.context["pagina"]}
        self.assertEqual(righe[vecchia.pk].flusso["codice"], "visite_expiry_reminders")
        self.assertContains(r, reverse("admin_portale:automazioni_pianificati_mail",
                                       kwargs={"name": "visite_expiry_reminders"}))
        r = self.client.get(url, {"flusso": "visite_expiry_reminders"})
        self.assertEqual([m.pk for m in r.context["pagina"]], [vecchia.pk])

    def test_filtro_sorgente_comprende_i_flussi_del_modulo(self):
        from django.contrib.auth import get_user_model
        from django.urls import reverse

        admin = get_user_model().objects.create_superuser("flt_admin", "flt@example.com", "synthetic")
        self.client.force_login(admin)
        r = self.client.get(reverse("admin_portale:automazioni_rule_list"), {"source_code": "diario_preposto"})
        codici = [x.code for g in r.context["rules_by_source"] for x in g["rules"]]
        self.assertIn("managed-diario_preposto_scheda", codici)
        self.assertNotIn("managed-sicurezza_scheda_segnalazione", codici)
        self.assertContains(r, "Evento")

    def test_mail_mandata_da_un_modulo_durante_un_azione_resta_della_regola(self):
        from .models import AutomationAction, AutomationRule, AutomationRunLog
        from .services import execute_action

        au = AutomationRule.objects.create(code="au-kick", name="AU alert progetto", source_code="tasks",
                                           operation_type="insert", trigger_scope="all_inserts")
        azione = AutomationAction.objects.create(rule=au, order=1, action_type="write_log", config_json={})
        run_log = AutomationRunLog.objects.create(rule=au, source_code="tasks", operation_type="insert",
                                                  payload_json={})

        def manda_dal_modulo(*args, **kwargs):
            EmailMessage("Alert progetto", "x", to=["pm@example.com"]).send()
            return {"status": "success", "result_message": ""}

        with patch("automazioni.services._execute_action", side_effect=manda_dal_modulo):
            execute_action(azione, {"id": 1}, run_log=run_log)
        riga = EmailInviata.objects.get(oggetto="Alert progetto")
        self.assertEqual((riga.regola_id, riga.run_log_id), (au.pk, run_log.pk))

    def test_pulsante_modifica_flusso(self):
        from django.contrib.auth import get_user_model
        from django.urls import reverse

        from .models import AutomationRule

        au = AutomationRule.objects.create(code="au-mod", name="AU mod", source_code="assenze",
                                           operation_type="insert", trigger_scope="all_inserts")
        EmailInviata.objects.create(origine="hub", sorgente="Monitoraggio", destinatari="it@example.com",
                                    oggetto="[Monitoraggio IT] 45 problemi aperti — 15-11-2026")
        EmailInviata.objects.create(origine="automazione", sorgente="assenze", destinatari="a@example.com",
                                    oggetto="Regola", regola=au)
        admin = get_user_model().objects.create_superuser("mod_admin", "mod@example.com", "synthetic")
        self.client.force_login(admin)
        r = self.client.get(reverse("admin_portale:automazioni_mail_inviate"))
        self.assertContains(r, ">Modifica flusso</", count=2)
        self.assertContains(r, reverse("admin_portale:automazioni_pianificati_mail",
                                       kwargs={"name": "assets_it_monitoring_alerts"}) + "?next=")
        self.assertContains(r, reverse("admin_portale:automazioni_rule_designer", args=[au.pk]))
        self.assertContains(r, 'id="amp-drawer-body"')
        # Il pannello si apre anche per questo flusso (risposta HTMX).
        p = self.client.get(reverse("admin_portale:automazioni_pianificati_mail",
                                    kwargs={"name": "assets_it_monitoring_alerts"}), HTTP_HX_REQUEST="true")
        self.assertEqual(p.status_code, 200)
