from __future__ import annotations

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase

from anagrafica.models import Reparto
from suggestion_corner.models import SuggestionCorner

User = get_user_model()


class SuggestionCornerCleanTest(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="TORNI")
        self.u1 = User.objects.create(username="mario")
        self.u2 = User.objects.create(username="luigi")

    def _base(self, **kw):
        defaults = dict(reparto_provenienza=self.reparto, opportunity="Test.")
        defaults.update(kw)
        return SuggestionCorner(**defaults)

    def test_clean_ok_incaricato_diverso_da_controllore(self):
        s = self._base(incaricato=self.u1, controllore=self.u2)
        s.clean()  # non solleva

    def test_clean_ok_se_uno_dei_due_none(self):
        s = self._base(incaricato=self.u1, controllore=None)
        s.clean()  # non solleva

    def test_clean_solleva_se_incaricato_uguale_controllore(self):
        s = self._base(incaricato=self.u1, controllore=self.u1)
        with self.assertRaises(ValidationError):
            s.clean()

    def test_prep_evento_setta_transient(self):
        s = self._base()
        s._prep_evento(self.u1, foo="bar")
        self.assertEqual(s._evento_attore, self.u1)
        self.assertEqual(s._evento_payload, {"foo": "bar"})


import datetime


class SuggestionCornerClassificazioneTest(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="CNC")
        self.u1 = User.objects.create(username="incaricato1")
        self.u2 = User.objects.create(username="controllore1")

    def _seg(self, **kw):
        defaults = dict(reparto_provenienza=self.reparto, opportunity="Test flusso.")
        defaults.update(kw)
        return SuggestionCorner.objects.create(**defaults)

    def test_notifica_sms_team_avanza_e_crea_storico(self):
        s = self._seg()
        self.assertEqual(s.stato, "INSERITA")
        s.notifica_sms_team()
        s.save()
        self.assertEqual(s.stato, "DA_CLASSIFICARE")
        voce = s.storico.get()
        self.assertEqual(voce.stato_precedente, "INSERITA")
        self.assertEqual(voce.stato_nuovo, "DA_CLASSIFICARE")

    def test_classifica_setta_stato_sms_e_autore(self):
        s = self._seg()
        s.notifica_sms_team()
        s.classifica(SuggestionCorner.StatoSMS.SMS_SI, attore=self.u1)
        s.save()
        self.assertEqual(s.stato, "CLASSIFICATA")
        self.assertEqual(s.stato_sms, "SMS_SI")
        voce = s.storico.filter(stato_nuovo="CLASSIFICATA").get()
        self.assertEqual(voce.autore, self.u1)

    def test_classifica_rifiuta_stato_sms_invalido(self):
        s = self._seg()
        s.notifica_sms_team()
        with self.assertRaises(ValidationError):
            s.classifica("DA_GESTIRE")

    def test_definisci_plan_enforce_incaricato_diverso(self):
        s = self._seg()
        s.notifica_sms_team()
        s.classifica(SuggestionCorner.StatoSMS.SMS_SI)
        ieri = datetime.date.today()
        with self.assertRaises(ValidationError):
            s.definisci_plan(
                incaricato=self.u1, controllore=self.u1,
                data_limite_esecuzione=ieri, data_limite_controllo=ieri,
            )

    def test_definisci_plan_ok(self):
        s = self._seg()
        s.notifica_sms_team()
        s.classifica(SuggestionCorner.StatoSMS.SMS_SI)
        d1 = datetime.date.today() + datetime.timedelta(days=10)
        d2 = datetime.date.today() + datetime.timedelta(days=20)
        s.definisci_plan(
            incaricato=self.u1, controllore=self.u2,
            data_limite_esecuzione=d1, data_limite_controllo=d2,
            plan_testo="Piano di miglioramento.",
        )
        s.save()
        self.assertEqual(s.stato, "PLAN_DEFINITO")
        self.assertTrue(s.plan_eseguito)
        self.assertEqual(s.incaricato, self.u1)
        self.assertEqual(s.controllore, self.u2)
        self.assertEqual(s.data_limite_esecuzione, d1)

    def test_uno_storico_per_transizione(self):
        s = self._seg()
        s.notifica_sms_team()
        s.classifica(SuggestionCorner.StatoSMS.SMS_NO)
        s.save()
        self.assertEqual(s.storico.count(), 2)


class SuggestionCornerDoTest(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="PRESS")
        self.u1 = User.objects.create(username="doer")
        self.u2 = User.objects.create(username="checker")

    def _fino_a_do_in_corso(self):
        s = SuggestionCorner.objects.create(
            reparto_provenienza=self.reparto, opportunity="Flusso DO.",
        )
        s.notifica_sms_team()
        s.classifica(SuggestionCorner.StatoSMS.SMS_SI)
        d = datetime.date.today() + datetime.timedelta(days=10)
        s.definisci_plan(incaricato=self.u1, controllore=self.u2,
                         data_limite_esecuzione=d, data_limite_controllo=d)
        s.avvia_do()
        s.save()
        return s

    def test_avvia_do(self):
        s = self._fino_a_do_in_corso()
        self.assertEqual(s.stato, "DO_IN_CORSO")

    def test_completa_do_si_poi_avvia_check(self):
        s = self._fino_a_do_in_corso()
        s.completa_do(SuggestionCorner.EsitoAttivita.SI, do_testo="Fatto.")
        s.save()
        self.assertEqual(s.stato, "DO_COMPLETATO")
        self.assertTrue(s.do_eseguito)
        self.assertEqual(s.esito_do, "SI")
        self.assertIsNotNone(s.data_esecuzione_do)
        s.avvia_check()
        s.save()
        self.assertEqual(s.stato, "CHECK_IN_CORSO")

    def test_avvia_check_bloccato_se_esito_no(self):
        from django_fsm import TransitionNotAllowed
        s = self._fino_a_do_in_corso()
        s.completa_do(SuggestionCorner.EsitoAttivita.NO)
        s.save()
        with self.assertRaises(TransitionNotAllowed):
            s.avvia_check()

    def test_do_da_rifare_riporta_in_do_in_corso(self):
        s = self._fino_a_do_in_corso()
        s.completa_do(SuggestionCorner.EsitoAttivita.NO)
        s.save()
        nuova = datetime.date.today() + datetime.timedelta(days=30)
        s.do_da_rifare(nuova_data_limite_esecuzione=nuova)
        s.save()
        self.assertEqual(s.stato, "DO_IN_CORSO")
        self.assertFalse(s.do_eseguito)
        self.assertEqual(s.esito_do, "")
        self.assertEqual(s.data_limite_esecuzione, nuova)
