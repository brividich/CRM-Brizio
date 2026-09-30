"""Gli avvisi del flusso DPI passano dal motore automazioni (flussi gestiti)."""

from __future__ import annotations

from unittest import mock

from django.core import mail
from django.test import TestCase, override_settings

from automazioni.managed_flows import catalog, install_flows
from automazioni.models import AutomationRule, AutomationRunLog, ManagedFlow

from . import flusso
from .models import CategoriaDPI, DPIImpostazioni, RichiestaDPI, StatoRichiesta

CODICI = ("dpi_richiesta_da_approvare", "dpi_avviso_consegna", "dpi_report_consegna")


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class FlussoDpiNelMotoreTests(TestCase):
    def setUp(self):
        impost = DPIImpostazioni.get_singleton()
        impost.magazzino_emails = "magazzino@example.test"
        impost.amministrazione_emails = "amministrazione@example.test"
        impost.save()
        cat = CategoriaDPI.objects.create(nome="Mani", icona_emoji="gloves", vita_utile_giorni=180)
        self.richiesta = RichiestaDPI.objects.create(
            categoria=cat, stato=StatoRichiesta.APPROVATA, richiedente_nome="Mario Rossi"
        )

    def test_i_tre_avvisi_sono_nel_catalogo_del_motore(self):
        for code in CODICI:
            self.assertIn(code, catalog())
            self.assertEqual(catalog()[code]["kind"], "event")

    def test_dopo_l_installazione_ogni_avviso_e_una_regola_del_designer(self):
        install_flows()
        for code in CODICI:
            self.assertTrue(ManagedFlow.objects.filter(code=code, kind="event").exists(), code)
            self.assertTrue(AutomationRule.objects.filter(code="managed-" + code, is_active=True, is_draft=False).exists())

    def test_l_invio_passa_dal_motore_e_lascia_il_log(self):
        install_flows()
        flusso.notifica_approvata(self.richiesta)
        self.assertEqual(len([m for m in mail.outbox if "Da consegnare" in m.subject]), 1)
        rule = AutomationRule.objects.get(code="managed-dpi_avviso_consegna")
        self.assertTrue(AutomationRunLog.objects.filter(rule=rule, status="success").exists())

    def test_regola_spenta_nel_designer_sopprime_l_avviso(self):
        install_flows()
        AutomationRule.objects.filter(code="managed-dpi_avviso_consegna").update(is_active=False)
        flusso.notifica_approvata(self.richiesta)
        self.assertEqual([m for m in mail.outbox if "Da consegnare" in m.subject], [])

    def test_prima_dell_installazione_l_avviso_parte_comunque(self):
        flusso.notifica_approvata(self.richiesta)
        self.assertEqual(len([m for m in mail.outbox if "Da consegnare" in m.subject]), 1)
