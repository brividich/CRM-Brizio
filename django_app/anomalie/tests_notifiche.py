"""Pannello unico delle mail anomalie (Configurazione → Notifiche e Automazioni).

Lo stesso dato si vede e si modifica da due pagine: il pannello legge e scrive
dove i dati stanno già (liste del modulo, SiteConfig, regola Automazioni).
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from anomalie import notifiche
from anomalie import views as anomalie_views
from anomalie.escalation_config import get_escalation_config
from automazioni.models import AutomationAction, AutomationActionType, AutomationRule

User = get_user_model()


class _ListeTmpMixin:
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.lists_path = Path(self._tmp.name) / "anomalie_liste.json"
        self.lists_path.write_text(json.dumps({
            "causali_doc": ["OP", "XX"],
            "conferma_aggiornamenti": ["vecchio@example.test"],
        }), encoding="utf-8")
        p = patch.object(anomalie_views, "_anomalie_lists_path", return_value=self.lists_path)
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self._tmp.cleanup)

    def _file(self):
        return json.loads(self.lists_path.read_text(encoding="utf-8"))

    def _regola(self, to="it@example.test", attiva=True):
        rule = AutomationRule.objects.create(
            code=notifiche.REGOLA_NUOVA_ANOMALIA, name="Nuova anomalia", source_code="anomalie",
            operation_type="insert", is_active=attiva, is_draft=False,
        )
        AutomationAction.objects.create(
            rule=rule, order=1, action_type=AutomationActionType.SEND_ANOMALIE_MAIL_ACTION,
            config_json={"to": to, "action": "aggiorna_avanzamento"},
        )
        return rule


class StatoPannelloTests(_ListeTmpMixin, TestCase):
    def test_elenca_tutte_le_mail_con_liste_e_regola(self):
        self._regola()
        stato = notifiche.stato_pannello()
        codes = [r["code"] for r in stato["righe"]]
        self.assertEqual(codes, ["controllo", "nuova_anomalia", "riepilogo", "decisioni_operatore",
                                 "op_completato", "resoconto", "rdc", "ricorrenza", "digest"])
        liste = {l["key"]: l["valori"] for l in stato["liste"]}
        self.assertEqual(liste["conferma_aggiornamenti"], ["vecchio@example.test"])
        self.assertEqual(stato["nuova_anomalia"]["to"], "it@example.test")
        self.assertTrue(stato["nuova_anomalia"]["attiva"])

    def test_senza_regola_la_mail_nuova_anomalia_risulta_spenta(self):
        stato = notifiche.stato_pannello()
        riga = next(r for r in stato["righe"] if r["code"] == "nuova_anomalia")
        self.assertFalse(riga["attiva"])
        self.assertIsNone(riga["toggle"])


class SalvaPannelloTests(_ListeTmpMixin, TestCase):
    def test_salva_liste_senza_toccare_le_altre(self):
        ok, _msg = notifiche.salva_pannello({"liste": {
            "conferma_aggiornamenti": ["a@example.test", "A@example.test"],
            "escalation_supervisori": "s1@example.test\ns2@example.test",
        }})
        self.assertTrue(ok)
        data = self._file()
        self.assertEqual(data["conferma_aggiornamenti"], ["a@example.test"])
        self.assertEqual(data["escalation_supervisori"], ["s1@example.test", "s2@example.test"])
        self.assertEqual(data["causali_doc"], ["OP", "XX"])

    def test_email_non_valida_blocca_tutto(self):
        ok, msg = notifiche.salva_pannello({"liste": {"conferma_aggiornamenti": ["non-una-mail"]}})
        self.assertFalse(ok)
        self.assertIn("non-una-mail", msg)
        self.assertEqual(self._file()["conferma_aggiornamenti"], ["vecchio@example.test"])

    def test_interruttori_e_soglie_finiscono_in_siteconfig(self):
        ok, _ = notifiche.salva_pannello({
            "attivi": {"attivo": True, "digest_attivo": True, "decisioni_operatore_attivo": False},
            "parametri": {"soglia_ore": 48, "ora_invio": 7, "ricorrenza_n": 5},
        })
        self.assertTrue(ok)
        cfg = get_escalation_config()
        self.assertTrue(cfg["attivo"])
        self.assertTrue(cfg["digest_attivo"])
        self.assertFalse(cfg["decisioni_operatore_attivo"])
        self.assertEqual((cfg["soglia_ore"], cfg["ora_invio"], cfg["ricorrenza_n"]), (48, 7, 5))

    def test_indirizzo_nuova_anomalia_va_nella_regola(self):
        rule = self._regola()
        ok, _ = notifiche.salva_pannello({"nuova_anomalia": {"to": "qualita@example.test", "attiva": True}})
        self.assertTrue(ok)
        action = rule.actions.get()
        self.assertEqual(action.config_json["to"], "qualita@example.test")
        self.assertEqual(action.config_json["action"], "aggiorna_avanzamento")
        rule.refresh_from_db()
        self.assertTrue(rule.is_active)

    def test_indirizzo_vuoto_spegne_la_regola(self):
        rule = self._regola()
        ok, _ = notifiche.salva_pannello({"nuova_anomalia": {"to": "", "attiva": True}})
        self.assertTrue(ok)
        rule.refresh_from_db()
        self.assertFalse(rule.is_active)


class PagineNotificheTests(_ListeTmpMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser("ntf_admin", "ntf@example.test", "x")

    def test_api_nega_chi_non_gestisce_la_configurazione(self):
        user = User.objects.create_user("ntf_user", "u@example.test", "x")
        self.client.force_login(user)
        with patch.object(anomalie_views, "_can_manage_anomalie_config", return_value=False):
            r = self.client.post(reverse("api_anomalie_notifiche"), data="{}", content_type="application/json")
        self.assertEqual(r.status_code, 403)

    def test_api_salva(self):
        self.client.force_login(self.admin)
        r = self.client.post(
            reverse("api_anomalie_notifiche"),
            data=json.dumps({"liste": {"rdc_segnalazione": ["rdc@example.test"]}}),
            content_type="application/json",
        )
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(self._file()["rdc_segnalazione"], ["rdc@example.test"])

    def test_stesso_pannello_in_configurazione_e_in_automazioni(self):
        self._regola(to="it@example.test")
        self.client.force_login(self.admin)
        conf = self.client.get(reverse("anomalie_configurazione_page") + "?tab=notifiche")
        auto = self.client.get(reverse("admin_portale:automazioni_event_notifications"))
        for r in (conf, auto):
            self.assertEqual(r.status_code, 200)
            self.assertContains(r, 'id="ntf-panel"')
            self.assertContains(r, "Resoconto OP da controllare")
            self.assertContains(r, "vecchio@example.test")
            self.assertContains(r, 'value="it@example.test"')
            self.assertContains(r, "Salva notifiche")

    def test_configurazione_non_ha_piu_i_campi_email_doppi(self):
        self.client.force_login(self.admin)
        r = self.client.get(reverse("anomalie_configurazione_page") + "?tab=config")
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'id="conferma_aggiornamenti"')
        self.assertNotContains(r, 'id="esc_attivo"')
        self.assertContains(r, "?tab=notifiche")
