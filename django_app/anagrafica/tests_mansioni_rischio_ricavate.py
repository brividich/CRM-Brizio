"""Mansionario fase 5: mansioni di rischio ricavate dalle mansioni svolte. Dati sintetici.

La mansione di rischio di una persona è quella scritta in anagrafica più quelle
delle mansioni su cui è in lista (Mansionario), più le aggiunte e meno le
esclusioni individuali. DPI, visite, formazione e schede di sicurezza la leggono.
"""
from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from core.legacy_models import AnagraficaDipendente

from .models import (
    CompetenzaSkm, DipendenteMansioneRischioOverride as O, EsposizioneRischio, FattoreRischio, Mansione,
    Reparto, TipoVisitaMedica, TrainingCourse, TrainingPlan, TrainingRequirementRule,
)
from .services import mansionario
from .services import mansionario_struttura as svc
from .tests import _ensure_anagrafica_table

User = get_user_model()
OGGI = timezone.localdate()


class _Base(TestCase):
    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()

    def setUp(self):
        self.audiometria = TipoVisitaMedica.objects.create(nome="Audiometria (f5)", durata_mesi=24)
        self.spirometria = TipoVisitaMedica.objects.create(nome="Spirometria (f5)", durata_mesi=12)
        self.mu = Mansione.objects.create(nome="ADDETTO MACCHINE UTENSILI F5")
        self.mu.visite_richieste.add(self.audiometria)
        self.vern = Mansione.objects.create(nome="ADDETTO VERNICIATURA F5")
        self.vern.visite_richieste.add(self.spirometria)
        reparto = Reparto.objects.create(nome="VERNICIATURA F5")
        self.cabina = CompetenzaSkm.objects.create(competenza_key="F5-CAB", display="Cabina F5",
                                                   tipo=CompetenzaSkm.TIPO_PROCESSO, reparto=reparto)
        self.cabina.mansioni_rischio.add(self.vern)
        self.dip = AnagraficaDipendente.objects.create(nome="UNO", cognome="FASECINQUE",
                                                       aliasusername="fasecinque.uno",
                                                       mansione="ADDETTO MACCHINE UTENSILI F5")
        self.lid = self.dip.pk


class RicavateDalleMansioniTests(_Base):
    def test_senza_mansioni_svolte_resta_quella_in_anagrafica(self):
        det = mansionario.requisiti_dipendente_dettaglio(self.lid)
        self.assertEqual([v.pk for v in det["requisiti"]["visite"]], [self.audiometria.pk])
        self.assertEqual([(e["mansione_rischio"].pk, e["origine"]) for e in det["mansioni_rischio"]],
                         [(self.mu.pk, "ANAGRAFICA")])

    def test_mansione_svolta_aggiunge_la_sua_mansione_di_rischio(self):
        svc.assegna(self.cabina, legacy_anagrafica_id=self.lid, livello="I")
        det = mansionario.requisiti_dipendente_dettaglio(self.lid)
        self.assertEqual({v.pk for v in det["requisiti"]["visite"]}, {self.audiometria.pk, self.spirometria.pk})
        self.assertEqual(det["origini"][("visite", self.spirometria.pk)],
                         ["Mansione di rischio «ADDETTO VERNICIATURA F5» (da mansione Cabina F5)"])
        voce = next(e for e in det["mansioni_rischio"] if e["mansione_rischio"].pk == self.vern.pk)
        self.assertEqual((voce["origine"], voce["da"]), ("MANSIONARIO", ["Cabina F5"]))

    def test_nulla_toglie_la_mansione_in_anagrafica(self):
        # La persona svolge solo la cabina: la mansione del medico resta.
        svc.assegna(self.cabina, legacy_anagrafica_id=self.lid, livello="U")
        nomi = mansionario.nomi_mansioni_rischio([self.lid])[self.lid]
        self.assertEqual(nomi, ["ADDETTO MACCHINE UTENSILI F5", "ADDETTO VERNICIATURA F5"])

    def test_stessa_mansione_di_rischio_da_due_fonti_una_voce(self):
        self.cabina.mansioni_rischio.add(self.mu)
        svc.assegna(self.cabina, legacy_anagrafica_id=self.lid, livello="U")
        det = mansionario.requisiti_dipendente_dettaglio(self.lid)
        mu = [e for e in det["mansioni_rischio"] if e["mansione_rischio"].pk == self.mu.pk]
        self.assertEqual(len(mu), 1)
        self.assertEqual((mu[0]["origine"], mu[0]["da"]), ("ANAGRAFICA", ["Cabina F5"]))

    def test_tolto_dalla_mansione_non_conta_piu(self):
        ab = svc.assegna(self.cabina, legacy_anagrafica_id=self.lid, livello="U")
        svc.togli(ab)
        self.assertNotIn("ADDETTO VERNICIATURA F5", mansionario.nomi_mansioni_rischio([self.lid])[self.lid])

    def test_mansione_disattivata_non_conta(self):
        svc.assegna(self.cabina, legacy_anagrafica_id=self.lid, livello="U")
        self.cabina.attiva = False
        self.cabina.save(update_fields=["attiva"])
        self.assertEqual(mansionario.mansioni_rischio_ricavate([self.lid]), {})

    def test_esclusione_individuale_vale_anche_sulle_ricavate(self):
        svc.assegna(self.cabina, legacy_anagrafica_id=self.lid, livello="U")
        O.objects.create(legacy_anagrafica_id=self.lid, mansione_rischio=self.vern, azione=O.AZIONE_ESCLUDI,
                         motivo="Indicazione del medico (sintetica)", data_inizio=OGGI - timedelta(days=1))
        det = mansionario.requisiti_dipendente_dettaglio(self.lid)
        self.assertNotIn(self.spirometria.pk, {v.pk for v in det["requisiti"]["visite"]})
        self.assertEqual([e["mansione_rischio"].pk for e in det["mansioni_rischio_escluse"]], [self.vern.pk])
        self.assertNotIn("ADDETTO VERNICIATURA F5", mansionario.nomi_mansioni_rischio([self.lid])[self.lid])

    def test_aggiunta_individuale_sul_catalogo(self):
        O.objects.create(legacy_anagrafica_id=self.lid, mansione_rischio=self.vern, azione=O.AZIONE_AGGIUNGI,
                         motivo="Sostituzione in cabina (sintetica)", data_inizio=OGGI)
        det = mansionario.requisiti_dipendente_dettaglio(self.lid)
        self.assertIn(self.spirometria.pk, {v.pk for v in det["requisiti"]["visite"]})
        self.assertIn("aggiunta individuale", det["origini"][("visite", self.spirometria.pk)][0])

    def test_fattori_della_mansione_di_rischio_ricavata(self):
        fumi = FattoreRischio.objects.create(codice="F5-FUMI", nome="Fumi (f5)")
        oculistica = TipoVisitaMedica.objects.create(nome="Oculistica (f5)", durata_mesi=24)
        fumi.tipi_visita.add(oculistica)
        EsposizioneRischio.objects.create(fattore=fumi, mansione=self.vern)
        svc.assegna(self.cabina, legacy_anagrafica_id=self.lid, livello="L")
        self.assertIn(oculistica, mansionario.requisiti_dipendente(self.lid)["visite"])


class ModuliLeggonoLaMansioneRicavataTests(_Base):
    def test_formazione_obbligatoria_da_mansione_svolta(self):
        from .services.training_eligibility import _legacy_ids_pertinenti

        piano = TrainingPlan.objects.create(codice="P-F5", nome="Piano f5")
        corso = TrainingCourse.objects.create(piano=piano, codice="C-F5", titolo="Verniciatura sicura (f5)",
                                              durata_ore_teorica=4)
        TrainingRequirementRule.objects.create(corso=corso, mansione=self.vern)
        dipendenti = {self.lid: {"nome": "FASECINQUE UNO", "mansione": self.dip.mansione, "reparto": ""}}
        ids, _ = _legacy_ids_pertinenti(corso, dipendenti)
        self.assertEqual(ids, set())
        svc.assegna(self.cabina, legacy_anagrafica_id=self.lid, livello="I")
        ids, has_rules = _legacy_ids_pertinenti(corso, dipendenti)
        self.assertEqual((ids, has_rules), ({self.lid}, True))

    def test_schede_di_sicurezza_per_chi_svolge_la_mansione(self):
        from schede_sicurezza.models import ProdottoChimico, SchedaSicurezza
        from schede_sicurezza.reports import matrice_presa_visione
        from schede_sicurezza.services.assegnazioni import profilo_sds_utente
        from schede_sicurezza.tests_reports import _pdf, crea_dipendente_con_account

        prodotto = ProdottoChimico.objects.create(nome="Vernice sintetica F5")
        prodotto.mansioni.add(self.vern)
        scheda = SchedaSicurezza.objects.create(prodotto=prodotto, pdf=_pdf(), versione="1", is_corrente=True)
        user = crea_dipendente_con_account("f5", mansione="ADDETTO MACCHINE UTENSILI F5")
        lid = AnagraficaDipendente.objects.get(aliasusername="dipf5").pk

        self.assertEqual(profilo_sds_utente(user).schede, [])
        svc.assegna(self.cabina, legacy_anagrafica_id=lid, livello="U")
        profilo = profilo_sds_utente(user)
        self.assertEqual(profilo.schede, [scheda])
        self.assertIn("ADDETTO VERNICIATURA F5", profilo.mansione_nome)
        riga = next(m for m in matrice_presa_visione() if m.mansione_id == self.vern.pk).righe[0]
        self.assertEqual(riga.totale_dipendenti, 1)


class PannelloSicurezzaTests(_Base):
    def test_pannello_con_override_senza_autore_e_mansioni_ricavate(self):
        from django.test import override_settings
        from django.urls import reverse

        admin = User.objects.create_superuser("f5_admin", "f5@example.invalid", "x")
        svc.assegna(self.cabina, legacy_anagrafica_id=self.lid, livello="U")
        O.objects.create(legacy_anagrafica_id=self.lid, mansione_rischio=self.vern, azione=O.AZIONE_AGGIUNGI,
                         motivo="Senza autore (sintetico)", data_inizio=OGGI)  # autore cancellato: created_by vuoto
        self.client.force_login(admin)
        with override_settings(LEGACY_AUTH_ENABLED=False):
            r = self.client.get(reverse("anagrafica:dipendente_sicurezza_panel", args=[self.lid]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "da mansione Cabina F5")
        self.assertContains(r, "in anagrafica")
