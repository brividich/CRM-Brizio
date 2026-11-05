"""Centri di costo: un centro con più reparti (aree), un reparto in un solo centro."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


from .centri_costo_dati import ALIAS_AREA, ELENCO, NUOVE_AREE, assicura_cam_manager, carica_elenco
from .models import AmbitoRuolo, AreaAziendale, CentroDiCosto, Reparto, RuoloOperativo, SubnavLinkAnagrafica


def _carica():
    return carica_elenco(CentroDiCosto, AreaAziendale, Reparto, RuoloOperativo)


class ElencoTests(TestCase):
    def setUp(self):
        self.ut = Reparto.objects.create(nome="UT")
        self.agg = Reparto.objects.create(nome="AGG/MONT")
        self.controllo = Reparto.objects.create(nome="CONTROLLO")
        self.aggiustaggio = AreaAziendale.objects.create(nome="AGGIUSTAGGIO", reparto=self.agg)
        self.marcatura = AreaAziendale.objects.create(nome="MARCATURA", reparto=self.agg)
        self.it = AreaAziendale.objects.create(nome="IT", reparto=self.ut)
        self.taratura = AreaAziendale.objects.create(nome="Taratura", reparto=self.controllo, is_active=False)
        self.direzione = AreaAziendale.objects.create(nome="DIREZIONE", reparto=self.ut)
        self.car = RuoloOperativo.objects.create(nome="Caporeparto", sigla="CAR")
        self.manuale = RuoloOperativo.objects.create(nome="Operatore Manuale")
        self.itm = RuoloOperativo.objects.create(nome="Information Technology Manager", sigla="ITM")

    def test_elenco_coerente(self):
        reparti = [r for r, _c, _ruoli in ELENCO]
        self.assertEqual(len(reparti), len(set(reparti)))
        self.assertEqual(len({c for _r, c, _ruoli in ELENCO if c}), 25)
        self.assertLessEqual(set(ALIAS_AREA) | set(NUOVE_AREE), set(reparti))

    def test_piu_reparti_nello_stesso_centro(self):
        _carica()
        centro = CentroDiCosto.objects.get(nome="AGGIUSTAGGIO")
        self.assertEqual(
            set(centro.aree.values_list("nome", flat=True)),
            {"AGGIUSTAGGIO", "LAVAGGIO CONDOTTI", "MARCATURA", "PROVA PRESSIONE"},
        )

    def test_alias_collega_area_senza_rinominarla(self):
        _carica()
        self.it.refresh_from_db()
        self.assertEqual(self.it.nome, "IT")
        self.assertEqual(self.it.centro_di_costo.nome, "STRUTTURA")
        self.assertFalse(AreaAziendale.objects.filter(nome="UFFICIO IT").exists())

    def test_reparto_mancante_nasce_vuoto_nel_reparto_del_portale(self):
        esito = _carica()
        self.assertIn("CND", esito["aree_create"])
        cnd = AreaAziendale.objects.get(nome="CND")
        self.assertEqual(cnd.reparto, self.controllo)
        self.assertEqual(cnd.centro_di_costo.nome, "CND")
        self.assertIsNone(AreaAziendale.objects.get(nome="TNCG").reparto)

    def test_area_spenta_dell_elenco_si_riattiva(self):
        esito = _carica()
        self.taratura.refresh_from_db()
        self.assertTrue(self.taratura.is_active)
        self.assertEqual(esito["aree_riattivate"], ["Taratura"])
        self.assertEqual(self.taratura.centro_di_costo.nome, "STRUTTURA")

    def test_direzione_senza_centro(self):
        _carica()
        self.direzione.refresh_from_db()
        self.assertIsNone(self.direzione.centro_di_costo)

    def test_ruoli_per_sigla_e_nome_e_nessun_ruolo_inventato(self):
        esito = _carica()
        self.assertEqual(set(self.aggiustaggio.ruoli_reparto.all()), {self.car, self.manuale})
        self.assertEqual(set(self.it.ruoli_reparto.all()), {self.itm})
        self.assertIn("CAMM", esito["ruoli_mancanti"])
        self.assertFalse(RuoloOperativo.objects.filter(nome="CAMM").exists())

    def test_rilancio_non_cambia_le_scelte_fatte(self):
        _carica()
        altro = CentroDiCosto.objects.create(nome="ALTRO")
        self.marcatura.refresh_from_db()
        self.marcatura.centro_di_costo = altro
        self.marcatura.save()
        conteggi = (CentroDiCosto.objects.count(), AreaAziendale.objects.count())
        esito = _carica()
        self.marcatura.refresh_from_db()
        self.assertEqual(self.marcatura.centro_di_costo, altro)
        self.assertEqual((CentroDiCosto.objects.count(), AreaAziendale.objects.count()), conteggi)
        self.assertEqual((esito["centri"], esito["aree_create"], esito["collegate"]), (0, [], 0))


class CamManagerTests(TestCase):
    def _assicura(self):
        return assicura_cam_manager(RuoloOperativo, AmbitoRuolo, AreaAziendale)

    def test_senza_reparto_non_crea_nulla(self):
        self.assertIsNone(self._assicura())
        self.assertFalse(RuoloOperativo.objects.filter(sigla="CAMM").exists())

    def test_crea_il_ruolo_una_volta_e_lo_mette_nel_reparto(self):
        area = AreaAziendale.objects.create(nome="UFFICIO TECNICO (CAM)")
        ambito = AmbitoRuolo.objects.filter(nome__iexact="Produttivo").first()
        self._assicura()
        self._assicura()
        ruolo = RuoloOperativo.objects.get(sigla="CAMM")
        self.assertEqual((ruolo.nome, ruolo.classe, ruolo.ambito), ("CAM Manager", "INDIRETTO", ambito))
        self.assertEqual(list(area.ruoli_reparto.all()), [ruolo])


class PaginaTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("cc_admin", "cc@example.test", "x")
        self.client.force_login(self.admin)
        self.centro = CentroDiCosto.objects.create(nome="STRUTTURA")
        self.altro = CentroDiCosto.objects.create(nome="LOGISTICA")
        self.area = AreaAziendale.objects.create(nome="IT", centro_di_costo=self.centro)
        self.libera = AreaAziendale.objects.create(nome="DIREZIONE")
        self.ruolo = RuoloOperativo.objects.create(nome="Information Technology Manager", sigla="ITM")

    def _utente_normale(self):
        utente = get_user_model().objects.create_user("cc_user", "u@example.test", "x")
        self.client.force_login(utente)

    def test_pagina_mostra_centri_e_senza_centro(self):
        r = self.client.get(reverse("anagrafica:centri_costo"), follow=True)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "STRUTTURA")
        self.assertContains(r, "Reparti senza centro di costo (1)")
        self.assertNotContains(r, "{#")

    def test_voce_di_menu(self):
        self.assertTrue(SubnavLinkAnagrafica.objects.filter(url_value="anagrafica:centri_costo").exists())

    def test_reparto_in_un_solo_centro(self):
        url = reverse("anagrafica:centro_costo_reparto_salva", args=[self.area.pk])
        self.client.post(url, {"centro_di_costo": self.altro.pk, "ruoli": [self.ruolo.pk]})
        self.area.refresh_from_db()
        self.assertEqual(self.area.centro_di_costo, self.altro)
        self.assertEqual(self.centro.aree.count(), 0)
        self.assertEqual(list(self.area.ruoli_reparto.all()), [self.ruolo])

    def test_togliere_il_centro(self):
        self.client.post(reverse("anagrafica:centro_costo_reparto_salva", args=[self.area.pk]), {"centro_di_costo": ""})
        self.area.refresh_from_db()
        self.assertIsNone(self.area.centro_di_costo)

    def test_crea_senza_doppioni(self):
        url = reverse("anagrafica:centro_costo_crea")
        self.client.post(url, {"nome": "Nuovo  centro"})
        self.client.post(url, {"nome": "NUOVO CENTRO"})
        self.assertEqual(CentroDiCosto.objects.filter(nome__iexact="nuovo centro").count(), 1)

    def test_modifica_non_prende_il_nome_di_un_altro(self):
        self.client.post(
            reverse("anagrafica:centro_costo_modifica", args=[self.altro.pk]),
            {"nome": "struttura", "is_active": "1"},
        )
        self.altro.refresh_from_db()
        self.assertEqual(self.altro.nome, "LOGISTICA")

    def test_elimina_solo_se_vuoto(self):
        self.client.post(reverse("anagrafica:centro_costo_elimina", args=[self.centro.pk]))
        self.assertTrue(CentroDiCosto.objects.filter(pk=self.centro.pk).exists())
        self.client.post(reverse("anagrafica:centro_costo_elimina", args=[self.altro.pk]))
        self.assertFalse(CentroDiCosto.objects.filter(pk=self.altro.pk).exists())

    def test_chi_non_amministra_non_cambia(self):
        self._utente_normale()
        self.client.post(reverse("anagrafica:centro_costo_crea"), {"nome": "ABUSIVO"})
        self.client.post(reverse("anagrafica:centro_costo_reparto_salva", args=[self.area.pk]), {"centro_di_costo": self.altro.pk})
        self.area.refresh_from_db()
        self.assertEqual(self.area.centro_di_costo, self.centro)
        self.assertFalse(CentroDiCosto.objects.filter(nome="ABUSIVO").exists())

    def test_area_da_reparti_salva_il_centro_ma_le_impostazioni_non_lo_toccano(self):
        url = reverse("anagrafica:area_aziendale_edit", args=[self.area.pk])
        self.client.post(url, {"nome": "IT", "is_active": "1"})  # come il form delle Impostazioni
        self.area.refresh_from_db()
        self.assertEqual(self.area.centro_di_costo, self.centro)
        self.client.post(url, {"nome": "IT", "is_active": "1", "centro_di_costo": self.altro.pk})
        self.area.refresh_from_db()
        self.assertEqual(self.area.centro_di_costo, self.altro)
