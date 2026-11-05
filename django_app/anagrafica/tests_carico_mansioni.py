"""Carico sulle mansioni: stessi numeri del Prospetto in report, centri di costo e schede."""
from django.urls import reverse

from .models import SkillMatrixConfig
from .reportistica import sezioni as catalogo
from .reportistica.dati import Contesto, Perimetro
from .services import capo_team, carico_mansioni
from .services import prospetto_struttura as svc
from .tests_prospetto import _Base


class CaricoTests(_Base):
    def _rep(self, chiave, **opzioni):
        ctx = Contesto(date_from=self.oggi, date_to=self.oggi, perimetro=Perimetro.from_dict({}), today=self.oggi)
        return catalogo.get(chiave).calcola(ctx, opzioni)

    def test_stessi_numeri_del_prospetto(self):
        c = carico_mansioni.calcola()
        base = svc.Base()
        cfg = base.config
        mis = svc.misure(base, base.stato, soglia_mansioni=cfg.soglia_mansioni_persona,
                         soglia_concentrazione=cfg.soglia_concentrazione, capi=capo_team.mappa_capi())
        self.assertTrue(c.per_persona)
        for mid, r in c.per_mansione.items():
            p = mis["per_mansione"][mid]
            self.assertEqual((r["lista"], r["operativi"], r["stato"], r["concentrazione"], r["concentrato"], r["fte"]),
                             (p["lista"], p["operativi"], p["stato"], p["concentrazione"], p["concentrato"], p["fte"]), mid)
        self.assertEqual(c.conteggi()["scoperte"], mis["kpi"]["scoperte"])
        self.assertEqual(c.conteggi()["uomo_solo"], mis["kpi"]["uomo_solo"])
        self.assertEqual(c.conteggi()["concentrate"], mis["kpi"]["concentrate"])
        self.assertEqual({p for p, x in c.per_persona.items() if x["troppe"]}, mis["troppe"])
        self.assertEqual({p for p, x in c.per_persona.items() if x["chiave"]}, set(mis["uniche"]))

    def test_costi_per_centro_come_il_prospetto(self):
        c = carico_mansioni.calcola()
        base = svc.Base()
        cfg = base.config
        mis = svc.misure(base, base.stato, soglia_mansioni=cfg.soglia_mansioni_persona,
                         soglia_concentrazione=cfg.soglia_concentrazione, capi=capo_team.mappa_capi())
        costi = carico_mansioni.costi_per_centro(c)["centri"]
        self.assertTrue(costi)
        for cid, x in costi.items():
            self.assertEqual(x["rml"], svc._euro(mis["per_centro"][cid]["rml"]), cid)

    def test_le_soglie_arrivano_alla_persona_e_al_report(self):
        SkillMatrixConfig.get_instance()
        SkillMatrixConfig.objects.update(soglia_mansioni_persona=1)
        c = carico_mansioni.calcola()
        persona = c.persona(self.verdi)
        self.assertTrue(persona["troppe"])
        self.assertEqual(persona["soglia"], 1)
        self.assertTrue(persona["chiave"])
        righe = self._rep("carico_persone", solo_segnalate=True).righe
        self.assertTrue(any("su troppe mansioni" in r["segnali"] for r in righe))

    def test_persona_senza_mansioni_o_sconosciuta(self):
        self.assertEqual(carico_mansioni.calcola().persona(999999)["n"], 0)
        self.assertFalse(carico_mansioni.calcola().persona(999999)["in_forza"])

    def test_report_copertura_con_centro_e_carico(self):
        res = self._rep("copertura_mansioni")
        c = carico_mansioni.calcola()
        riga = next(r for r in res.righe if r["mansione"] == self.m1.nome)
        attesa = c.per_mansione[self.m1.pk]
        self.assertEqual((riga["operativi"], riga["in_lista"], riga["stato"]), (attesa["operativi"], attesa["lista"], attesa["stato"]))
        self.assertEqual(riga["carico"], f"{attesa['concentrazione']}%")
        self.assertEqual(riga["centro_costo"], self.m1.area.centro_di_costo.nome)
        solo = self._rep("copertura_mansioni", solo_da_guardare=True).righe
        self.assertTrue(all(r["stato"] != "ok" or r["segnali"] for r in solo))

    def test_pagina_centri_costi_solo_a_chi_puo(self):
        pagina = self.client.get(reverse("anagrafica:centri_costo"))
        self.assertContains(pagina, "Mansioni da guardare")
        self.assertContains(pagina, "cc-misure")
        self.assertContains(pagina, "costo medio")
        self.assertContains(pagina, reverse("anagrafica:prospetti"))

    def test_pagina_centri_senza_permesso_costi(self):
        from unittest import mock

        with mock.patch("anagrafica.views_centri_costo._helpers._check_hr_permission", return_value=False):
            pagina = self.client.get(reverse("anagrafica:centri_costo"))
        self.assertContains(pagina, "Mansioni da guardare")
        self.assertNotContains(pagina, "costo medio")

    def test_pagina_centri_regge_senza_carico(self):
        from unittest import mock

        with mock.patch("anagrafica.services.carico_mansioni.calcola", side_effect=RuntimeError("giù")):
            pagina = self.client.get(reverse("anagrafica:centri_costo"))
        self.assertEqual(pagina.status_code, 200)
        self.assertNotContains(pagina, "Mansioni da guardare")

    def test_esplora_mostra_i_segnali(self):
        pagina = self.client.get(reverse("anagrafica:esplora_struttura"), {"mansione": self.m1.pk})
        self.assertContains(pagina, "Carico")
        self.assertContains(pagina, "Stato")
        pagina = self.client.get(reverse("anagrafica:esplora_struttura"), {"area": self.m1.area_id})
        self.assertContains(pagina, "Mansioni da guardare")

    def test_scheda_struttura_mansione(self):
        pagina = self.client.get(reverse("anagrafica:struttura_scheda_mansione", args=[self.m1.pk]),
                                 HTTP_HX_REQUEST="true")
        self.assertContains(pagina, "Stato:")
        self.assertContains(pagina, self.m1.area.centro_di_costo.nome)

    def test_export_centri_con_i_segnali(self):
        from .exports import EXPORT_SPECS

        spec = EXPORT_SPECS["centri_costo"]
        self.assertIn(("Mansioni scoperte", "scoperte"), list(spec.columns))
