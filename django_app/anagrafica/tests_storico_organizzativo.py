"""Storico organizzativo per-campo: periodi con data di inizio e fine.

È il log di audit sotto agli spostamenti organizzativi (vedi
``tests_assegnazioni.py``): copre la chiusura automatica del periodo precedente
e la distinzione fra periodo in corso e periodo con decorrenza futura.
"""
from __future__ import annotations

import datetime

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import (
    AreaAziendale, DipendenteAnagraficaAziendale, DipendenteCambiamentoOrganizzativo,
    Reparto, RuoloAziendale,
)
from .tests import _ensure_anagrafica_table

User = get_user_model()

TIPO_MANSIONE = DipendenteCambiamentoOrganizzativo.TIPO_MANSIONE
TIPO_REPARTO = DipendenteCambiamentoOrganizzativo.TIPO_REPARTO
TIPO_AREA = DipendenteCambiamentoOrganizzativo.TIPO_AREA
TIPO_AREA_AZIENDALE = DipendenteCambiamentoOrganizzativo.TIPO_AREA_AZIENDALE
TIPO_RUOLO_AZIENDALE = DipendenteCambiamentoOrganizzativo.TIPO_RUOLO_AZIENDALE


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class ChiusuraPeriodoTests(TestCase):
    """chiudi_periodo_aperto trasforma la sequenza di eventi in intervalli contigui."""

    def _riga(self, legacy_id, tipo, nuovo, inizio, fine=None):
        return DipendenteCambiamentoOrganizzativo.objects.create(
            legacy_anagrafica_id=legacy_id, tipo=tipo, valore_nuovo=nuovo,
            data_effetto=inizio, data_fine=fine,
        )

    def test_periodo_aperto_si_chiude_al_giorno_prima_della_nuova_decorrenza(self):
        vecchio = self._riga(1001, TIPO_MANSIONE, "Saldatore", datetime.date(2026, 1, 1))
        chiuse = DipendenteCambiamentoOrganizzativo.chiudi_periodo_aperto(
            1001, TIPO_MANSIONE, datetime.date(2026, 6, 1)
        )
        vecchio.refresh_from_db()
        self.assertEqual(chiuse, 1)
        self.assertEqual(vecchio.data_fine, datetime.date(2026, 5, 31))

    def test_nessun_periodo_aperto_non_fa_nulla(self):
        self._riga(1002, TIPO_MANSIONE, "Saldatore", datetime.date(2026, 1, 1),
                   fine=datetime.date(2026, 3, 1))
        chiuse = DipendenteCambiamentoOrganizzativo.chiudi_periodo_aperto(
            1002, TIPO_MANSIONE, datetime.date(2026, 6, 1)
        )
        self.assertEqual(chiuse, 0)

    def test_chiusura_isolata_per_tipo_e_per_dipendente(self):
        altro_tipo = self._riga(1003, TIPO_REPARTO, "UT", datetime.date(2026, 1, 1))
        altro_dip = self._riga(1004, TIPO_MANSIONE, "Saldatore", datetime.date(2026, 1, 1))
        DipendenteCambiamentoOrganizzativo.chiudi_periodo_aperto(
            1003, TIPO_MANSIONE, datetime.date(2026, 6, 1)
        )
        altro_tipo.refresh_from_db()
        altro_dip.refresh_from_db()
        self.assertIsNone(altro_tipo.data_fine)
        self.assertIsNone(altro_dip.data_fine)

    def test_decorrenza_retroattiva_non_genera_fine_prima_dell_inizio(self):
        vecchio = self._riga(1005, TIPO_MANSIONE, "Saldatore", datetime.date(2026, 6, 1))
        DipendenteCambiamentoOrganizzativo.chiudi_periodo_aperto(
            1005, TIPO_MANSIONE, datetime.date(2026, 1, 1)
        )
        vecchio.refresh_from_db()
        self.assertEqual(vecchio.data_fine, datetime.date(2026, 6, 1))
        self.assertGreaterEqual(vecchio.data_fine, vecchio.data_effetto)

    def test_is_in_corso_riflette_data_fine(self):
        from django.utils import timezone
        oggi = timezone.localdate()
        aperto = self._riga(1006, TIPO_MANSIONE, "Saldatore", oggi - datetime.timedelta(days=30))
        chiuso = self._riga(1006, TIPO_REPARTO, "UT", oggi - datetime.timedelta(days=30),
                            fine=oggi - datetime.timedelta(days=1))
        self.assertTrue(aperto.is_in_corso)
        self.assertFalse(chiuso.is_in_corso)

    def test_periodo_con_decorrenza_futura_e_programmato_non_in_corso(self):
        """Il bug segnalato: una riga aperta ma datata al futuro non è "in corso"
        — il valore vecchio è ancora quello valido oggi."""
        from django.utils import timezone
        futuro = timezone.localdate() + datetime.timedelta(days=24)
        riga = self._riga(1007, TIPO_REPARTO, "TORNI", futuro)
        self.assertTrue(riga.is_programmato)
        self.assertFalse(riga.is_in_corso)

    def test_periodo_aperto_gia_decorso_e_in_corso_non_programmato(self):
        from django.utils import timezone
        passato = timezone.localdate() - datetime.timedelta(days=3)
        riga = self._riga(1008, TIPO_REPARTO, "CNC", passato)
        self.assertFalse(riga.is_programmato)
        self.assertTrue(riga.is_in_corso)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class RegistraCambiamentoTests(TestCase):
    """_registra_cambiamento apre un periodo e chiude quello precedente."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            username="storico_reg_admin", email="storico_reg_admin@x.local", password="x"
        )

    def test_due_cambiamenti_producono_una_catena_di_periodi(self):
        from .views import _registra_cambiamento
        _registra_cambiamento(1101, TIPO_MANSIONE, "", "Saldatore", self.admin,
                              data_effetto=datetime.date(2026, 1, 1))
        _registra_cambiamento(1101, TIPO_MANSIONE, "Saldatore", "Capoturno", self.admin,
                              data_effetto=datetime.date(2026, 6, 1))
        periodi = list(
            DipendenteCambiamentoOrganizzativo.objects
            .filter(legacy_anagrafica_id=1101, tipo=TIPO_MANSIONE)
            .order_by("data_effetto")
        )
        self.assertEqual(len(periodi), 2)
        self.assertEqual(periodi[0].valore_nuovo, "Saldatore")
        self.assertEqual(periodi[0].data_fine, datetime.date(2026, 5, 31))
        self.assertEqual(periodi[1].valore_nuovo, "Capoturno")
        self.assertIsNone(periodi[1].data_fine)

    def test_un_solo_periodo_in_corso_per_tipo(self):
        from .views import _registra_cambiamento
        for anno, valore in ((2024, "A"), (2025, "B"), (2026, "C")):
            _registra_cambiamento(1102, TIPO_MANSIONE, "", valore, self.admin,
                                  data_effetto=datetime.date(anno, 1, 1))
        aperti = DipendenteCambiamentoOrganizzativo.objects.filter(
            legacy_anagrafica_id=1102, tipo=TIPO_MANSIONE, data_fine__isnull=True
        )
        self.assertEqual(aperti.count(), 1)
        self.assertEqual(aperti.first().valore_nuovo, "C")

    def test_valore_invariato_non_chiude_il_periodo_in_corso(self):
        from .views import _registra_cambiamento
        _registra_cambiamento(1103, TIPO_MANSIONE, "", "Saldatore", self.admin,
                              data_effetto=datetime.date(2026, 1, 1))
        esito = _registra_cambiamento(1103, TIPO_MANSIONE, "Saldatore", " saldatore ", self.admin,
                                      data_effetto=datetime.date(2026, 6, 1))
        self.assertIsNone(esito)
        riga = DipendenteCambiamentoOrganizzativo.objects.get(
            legacy_anagrafica_id=1103, tipo=TIPO_MANSIONE
        )
        self.assertIsNone(riga.data_fine)

    def test_senza_decorrenza_esplicita_il_periodo_parte_da_oggi(self):
        from django.utils import timezone
        from .views import _registra_cambiamento
        riga = _registra_cambiamento(1104, TIPO_MANSIONE, "", "Saldatore", self.admin)
        self.assertEqual(riga.data_effetto, timezone.localdate())
