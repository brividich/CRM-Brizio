"""Remediation R3 (26/11/2026 sera): catalogo corsi e obblighi.

Una regola sola per «obbligatorio» (spunta + motore), «Da assegnare» dal motore dei requisiti,
validità in blocco con un ricalcolo e le versioni, report del corso coerenti con la scheda,
sessioni annullate fuori dai conteggi, elimina corso senza 500 né cascate, export elenco corsi
con i filtri della pagina, onboarding con i corsi del motore. Dati sintetici.
"""
from __future__ import annotations

import csv
import io
import zipfile
from datetime import time, timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from core.legacy_models import AnagraficaDipendente

from .models import DipendenteAnagraficaAziendale, DipendenteRuoloOperativo, RuoloOperativo
from .models_formazione import (
    TrainingAssignment,
    TrainingCourse,
    TrainingCourseVersion,
    TrainingDeadline,
    TrainingEmployeeRecord,
    TrainingEnrollment,
    TrainingLesson,
    TrainingPlan,
    TrainingRequirementRule,
    TrainingSession,
)
from .services import formazione_catalogo as cat

OGGI = timezone.localdate()


class _Base(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("hr.r3", "hr.r3@example.invalid", "pwd12345")
        self.client.force_login(self.admin)
        self.piano = TrainingPlan.objects.create(codice="PR3", nome="Piano sintetico R3")
        self.anna = AnagraficaDipendente.objects.create(nome="Anna", cognome="SINTETICA", aliasusername="r3.anna")
        self.bruno = AnagraficaDipendente.objects.create(nome="Bruno", cognome="SINTETICO", aliasusername="r3.bruno")
        self.ex = AnagraficaDipendente.objects.create(nome="Ezio", cognome="USCITO", aliasusername="r3.ezio")
        DipendenteAnagraficaAziendale.objects.create(legacy_anagrafica_id=self.ex.pk,
                                                     data_cessazione=OGGI - timedelta(days=30))

    def corso(self, codice, **kw):
        kw.setdefault("durata_ore_teorica", Decimal("2"))
        kw.setdefault("stato", "ATTIVO")
        return TrainingCourse.objects.create(piano=self.piano, codice=codice, titolo=f"Corso {codice}", **kw)


# ── A ──────────────────────────────────────────────────────────────────────
class SpuntaObbligatorioRicalcolaTests(_Base):
    def test_spunta_crea_le_scadenze(self):
        c = self.corso("A1")
        self.assertFalse(TrainingDeadline.objects.filter(corso=c).exists())
        c.obbligatorio = True
        with self.captureOnCommitCallbacks(execute=True):
            c.save()
        tenuti = set(TrainingDeadline.objects.filter(corso=c, is_required=True)
                     .values_list("legacy_anagrafica_id", flat=True))
        self.assertIn(self.anna.pk, tenuti)
        self.assertNotIn(self.ex.pk, tenuti)


# ── B ──────────────────────────────────────────────────────────────────────
class ObbligatorioRegolaUnicaTests(_Base):
    def setUp(self):
        super().setUp()
        self.tutti = self.corso("B1", obbligatorio=True)
        self.ruolo = RuoloOperativo.objects.create(nome="Preposto R3")
        self.per_ruolo = self.corso("B2")
        TrainingRequirementRule.objects.create(corso=self.per_ruolo, ruolo_operativo=self.ruolo)
        self.da_cache = self.corso("B3")
        TrainingDeadline.objects.create(corso=self.da_cache, legacy_anagrafica_id=self.anna.pk, is_required=True,
                                        stato_scadenza="MAI_FREQUENTATO")
        self.scaduta = self.corso("B4")
        TrainingRequirementRule.objects.create(corso=self.scaduta, ruolo_operativo=self.ruolo,
                                               data_fine_validita=OGGI - timedelta(days=1))
        self.facoltativo = self.corso("B5")

    def test_funzione_unica(self):
        ob = cat.corsi_obbligatori()
        self.assertEqual(ob[self.tutti.pk], cat.PER_TUTTI)
        self.assertEqual(ob[self.per_ruolo.pk], cat.PER_MANSIONE)
        self.assertEqual(ob[self.da_cache.pk], cat.PER_MANSIONE)
        self.assertNotIn(self.scaduta.pk, ob)
        self.assertNotIn(self.facoltativo.pk, ob)
        self.assertEqual(cat.etichetta_obbligo(cat.PER_TUTTI), "Sì · per tutti")

    def test_elenco_filtro_e_colonna(self):
        r = self.client.get(reverse("anagrafica:formazione_corsi_list"), {"obbligatorio": "1"})
        codici = {c.codice for c in r.context["page_obj"]}
        self.assertEqual(codici, {"B1", "B2", "B3"})
        self.assertContains(r, "Sì · per mansione/ruolo/processo")
        self.assertContains(r, "Sì · per tutti")
        r = self.client.get(reverse("anagrafica:formazione_corsi_list"), {"obbligatorio": "0"})
        self.assertEqual({c.codice for c in r.context["page_obj"]}, {"B4", "B5"})

    def test_piano_tipi_export(self):
        r = self.client.get(reverse("anagrafica:formazione_piano_detail", args=[self.piano.pk]))
        self.assertContains(r, "Sì · per mansione/ruolo/processo")
        from .exports_formazione import _formazione_corsi_rows
        req = RequestFactory().get("/", {"obbligatorio": "1"})
        righe = {x["codice"]: x for x in _formazione_corsi_rows(req, "filtered")}
        self.assertEqual(set(righe), {"B1", "B2", "B3"})
        self.assertEqual(righe["B1"]["obbligatorio"], "Sì · per tutti")


# ── C ──────────────────────────────────────────────────────────────────────
class DaAssegnareDalMotoreTests(_Base):
    def test_ruolo_chiuso_e_regola_scaduta_non_contano(self):
        from .services.training_eligibility import candidati_corso

        ruolo = RuoloOperativo.objects.create(nome="Carrellista R3")
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=self.anna.pk, ruolo=ruolo)
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=self.bruno.pk, ruolo=ruolo,
                                                data_fine=OGGI - timedelta(days=10))
        c = self.corso("C1")
        TrainingRequirementRule.objects.create(corso=c, ruolo_operativo=ruolo)
        res = candidati_corso(c)
        self.assertTrue(res["pool_filtrato"])
        self.assertEqual({x["legacy_id"] for x in res["idonei"]}, {self.anna.pk})

        scaduta = self.corso("C2")
        TrainingRequirementRule.objects.create(corso=scaduta, ruolo_operativo=ruolo,
                                               data_fine_validita=OGGI - timedelta(days=1))
        self.assertEqual(candidati_corso(scaduta)["idonei"], [])

    def test_in_scadenza_e_valido(self):
        from .services.training_eligibility import candidati_corso

        c = self.corso("C3", obbligatorio=True, validita_mesi=12)
        TrainingEmployeeRecord.objects.create(corso=c, legacy_anagrafica_id=self.anna.pk, idoneo=True,
                                              data_completamento=OGGI - timedelta(days=340),
                                              data_scadenza=OGGI + timedelta(days=20))
        TrainingEmployeeRecord.objects.create(corso=c, legacy_anagrafica_id=self.bruno.pk, idoneo=True,
                                              data_completamento=OGGI, data_scadenza=OGGI + timedelta(days=360))
        res = candidati_corso(c)
        per_id = {x["legacy_id"]: x for x in res["idonei"]}
        self.assertEqual(per_id[self.anna.pk]["stato"], "IN_SCADENZA_30")
        self.assertTrue(per_id[self.anna.pk]["preselect"])
        self.assertNotIn(self.bruno.pk, per_id)
        self.assertNotIn(self.ex.pk, per_id)


# ── D ──────────────────────────────────────────────────────────────────────
class ValiditaInBloccoTests(_Base):
    def test_un_ricalcolo_e_versioni(self):
        c1, c2 = self.corso("D1", validita_mesi=0), self.corso("D2", validita_mesi=0)
        with mock.patch("anagrafica.services.scadenze.ricalcola_tutto") as ric, \
                self.captureOnCommitCallbacks(execute=True):
            esito = cat.imposta_validita([c1.pk, c2.pk], "24", user=self.admin)
        self.assertEqual(esito["corsi"], 2)
        self.assertEqual(ric.call_count, 1)
        ric.assert_called_with(None)
        for c in (c1, c2):
            self.assertTrue(TrainingCourseVersion.objects.filter(corso=c, validita_mesi_snapshot=24).exists())


# ── E / F ─────────────────────────────────────────────────────────────────
class SchedaEReportTests(_Base):
    def setUp(self):
        super().setUp()
        self.c = self.corso("E1", validita_mesi=12)
        # Anna: un non idoneo e poi due idonei (l'ultimo valido); Ezio (ex) idoneo valido.
        TrainingEmployeeRecord.objects.create(corso=self.c, legacy_anagrafica_id=self.anna.pk, idoneo=False,
                                              data_completamento=OGGI - timedelta(days=200))
        TrainingEmployeeRecord.objects.create(corso=self.c, legacy_anagrafica_id=self.anna.pk, idoneo=True,
                                              data_completamento=OGGI - timedelta(days=100),
                                              data_scadenza=OGGI + timedelta(days=200))
        TrainingEmployeeRecord.objects.create(corso=self.c, legacy_anagrafica_id=self.anna.pk, idoneo=True,
                                              data_completamento=OGGI - timedelta(days=10),
                                              data_scadenza=OGGI + timedelta(days=300))
        TrainingEmployeeRecord.objects.create(corso=self.c, legacy_anagrafica_id=self.ex.pk, idoneo=True,
                                              data_completamento=OGGI - timedelta(days=50),
                                              data_scadenza=OGGI + timedelta(days=250))
        # Bruno: solo un'assegnazione aperta (prima non compariva fra le persone del corso).
        TrainingAssignment.objects.create(corso=self.c, legacy_anagrafica_id=self.bruno.pk, stato="ASSEGNATO")

    def test_scheda_persone_del_corso(self):
        r = self.client.get(reverse("anagrafica:formazione_corso_detail", args=[self.c.pk]))
        self.assertEqual(r.status_code, 200)
        righe = {d["legacy_id"]: d for d in r.context["dipendenti_iscritti"]}
        self.assertEqual(set(righe), {self.anna.pk, self.bruno.pk})
        self.assertEqual(r.context["n_ex_dipendenti"], 1)
        self.assertEqual(righe[self.anna.pk]["n_completati"], 2)  # solo idonei
        self.assertEqual(righe[self.anna.pk]["stato_sint"], "COMPLETATO")
        self.assertEqual(r.context["n_completamenti"], 3)
        self.assertEqual(r.context["come_si_fa"]["assegnati"], 1)
        self.assertContains(r, "Persone con un'attività sul corso")
        pool = {lid for lid, _n in r.context["dipendenti_pool"]}
        self.assertIn(self.anna.pk, pool)
        self.assertNotIn(self.ex.pk, pool)

    def test_sola_lettura(self):
        with mock.patch("anagrafica.views._helpers._can_edit_formazione", return_value=False):
            r = self.client.get(reverse("anagrafica:formazione_corso_detail", args=[self.c.pk]))
        self.assertNotContains(r, 'data-corso-tab="persone"')

    def test_csv(self):
        r = self.client.get(reverse("anagrafica:formazione_corso_report_iscritti_csv", args=[self.c.pk]))
        righe = list(csv.reader(io.StringIO(r.content.decode("utf-8-sig")), delimiter=";"))
        self.assertIn("Completamenti idonei", righe[0])
        per_id = {int(x[1]): x for x in righe[1:]}
        self.assertEqual(set(per_id), {self.anna.pk, self.bruno.pk, self.ex.pk})
        self.assertEqual(per_id[self.anna.pk][3], "Completato")
        self.assertEqual(per_id[self.anna.pk][6], "2")
        self.assertTrue(per_id[self.ex.pk][2].startswith("No"))
        self.assertEqual(int(righe[-1][1]), self.ex.pk)  # ex dipendenti in fondo

    def test_zip_solo_ultimo_valido(self):
        import tempfile

        from django.test import override_settings
        with tempfile.TemporaryDirectory() as root, override_settings(ANAGRAFICA_PRIVATE_ROOT=root):
            r = self.client.get(reverse("anagrafica:formazione_corso_attestati_zip", args=[self.c.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(zipfile.ZipFile(io.BytesIO(r.content)).namelist()), 2)  # Anna (ultimo) + Ezio

    def test_report_conformita_corso_facoltativo(self):
        r = self.client.get(reverse("anagrafica:formazione_corso_detail", args=[self.c.pk]))
        self.assertContains(r, "obbligatori=0")
        self.assertContains(r, "Scaduti, in scadenza e mai frequentati")

    def test_fogli_firme_solo_lezioni_da_fare(self):
        from .services import attestato_pdf

        aperta = TrainingSession.objects.create(corso=self.c, codice_sessione="E1-A", stato="PIANIFICATA",
                                                data_inizio=OGGI, data_fine=OGGI + timedelta(days=10))
        annullata = TrainingSession.objects.create(corso=self.c, codice_sessione="E1-X", stato="ANNULLATA",
                                                   data_inizio=OGGI, data_fine=OGGI + timedelta(days=10))
        TrainingEnrollment.objects.create(sessione=aperta, legacy_anagrafica_id=self.anna.pk)
        for n, (sess, giorno) in enumerate(((aperta, OGGI - timedelta(days=1)), (aperta, OGGI + timedelta(days=2)),
                                            (annullata, OGGI + timedelta(days=2))), start=1):
            TrainingLesson.objects.create(sessione=sess, numero=n, data=giorno, ora_inizio=time(9),
                                          ora_fine=time(12), argomento="Sintetico")
        with mock.patch.object(attestato_pdf, "_foglio_firme_lezione_story", return_value=[]) as story:
            attestato_pdf.build_registri_corso_pdf_bytes(self.c)
        self.assertEqual(story.call_count, 1)


# ── G ──────────────────────────────────────────────────────────────────────
class SessioniAnnullateTests(_Base):
    def test_annullate_fuori(self):
        c = self.corso("G1")
        TrainingSession.objects.create(corso=c, codice_sessione="G1-OK", modalita="IN_SEDE", stato="COMPLETATA",
                                       data_inizio=OGGI - timedelta(days=9), data_fine=OGGI - timedelta(days=9))
        TrainingSession.objects.create(corso=c, codice_sessione="G1-NO", modalita="ESTERNO", stato="ANNULLATA",
                                       data_inizio=OGGI - timedelta(days=5), data_fine=OGGI - timedelta(days=5))
        r = self.client.get(reverse("anagrafica:formazione_corso_detail", args=[c.pk]))
        self.assertEqual([s.codice_sessione for s in r.context["sessioni_list"]], ["G1-OK"])
        self.assertContains(r, "stato=NON_ANNULLATE")
        r = self.client.get(reverse("anagrafica:formazione_corsi_list"))
        corso = next(x for x in r.context["page_obj"] if x.pk == c.pk)
        self.assertEqual([k for k, _e in corso.modi], ["IN_SEDE"])
        conteggi = {k: n for k, _e, n in r.context["modi_conteggi"]}
        self.assertEqual((conteggi["aula"], conteggi["esterno"]), (1, 0))
        r = self.client.get(reverse("anagrafica:formazione_piano_detail", args=[self.piano.pk]))
        self.assertEqual(next(x for x in r.context["corsi"] if x.pk == c.pk).n_sessioni, 1)
        r = self.client.get(reverse("anagrafica:formazione_sessioni_list"), {"corso": c.pk, "stato": "NON_ANNULLATE"})
        self.assertEqual([s.codice_sessione for s in r.context["page_obj"]], ["G1-OK"])


# ── H ──────────────────────────────────────────────────────────────────────
class EliminaCorsoTests(_Base):
    def test_bloccato_con_storico(self):
        c = self.corso("H1")
        TrainingEmployeeRecord.objects.create(corso=c, legacy_anagrafica_id=self.anna.pk, idoneo=True,
                                              data_completamento=OGGI)
        r = self.client.post(reverse("anagrafica:formazione_corso_delete", args=[c.pk]), follow=True)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(TrainingCourse.objects.filter(pk=c.pk).exists())
        self.assertContains(r, "Archivia il corso")

    def test_bloccato_con_assegnazione_e_libero_senza(self):
        c = self.corso("H2")
        TrainingAssignment.objects.create(corso=c, legacy_anagrafica_id=self.anna.pk)
        self.assertEqual(cat.motivi_blocco_eliminazione(c), ["assegnazioni"])
        self.client.post(reverse("anagrafica:formazione_corso_delete", args=[c.pk]))
        self.assertTrue(TrainingCourse.objects.filter(pk=c.pk).exists())
        vuoto = self.corso("H3")
        self.client.post(reverse("anagrafica:formazione_corso_delete", args=[vuoto.pk]))
        self.assertFalse(TrainingCourse.objects.filter(pk=vuoto.pk).exists())


# ── I ──────────────────────────────────────────────────────────────────────
class ExportElencoCorsiTests(_Base):
    def test_stesse_righe_e_colonne(self):
        from .exports_formazione import _formazione_corsi_rows

        c = self.corso("I1", ente_formativo=None)
        TrainingSession.objects.create(corso=c, codice_sessione="I1-S", modalita="IN_SEDE", stato="COMPLETATA",
                                       data_inizio=OGGI, data_fine=OGGI)
        self.corso("I2")
        params = {"modo": "aula"}
        r = self.client.get(reverse("anagrafica:formazione_corsi_list"), params)
        pagina = [x.codice for x in r.context["page_obj"]]
        righe = _formazione_corsi_rows(RequestFactory().get("/", params), "filtered")
        self.assertEqual([x["codice"] for x in righe], pagina)
        self.assertEqual(righe[0]["modi"], "In aula")
        self.assertIn("tipo", righe[0])
        self.assertIn("enti", righe[0])

    def test_una_tantum_e_senza_tipo(self):
        attivo = self.corso("I3")
        attivo.titolo = "Aggiornamento antincendio sintetico"
        attivo.save()
        spento = self.corso("I4", is_active=False)
        spento.titolo = "Aggiornamento primo soccorso sintetico"
        spento.save()
        ids = cat.ids_una_tantum_da_rivedere()
        self.assertIn(attivo.pk, ids)
        self.assertNotIn(spento.pk, ids)
        r = self.client.get(reverse("anagrafica:formazione_tipi_corso"))
        n = TrainingCourse.objects.filter(tipo__isnull=True).count()
        self.assertEqual(r.context["n_senza_tipo"], n)
        r = self.client.get(reverse("anagrafica:formazione_corsi_list"))
        self.assertEqual(r.context["n_senza_tipo"], n)


# ── J ──────────────────────────────────────────────────────────────────────
class OnboardingCorsiDalMotoreTests(_Base):
    def test_obbligatorio_per_tutti_nella_pratica(self):
        from .services import onboarding

        c = self.corso("J1", obbligatorio=True)
        voci = onboarding.task_definitions(mansione="Mansione sintetica R3")
        self.assertIn(f"corso_{c.pk}", {v["codice"] for v in voci})
        self.assertNotIn("formazione_corsi_obbligatori", {v["codice"] for v in voci})

    def test_regola_del_ruolo_scelto(self):
        from .services import onboarding

        ruolo = RuoloOperativo.objects.create(nome="Addetto R3")
        c = self.corso("J2")
        TrainingRequirementRule.objects.create(corso=c, ruolo_operativo=ruolo)
        voci = onboarding.task_definitions(mansione="", ruolo_ids=[ruolo.pk])
        self.assertIn(f"corso_{c.pk}", {v["codice"] for v in voci})
