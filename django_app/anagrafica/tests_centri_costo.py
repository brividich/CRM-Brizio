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

    def _mansione_in_it(self):
        from .models_skillmatrix import AbilitazioneMacchina, CompetenzaSkm

        self.area.ruoli_reparto.add(self.ruolo)
        m = CompetenzaSkm.objects.create(competenza_key="gestione_rete", display="Gestione della rete",
                                         tipo=CompetenzaSkm.TIPO_PROCESSO, area=self.area)
        m.ruoli.add(self.ruolo)
        AbilitazioneMacchina.objects.create(legacy_anagrafica_id=987001, competenza=m, livello="U")
        return m

    def test_ogni_centro_ha_il_suo_albero_reparto_ruolo_mansione(self):
        m = self._mansione_in_it()
        r = self.client.get(reverse("anagrafica:centri_costo"))
        scheda = next(s for s in r.context["schede"] if s["centro"].pk == self.centro.pk)
        reparto = scheda["albero"][0]
        self.assertEqual((reparto["nome"], reparto["persone"]), ("IT", "0 persone"))
        ruolo = reparto["ruoli"][0]
        self.assertIn("Information Technology Manager", ruolo["nome"])
        self.assertEqual([x["nome"] for x in ruolo["mansioni"]], ["Gestione della rete"])
        # Chi non è in forza non conta: stesso criterio di «Esplora la struttura».
        self.assertEqual(ruolo["mansioni"][0]["persone"], "0 persone")
        self.assertIn(f"mansione={m.pk}", ruolo["mansioni"][0]["url"])
        vuoto = next(s for s in r.context["schede"] if s["centro"].pk == self.altro.pk)
        self.assertEqual(vuoto["albero"], [])
        for testo in ("<em>Reparto:</em>", "<em>Ruolo:</em>", "<em>Mansione:</em>", "Gestione della rete",
                      "Nessun reparto in questo centro.", "Apri tutto", "Chiudi tutto", 'class="fx-flusso"'):
            self.assertContains(r, testo)
        self.assertEqual(self.client.get(ruolo["mansioni"][0]["url"]).status_code, 200)

    def test_il_centro_nell_indirizzo_si_apre_con_la_sua_scheda(self):
        r = self.client.get(reverse("anagrafica:centri_costo"))
        self.assertIsNone(r.context["scelta"])
        self.assertContains(r, "Apri un centro di costo: qui compaiono i suoi dati")
        # Ogni centro porta con sé la sua scheda: aprendolo compare a destra senza ricaricare.
        self.assertContains(r, "<template data-cc-modello>", count=2)
        r = self.client.get(reverse("anagrafica:centri_costo"), {"centro": self.centro.pk})
        scelta = r.context["scelta"]
        self.assertEqual(scelta["centro"], self.centro)
        campi = dict(scelta["scheda"]["campi"])
        self.assertEqual((campi["Centro di costo"], campi["Stato"], campi["Reparti"], campi["Persone"]),
                         ("STRUTTURA", "Attivo", "IT", "0"))
        self.assertEqual([x["nome"] for x in scelta["scheda"]["collegate"]][:2], ["Esplora la struttura", "Persone del centro"])
        self.assertContains(r, f'id="cc-{self.centro.pk}" data-cc-centro="{self.centro.pk}"')
        self.assertContains(r, " open>")
        self.assertIsNone(self.client.get(reverse("anagrafica:centri_costo"), {"centro": "abc"}).context["scelta"])
        for x in scelta["scheda"]["collegate"]:
            self.assertEqual(self.client.get(x["url"]).status_code, 200, x["nome"])

    def test_da_fare_e_comandi_di_modifica(self):
        r = self.client.get(reverse("anagrafica:centri_costo"))
        self.assertEqual([(x["titolo"], x["n"]) for x in r.context["da_fare"]], [("Reparti senza centro di costo", 1)])
        self.assertContains(r, "data-cc-nuovo")
        self.assertContains(r, "data-cc-id")
        self._utente_normale()
        r = self.client.get(reverse("anagrafica:centri_costo"), follow=True)
        if r.status_code == 200 and "schede" in (r.context or {}):
            self.assertNotContains(r, "data-cc-nuovo")
            self.assertNotContains(r, "data-cc-id")

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
