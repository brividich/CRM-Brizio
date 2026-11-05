"""Centro di costo nei report: stessi numeri ovunque, dalla catena dipendente → area → centro.

Scenario di ``tests_capo_team``: rossi (IN1) e bianchi (IN2) nel centro LAVORAZIONI,
neri e verdi in SA1 senza centro, gialli senza area.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal as D

from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from core.legacy_anagrafica import fetch_anagrafica_rows

from .exports import EXPORT_SPECS
from .models import CentroDiCosto, CostoOrarioMensile, ReportBlocco, ReportModello, RuoloOperativo
from .reportistica import sezioni as catalogo
from .reportistica.conversazione import interpreta_senza_ai, normalizza_specifica, specifica_vuota
from .reportistica.dati import SENZA_CENTRO, Contesto, Perimetro
from .reportistica.forms import scelte_perimetro
from .reportistica.predefiniti import MODELLI, crea_predefiniti
from .services.colonne_elenco import REGISTRO
from .services.reparto_canonico import enrich_rows_reparto_canonico
from .tests_capi_mansione import _ScenarioMansioni
from .views_centri_costo import persone_per_area

User = get_user_model()


class _Base(_ScenarioMansioni):
    def setUp(self):
        super().setUp()
        self.centro = CentroDiCosto.objects.create(nome="LAVORAZIONI")
        for area in (self.in1, self.in2):
            area.centro_di_costo = self.centro
            area.save(update_fields=["centro_di_costo"])
        self.in1.ruoli_reparto.add(self.op)
        self.oggi = timezone.localdate()
        self.admin = User.objects.create_superuser("cc_rep_admin", "cc@example.invalid", "x")
        self.client.force_login(self.admin)

    def ctx(self, **perimetro) -> Contesto:
        return Contesto(date_from=self.oggi - timedelta(days=365), date_to=self.oggi,
                        perimetro=Perimetro.from_dict(perimetro), today=self.oggi)

    def _sezione(self, chiave, ctx=None, **opzioni):
        return catalogo.get(chiave).calcola(ctx or self.ctx(), opzioni)


class FonteUnicaTests(_Base):
    def test_riga_e_persona_prendono_il_centro_dall_area(self):
        righe = {int(r["id"]): r for r in enrich_rows_reparto_canonico(fetch_anagrafica_rows())}
        self.assertEqual(righe[self.rossi]["centro_di_costo_nome"], "LAVORAZIONI")
        self.assertEqual(righe[self.neri]["centro_di_costo_nome"], "")
        self.assertEqual(righe[self.gialli]["centro_di_costo_nome"], "")
        persone = {p.id: p for p in self.ctx().dipendenti()}
        self.assertEqual(persone[self.bianchi].centro_costo, "LAVORAZIONI")
        self.assertEqual(persone[self.verdi].centro_costo, "")

    def test_cambio_del_centro_si_vede_subito(self):
        altro = CentroDiCosto.objects.create(nome="ALTRO")
        self.sa1.centro_di_costo = altro
        self.sa1.save(update_fields=["centro_di_costo"])
        self.assertEqual({p.id for p in self.ctx(centri_costo=["ALTRO"]).dipendenti()}, {self.neri, self.verdi})


class PerimetroTests(_Base):
    def test_andata_e_ritorno_e_etichetta(self):
        p = Perimetro.from_dict({"centri_costo": ["LAVORAZIONI"]})
        self.assertEqual(Perimetro.from_dict(p.as_dict()).centri_costo, ["LAVORAZIONI"])
        self.assertIn("Centri di costo: LAVORAZIONI", p.label())

    def test_filtro_senza_differenza_di_maiuscole(self):
        self.assertEqual({p.id for p in self.ctx(centri_costo=["lavorazioni"]).dipendenti()},
                         {self.rossi, self.bianchi})

    def test_filtro_si_somma_agli_altri(self):
        self.assertEqual({p.id for p in self.ctx(centri_costo=["LAVORAZIONI"], aree=["IN1"]).dipendenti()},
                         {self.rossi})

    def test_vecchi_modelli_senza_il_filtro_non_cambiano(self):
        self.assertEqual(len(Perimetro.from_dict({"reparti": []}).centri_costo), 0)
        self.assertEqual(len(self.ctx().dipendenti()), 5)

    def test_scelte_solo_centri_attivi(self):
        CentroDiCosto.objects.create(nome="SPENTO", is_active=False)
        self.assertEqual(scelte_perimetro([])["centri_costo"], [("LAVORAZIONI", "LAVORAZIONI")])


class OrganicoPerCentroTests(_Base):
    def _per_centro(self, res):
        return {r["centro"]: r["persone"] for r in res.righe if r["livello"] == "Centro di costo"}

    def test_la_somma_fa_il_totale(self):
        res = self._sezione("centri_costo")
        self.assertEqual(self._per_centro(res), {"LAVORAZIONI": 2, SENZA_CENTRO: 3})
        self.assertEqual(sum(self._per_centro(res).values()), 5)
        self.assertEqual({k.label: k.value for k in res.kpis},
                         {"Centri di costo": 1, "Persone": 5, SENZA_CENTRO: 3})

    def test_reparti_ruoli_e_percentuali(self):
        righe = {(r["centro"], r.get("reparto", "")): r for r in self._sezione("centri_costo").righe}
        self.assertEqual(righe[("LAVORAZIONI", "IN1")]["persone"], 1)
        self.assertEqual(righe[("LAVORAZIONI", "IN1")]["ruoli"], "Operatore")
        self.assertEqual(righe[("LAVORAZIONI", "IN1")]["reparto_portale"], "Fresatura")
        self.assertEqual(righe[("LAVORAZIONI", "")]["pct"], 40.0)
        self.assertEqual(righe[(SENZA_CENTRO, "SA1")]["persone"], 2)
        self.assertEqual(righe[(SENZA_CENTRO, "Senza area")]["persone"], 1)

    def test_stessi_numeri_della_pagina_centri_di_costo(self):
        pagina = persone_per_area()
        righe = {r["reparto"]: r["persone"] for r in self._sezione("centri_costo").righe if r.get("reparto")}
        self.assertEqual(righe["IN1"], pagina[self.in1.pk])
        self.assertEqual(righe["IN2"], pagina[self.in2.pk])
        self.assertEqual(righe["SA1"], pagina[self.sa1.pk])

    def test_rispetta_il_perimetro_e_i_cessati(self):
        res = self._sezione("centri_costo", self.ctx(reparti=["Fresatura"]))
        self.assertEqual(self._per_centro(res), {"LAVORAZIONI": 2})
        self.assertEqual({k.label: k.value for k in res.kpis}[SENZA_CENTRO], 0)

    def test_opzioni(self):
        CentroDiCosto.objects.create(nome="VUOTO")
        CentroDiCosto.objects.create(nome="SPENTO", is_active=False)
        self.assertNotIn("VUOTO", self._per_centro(self._sezione("centri_costo")))
        tutti = self._sezione("centri_costo", solo_con_persone=False)
        self.assertEqual(self._per_centro(tutti)["VUOTO"], 0)
        self.assertNotIn("SPENTO", self._per_centro(tutti))
        solo = self._sezione("centri_costo", includi_reparti=False)
        self.assertTrue(all(r["livello"] == "Centro di costo" for r in solo.righe))


class AltreSezioniTests(_Base):
    def test_nessuna_sezione_si_rompe_e_le_colonne_esistono(self):
        for s in catalogo.catalogo():
            with self.subTest(sezione=s.key):
                s.calcola(self.ctx())
        con_persone = ["personale_elenco", "organico_movimenti", "scadenzario_unico", "formazione_erogata",
                       "costo_orario_persone"]
        for chiave in con_persone:
            self.assertIn("centro_costo", dict(catalogo.get(chiave).colonne), chiave)

    def test_elenco_personale(self):
        righe = {r["nominativo"]: r for r in self._sezione("personale_elenco").righe}
        self.assertEqual(sum(1 for r in righe.values() if r["centro_costo"] == "LAVORAZIONI"), 2)

    def test_distribuzione_dell_organico(self):
        res = self._sezione("organico_indicatori", dimensioni=["centro_costo"])
        voci = {r["voce"]: r["n"] for r in res.righe if r["dimensione"] == "Centro di costo"}
        self.assertEqual(voci, {"LAVORAZIONI": 2, "Non registrato": 3})

    def test_organigramma(self):
        righe = {r["area"]: r for r in self._sezione("organigramma").righe if r["area"]}
        self.assertEqual(righe["IN1"]["centro_costo"], "LAVORAZIONI")
        self.assertEqual(righe["SA1"]["centro_costo"], "")

    def test_formazione_erogata_per_centro(self):
        from .models_formazione import TrainingCourse, TrainingEmployeeRecord, TrainingPlan

        piano = TrainingPlan.objects.create(codice="PT", nome="Piano test", stato="ATTIVO")
        corso = TrainingCourse.objects.create(piano=piano, codice="C1", titolo="Corso C1", durata_ore_teorica=4,
                                              validita_mesi=12)
        for pid in (self.rossi, self.bianchi, self.neri):
            TrainingEmployeeRecord.objects.create(
                corso=corso, legacy_anagrafica_id=pid, data_completamento=self.oggi - timedelta(days=10), idoneo=True,
                course_code_snapshot="C1", course_title_snapshot="Corso C1")
        res = self._sezione("formazione_erogata", dettaglio="centro_costo")
        righe = {r["voce"]: r for r in res.righe}
        self.assertEqual((righe["LAVORAZIONI"]["persone"], righe["LAVORAZIONI"]["ore"]), (2, 8))
        self.assertEqual((righe[SENZA_CENTRO]["persone"], righe[SENZA_CENTRO]["ore"]), (1, 4))
        self.assertEqual(righe["LAVORAZIONI"]["centro_costo"], "LAVORAZIONI")
        self.assertIn("centro di costo", " ".join(res.note))
        filtro = self._sezione("formazione_erogata", dettaglio="centro_costo", confronto_ore="meno_di", soglia_ore=5)
        self.assertEqual([r["voce"] for r in filtro.righe], [SENZA_CENTRO])
        kpi = {k.label for k in filtro.kpis}
        self.assertIn("Centri di costo con meno di 5 ore", kpi)

    def test_struttura(self):
        for chiave in ("ruoli_persone", "ruoli_mansioni_persona"):
            self.assertIn("centro_costo", dict(catalogo.get(chiave).colonne), chiave)
        righe = {r["nominativo"]: r for r in self._sezione("ruoli_mansioni_persona").righe}
        self.assertEqual(sum(1 for r in righe.values() if r["centro_costo"] == "LAVORAZIONI"), 2)


class CostoOrarioPerCentroTests(_Base):
    def setUp(self):
        super().setUp()
        self.mese = self.oggi.replace(day=1)
        self.prima = (self.mese - timedelta(days=1)).replace(day=1)
        for i, (pid, rml) in enumerate(((self.rossi, "2000.00"), (self.bianchi, "4000.00"), (self.neri, "3000.00"))):
            for mese in (self.prima, self.mese):
                CostoOrarioMensile.objects.create(
                    tax_code=f"SNTTST80A01H50{i}Z", legacy_anagrafica_id=pid, mese=mese, rml=D(rml),
                    divisore_giorni=D("26"), divisore_ore=D("6.66"),
                    costo_orario=(D(rml) / D("26") / D("6.66")).quantize(D("0.0001")))

    def test_ripartito_tiene_i_totali_del_reparto(self):
        centro = {r["voce"]: r for r in self._sezione("costo_orario_ripartito", per="centro_costo").righe}
        self.assertEqual(centro["LAVORAZIONI"]["rml"], D("6000.00"))
        self.assertEqual(centro["LAVORAZIONI"]["persone"], 2)
        self.assertEqual(centro[SENZA_CENTRO]["rml"], D("3000.00"))
        reparto = self._sezione("costo_orario_ripartito", per="reparto").righe
        self.assertEqual(sum(r["rml"] for r in centro.values()), sum(r["rml"] for r in reparto))

    def test_senza_centro_evidenziato_e_nota_sul_centro_di_oggi(self):
        res = self._sezione("costo_orario_ripartito", per="centro_costo")
        toni = {r["voce"]: t for r, t in zip(res.righe, res.toni, strict=True)}
        self.assertEqual(toni["LAVORAZIONI"], "")
        self.assertNotEqual(toni[SENZA_CENTRO], "")
        self.assertIn("quello di oggi", " ".join(res.note))
        self.assertNotIn("quello di oggi", " ".join(self._sezione("costo_orario_ripartito", per="reparto").note))

    def test_andamento(self):
        res = self._sezione("costo_orario_andamento", per="centro_costo")
        gruppi = {r["gruppo"] for r in res.righe}
        self.assertEqual(gruppi, {"LAVORAZIONI", SENZA_CENTRO})
        riga = next(r for r in res.righe if r["gruppo"] == "LAVORAZIONI" and r["mese"] == self.mese.strftime("%m/%Y"))
        self.assertEqual((riga["persone"], riga["rml"]), (2, D("6000.00")))
        self.assertIn("quello di oggi", " ".join(res.note))

    def test_per_persona(self):
        righe = {r["nominativo"]: r["centro_costo"] for r in self._sezione("costo_orario_persone").righe}
        self.assertEqual(sorted(righe.values()), ["", "LAVORAZIONI", "LAVORAZIONI"])

    def test_pagina_costo_orario_filtra_e_dice_il_centro(self):
        r = self.client.get(reverse("anagrafica:costo_orario"))
        self.assertEqual(len(r.context["righe"]), 3)
        self.assertEqual(r.context["centri"], ["LAVORAZIONI"])
        self.assertContains(r, 'name="centro_costo"')
        r = self.client.get(reverse("anagrafica:costo_orario"), {"centro_costo": "LAVORAZIONI"})
        self.assertEqual({x["legacy_id"] for x in r.context["righe"]}, {self.rossi, self.bianchi})

    def test_pagina_e_report_dicono_lo_stesso_reparto(self):
        """Il testo legacy è diverso dal reparto canonico: pagina e report usano il canonico."""
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("UPDATE anagrafica_dipendenti SET reparto = %s WHERE id = %s", ["TESTO VECCHIO", self.rossi])
        r = self.client.get(reverse("anagrafica:costo_orario"))
        pagina = {x["legacy_id"]: x["reparto"] for x in r.context["righe"]}
        self.assertEqual(pagina[self.rossi], "Fresatura")
        report = {p.id: p.reparto for p in self.ctx().dipendenti()}
        self.assertEqual(pagina[self.rossi], report[self.rossi])

    def test_storico_filtra(self):
        r = self.client.get(reverse("anagrafica:costo_orario_storico"), {"centro_costo": "LAVORAZIONI"})
        self.assertEqual({x["legacy_id"] for x in r.context["righe"]}, {self.rossi, self.bianchi})

    def test_export_hanno_la_colonna(self):
        spec = EXPORT_SPECS["costo_orario"]
        self.assertIn(("Centro di costo", "centro_costo"), spec.columns)
        richiesta = self.client.get(reverse("anagrafica:costo_orario"), {"centro_costo": "LAVORAZIONI"}).wsgi_request
        righe = spec.dataset(richiesta, "filtered")
        self.assertEqual({x["centro_costo"] for x in righe}, {"LAVORAZIONI"})
        self.assertIn("Centro di costo: LAVORAZIONI", spec.filters_label(richiesta))
        storico = EXPORT_SPECS["costo_orario_storico"]
        self.assertIn("LAVORAZIONI", {x["centro_costo"] for x in storico.dataset(richiesta, "full")})
        r = self.client.get(reverse("anagrafica:export", args=["costo_orario"]), {"format": "xlsx", "scope": "full"})
        self.assertEqual(r.status_code, 200)


class ChiediUnReportTests(_Base):
    def _scelte(self):
        return {**scelte_perimetro([]), "reparti": [("LOGISTICA", "LOGISTICA")], "aree": [("LOGISTICA", "LOGISTICA")],
                "centri_costo": [("LOGISTICA", "LOGISTICA"), ("STRUTTURA", "STRUTTURA")]}

    def test_il_centro_nominato_non_filtra_anche_il_reparto_omonimo(self):
        spec = interpreta_senza_ai("elenco del personale del centro di costo LOGISTICA", specifica_vuota(), self._scelte())
        self.assertEqual(spec["perimetro"]["centri_costo"], ["LOGISTICA"])
        self.assertNotIn("reparti", spec["perimetro"])
        self.assertNotIn("aree", spec["perimetro"])

    def test_la_sigla_cdc_vale(self):
        spec = interpreta_senza_ai("elenco del personale cdc struttura", specifica_vuota(), self._scelte())
        self.assertEqual(spec["perimetro"]["centri_costo"], ["STRUTTURA"])

    def test_parola_comune_non_diventa_un_centro(self):
        spec = interpreta_senza_ai("organigramma e struttura della logistica", specifica_vuota(), self._scelte())
        self.assertNotIn("centri_costo", spec["perimetro"])
        self.assertEqual(spec["perimetro"]["reparti"], ["LOGISTICA"])

    def test_richiesta_della_sezione(self):
        spec = interpreta_senza_ai("organico per centro di costo", specifica_vuota(), self._scelte())
        self.assertIn("centri_costo", [s["sezione"] for s in spec["sezioni"]])

    def test_risposta_ai_validata(self):
        grezza = {"perimetro": {"centri_costo": ["logistica", "INVENTATO"]},
                  "sezioni": [{"sezione": "centri_costo"}]}
        richiesta = self.client.get(reverse("anagrafica:costo_orario")).wsgi_request
        spec, avvisi = normalizza_specifica(grezza, richiesta, self._scelte(), [])
        self.assertEqual(spec["perimetro"]["centri_costo"], ["LOGISTICA"])
        self.assertTrue(any("INVENTATO" in a for a in avvisi))


class ModelloProntoTests(_Base):
    def test_usa_sezioni_e_opzioni_esistenti(self):
        spec = next(m for m in MODELLI if m["codice_sistema"] == "centri_costo")
        for b in spec["blocchi"]:
            sezione = catalogo.get(b["sezione"])
            self.assertIsNotNone(sezione)
            valori = (b.get("opzioni") or {}).get("valori") or {}
            if "per" in valori:
                self.assertEqual(sezione.valori_opzioni(valori)["per"], "centro_costo")

    def test_si_crea_una_volta_e_non_tocca_le_modifiche(self):
        ReportModello.objects.filter(codice_sistema="centri_costo").delete()
        self.assertEqual(crea_predefiniti(ReportModello, ReportBlocco), 1)
        m = ReportModello.objects.get(codice_sistema="centri_costo")
        m.nome = "Modificato"
        m.save(update_fields=["nome"])
        self.assertEqual(crea_predefiniti(ReportModello, ReportBlocco), 0)
        self.assertEqual(ReportModello.objects.get(codice_sistema="centri_costo").nome, "Modificato")


class DocumentoTests(_Base):
    def setUp(self):
        super().setUp()
        self.modello = ReportModello.objects.get(codice_sistema="centri_costo")
        self.url = reverse("anagrafica:reportistica_genera", args=[self.modello.pk])
        for pid in (self.rossi, self.neri):
            CostoOrarioMensile.objects.create(
                tax_code=f"SNTTST80A01H50{pid % 10}Z", legacy_anagrafica_id=pid, mese=self.oggi.replace(day=1),
                rml=D("3463.20"), divisore_giorni=D("26"), divisore_ore=D("6.66"), costo_orario=D("20.0000"))

    def _post(self, azione, **extra):
        return self.client.post(self.url, {"titolo": "Centri", "periodo_tipo": "ULTIMI_12_MESI", "azione": azione, **extra})

    def test_il_form_offre_il_filtro(self):
        r = self.client.get(self.url)
        self.assertContains(r, 'name="centri_costo"')
        self.assertContains(r, "Organico per centro di costo")
        self.assertNotContains(r, "{#")

    def test_anteprima_col_filtro(self):
        r = self._post("anteprima", centri_costo=["LAVORAZIONI"])
        self.assertContains(r, "Centri di costo: LAVORAZIONI")
        self.assertContains(r, "RML e costo orario per centro di costo")
        self.assertNotContains(r, SENZA_CENTRO + "</td>")

    def test_pdf_ed_excel(self):
        pdf = self._post("pdf")
        self.assertEqual(pdf["Content-Type"], "application/pdf")
        xlsx = self._post("xlsx", centri_costo=["LAVORAZIONI"])
        self.assertIn("spreadsheet", xlsx["Content-Type"])

    def test_senza_permesso_hr_niente_costi(self):
        from unittest.mock import patch

        senza_costi = lambda sezione, request: not sezione.key.startswith("costo_orario")  # noqa: E731
        with patch.object(catalogo.Sezione, "consentita", senza_costi):
            r = self._post("anteprima")
        self.assertContains(r, "Sezione omessa")
        self.assertContains(r, "Organico per centro di costo")
        self.assertNotContains(r, "3.463,20")


class PagineTests(_Base):
    def test_colonna_dell_elenco_dal_registro(self):
        self.assertEqual(REGISTRO["centro_costo"].campo, "centro_di_costo_nome")
        r = self.client.get(reverse("anagrafica:dipendenti_list"), {"colonne": "centro_costo"})
        self.assertEqual(r.status_code, 200)

    def test_report_dipendenti_colonna_filtro_e_csv(self):
        url = reverse("anagrafica:dipendenti_report")
        r = self.client.get(url)
        self.assertContains(r, "<th>Centro di costo</th>", html=False)
        self.assertEqual(r.context["centri_costo"], ["LAVORAZIONI"])
        r = self.client.get(url, {"centro_costo": "LAVORAZIONI"})
        self.assertEqual({int(x["id"]) for x in r.context["page_obj"]}, {self.rossi, self.bianchi})
        righe = self.client.get(url, {"centro_costo": "LAVORAZIONI", "format": "csv"}).content.decode(errors="ignore").splitlines()
        self.assertIn("Centro di costo", righe[0])
        self.assertEqual(len(righe), 3)
        self.assertTrue(all("LAVORAZIONI" in x for x in righe[1:]))

    def test_scheda_dipendente(self):
        r = self.client.get(reverse("anagrafica:dipendente_detail", args=[self.rossi]))
        self.assertContains(r, "Centro di costo")
        self.assertContains(r, "LAVORAZIONI")


class EtichetteTests(_Base):
    def test_ruolo_del_reparto_con_sigla(self):
        cam = RuoloOperativo.objects.create(nome="CAM Manager", sigla="CAMM")
        self.in1.ruoli_reparto.add(cam)
        righe = {r.get("reparto"): r for r in self._sezione("centri_costo").righe}
        self.assertEqual(righe["IN1"]["ruoli"], "CAMM, Operatore")
