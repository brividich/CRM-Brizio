"""Esplora la struttura: scendere, risalire, altre strade, voci «Senza…», permessi.

Scenario di ``tests_capo_team``: rossi (IN1) e bianchi (IN2) nel centro LAVORAZIONI,
neri e verdi in SA1 senza centro, gialli senza area.
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.urls import reverse

from .models import CentroDiCosto, SubnavLinkAnagrafica
from .models_skillmatrix import AbilitazioneMacchina, CompetenzaCatalogo, CompetenzaSkm, VoceMacchinaCatalogo
from .services import esplora_struttura as svc
from .tests_capi_mansione import _ScenarioMansioni
from .views_centri_costo import persone_per_area

User = get_user_model()
URL = "anagrafica:esplora_struttura"


class _Base(_ScenarioMansioni):
    def setUp(self):
        super().setUp()
        self.centro = CentroDiCosto.objects.create(nome="LAVORAZIONI")
        for area in (self.in1, self.in2):
            area.centro_di_costo = self.centro
            area.save(update_fields=["centro_di_costo"])
        self.fresa = self._crea_mansione("Fresa F1", self.in1, self.op)
        self.taglio = self._crea_mansione("Taglio T1", self.sa1, self.op)
        self.orfana = CompetenzaSkm.objects.create(competenza_key="orfana", display="Orfana",
                                                   tipo=CompetenzaSkm.TIPO_PROCESSO)
        self.catalogo = CompetenzaCatalogo.objects.create(nome="Set-up", chiave="set-up")
        self.voce = VoceMacchinaCatalogo.objects.create(codice="V1", nome="Set-up F1", mansione=self.fresa,
                                                        catalogo=self.catalogo, livello_minimo="U", bloccante=True)
        self.voce2 = VoceMacchinaCatalogo.objects.create(codice="V2", nome="Set-up T1", mansione=self.taglio,
                                                         catalogo=self.catalogo)
        AbilitazioneMacchina.objects.create(legacy_anagrafica_id=self.rossi, competenza=self.fresa, livello="U")
        self.admin = User.objects.create_superuser("esp_admin", "esp@example.invalid", "x")
        self.client.force_login(self.admin)

    def _crea_mansione(self, nome, area, ruolo):
        m = CompetenzaSkm.objects.create(competenza_key=nome.lower().replace(" ", "_"), display=nome,
                                         tipo=CompetenzaSkm.TIPO_PROCESSO, area=area)
        m.ruoli.add(ruolo)
        return m

    def get(self, **params):
        return self.client.get(reverse(URL), params)

    def colonna(self, r, livello):
        return next(c for c in r.context["colonne"] if c["livello"] == livello)["voci"]


class ScendereTests(_Base):
    def test_partenza_solo_centri_e_conteggi(self):
        r = self.get()
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "{#")
        voci = {v["nome"]: v["n"] for v in self.colonna(r, "centro")}
        self.assertEqual(voci, {"LAVORAZIONI": 2, svc.ETICHETTE_SENZA["centro"]: 3})
        self.assertIsNone(self.colonna(r, "area"))

    def test_catena_fino_alla_competenza(self):
        r = self.get(centro=self.centro.pk)
        self.assertEqual({v["nome"] for v in self.colonna(r, "area")}, {"IN1", "IN2"})
        r = self.get(centro=self.centro.pk, area=self.in1.pk)
        self.assertIn(self.op.pk, {v["id"] for v in self.colonna(r, "ruolo")})
        r = self.get(centro=self.centro.pk, area=self.in1.pk, ruolo=self.op.pk)
        self.assertEqual([v["nome"] for v in self.colonna(r, "mansione")], ["Fresa F1"])
        r = self.get(centro=self.centro.pk, area=self.in1.pk, ruolo=self.op.pk, mansione=self.fresa.pk)
        self.assertEqual([v["nome"] for v in self.colonna(r, "competenza")], ["Set-up F1"])
        r = self.get(centro=self.centro.pk, area=self.in1.pk, ruolo=self.op.pk, mansione=self.fresa.pk, competenza=self.voce.pk)
        self.assertEqual(r.context["dettaglio"]["tipo"], "Competenza")
        self.assertEqual(dict(r.context["dettaglio"]["dati"])["Bloccante"], "Sì")

    def test_la_voce_scelta_e_evidenziata_a_ogni_livello(self):
        r = self.get(centro=self.centro.pk, area=self.in1.pk, ruolo=self.op.pk, mansione=self.fresa.pk)
        for livello in ("centro", "area", "ruolo", "mansione"):
            self.assertEqual(sum(1 for v in self.colonna(r, livello) if v["scelta"]), 1, livello)

    def test_competenza_senza_dati_lo_dice(self):
        VoceMacchinaCatalogo.objects.filter(mansione=self.fresa).delete()
        r = self.get(mansione=self.fresa.pk)
        self.assertContains(r, "Nessuna competenza caricata per questa mansione.")

    def test_stessi_numeri_di_reparti_aree_e_capi(self):
        pagina = persone_per_area()
        voci = {v["id"]: v["n"] for v in self.colonna(self.get(centro=self.centro.pk), "area")}
        self.assertEqual(voci[self.in1.pk], pagina[self.in1.pk])
        self.assertEqual(voci[self.in2.pk], pagina[self.in2.pk])


class RisalireTests(_Base):
    def test_il_percorso_ha_tutti_i_livelli_e_link_giusti(self):
        r = self.get(centro=self.centro.pk, area=self.in1.pk, ruolo=self.op.pk, mansione=self.fresa.pk)
        b = r.context["briciole"]
        self.assertEqual([x.get("livello") for x in b], [None, "Centro di costo", "Reparto", "Ruolo", "Mansione"])
        self.assertTrue(b[-1]["url_corrente"])
        su = self.client.get(b[2]["url"])
        self.assertEqual(su.context["dettaglio"]["titolo"], "IN1")
        self.assertIsNone(self.colonna(su, "mansione"))

    def test_entrare_da_un_livello_completa_quelli_sopra(self):
        r = self.get(mansione=self.fresa.pk)
        s = r.context["scelti"]
        self.assertEqual((s["centro"], s["area"], s["ruolo"], s["mansione"]),
                         (self.centro.pk, self.in1.pk, self.op.pk, self.fresa.pk))
        r = self.get(area=self.in2.pk)
        self.assertEqual(r.context["scelti"]["centro"], self.centro.pk)
        r = self.get(competenza=self.voce2.pk)
        self.assertEqual(r.context["scelti"]["area"], self.sa1.pk)
        self.assertEqual(r.context["scelti"]["centro"], svc.SENZA)
        r = self.get(ruolo=self.op.pk)
        self.assertIsNotNone(r.context["scelti"]["area"])

    def test_percorsi_incoerenti_o_sporchi_non_rompono(self):
        for params in ({"centro": "abc"}, {"centro": "999999"}, {"area": "999999"}, {"ruolo": "999999"},
                       {"mansione": "999999"}, {"competenza": "999999"}, {"centro": "-1"},
                       {"area": self.in1.pk, "ruolo": self.gialli},
                       {"centro": self.centro.pk, "area": self.in1.pk, "ruolo": self.op.pk, "mansione": self.taglio.pk}):
            with self.subTest(params=params):
                self.assertEqual(self.get(**params).status_code, 200)
        r = self.get(centro=self.centro.pk, area=self.in1.pk, ruolo=self.op.pk, mansione=self.taglio.pk)
        self.assertIsNone(r.context["scelti"]["mansione"])
        r = self.get(centro=svc.SENZA, area=self.in1.pk)
        self.assertEqual(r.context["scelti"]["centro"], self.centro.pk)


class AltreStradeTests(_Base):
    def test_stesso_ruolo_in_altri_reparti(self):
        r = self.get(area=self.in1.pk, ruolo=self.op.pk)
        altri = r.context["dettaglio"]["altri_reparti"]
        self.assertEqual([a["nome"] for a in altri], ["SA1"])
        arrivo = self.client.get(altri[0]["url"])
        self.assertEqual(arrivo.context["scelti"]["area"], self.sa1.pk)
        self.assertEqual(arrivo.context["scelti"]["ruolo"], self.op.pk)

    def test_gerarchia_del_ruolo(self):
        g = self.get(area=self.in1.pk, ruolo=self.op.pk).context["dettaglio"]["gerarchia"]
        self.assertEqual([(x["nome"], x["sotto"]) for x in g], [("Caporeparto", "riporta a")])
        self.assertIn(f"area={self.in1.pk}", g[0]["url"])

    def test_stessa_mansione_sotto_altro_ruolo(self):
        self.fresa.ruoli.add(self.capo)
        d = self.get(area=self.in1.pk, ruolo=self.op.pk, mansione=self.fresa.pk).context["dettaglio"]
        self.assertEqual([x["nome"] for x in d["altri_ruoli"]], ["Caporeparto"])
        arrivo = self.client.get(d["altri_ruoli"][0]["url"])
        self.assertEqual(arrivo.context["scelti"]["ruolo"], self.capo.pk)
        self.assertEqual(arrivo.context["scelti"]["mansione"], self.fresa.pk)

    def test_stessa_competenza_su_altra_mansione(self):
        d = self.get(competenza=self.voce.pk).context["dettaglio"]
        self.assertEqual([x["nome"] for x in d["altre_mansioni"]], ["Taglio T1"])
        arrivo = self.client.get(d["altre_mansioni"][0]["url"])
        self.assertEqual(arrivo.context["scelti"]["competenza"], self.voce2.pk)

    def test_pagine_filtrate_del_centro_si_aprono(self):
        strade = self.get(centro=self.centro.pk).context["strade"]
        nomi = {s["nome"]: s["url"] for s in strade}
        self.assertIn("centro_costo=LAVORAZIONI", nomi["Persone del centro di costo"])
        self.assertIn("centro_costo=LAVORAZIONI", nomi["Costo orario del centro"])
        for s in strade:
            with self.subTest(strada=s["nome"]):
                self.assertEqual(self.client.get(s["url"]).status_code, 200)

    def test_tutte_le_strade_di_ogni_livello_si_aprono(self):
        for params in ({}, {"area": self.in1.pk}, {"area": self.in1.pk, "ruolo": self.op.pk},
                       {"mansione": self.fresa.pk}, {"competenza": self.voce.pk}):
            for s in self.get(**params).context["strade"]:
                with self.subTest(params=params, strada=s["nome"]):
                    self.assertEqual(self.client.get(s["url"]).status_code, 200)

    def test_persone_portano_alla_scheda(self):
        r = self.get(area=self.in1.pk, ruolo=self.op.pk)
        self.assertContains(r, reverse("anagrafica:dipendente_detail", args=[self.rossi]))
        d = self.get(mansione=self.fresa.pk).context["dettaglio"]
        self.assertEqual([p["id"] for p in d["persone"]], [self.rossi])
        self.assertIn("livello U", d["persone"][0]["nota"])


class VociSenzaTests(_Base):
    def test_nessuno_sparisce(self):
        r = self.get(centro=svc.SENZA)
        nomi = {v["nome"] for v in self.colonna(r, "area")}
        self.assertEqual(nomi, {"SA1", svc.ETICHETTE_SENZA["area"]})
        r = self.get(centro=svc.SENZA, area=svc.SENZA)
        self.assertEqual(r.context["dettaglio"]["persone"][0]["id"], self.gialli)
        ruoli = {v["id"] for v in self.colonna(r, "ruolo")}
        self.assertIn(svc.SENZA, ruoli)

    def test_mansione_orfana_raggiungibile(self):
        r = self.get(mansione=self.orfana.pk)
        s = r.context["scelti"]
        self.assertEqual((s["centro"], s["area"], s["ruolo"], s["mansione"]),
                         (svc.SENZA, svc.SENZA, svc.SENZA, self.orfana.pk))

    def test_le_responsabilita_stanno_nel_reparto(self):
        r = self.get(area=self.in1.pk, ruolo=self.capo.pk)
        self.assertIn(self.resp_fres.nome, [v["nome"] for v in self.colonna(r, "mansione")])


class CercaTests(_Base):
    def test_trova_ogni_livello_e_il_link_funziona(self):
        for testo, livello in (("lavoraz", "Centro di costo"), ("IN1", "Reparto"), ("capor", "Ruolo"),
                               ("fresa f1", "Mansione"), ("set-up f1", "Competenza")):
            with self.subTest(testo=testo):
                r = self.get(q=testo)
                trovati = [x for x in r.context["risultati"] if x["livello"] == livello]
                self.assertTrue(trovati)
                self.assertEqual(self.client.get(trovati[0]["url"]).status_code, 200)

    def test_niente_risultati_lo_dice_e_testo_corto_non_cerca(self):
        self.assertContains(self.get(q="zzzzz"), "Nessun punto della struttura")
        self.assertIsNone(self.get(q="z").context["risultati"])

    def test_non_si_interpreta_html(self):
        r = self.get(q="<script>x</script>")
        self.assertNotContains(r, "<script>x</script>")


class PermessiEIngressiTests(_Base):
    def test_chi_non_vede_la_struttura_non_entra(self):
        utente = User.objects.create_user("esp_user", "u@example.invalid", "x")
        self.client.force_login(utente)
        r = self.client.get(reverse(URL))
        self.assertIn(r.status_code, (302, 403))

    def test_voce_di_menu_e_binding(self):
        from core.models import RoutePermissionBinding

        self.assertTrue(SubnavLinkAnagrafica.objects.filter(url_value=URL).exists())
        sorella = RoutePermissionBinding.objects.filter(route_name="anagrafica:struttura_org").first()
        if sorella:
            self.assertTrue(RoutePermissionBinding.objects.filter(route_name=URL).exists())

    def test_ingressi_dalle_altre_pagine(self):
        base = reverse(URL)
        for rotta, args in (("anagrafica:centri_costo", []), ("anagrafica:aree_list", []),
                            ("anagrafica:struttura_org", []), ("anagrafica:mansionario_mansione", [self.fresa.pk]),
                            ("anagrafica:struttura_scheda_ruolo", [self.op.pk])):
            with self.subTest(rotta=rotta):
                self.assertContains(self.client.get(reverse(rotta, args=args)), base)

    def test_scheda_dipendente_porta_al_reparto(self):
        r = self.client.get(reverse("anagrafica:dipendente_detail", args=[self.rossi]))
        self.assertContains(r, f"{reverse(URL)}?area={self.in1.pk}")

    def test_centri_di_costo_porta_a_persone_e_costi(self):
        r = self.client.get(reverse("anagrafica:centri_costo"))
        self.assertContains(r, f"{reverse('anagrafica:dipendenti_report')}?centro_costo=LAVORAZIONI")
        self.assertContains(r, f"{reverse('anagrafica:costo_orario')}?centro_costo=LAVORAZIONI")

    def test_elenco_dipendenti_filtra_per_centro(self):
        url = reverse("anagrafica:dipendenti_list")
        self.assertContains(self.client.get(url), 'name="centro_costo"')
        r = self.client.get(url, {"centro_costo": "LAVORAZIONI"})
        self.assertContains(r, "ROSSI")
        self.assertNotContains(r, "VERDI")


class EsploraRiccaTests(_Base):
    """Le persone e il passaggio rapido tra le voci."""

    def _get(self, **parametri):
        return self.client.get(reverse(URL), parametri)

    def test_le_colonne_delle_persone_seguono_il_livello(self):
        centro = self._get(centro=self.in1.centro_di_costo_id or svc.SENZA).context["dettaglio"]
        self.assertTrue(centro["colonne_persone"]["reparto"])
        self.assertTrue(centro["colonne_persone"]["ruolo"])
        reparto = self._get(area=self.in1.pk).context["dettaglio"]
        self.assertFalse(reparto["colonne_persone"]["reparto"])
        self.assertTrue(reparto["colonne_persone"]["ruolo"])
        mansione = self._get(mansione=self.fresa.pk).context["dettaglio"]
        self.assertTrue(mansione["colonne_persone"]["nota"])
        riga = mansione["persone"][0]
        self.assertEqual(riga["id"], self.rossi)
        self.assertTrue(riga["mansioni"])
        self.assertTrue(riga["esito"])

    def test_contratto_e_costi_solo_a_chi_lavora_sui_dati_hr(self):
        chiesta = svc.costruisci({"area": str(self.in1.pk)}, riservati=True)["dettaglio"]
        self.assertTrue(chiesta["colonne_persone"]["riservati"])
        self.assertIn("contratto", chiesta["persone"][0])
        senza = svc.costruisci({"area": str(self.in1.pk)}, riservati=False)["dettaglio"]
        self.assertFalse(senza["colonne_persone"]["riservati"])
        self.assertNotIn("contratto", senza["persone"][0])
        self.assertNotIn("costo", senza["persone"][0])
        self.assertNotIn("Costo orario medio", [k[0] for k in senza["kpi"]])

    def test_vista_parziale_senza_la_pagina_intorno(self):
        r = self._get(area=self.in1.pk, parziale=1)
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "es-colonne")
        self.assertNotContains(r, "<html")
        self.assertNotContains(r, "parziale=1")
        intera = self._get(area=self.in1.pk)
        self.assertContains(intera, 'id="es-vivo"')

    def test_cambiando_reparto_restano_ruolo_e_mansione_se_esistono(self):
        r = self._get(area=self.in1.pk, ruolo=self.op.pk, mansione=self.fresa.pk)
        reparti = next(c for c in r.context["colonne"] if c["livello"] == "area")["voci"]
        scelta = next(v for v in reparti if v["scelta"])
        self.assertNotIn("ruolo=", scelta["url"])
        s = r.context["scelti"]
        d = svc.Dati.carica()
        for a in d.aree_centro(s["centro"]):
            if a.pk == self.in1.pk:
                continue
            resta = svc._dove_si_resta(d, s, a)
            info = d.ruoli_area(a).get(self.op.pk)
            self.assertEqual("ruolo" in resta, info is not None)
            if info is not None:
                self.assertEqual("mansione" in resta, self.fresa in info["mansioni"])

    def test_voce_precedente_e_successiva(self):
        colonne = [{"titolo": "Reparti", "voci": [{"scelta": False, "nome": "A"}, {"scelta": True, "nome": "B"}, {"scelta": False, "nome": "C"}]},
                   {"titolo": "Ruoli", "voci": None}]
        v = svc._vicini(colonne)
        self.assertEqual((v["prec"]["nome"], v["succ"]["nome"], v["posto"], v["totale"]), ("A", "C", 2, 3))
        self.assertIsNone(svc._vicini([{"titolo": "Centri", "voci": [{"scelta": False, "nome": "A"}]}]))
