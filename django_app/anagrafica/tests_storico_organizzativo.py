"""Storico organizzativo del dipendente come periodi con data di inizio e fine.

Copre: la chiusura automatica del periodo precedente su mansione, reparto, area
aziendale e ruolo aziendale; la decorrenza scelta da HR nei form di anagrafica
aziendale; il backfill della catena di periodi; e il markup della tabella storico
in scheda dipendente.
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
        aperto = self._riga(1006, TIPO_MANSIONE, "Saldatore", datetime.date(2026, 1, 1))
        chiuso = self._riga(1006, TIPO_REPARTO, "UT", datetime.date(2026, 1, 1),
                            fine=datetime.date(2026, 2, 1))
        self.assertTrue(aperto.is_in_corso)
        self.assertFalse(chiuso.is_in_corso)


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


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class MansioneRepartoDecorrenzaViewTests(TestCase):
    """I mini-form di scheda dipendente accettano la data di decorrenza."""

    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()
        cls.admin = User.objects.create_superuser(
            username="storico_view_admin", email="storico_view_admin@x.local", password="x"
        )

    def setUp(self):
        self.client.force_login(self.admin)
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM anagrafica_dipendenti")
            cursor.execute(
                "INSERT INTO anagrafica_dipendenti (aliasusername, nome, cognome, attivo) "
                "VALUES (%s, %s, %s, %s)",
                ["g.storico", "Gino", "Storico", 1],
            )
            cursor.execute(
                "SELECT id FROM anagrafica_dipendenti WHERE aliasusername = %s", ["g.storico"]
            )
            self.legacy_id = int(cursor.fetchone()[0])

    def _periodi(self, tipo):
        return list(
            DipendenteCambiamentoOrganizzativo.objects
            .filter(legacy_anagrafica_id=self.legacy_id, tipo=tipo)
            .order_by("data_effetto")
        )

    def test_mansione_set_usa_la_decorrenza_del_form(self):
        self.client.post(
            reverse("anagrafica:dipendente_mansione_set", args=[self.legacy_id]),
            {"mansione_nome": "Saldatore", "data_decorrenza": "2026-03-15"},
        )
        periodi = self._periodi(TIPO_MANSIONE)
        self.assertEqual(len(periodi), 1)
        self.assertEqual(periodi[0].data_effetto, datetime.date(2026, 3, 15))

    def test_secondo_cambio_mansione_chiude_il_periodo_precedente(self):
        url = reverse("anagrafica:dipendente_mansione_set", args=[self.legacy_id])
        self.client.post(url, {"mansione_nome": "Saldatore", "data_decorrenza": "2026-01-01"})
        self.client.post(url, {"mansione_nome": "Capoturno", "data_decorrenza": "2026-07-01"})
        periodi = self._periodi(TIPO_MANSIONE)
        self.assertEqual([p.valore_nuovo for p in periodi], ["Saldatore", "Capoturno"])
        self.assertEqual(periodi[0].data_fine, datetime.date(2026, 6, 30))
        self.assertIsNone(periodi[1].data_fine)

    def test_decorrenza_malformata_ricade_su_oggi(self):
        from django.utils import timezone
        self.client.post(
            reverse("anagrafica:dipendente_mansione_set", args=[self.legacy_id]),
            {"mansione_nome": "Saldatore", "data_decorrenza": "non-una-data"},
        )
        periodi = self._periodi(TIPO_MANSIONE)
        self.assertEqual(periodi[0].data_effetto, timezone.localdate())

    def test_reparto_set_storicizza_reparto_e_area_aziendale(self):
        rep = Reparto.objects.create(nome="UT")
        area = AreaAziendale.objects.create(nome="IN1", reparto=rep)
        self.client.post(
            reverse("anagrafica:dipendente_reparto_set", args=[self.legacy_id]),
            {"reparto": "UT", "area_aziendale": str(area.pk), "data_decorrenza": "2026-04-01"},
        )
        area_periodi = self._periodi(TIPO_AREA)
        area_az_periodi = self._periodi(TIPO_AREA_AZIENDALE)
        self.assertEqual(len(area_periodi), 1)
        self.assertEqual(area_periodi[0].valore_nuovo, "UT")
        self.assertEqual(area_periodi[0].data_effetto, datetime.date(2026, 4, 1))
        self.assertEqual(len(area_az_periodi), 1)
        self.assertEqual(area_az_periodi[0].valore_nuovo, "IN1")
        self.assertEqual(area_az_periodi[0].data_effetto, datetime.date(2026, 4, 1))

    def test_cambio_area_aziendale_chiude_il_periodo_precedente(self):
        rep = Reparto.objects.create(nome="UT")
        area1 = AreaAziendale.objects.create(nome="IN1", reparto=rep)
        area2 = AreaAziendale.objects.create(nome="IN2", reparto=rep)
        url = reverse("anagrafica:dipendente_reparto_set", args=[self.legacy_id])
        self.client.post(url, {"reparto": "UT", "area_aziendale": str(area1.pk),
                               "data_decorrenza": "2026-01-01"})
        self.client.post(url, {"reparto": "UT", "area_aziendale": str(area2.pk),
                               "data_decorrenza": "2026-09-01"})
        periodi = self._periodi(TIPO_AREA_AZIENDALE)
        self.assertEqual([p.valore_nuovo for p in periodi], ["IN1", "IN2"])
        self.assertEqual(periodi[0].data_fine, datetime.date(2026, 8, 31))
        self.assertIsNone(periodi[1].data_fine)
        # Il reparto non è cambiato: resta un solo periodo, ancora aperto.
        area_periodi = self._periodi(TIPO_AREA)
        self.assertEqual(len(area_periodi), 1)
        self.assertIsNone(area_periodi[0].data_fine)

    def test_storico_in_pagina_mostra_dal_al_e_in_corso(self):
        url = reverse("anagrafica:dipendente_mansione_set", args=[self.legacy_id])
        self.client.post(url, {"mansione_nome": "Saldatore", "data_decorrenza": "2026-01-01"})
        self.client.post(url, {"mansione_nome": "Capoturno", "data_decorrenza": "2026-07-01"})
        resp = self.client.get(
            reverse("anagrafica:dipendente_detail", args=[self.legacy_id])
        )
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode()
        self.assertIn("30-06-2026", content)
        self.assertIn("In corso", content)
        self.assertIn('name="data_decorrenza"', content)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AnagraficaAziendaleStoricoTests(TestCase):
    """Il form completo 'Modifica dati aziendali' storicizza reparto, area
    aziendale e ruolo aziendale con la decorrenza indicata."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            username="storico_az_admin", email="storico_az_admin@x.local", password="x"
        )

    def setUp(self):
        self.client.force_login(self.admin)
        self.rep = Reparto.objects.create(nome="UT")
        self.area = AreaAziendale.objects.create(nome="IN1", reparto=self.rep)
        RuoloAziendale.objects.create(nome="Capoturno")
        RuoloAziendale.objects.create(nome="Responsabile")

    def _periodi(self, legacy_id, tipo):
        return list(
            DipendenteCambiamentoOrganizzativo.objects
            .filter(legacy_anagrafica_id=legacy_id, tipo=tipo)
            .order_by("data_effetto")
        )

    def test_ruolo_aziendale_apre_un_periodo_con_la_decorrenza(self):
        self.client.post(
            reverse("anagrafica:dipendente_aziendale_save", args=[1201]),
            {"area": "UT", "ruolo_aziendale": "Capoturno", "data_decorrenza": "2026-02-01"},
        )
        periodi = self._periodi(1201, TIPO_RUOLO_AZIENDALE)
        self.assertEqual(len(periodi), 1)
        self.assertEqual(periodi[0].valore_nuovo, "Capoturno")
        self.assertEqual(periodi[0].data_effetto, datetime.date(2026, 2, 1))
        self.assertIsNone(periodi[0].data_fine)

    def test_secondo_cambio_ruolo_chiude_il_precedente(self):
        url = reverse("anagrafica:dipendente_aziendale_save", args=[1202])
        self.client.post(url, {"area": "UT", "ruolo_aziendale": "Capoturno",
                               "data_decorrenza": "2026-01-01"})
        self.client.post(url, {"area": "UT", "ruolo_aziendale": "Responsabile",
                               "data_decorrenza": "2026-05-01"})
        periodi = self._periodi(1202, TIPO_RUOLO_AZIENDALE)
        self.assertEqual([p.valore_nuovo for p in periodi], ["Capoturno", "Responsabile"])
        self.assertEqual(periodi[0].data_fine, datetime.date(2026, 4, 30))
        self.assertIsNone(periodi[1].data_fine)

    def test_reparto_dal_form_completo_viene_storicizzato_una_volta_sola(self):
        """Il form salva la riga prima del sync: i valori precedenti vanno letti
        prima del save, altrimenti il cambiamento passerebbe inosservato."""
        url = reverse("anagrafica:dipendente_aziendale_save", args=[1203])
        self.client.post(url, {"area": "UT", "data_decorrenza": "2026-01-01"})
        Reparto.objects.create(nome="MAG")
        self.client.post(url, {"area": "MAG", "data_decorrenza": "2026-06-01"})
        periodi = self._periodi(1203, TIPO_AREA)
        self.assertEqual([p.valore_nuovo for p in periodi], ["UT", "MAG"])
        self.assertEqual(periodi[0].data_fine, datetime.date(2026, 5, 31))
        self.assertIsNone(periodi[1].data_fine)

    def test_area_aziendale_dal_form_completo_viene_storicizzata(self):
        area2 = AreaAziendale.objects.create(nome="IN2", reparto=self.rep)
        url = reverse("anagrafica:dipendente_aziendale_save", args=[1204])
        self.client.post(url, {"area": "UT", "area_aziendale": str(self.area.pk),
                               "data_decorrenza": "2026-01-01"})
        self.client.post(url, {"area": "UT", "area_aziendale": str(area2.pk),
                               "data_decorrenza": "2026-06-01"})
        periodi = self._periodi(1204, TIPO_AREA_AZIENDALE)
        self.assertEqual([p.valore_nuovo for p in periodi], ["IN1", "IN2"])
        self.assertEqual(periodi[0].data_fine, datetime.date(2026, 5, 31))
        self.assertIsNone(periodi[1].data_fine)

    def test_salvataggio_senza_modifiche_non_duplica_periodi(self):
        url = reverse("anagrafica:dipendente_aziendale_save", args=[1205])
        payload = {"area": "UT", "area_aziendale": str(self.area.pk),
                   "ruolo_aziendale": "Capoturno", "data_decorrenza": "2026-01-01"}
        self.client.post(url, payload)
        self.client.post(url, dict(payload, data_decorrenza="2026-06-01"))
        for tipo in (TIPO_AREA, TIPO_AREA_AZIENDALE, TIPO_RUOLO_AZIENDALE):
            with self.subTest(tipo=tipo):
                periodi = self._periodi(1205, tipo)
                self.assertEqual(len(periodi), 1)
                self.assertIsNone(periodi[0].data_fine)

    def test_dati_aziendali_persistono_come_prima(self):
        """Regressione: la storicizzazione non deve alterare il salvataggio."""
        self.client.post(
            reverse("anagrafica:dipendente_aziendale_save", args=[1206]),
            {"area": "UT", "area_aziendale": str(self.area.pk), "ruolo_aziendale": "Capoturno",
             "data_decorrenza": "2026-01-01"},
        )
        az = DipendenteAnagraficaAziendale.objects.get(legacy_anagrafica_id=1206)
        self.assertEqual(az.area, "UT")
        self.assertEqual(az.area_aziendale_id, self.area.pk)
        self.assertEqual(az.ruolo_aziendale, "Capoturno")
