"""Campanella: non lette in alto, azioni sulla singola voce, modulo riconoscibile, avvisi dalle mail delle regole."""
from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from core.models import Notifica
from core.notifiche_meta import MODULI, TIPO_META, notifica_meta, tipi_del_modulo
from core.templatetags.notifiche_extras import quando_notifica


class RegistroModuliTests(SimpleTestCase):
    def test_ogni_tipo_ha_modulo_e_categoria_validi(self):
        from core.notifiche_meta import CATEGORIE

        for tipo, meta in TIPO_META.items():
            self.assertIn(meta["modulo"], MODULI, tipo)
            self.assertIn(meta["categoria"], CATEGORIE, tipo)

    def test_tipo_ignoto_ricade_in_altro(self):
        self.assertEqual(notifica_meta("inesistente")["modulo"], "altro")
        self.assertIn("ticket_risolto", tipi_del_modulo("ticket"))

    def test_quando(self):
        ora = timezone.now()
        self.assertEqual(quando_notifica(ora), "adesso")
        self.assertEqual(quando_notifica(ora - timedelta(minutes=12)), "12 min fa")
        self.assertEqual(quando_notifica(None), "")


class CampanellaDaMailTests(TestCase):
    def _azione(self, sorgente, **config):
        return SimpleNamespace(config_json=config, rule=SimpleNamespace(source_code=sorgente))

    def test_ticket_link_diverso_per_richiedente_e_gestore(self):
        from automazioni.campanella import da_mail

        ids = {"rich@example.test": [11], "tec@example.test": [22]}
        with mock.patch("core.notifiche.legacy_user_ids_for_email", side_effect=lambda e: ids.get(e, [])):
            n = da_mail(self._azione("tickets"), {"id": 5, "richiedente_email": "rich@example.test"},
                        ["Rich@example.test", "tec@example.test"], "Ticket #5 chiuso")
        self.assertEqual(n, 2)
        self.assertEqual(Notifica.objects.get(legacy_user_id=11).url_azione, "/tickets/5/")
        self.assertEqual(Notifica.objects.get(legacy_user_id=22).url_azione, "/tickets/gestione/5/")
        self.assertEqual(Notifica.objects.get(legacy_user_id=11).tipo, "ticket_avviso")

    def test_niente_doppione_se_il_modulo_ha_gia_avvisato(self):
        from automazioni.campanella import da_mail

        Notifica.objects.create(legacy_user_id=7, tipo="assenza_approvata", messaggio="ok",
                                url_azione="/assenze/le-mie-richieste/")
        with mock.patch("core.notifiche.legacy_user_ids_for_email", return_value=[7]):
            n = da_mail(self._azione("assenze"), {"capo_email": "capo@example.test"}, ["dip@example.test"], "Esito")
        self.assertEqual(n, 0)

    def test_altre_sorgenti_solo_se_richiesto(self):
        from automazioni.campanella import da_mail

        with mock.patch("core.notifiche.legacy_user_ids_for_email", return_value=[3]):
            self.assertEqual(da_mail(self._azione("anomalie"), {}, ["x@example.test"], "A"), 0)
            self.assertEqual(da_mail(self._azione("anomalie", campanella=True), {}, ["x@example.test"], "A"), 1)
            self.assertEqual(da_mail(self._azione("tickets", campanella=False), {"id": 1}, ["x@example.test"], "B"), 0)
        self.assertEqual(Notifica.objects.get(legacy_user_id=3).tipo, "automazione")
