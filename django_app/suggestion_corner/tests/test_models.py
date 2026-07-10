from __future__ import annotations

import datetime

from django.test import TestCase
from django.utils import timezone

from django.core.exceptions import ValidationError

from anagrafica.models import AreaAziendale, Reparto
from suggestion_corner.models import SuggestionCorner


class ProvenienzaRepartoAreaTest(TestCase):
    """Provenienza/destinazione = Reparto OPPURE Area Aziendale."""

    def setUp(self):
        self.cnc = Reparto.objects.create(nome="CNC")
        self.it = AreaAziendale.objects.create(nome="IT", reparto=self.cnc)
        self.orfana = AreaAziendale.objects.create(nome="GENERICA", reparto=None)

    def test_save_area_valorizza_reparto_padre(self):
        s = SuggestionCorner.objects.create(
            area_provenienza=self.it, opportunity="x")
        s = SuggestionCorner.objects.get(pk=s.pk)  # re-fetch (FSMField vieta refresh_from_db)
        self.assertEqual(s.area_provenienza, self.it)
        self.assertEqual(s.reparto_provenienza, self.cnc)  # padre dedotto

    def test_save_area_senza_padre_lascia_reparto_nullo(self):
        s = SuggestionCorner.objects.create(
            area_provenienza=self.orfana, opportunity="x")
        s = SuggestionCorner.objects.get(pk=s.pk)
        self.assertEqual(s.area_provenienza, self.orfana)
        self.assertIsNone(s.reparto_provenienza)

    def test_clean_nuova_senza_provenienza_fallisce(self):
        s = SuggestionCorner(opportunity="x")  # né reparto né area, non importata
        with self.assertRaises(ValidationError):
            s.clean()

    def test_clean_record_storico_esente(self):
        # Un record importato (legacy_sharepoint_id) può non avere provenienza.
        s = SuggestionCorner(opportunity="x", legacy_sharepoint_id=42)
        s.clean()  # non solleva

    def test_clean_ok_con_solo_area(self):
        s = SuggestionCorner(opportunity="x", area_provenienza=self.it)
        s.clean()  # non solleva

    def test_provenienza_display_priorita_area(self):
        s = SuggestionCorner.objects.create(
            reparto_provenienza=self.cnc, area_provenienza=self.it, opportunity="x")
        self.assertEqual(s.provenienza_display, "IT")  # area vince sul reparto

    def test_provenienza_display_solo_reparto(self):
        s = SuggestionCorner.objects.create(reparto_provenienza=self.cnc, opportunity="x")
        self.assertEqual(s.provenienza_display, "CNC")

    def test_destinazione_display_vuota(self):
        s = SuggestionCorner.objects.create(reparto_provenienza=self.cnc, opportunity="x")
        self.assertEqual(s.destinazione_display, "—")


class SuggestionCornerModelTest(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="TORNI")

    def _base(self, **kw):
        defaults = dict(
            reparto_provenienza=self.reparto,
            opportunity="Migliorare l'illuminazione del reparto.",
        )
        defaults.update(kw)
        return SuggestionCorner.objects.create(**defaults)

    def test_stato_default_inserita(self):
        s = self._base()
        self.assertEqual(s.stato, "INSERITA")
        self.assertEqual(s.stato_sms, SuggestionCorner.StatoSMS.DA_GESTIRE)
        self.assertTrue(s.da_portale)
        self.assertFalse(s.anonima)

    def test_scaduto_do_true_quando_limite_passato_e_non_eseguito(self):
        ieri = timezone.now().date() - datetime.timedelta(days=1)
        s = self._base(data_limite_esecuzione=ieri, do_eseguito=False)
        self.assertTrue(s.scaduto_do)

    def test_scaduto_do_false_se_eseguito(self):
        ieri = timezone.now().date() - datetime.timedelta(days=1)
        s = self._base(data_limite_esecuzione=ieri, do_eseguito=True)
        self.assertFalse(s.scaduto_do)

    def test_scaduto_do_false_senza_limite(self):
        s = self._base()
        self.assertFalse(s.scaduto_do)

    def test_scaduto_check_true_quando_limite_passato_e_non_eseguito(self):
        ieri = timezone.now().date() - datetime.timedelta(days=1)
        s = self._base(data_limite_controllo=ieri, check_eseguito=False)
        self.assertTrue(s.scaduto_check)

    def test_scaduto_check_false_se_eseguito(self):
        ieri = timezone.now().date() - datetime.timedelta(days=1)
        s = self._base(data_limite_controllo=ieri, check_eseguito=True)
        self.assertFalse(s.scaduto_check)

    def test_scaduto_check_false_senza_limite(self):
        s = self._base()
        self.assertFalse(s.scaduto_check)


class SuggestionCornerAllegatoTest(TestCase):
    def test_allegato_link_esterno(self):
        from suggestion_corner.models import SuggestionCornerAllegato

        reparto = Reparto.objects.create(nome="CNC")
        seg = SuggestionCorner.objects.create(
            reparto_provenienza=reparto, opportunity="Test allegato.",
        )
        a = SuggestionCornerAllegato.objects.create(
            segnalazione=seg,
            link_esterno=r"\\novisrv\Area Qualita\SMS_Suggestion Corner\2024",
        )
        self.assertEqual(seg.allegati.count(), 1)
        self.assertIn("novisrv", a.link_esterno)


class SuggestionCornerStoricoTest(TestCase):
    def test_storico_voce_manuale(self):
        from suggestion_corner.models import SuggestionCornerStorico

        reparto = Reparto.objects.create(nome="PRESETTING")
        seg = SuggestionCorner.objects.create(
            reparto_provenienza=reparto, opportunity="Test storico.",
        )
        v = SuggestionCornerStorico.objects.create(
            segnalazione=seg, stato_precedente="INSERITA", stato_nuovo="DA_CLASSIFICARE",
        )
        self.assertEqual(seg.storico.count(), 1)
        self.assertEqual(v.stato_nuovo, "DA_CLASSIFICARE")


class SuggestionCornerConfigTest(TestCase):
    def test_config_singleton_forza_pk_1(self):
        from suggestion_corner.models import SuggestionCornerConfig

        c1 = SuggestionCornerConfig.load()
        c1.giorni_sollecito_1 = 20
        c1.save()
        c2 = SuggestionCornerConfig.load()
        self.assertEqual(c2.pk, 1)
        self.assertEqual(c2.giorni_sollecito_1, 20)
        self.assertEqual(SuggestionCornerConfig.objects.count(), 1)

    def test_config_default(self):
        from suggestion_corner.models import SuggestionCornerConfig

        c = SuggestionCornerConfig.load()
        self.assertEqual(c.giorni_sollecito_1, 30)
        self.assertEqual(c.giorni_sollecito_2, 15)
        self.assertEqual(c.giorni_sollecito_3, 5)
        self.assertEqual(c.giorni_escalation_oltre_scadenza, 7)
        self.assertEqual(c.sms_team_group_name, "SMS_TEAM")


class SuggestionCornerProcessoMappingTest(TestCase):
    def test_mapping_valore_libero_unique(self):
        from django.db import IntegrityError

        from suggestion_corner.models import SuggestionCornerProcessoMapping

        SuggestionCornerProcessoMapping.objects.create(valore_libero="Tornitura")
        with self.assertRaises(IntegrityError):
            SuggestionCornerProcessoMapping.objects.create(valore_libero="Tornitura")
