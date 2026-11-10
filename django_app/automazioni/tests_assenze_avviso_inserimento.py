from importlib import import_module

from django.apps import apps as global_apps
from django.contrib.auth import get_user_model
from django.test import TestCase

from assenze.models import AssenzaInseritaDa

from .assenze_avviso_inserimento import APPROVED_RULE, SKIP_RULE, applica, avvisa_dipendente, togli_doppione
from .models import AutomationAction, AutomationCondition, AutomationRule
from .services import _enrich_assenze_payload, _resolve_action_run_if

MAILBOX = "assenze@example.com"


class AvvisoSaltaApprovazioneTests(TestCase):
    def setUp(self):
        skip = AutomationRule.objects.create(code=SKIP_RULE, name="skip", source_code="assenze",
                                             operation_type="insert", trigger_scope="all_inserts")
        AutomationCondition.objects.create(rule=skip, order=1, field_name="salta_approvazione", operator="is_true", value_type="bool")
        AutomationAction.objects.create(rule=skip, order=1, action_type="update_trigger_record",
                                        config_json={"update_fields": {"moderation_status": 0}})
        AutomationAction.objects.create(rule=skip, order=2, action_type="send_email", description="Avviso",
                                        config_json={"to": MAILBOX, "cc": "{capo_email}", "subject_template": "Synthetic"})
        AutomationAction.objects.create(rule=skip, order=3, action_type="write_log", config_json={"message_template": "x"})
        approved = AutomationRule.objects.create(code=APPROVED_RULE, name="approved", source_code="assenze",
                                                 operation_type="update", trigger_scope="specific_field")
        AutomationCondition.objects.create(rule=approved, order=1, field_name="moderation_status", operator="changed_to",
                                           expected_value="0", value_type="int")

    def _assert_cc_per_autore(self):
        for dal_capo, attese in ((True, [""]), (False, ["{capo_email}"])):
            partono = [m.config_json["cc"] for m in self._mails()
                       if _resolve_action_run_if(m.config_json, {"inserito_dal_capo": dal_capo})[0]]
            self.assertEqual(partono, attese, dal_capo)

    def _mails(self):
        return list(AutomationAction.objects.filter(rule__code=SKIP_RULE, action_type="send_email").order_by("order"))

    def test_caporeparto_in_cc_solo_se_non_ha_inserito_lui(self):
        applica()
        self._assert_cc_per_autore()
        self.assertEqual([m.config_json["to"] for m in self._mails()], [MAILBOX, MAILBOX])
        self.assertEqual(list(AutomationAction.objects.filter(rule__code=SKIP_RULE).order_by("order")
                              .values_list("action_type", flat=True)),
                         ["update_trigger_record", "send_email", "send_email", "write_log"])

    def test_avviso_dopo_approvazione_esclude_salta_approvazione(self):
        applica()
        cond = AutomationCondition.objects.get(rule__code=APPROVED_RULE, field_name="salta_approvazione")
        self.assertEqual((cond.operator, cond.value_type), ("is_false", "bool"))

    def test_migrazione_idempotente_e_fail_closed(self):
        migration = import_module("automazioni.migrations.0031_assenze_avviso_salta_approvazione")
        migration.applica(global_apps, None)
        migration.applica(global_apps, None)
        self.assertEqual(len(self._mails()), 2)
        self.assertEqual(AutomationCondition.objects.filter(rule__code=APPROVED_RULE).count(), 2)

    def test_0034_aggiunge_caporeparto_se_la_mail_andava_solo_ad_assenze(self):
        # Forma di produzione: una sola mail ad assenza@, CC vuoto, nessun run_if.
        AutomationAction.objects.filter(rule__code=SKIP_RULE, action_type="send_email").update(
            config_json={"to": MAILBOX, "cc": "", "subject_template": "Synthetic"})
        migration = import_module("automazioni.migrations.0034_assenze_salta_approvazione_caporeparto_cc")
        migration.applica(global_apps, None)
        migration.applica(global_apps, None)
        self._assert_cc_per_autore()
        self.assertEqual([m.config_json["to"] for m in self._mails()], [MAILBOX, MAILBOX])

    def test_divisione_0031_sul_profilo_passa_al_criterio_autore_capo(self):
        mail = self._mails()[0]
        solo = dict(mail.config_json, cc="", run_if={"field_name": "inserito_da_gruppo", "operator": "equals",
                                                     "expected_value": "CAR", "value_type": "string"})
        AutomationAction.objects.filter(pk=mail.pk).update(config_json=dict(mail.config_json, run_if={**solo["run_if"], "negate": True}))
        AutomationAction.objects.create(rule=mail.rule, order=mail.order + 1, action_type="send_email", config_json=solo)
        self.assertEqual(applica()["mail_inserimento"], "criterio aggiornato")
        self._assert_cc_per_autore()
        self.assertEqual(applica()["mail_inserimento"], "già divisa")

    def test_dipendente_avvisato_tranne_malattia(self):
        applica()
        self.assertEqual(avvisa_dipendente(), "aggiunta")
        self.assertEqual(avvisa_dipendente(), "già presente")
        tipi = list(AutomationAction.objects.filter(rule__code=SKIP_RULE).order_by("order")
                    .values_list("action_type", flat=True))
        self.assertEqual(tipi, ["update_trigger_record", "send_email", "send_email", "send_email", "write_log"])
        mail = self._mails()[-1]
        self.assertEqual(mail.config_json["to"], "{dipendente_email}")
        for tipo, parte in (("Permesso", True), ("Ferie", True), ("Flessibilità", True), ("Malattia", False)):
            self.assertEqual(_resolve_action_run_if(mail.config_json, {"tipo_assenza": tipo})[0], parte, tipo)

    def test_0037_idempotente_e_fail_closed(self):
        migration = import_module("automazioni.migrations.0037_assenze_salta_approvazione_avvisa_dipendente")
        migration.applica(global_apps, None)
        migration.applica(global_apps, None)
        self.assertEqual([m.config_json["to"] for m in self._mails()], [MAILBOX, "{dipendente_email}"])
        AutomationCondition.objects.filter(rule__code=SKIP_RULE).delete()
        with self.assertRaises(ValueError):
            avvisa_dipendente()

    def test_regola_personalizzata_non_viene_toccata(self):
        AutomationAction.objects.filter(rule__code=SKIP_RULE, action_type="send_email").update(config_json={"to": MAILBOX})
        AutomationAction.objects.create(rule=AutomationRule.objects.get(code=SKIP_RULE), order=4,
                                        action_type="send_email", config_json={"to": "altro@example.com"})
        with self.assertRaises(ValueError):
            applica()
        self.assertFalse(AutomationCondition.objects.filter(rule__code=APPROVED_RULE, field_name="salta_approvazione").exists())
        self.assertEqual(len(self._mails()), 2)

    def test_0033_toglie_la_seconda_mail_anche_con_regola_personalizzata(self):
        AutomationAction.objects.filter(rule__code=SKIP_RULE, action_type="send_email").update(config_json={"to": MAILBOX})
        migration = import_module("automazioni.migrations.0033_assenze_una_sola_mail_salta_approvazione")
        migration.applica(global_apps, None)
        migration.applica(global_apps, None)
        cond = AutomationCondition.objects.get(rule__code=APPROVED_RULE, field_name="salta_approvazione")
        self.assertEqual((cond.operator, cond.value_type), ("is_false", "bool"))
        self.assertEqual(len(self._mails()), 1)

    def test_0033_fail_closed_senza_filtro_salta_approvazione(self):
        AutomationCondition.objects.filter(rule__code=SKIP_RULE).delete()
        with self.assertRaises(ValueError):
            togli_doppione()
        self.assertFalse(AutomationCondition.objects.filter(rule__code=APPROVED_RULE, field_name="salta_approvazione").exists())

    def test_payload_assenze_espone_profilo_di_chi_ha_inserito(self):
        AssenzaInseritaDa.objects.create(assenza_id=987654, gruppo="CAR", inserito_da="synthetic.user")
        self.assertEqual(_enrich_assenze_payload({"id": 987654})["inserito_da_gruppo"], "CAR")
        self.assertEqual(_enrich_assenze_payload({"id": 987655})["inserito_da_gruppo"], "")
        self.assertIs(_enrich_assenze_payload({"id": 987654})["inserito_dal_capo"], True)
        self.assertIs(_enrich_assenze_payload({"id": 987655})["inserito_dal_capo"], False)

    def test_caporeparto_con_profilo_amministrazione_conta_come_capo(self):
        get_user_model().objects.create(username="synthetic.capo", email="Capo@example.com")
        get_user_model().objects.create(username="synthetic.admin", email="admin@example.com")
        AssenzaInseritaDa.objects.create(assenza_id=987660, gruppo="AMMINISTRAZIONE", inserito_da="synthetic.capo")
        AssenzaInseritaDa.objects.create(assenza_id=987661, gruppo="AMMINISTRAZIONE", inserito_da="synthetic.admin")
        payload = {"capo_email": "capo@example.com"}
        self.assertIs(_enrich_assenze_payload({**payload, "id": 987660})["inserito_dal_capo"], True)
        self.assertIs(_enrich_assenze_payload({**payload, "id": 987661})["inserito_dal_capo"], False)


class AvvisoMalattiaCapoDoppioTests(TestCase):
    """0036: con l'approvazione unificata il capo non riceve anche «Inserimento malattia»."""

    def _regola(self, code, attiva=True):
        return AutomationRule.objects.create(code=code, name=code, source_code="assenze", operation_type="insert",
                                             trigger_scope="all_inserts", is_active=attiva)

    def _migra(self):
        import_module("automazioni.migrations.0036_assenze_malattia_avviso_capo_doppio").applica(global_apps, None)

    def test_disattiva_avviso_malattia_se_c_e_approvazione_unificata(self):
        self._regola("assenze-approvazione-unificata")
        avviso = self._regola("assenze-pa-malattia-avviso-capo")
        self._migra()
        self._migra()
        avviso.refresh_from_db()
        self.assertFalse(avviso.is_active)
        self.assertTrue(AutomationRule.objects.get(code="assenze-approvazione-unificata").is_active)

    def test_fail_closed_senza_approvazione_unificata(self):
        self._regola("assenze-approvazione-unificata", attiva=False)
        avviso = self._regola("assenze-pa-malattia-avviso-capo")
        self._migra()
        avviso.refresh_from_db()
        self.assertTrue(avviso.is_active)
