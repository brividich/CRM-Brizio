"""Coerenza formazione/qualifiche (ag4): menu, filtri, istruttori, libretto, qualifiche mancanti.

Solo dati sintetici.
"""
from __future__ import annotations

from datetime import date, time, timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.legacy_models import AnagraficaDipendente

from .models import (
    DipendenteAnagraficaAziendale,
    DipendenteQualifica,
    DipendenteRuoloOperativo,
    RuoloOperativo,
    RuoloQualifica,
    SubnavCategoriaAnagrafica,
    SubnavLinkAnagrafica,
    TipoQualifica,
)
from .models_formazione import (
    TrainingCourse,
    TrainingEnrollment,
    TrainingInstructor,
    TrainingLesson,
    TrainingPlan,
    TrainingSession,
)
from .tests import _ensure_anagrafica_table

User = get_user_model()


def _onboarded(user):
    try:
        from core.models import UserOnboarding

        UserOnboarding.objects.update_or_create(user=user, defaults={"completed": True})
    except Exception:  # pragma: no cover
        pass


@override_settings(LEGACY_AUTH_ENABLED=False)
class _Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()

    def setUp(self):
        self.admin = User.objects.create_superuser("ag4_admin", "ag4@example.invalid", "x")
        _onboarded(self.admin)
        self.client.force_login(self.admin)
        self.oggi = timezone.localdate()


class FormazionePagineTests(_Base):
    def test_piano_un_solo_pulsante_nuovo_corso(self):
        piano = TrainingPlan.objects.create(codice="PAG4", nome="Piano sintetico")
        resp = self.client.get(reverse("anagrafica:formazione_piano_detail", args=[piano.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "+ Nuovo corso")
        self.assertContains(resp, "+ Aggiungi corso", count=1)

    def test_corsi_pastiglie_e_pagine_conservano_i_filtri(self):
        piano = TrainingPlan.objects.create(codice="PAG4C", nome="Piano")
        for i in range(55):
            TrainingCourse.objects.create(piano=piano, codice=f"CAG{i:02d}", titolo=f"Corso sintetico {i}",
                                          durata_ore_teorica=1, stato="ATTIVO", obbligatorio=True)
        resp = self.client.get(reverse("anagrafica:formazione_corsi_list"),
                               {"q": "sintetico", "stato": "ATTIVO", "obbligatorio": "1", "attivi": "1",
                                "piano": str(piano.pk)})
        self.assertEqual(resp.status_code, 200)
        attesi = f"q=sintetico&amp;piano={piano.pk}&amp;stato=ATTIVO&amp;obbligatorio=1&amp;attivi=1&amp;"
        self.assertContains(resp, f'href="?{attesi}modo=slide"')
        self.assertContains(resp, f'href="?{attesi}tipo=nessuno"')
        self.assertContains(resp, f'href="?{attesi}page=2"')
        self.assertContains(resp, "Corsi online")
        self.assertNotContains(resp, "Cruscotto online")

    def test_dashboard_edizioni_al_posto_delle_aree(self):
        piano = TrainingPlan.objects.create(codice="PAG4D", nome="Piano")
        corso = TrainingCourse.objects.create(piano=piano, codice="CAGD", titolo="Corso", durata_ore_teorica=1)
        TrainingSession.objects.create(corso=corso, codice_sessione="SAG-IN", data_inizio=self.oggi,
                                       data_fine=self.oggi + timedelta(days=1), stato="IN_CORSO")
        TrainingSession.objects.create(corso=corso, codice_sessione="SAG-CH", data_inizio=self.oggi - timedelta(days=5),
                                       data_fine=self.oggi - timedelta(days=4), stato="PIANIFICATA")
        resp = self.client.get(reverse("anagrafica:formazione_dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "Aree del modulo")
        self.assertEqual(resp.context["edizioni_in_corso"], 1)
        self.assertEqual(resp.context["edizioni_da_chiudere"], 1)
        self.assertContains(resp, "?da_chiudere=1")

    def test_istruttori_sessioni_uguali_in_elenco_e_scheda_discenti_senza_ritirati(self):
        piano = TrainingPlan.objects.create(codice="PAG4I", nome="Piano")
        corso = TrainingCourse.objects.create(piano=piano, codice="CAGI", titolo="Corso", durata_ore_teorica=4)
        doc = TrainingInstructor.objects.create(tipo="INTERNO", nome="Docente Sintetico")
        titolare = TrainingSession.objects.create(corso=corso, codice_sessione="SAG-T", data_inizio=self.oggi,
                                                  data_fine=self.oggi, docente=doc)
        altra = TrainingSession.objects.create(corso=corso, codice_sessione="SAG-L", data_inizio=self.oggi,
                                               data_fine=self.oggi)
        TrainingLesson.objects.create(sessione=altra, numero=1, data=self.oggi, ora_inizio=time(9, 0),
                                      ora_fine=time(11, 0), docente=doc)
        TrainingEnrollment.objects.create(sessione=titolare, legacy_anagrafica_id=9101)
        TrainingEnrollment.objects.create(sessione=titolare, legacy_anagrafica_id=9102, stato="RITIRATO")
        elenco = self.client.get(reverse("anagrafica:formazione_istruttori_list"))
        riga = next(i for i in elenco.context["istruttori"] if i.pk == doc.pk)
        self.assertEqual(riga.n_sessioni, 2)
        self.assertNotContains(elenco, "Corsi svolti")
        scheda = self.client.get(reverse("anagrafica:formazione_istruttore_detail", args=[doc.pk]))
        self.assertEqual(len(scheda.context["sessioni"]), 2)
        self.assertEqual(scheda.context["discenti"], 1)
        self.assertContains(scheda, "Discenti")

    def test_scheda_corso_filtro_modalita_con_slide_e_test(self):
        piano = TrainingPlan.objects.create(codice="PAG4S", nome="Piano")
        corso = TrainingCourse.objects.create(piano=piano, codice="CAGS", titolo="Corso", durata_ore_teorica=1)
        TrainingSession.objects.create(corso=corso, codice_sessione="SAG-ON", data_inizio=self.oggi,
                                       data_fine=self.oggi, modalita="ONLINE")
        resp = self.client.get(reverse("anagrafica:formazione_corso_detail", args=[corso.pk]))
        self.assertContains(resp, '["ONLINE","Slide + test"]')
        self.assertContains(resp, 'data-value="ONLINE"')
        self.assertNotIn("moduli", resp.context)


class SubnavMod176Tests(TestCase):
    def setUp(self):
        SubnavLinkAnagrafica.objects.all().delete()
        SubnavCategoriaAnagrafica.objects.all().delete()
        cat = SubnavCategoriaAnagrafica.objects.create(nome="Competenze", ordine=1, is_active=True)
        SubnavLinkAnagrafica.objects.create(etichetta="Processi qualificati", url_type="named",
                                            url_value="anagrafica:mpq_cruscotto", categoria=cat, ordine=1,
                                            is_active=True)
        SubnavLinkAnagrafica.objects.create(etichetta="MOD.176 in officina", url_type="named",
                                            url_value="anagrafica:mpq_officina", categoria=cat, ordine=2,
                                            is_active=True)
        self.request = RequestFactory().get("/anagrafica/")
        self.request.user = User.objects.create_user(username="ag4_nav", password="x")

    def _etichette(self):
        from .templatetags.anagrafica_extras import subnav_anagrafica

        with mock.patch("core.middleware.acl_allows_path", return_value=True), \
                mock.patch("anagrafica.subnav_gates.section_gate_allows", return_value=True):
            nav = subnav_anagrafica({"request": self.request})
        return [c["label"] for item in nav["items"] for c in item.get("links", [])]

    def test_mod176_solo_con_technical_plan_approvato(self):
        self.assertNotIn("MOD.176 in officina", self._etichette())
        from .models_mpq import ClienteQualificante, ProcessoQualificato, TechnicalPlan
        from .services import mpq_utensili

        proc = ProcessoQualificato.objects.create(nome="Proc AG4", cliente=ClienteQualificante.objects.create(nome="Cli AG4"))
        tp = TechnicalPlan.objects.create(processo=proc, part_number="PN-AG4", tipologia_foro="Foro sintetico")
        rev = mpq_utensili.nuova_revisione(tp, modifiche="Prima emissione")
        mpq_utensili.approva(rev, approvato_da="Approvatore sintetico")
        self.assertIn("MOD.176 in officina", self._etichette())


class QualificheTests(_Base):
    def setUp(self):
        super().setUp()
        self.tipo = TipoQualifica.objects.create(nome="Patentino sintetico", categoria=TipoQualifica.CAT_SICUREZZA)
        self.p = AnagraficaDipendente.objects.create(nome="ADA", cognome="CORRENTE", aliasusername="ag4.ada")
        # Vecchia registrazione scaduta superata da un rinnovo valido.
        DipendenteQualifica.objects.create(legacy_anagrafica_id=self.p.pk, tipo=self.tipo,
                                           data_conseguimento=self.oggi - timedelta(days=2000),
                                           data_scadenza=self.oggi - timedelta(days=10))
        DipendenteQualifica.objects.create(legacy_anagrafica_id=self.p.pk, tipo=self.tipo,
                                           data_conseguimento=self.oggi - timedelta(days=5),
                                           data_scadenza=self.oggi + timedelta(days=60))

    def test_catalogo_senza_tabella_scadenze_con_link_scadenzario(self):
        resp = self.client.get(reverse("anagrafica:qualifiche_list"))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "Scadenze in arrivo o già scadute")
        self.assertContains(resp, "Scadenzario qualifiche")

    def test_cruscotto_richiede_login(self):
        self.client.logout()
        resp = self.client.get(reverse("anagrafica:qualifiche_dashboard"))
        self.assertIn(resp.status_code, (302, 401, 403))

    def test_scheda_dipendente_solo_corrente_con_storico(self):
        resp = self.client.get(reverse("anagrafica:dipendente_detail", args=[self.p.pk]))
        self.assertEqual(resp.status_code, 200)
        qual = [q for q in resp.context["qualifiche_dip"] if q.tipo_id == self.tipo.pk]
        self.assertEqual(len(qual), 1)
        self.assertEqual(len(qual[0].precedenti), 1)
        self.assertContains(resp, "Registrazioni precedenti (1)")

    def test_libretto_qualifiche_correnti_e_processi(self):
        resp = self.client.get(reverse("anagrafica:dipendente_libretto_formativo", args=[self.p.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context["qualifiche_libretto"]), 1)
        self.assertEqual(resp.context["qualifiche_libretto"][0].stato_libretto, ("warn", "In scadenza ≤90gg"))
        self.assertContains(resp, "Processi qualificati MOD.128")

    def test_richiesta_a_ma_mancante(self):
        ruolo = RuoloOperativo.objects.create(nome="Ruolo sintetico AG4")
        RuoloQualifica.objects.create(ruolo=ruolo, qualifica=self.tipo, obbligatoria=True)
        manca = AnagraficaDipendente.objects.create(nome="BRUNO", cognome="MANCANTE", aliasusername="ag4.bruno")
        scaduta = AnagraficaDipendente.objects.create(nome="CARLA", cognome="SCADUTA", aliasusername="ag4.carla")
        cessato = AnagraficaDipendente.objects.create(nome="DINO", cognome="CESSATO", aliasusername="ag4.dino")
        DipendenteQualifica.objects.create(legacy_anagrafica_id=scaduta.pk, tipo=self.tipo,
                                           data_conseguimento=self.oggi - timedelta(days=900),
                                           data_scadenza=self.oggi - timedelta(days=1))
        for persona in (self.p, manca, scaduta, cessato):
            DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=persona.pk, ruolo=ruolo)
            DipendenteAnagraficaAziendale.objects.create(
                legacy_anagrafica_id=persona.pk,
                data_cessazione=date(2020, 1, 31) if persona is cessato else None)
        resp = self.client.get(reverse("anagrafica:tipo_qualifica_detail", args=[self.tipo.pk]))
        self.assertEqual(resp.status_code, 200)
        stati = {m["legacy_id"]: m["stato"] for m in resp.context["mancanti"]}
        self.assertEqual(stati, {manca.pk: "mancante", scaduta.pk: "scaduta"})
        self.assertContains(resp, "Richiesta a, ma mancante")
        self.assertContains(resp, "Ruolo «Ruolo sintetico AG4»")
