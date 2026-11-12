"""Centro di costo e carico collegati: dashboard, liste, export, Mansionario, Il mio team, Home."""
from datetime import timedelta
from unittest import mock

from django.test import RequestFactory
from django.urls import reverse

from .models import (
    DipendenteAnagraficaAziendale,
    DipendenteQualifica,
    TipoQualifica,
    TipoVisitaMedica,
    TrainingDeadline,
    VisitaMedica,
)
from .services import carico_mansioni, centro_filtro
from .services import mansionario_struttura as mstr
from .tests_formazione_dashboard_copertura import _corso
from .tests_prospetto import _Base


class _Dati(_Base):
    def setUp(self):
        super().setUp()
        self.corso = _corso("AI-05", "Antincendio sintetico")
        TrainingDeadline.objects.create(corso=self.corso, legacy_anagrafica_id=self.rossi,
                                        stato_scadenza="SCADUTO", is_required=True, data_scadenza=self.oggi - timedelta(days=3))
        TrainingDeadline.objects.create(corso=self.corso, legacy_anagrafica_id=self.verdi,
                                        stato_scadenza="SCADUTO", is_required=True, data_scadenza=self.oggi - timedelta(days=3))
        TrainingDeadline.objects.create(corso=self.corso, legacy_anagrafica_id=self.neri,
                                        stato_scadenza="SCADUTO", is_required=True, data_scadenza=self.oggi - timedelta(days=3))
        self.tipo = TipoVisitaMedica.objects.create(nome="Visita sintetica", durata_mesi=12)
        for pid in (self.rossi, self.verdi):
            VisitaMedica.objects.create(legacy_anagrafica_id=pid, tipo=self.tipo,
                                        data_svolgimento=self.oggi - timedelta(days=400),
                                        data_scadenza=self.oggi - timedelta(days=5))

    def _filtro(self, valore):
        return centro_filtro.leggi(RequestFactory().get("/", {"centro": valore}))


class FiltroTests(_Dati):
    def test_appartenenza_come_nei_report(self):
        lav = self._filtro(str(self.lav.pk))
        self.assertTrue(lav.attivo)
        self.assertIn(self.rossi, lav.ids)
        self.assertNotIn(self.verdi, lav.ids)
        self.assertEqual(lav.suffisso, f"&centro={self.lav.pk}")
        self.assertIn("LAVORAZIONI", lav.etichetta)

    def test_valore_sconosciuto_o_vuoto_non_filtra(self):
        for valore in ("", "999999", "abc"):
            f = self._filtro(valore)
            self.assertFalse(f.attivo, valore)
            self.assertTrue(f.contiene(self.rossi))
            self.assertEqual(f.suffisso, "")

    def test_i_centri_e_senza_centro_sommano_al_totale(self):
        tutti = TrainingDeadline.objects.filter(stato_scadenza="SCADUTO").count()
        somma = sum(self._filtro(v).applica(TrainingDeadline.objects.filter(stato_scadenza="SCADUTO")).count()
                    for v in (str(self.lav.pk), str(self.sal.pk), "senza"))
        self.assertEqual(somma, tutti)

    def test_senza_anagrafica_non_mostra_zeri_falsi(self):
        with mock.patch("anagrafica.services.centro_filtro.centro_per_persona", return_value={}):
            f = self._filtro(str(self.lav.pk))
        self.assertFalse(f.attivo)
        self.assertTrue(f.avviso)

    def test_i_filtri_della_pagina_restano_togliendo_il_centro(self):
        f = centro_filtro.leggi(RequestFactory().get("/", {"centro": str(self.lav.pk), "scad": "tutti", "page": "3"}))
        self.assertEqual(f.senza_filtro, "scad=tutti")


class DashboardTests(_Dati):
    def _lav(self, nome, **altri):
        return self.client.get(reverse(f"anagrafica:{nome}"), {"centro": self.lav.pk, **altri})

    def test_formazione_conta_solo_il_centro_e_porta_il_filtro_ai_link(self):
        senza = self.client.get(reverse("anagrafica:formazione_dashboard"))
        self.assertEqual(senza.context["kpi_scaduti"], 3)
        r = self._lav("formazione_dashboard")
        self.assertEqual(r.context["kpi_scaduti"], 1)
        self.assertEqual(r.context["copertura_corsi"][0]["totale"], 1)
        self.assertEqual({d.legacy_anagrafica_id for d in r.context["scadenze_urgenti"]}, {self.rossi})
        self.assertContains(r, f"?stato=SCADUTO&amp;centro={self.lav.pk}")
        self.assertContains(r, "Togli il filtro")

    def test_ogni_pagina_mostra_il_menu_dei_centri(self):
        for nome in ("formazione_dashboard", "formazione_scadenzario", "visite_mediche_dashboard", "scadenzario", "qualifiche_dashboard", "qualifiche_scadenzario"):
            self.assertContains(self._lav(nome), f'value="{self.lav.pk}" selected', msg_prefix=nome)
        for nome in ("dpi:report_persone", "dpi:report_consegne", "dpi:gestione_list"):
            self.assertContains(self.client.get(reverse(nome), {"centro": self.lav.pk}), f'value="{self.lav.pk}" selected', msg_prefix=nome)

    def test_il_numero_della_dashboard_e_la_lista_che_apre_coincidono(self):
        cruscotto = self._lav("formazione_dashboard")
        lista = self._lav("formazione_scadenzario", stato="SCADUTO")
        self.assertEqual(cruscotto.context["kpi_scaduti"], lista.context["totale"])
        self.assertEqual(lista.context["n_scaduti"], 1)

    def test_visite_filtrate_kpi_liste_e_copertura(self):
        senza = self.client.get(reverse("anagrafica:visite_mediche_dashboard"))
        self.assertEqual(senza.context["kpi_scadute"], 2)
        r = self._lav("visite_mediche_dashboard")
        self.assertEqual((r.context["kpi_scadute"], r.context["kpi_totali"]), (1, 1))
        self.assertEqual({v.legacy_anagrafica_id for v in r.context["scad_o_in_scad"]}, {self.rossi})
        riga = next(x for x in r.context["tipologie_stats"] if x["tipo"].pk == self.tipo.pk)
        self.assertEqual(riga["scadute_db"], 1)
        self.assertContains(r, f"?tipo=visita&amp;stato=scaduta&amp;centro={self.lav.pk}")

    def test_scadenzario_filtrato_con_centro_nel_csv(self):
        r = self._lav("scadenzario", tipo="formazione")
        self.assertEqual({v["legacy_id"] for v in r.context["page_obj"].object_list}, {self.rossi})
        self.assertEqual(r.context["fm_n_scaduti"], 1)
        self.assertContains(r, 'name="centro"')
        self.assertContains(r, f'value="{self.lav.pk}" selected')
        csv = self._lav("scadenzario", tipo="formazione", format="csv").content.decode("utf-8-sig")
        self.assertIn("Centro di costo", csv.splitlines()[0])
        self.assertIn("LAVORAZIONI", csv)
        self.assertNotIn("SALDATURE", csv)

    def test_gli_export_filtrati_seguono_il_centro(self):
        from . import exports_formazione, exports_hr, exports_persone

        req = RequestFactory().get("/", {"centro": str(self.lav.pk)})
        req.user = self.admin
        self.assertEqual(len(exports_formazione._formazione_scadenzario_rows(req, "filtered")), 1)
        self.assertEqual(len(exports_formazione._formazione_scadenzario_rows(req, "full")), 3)
        self.assertIn("LAVORAZIONI", exports_formazione._formazione_scadenzario_filters(req))
        self.assertEqual(len(exports_hr._visite_mediche_rows(req, "filtered")), 1)
        self.assertEqual(len(exports_hr._visite_mediche_rows(req, "full")), 2)
        copertura = next(x for x in exports_hr._visite_copertura_rows(req, "filtered") if x["tipologia"] == self.tipo.nome)
        self.assertEqual(copertura["scadute"], 1)
        self.assertIn("LAVORAZIONI", exports_persone._scadenzario_filters(req))


class MansionarioTests(_Base):
    def test_gli_stessi_numeri_del_carico(self):
        r = self.client.get(reverse("anagrafica:mansionario"))
        c = carico_mansioni.calcola().conteggi()
        self.assertEqual((r.context["kpi"]["scoperte"], r.context["kpi"]["uomo_solo"], r.context["kpi"]["concentrate"]),
                         (c["scoperte"], c["uomo_solo"], c["concentrate"]))
        self.assertContains(r, "data-f-centro=")
        self.assertContains(r, 'value="lavorazioni"')

    def test_cessato_in_lista_non_e_operativo_ma_si_vede(self):
        DipendenteAnagraficaAziendale.objects.update_or_create(
            legacy_anagrafica_id=self.bianchi, defaults={"data_cessazione": self.oggi - timedelta(days=1)})
        mstr.assegna(self.m2, legacy_anagrafica_id=self.rossi, livello="I")
        c = carico_mansioni.calcola()
        riga = next(x for x in carico_mansioni.su_riepilogo(mstr.riepilogo(), c) if x["mansione"].pk == self.m1.pk)
        self.assertEqual(riga["fuori_forza"], 1)
        self.assertEqual(riga["in_lista"], 2)
        self.assertEqual(riga["operativi"], c.per_mansione[self.m1.pk]["operativi"])
        self.assertEqual(riga["operativi"], 1)
        pagina = self.client.get(reverse("anagrafica:mansionario_mansione", args=[self.m1.pk]))
        self.assertContains(pagina, "non più in forza")
        self.assertEqual(pagina.context["n_fuori_forza"], 1)

    def test_senza_carico_restano_i_numeri_delle_liste(self):
        righe = carico_mansioni.su_riepilogo(mstr.riepilogo(), None)
        riga = next(x for x in righe if x["mansione"].pk == self.m1.pk)
        self.assertEqual((riga["operativi"], riga["fuori_forza"]), (2, 0))


class TeamEHomeTests(_Base):
    def test_il_mio_team_mostra_centro_e_segnali(self):
        with mock.patch("anagrafica.views_mio_team.membri_team", return_value=[self.verdi]), \
                mock.patch("anagrafica.views._current_legacy_anagrafica_id", return_value=self.rossi):
            r = self.client.get(reverse("anagrafica:mio_team"))
        riga = r.context["righe"][0]
        self.assertEqual(riga["centro"], "SALDATURE")
        attesi = carico_mansioni.calcola().persona(self.verdi)
        self.assertEqual(any("Unico operativo" in s for s in riga["carico"]), bool(attesi["chiave"]))
        self.assertContains(r, "SALDATURE")

    def test_home_con_le_mansioni_da_guardare(self):
        r = self.client.get(reverse("anagrafica:index"))
        self.assertEqual(r.context["carico_home"]["da_guardare"], carico_mansioni.calcola().conteggi()["da_guardare"])
        self.assertContains(r, "Mansioni da guardare")
        self.assertContains(r, reverse("anagrafica:centri_costo"))

    def test_home_senza_carico_resta_in_piedi(self):
        with mock.patch("anagrafica.services.carico_mansioni.calcola", side_effect=RuntimeError("anagrafica giù")):
            r = self.client.get(reverse("anagrafica:index"))
        self.assertEqual(r.status_code, 200)
        self.assertIsNone(r.context["carico_home"])


class QualificheTests(_Base):
    def setUp(self):
        super().setUp()
        self.tipo = TipoQualifica.objects.create(nome="Patentino sintetico")
        ieri = self.oggi - timedelta(days=1)
        for pid in (self.rossi, self.verdi):
            DipendenteQualifica.objects.create(legacy_anagrafica_id=pid, tipo=self.tipo, data_conseguimento=self.oggi - timedelta(days=400), data_scadenza=ieri)

    def test_cruscotto_e_scadenzario_filtrati_con_gli_stessi_numeri(self):
        tutti = self.client.get(reverse("anagrafica:qualifiche_dashboard"))
        self.assertEqual(tutti.context["n_scadute"], 2)
        r = self.client.get(reverse("anagrafica:qualifiche_dashboard"), {"centro": self.lav.pk})
        self.assertEqual(r.context["n_scadute"], 1)
        self.assertContains(r, f"?stato=scaduta&amp;centro={self.lav.pk}")
        self.assertContains(r, f"stato=tutte&amp;centro={self.lav.pk}")
        lista = self.client.get(reverse("anagrafica:qualifiche_scadenzario"), {"centro": self.lav.pk, "stato": "scaduta"})
        self.assertEqual([v["legacy_id"] for v in lista.context["voci"]], [self.rossi])

    def test_la_qualifica_superata_e_il_cessato_non_contano_nello_scadenzario(self):
        DipendenteQualifica.objects.create(legacy_anagrafica_id=self.rossi, tipo=self.tipo, data_conseguimento=self.oggi,
                                           data_scadenza=self.oggi + timedelta(days=300))
        DipendenteAnagraficaAziendale.objects.update_or_create(
            legacy_anagrafica_id=self.verdi, defaults={"data_cessazione": self.oggi - timedelta(days=1)})
        cruscotto = self.client.get(reverse("anagrafica:qualifiche_dashboard"))
        lista = self.client.get(reverse("anagrafica:qualifiche_scadenzario"), {"stato": "scaduta"})
        self.assertEqual(cruscotto.context["n_scadute"], 0)
        self.assertEqual(lista.context["voci"], [])

    def test_export_filtrato_e_csv_col_centro(self):
        from . import exports_qualifiche

        req = RequestFactory().get("/", {"centro": str(self.lav.pk), "stato": "scaduta"})
        req.user = self.admin
        righe = exports_qualifiche._scadenzario_rows(req, "filtered")
        self.assertEqual([x["centro_costo"] for x in righe], ["LAVORAZIONI"])
        self.assertEqual(len(exports_qualifiche._scadenzario_rows(req, "full")), 2)
        csv = self.client.get(reverse("anagrafica:qualifiche_scadenzario"), {"centro": self.lav.pk, "stato": "scaduta", "format": "csv"})
        self.assertIn("Centro di costo", csv.content.decode("utf-8-sig").splitlines()[0])


class ExportVisiteComeLaDashboardTests(_Base):
    def test_il_rinnovo_non_lascia_la_vecchia_scaduta_nell_export(self):
        from . import exports_hr

        tipo = TipoVisitaMedica.objects.create(nome="Visita rinnovata", durata_mesi=12)
        VisitaMedica.objects.create(legacy_anagrafica_id=self.rossi, tipo=tipo, data_svolgimento=self.oggi - timedelta(days=400),
                                    data_scadenza=self.oggi - timedelta(days=5))
        VisitaMedica.objects.create(legacy_anagrafica_id=self.rossi, tipo=tipo, data_svolgimento=self.oggi - timedelta(days=1),
                                    data_scadenza=self.oggi + timedelta(days=30))
        req = RequestFactory().get("/")
        req.user = self.admin
        righe = [x for x in exports_hr._visite_mediche_rows(req, "filtered") if x["tipo"] == tipo.nome]
        self.assertFalse([x for x in righe if "Scaduta" in x["stato"]])
        pagina = self.client.get(reverse("anagrafica:visite_mediche_dashboard"))
        self.assertEqual(sum(1 for v in pagina.context["scad_o_in_scad"] if v.tipo_id == tipo.pk), len(righe))
        copertura = next(x for x in exports_hr._visite_copertura_rows(req, "full") if x["tipologia"] == tipo.nome)
        riga = next(x for x in pagina.context["tipologie_stats"] if x["tipo"].pk == tipo.pk)
        self.assertEqual((copertura["valide"], copertura["scadute"]), (riga["valide_db"], riga["scadute_db"]))
