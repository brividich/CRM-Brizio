"""Coerenza formazione (26/11/2026): coda MOD.040, edizioni online, stato automatico,
integrità dati, efficacia con una regola sola, sessioni miste."""
from __future__ import annotations

from datetime import time, timedelta
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from .models_formazione import (
    TrainingCourse, TrainingCourseType, TrainingEfficacia, TrainingEmployeeRecord, TrainingEnrollment,
    TrainingLesson, TrainingPlan, TrainingSession,
)
from .services import formazione_aula as aula
from .services import formazione_integrita as fi
from .services import sessione_online as so
from .services.formazione_efficacia import valutazioni_da_fare

A, B = 6101, 6102
NOMI = {A: "VERDI ANNA", B: "NERI LUCA"}


class _Base(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("hr.coerenza", "hr@example.com", "pwd12345")
        self.client.force_login(self.admin)
        self.oggi = timezone.localdate()
        tipo = TrainingCourseType.objects.create(nome="Tipo coerenza", efficacia_mesi=3)
        piano = TrainingPlan.objects.create(codice="PC", nome="Piano coerenza")
        self.corso = TrainingCourse.objects.create(piano=piano, codice="CO-1", titolo="Corso coerenza",
                                                   durata_ore_teorica=Decimal("2"), stato="ATTIVO", tipo=tipo)
        p = mock.patch("anagrafica.views._helpers._build_nomi_map", return_value=NOMI)
        p.start()
        self.addCleanup(p.stop)

    def _sessione(self, codice, modalita="IN_SEDE", inizio=0, fine=0, stato="PIANIFICATA", **kw):
        return TrainingSession.objects.create(
            corso=self.corso, codice_sessione=codice, modalita=modalita, stato=stato,
            data_inizio=self.oggi + timedelta(days=inizio), data_fine=self.oggi + timedelta(days=fine),
            docente_nome="Docente prova", **kw)

    def _online(self, codice, scadenza_tra: int, fine=-10, pubblicata=True):
        s = self._sessione(codice, "ONLINE", inizio=-20, fine=fine, stato="IN_CORSO")
        cfg = so.config(s, crea=True)
        cfg.scadenza = self.oggi + timedelta(days=scadenza_tra)
        cfg.pubblicata_il = timezone.now() if pubblicata else None
        cfg.save()
        return s


class CodaMod040Tests(_Base):
    def test_completata_senza_chiusa_il_e_in_coda(self):
        s = self._sessione("S-MOD-1", inizio=-10, fine=-9, stato="COMPLETATA")
        self.assertIsNone(s.chiusa_il)
        self.assertIn(s, list(aula.edizioni_da_approvare()))
        r = self.client.get(reverse("anagrafica:formazione_sessioni_list") + "?da_approvare=1")
        self.assertContains(r, "S-MOD-1")
        self.assertContains(r, "Da approvare")

    def test_chiudi_su_completata_scrive_chiusa_il(self):
        s = self._sessione("S-MOD-2", inizio=-10, fine=-9, stato="COMPLETATA")
        out = aula.chiudi(s, self.admin, {})
        s.refresh_from_db()
        self.assertTrue(out.chiusa)
        self.assertIsNotNone(s.chiusa_il)

    def test_le_mie_attivita_mod040(self):
        from dashboard.views_mie_attivita import _my_mod040
        self._sessione("S-MOD-3", inizio=-10, fine=-9, stato="COMPLETATA")
        req = RequestFactory().get("/")
        req.user = self.admin
        with mock.patch("anagrafica.views.formazione._can_approve_formazione", return_value=True):
            voci = _my_mod040(req)
        self.assertEqual(voci[0]["code"], "S-MOD-3")
        self.assertIn("finita il", voci[0]["status"])

    def test_efficacia_scaduta_non_dice_entro(self):
        from dashboard.views_mie_attivita import _my_efficacia
        rec = TrainingEmployeeRecord.objects.create(legacy_anagrafica_id=A, corso=self.corso,
                                                    data_completamento=self.oggi - timedelta(days=100))
        TrainingEfficacia.objects.all().delete()
        TrainingEfficacia.objects.create(record=rec, legacy_anagrafica_id=A, attesa_dal=self.oggi - timedelta(days=5))
        req = RequestFactory().get("/")
        req.user = self.admin
        with mock.patch("dashboard.views_mie_attivita._anagrafica_id", return_value=9999), \
                mock.patch("anagrafica.services.capo_team.mappa_capi",
                           return_value={A: mock.Mock(legacy_id=9999)}):
            voci = _my_efficacia(req)
        self.assertTrue(voci[0]["status"].startswith("scaduta dal"))


class StatoEDaChiudereTests(_Base):
    def test_pianificata_diventa_in_corso(self):
        s = self._sessione("S-ST-1", inizio=0, fine=2)
        futura = self._sessione("S-ST-2", inizio=3, fine=4)
        self.assertEqual(aula.aggiorna_stati(), 1)
        s.refresh_from_db()
        futura.refresh_from_db()
        self.assertEqual((s.stato, futura.stato), ("IN_CORSO", "PIANIFICATA"))

    def test_online_da_chiudere_dopo_la_scadenza(self):
        scaduta = self._online("S-ON-1", scadenza_tra=-1)
        aperta = self._online("S-ON-2", scadenza_tra=5)   # data di fine passata ma lezione ancora aperta
        elenco = list(aula.da_chiudere())
        self.assertIn(scaduta, elenco)
        self.assertNotIn(aperta, elenco)
        self.assertEqual((aula.fase(scaduta), aula.fase(aperta)), ("dopo", "durante"))

    def test_integrita_e_da_chiudere_stessa_definizione(self):
        self._sessione("S-DC-1", inizio=-5, fine=-4)
        self._sessione("S-DC-2", inizio=-5, fine=-3, stato="IN_CORSO")
        self._online("S-DC-3", scadenza_tra=-2)
        controlli = {c.codice: c for c in fi.controlli_integrita()}
        self.assertEqual(controlli["pianificate_passate"].n, aula.da_chiudere().count())
        self.assertEqual(controlli["pianificate_passate"].n, 3)
        self.assertEqual(controlli["online_scadute_aperte"].n, 1)

    def test_paginazione_da_chiudere(self):
        r = self.client.get(reverse("anagrafica:formazione_sessioni_list") + "?da_chiudere=1")
        self.assertEqual(r.status_code, 200)
        self._sessione("S-DC-P", inizio=-5, fine=-4)
        r = self.client.get(reverse("anagrafica:formazione_sessioni_list") + "?da_chiudere=1")
        self.assertContains(r, "Pagina 1 di 1")

    def test_elenco_colonne_e_modalita(self):
        s = self._online("S-ON-L", scadenza_tra=5)
        TrainingEnrollment.objects.create(sessione=s, legacy_anagrafica_id=A)
        r = self.client.get(reverse("anagrafica:formazione_sessioni_list"))
        self.assertContains(r, "Esiti aperti")
        self.assertContains(r, "Online: slide + test")
        r = self.client.get(reverse("anagrafica:formazione_sessioni_list") + "?modalita=ESTERNO")
        self.assertNotContains(r, "S-ON-L")


class OnlineDettaglioTests(_Base):
    def test_online_durante_senza_ore_e_senza_chiusura(self):
        s = self._online("S-ON-D", scadenza_tra=5)
        r = self.client.get(reverse("anagrafica:formazione_sessione_detail", args=[s.pk]))
        self.assertNotContains(r, "⚡ Genera giornate")
        self.assertNotContains(r, "Ore formative")
        self.assertNotContains(r, "Programma dell'edizione")
        self.assertContains(r, "Lezione online in corso")
        self.assertNotContains(r, 'id="chiusura-edizione"')

    def test_online_dopo_chiudi_edizione(self):
        s = self._online("S-ON-C", scadenza_tra=-1)
        ea = TrainingEnrollment.objects.create(sessione=s, legacy_anagrafica_id=A)
        eb = TrainingEnrollment.objects.create(sessione=s, legacy_anagrafica_id=B, stato="IN_CORSO",
                                               verifica_superata=True, percentuale_presenza=Decimal("100"))
        prog = so.avanzamento(eb)
        prog.superata_il = timezone.now() - timedelta(days=3)
        prog.save()
        r = self.client.get(reverse("anagrafica:formazione_sessione_detail", args=[s.pk]))
        self.assertContains(r, "La lezione online è scaduta")
        self.assertContains(r, 'id="chiusura-edizione"')
        out = aula.chiudi_con_proposta(s, self.admin)
        self.assertTrue(out.chiusa)
        ea.refresh_from_db()
        eb.refresh_from_db()
        s.refresh_from_db()
        self.assertEqual((ea.stato, eb.stato, s.stato), ("ASSENTE", "COMPLETATO", "COMPLETATA"))
        self.assertIsNotNone(s.chiusa_il)
        self.assertTrue(TrainingEmployeeRecord.objects.filter(enrollment=eb).exists())


class IntegritaTests(_Base):
    def test_esterno_escluso_e_nuovi_controlli(self):
        self._sessione("S-EXT", "ESTERNO", inizio=-10, fine=-9, stato="COMPLETATA")
        aula_s = self._sessione("S-AULA", inizio=-10, fine=-9, stato="COMPLETATA")
        TrainingEnrollment.objects.create(sessione=aula_s, legacy_anagrafica_id=A, stato="ISCRITTO")
        TrainingEnrollment.objects.create(sessione=aula_s, legacy_anagrafica_id=B, stato="IN_CORSO",
                                          verifica_superata=True)
        c = {x.codice: x for x in fi.controlli_integrita()}
        self.assertEqual(c["completate_senza_presenze"].n, 1)
        self.assertEqual(c["completate_senza_presenze"].sessioni, [(aula_s.pk, "S-AULA")])
        self.assertEqual(c["completate_iscrizioni_aperte"].n, 1)
        self.assertEqual(c["test_superato_non_a_libretto"].n, 1)
        self.assertEqual(c["test_superato_non_a_libretto"].sessioni, [(aula_s.pk, "S-AULA")])
        r = self.client.get(reverse("anagrafica:formazione_integrita"))
        self.assertContains(r, reverse("anagrafica:formazione_sessione_detail", args=[aula_s.pk]))


class EfficaciaTests(_Base):
    def _valutazione(self, giorni):
        rec = TrainingEmployeeRecord.objects.create(legacy_anagrafica_id=A, corso=self.corso,
                                                    data_completamento=self.oggi - timedelta(days=100))
        TrainingEfficacia.objects.filter(record=rec).delete()
        return TrainingEfficacia.objects.create(record=rec, legacy_anagrafica_id=A,
                                                attesa_dal=self.oggi + timedelta(days=giorni))

    def test_una_regola_per_dovute(self):
        dovuta, vicina, lontana = self._valutazione(-3), self._valutazione(10), self._valutazione(40)
        tutte = aula.efficacie_da_valutare(tutte=True)
        self.assertEqual(tutte, list(valutazioni_da_fare(anticipo_giorni=aula.ANTICIPO_GIORNI_EFFICACIA)))
        self.assertIn(dovuta, tutte)
        self.assertIn(vicina, tutte)
        self.assertNotIn(lontana, tutte)

    def test_sola_lettura_senza_modulo(self):
        self._valutazione(-3)
        with mock.patch("anagrafica.views._helpers._can_edit_formazione", return_value=False), \
                mock.patch("anagrafica.views._helpers._can_view_formazione", return_value=True):
            r = self.client.get(reverse("anagrafica:formazione_efficacia"))
        self.assertContains(r, "VERDI ANNA")
        self.assertContains(r, reverse("anagrafica:dipendente_detail", args=[A]))
        self.assertNotContains(r, 'name="esito"')
        r = self.client.get(reverse("anagrafica:formazione_efficacia"))
        self.assertContains(r, 'name="esito"')


class SessioniMisteTests(_Base):
    def test_test_online_in_sessione_con_giornate_vale_solo_verifica(self):
        s = self._sessione("S-MIX", "MISTO", inizio=-1, fine=1, stato="IN_CORSO")
        TrainingLesson.objects.create(sessione=s, numero=1, data=self.oggi, ora_inizio=time(9), ora_fine=time(11),
                                      argomento="Aula")
        e = TrainingEnrollment.objects.create(sessione=s, legacy_anagrafica_id=A, ore_frequentate=Decimal("1"))
        so.salva_domanda(s, testo="2+2?", risposte=["4", "5"], giuste={0})
        cfg = so.config(s, crea=True)
        cfg.pubblicata_il = timezone.now()
        cfg.secondi_minimi_slide = 0
        cfg.save()
        self.assertTrue(so.solo_verifica(s, cfg))
        self.assertNotIn(e, list(so.iscrizioni_da_allineare(self.corso.pk, A)))
        d = so.domande_valide(s)[0]
        so.correggi(e, cfg, {d.pk: {d.opzioni.get(corretta=True).pk}})
        e.refresh_from_db()
        self.assertTrue(e.verifica_superata)
        self.assertEqual(e.ore_frequentate, Decimal("1"))
        self.assertIsNone(e.percentuale_presenza)
        self.assertNotEqual(e.stato, "COMPLETATO")
        self.assertFalse(TrainingEmployeeRecord.objects.filter(enrollment=e).exists())
