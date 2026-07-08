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


class SuggestionCornerCheckTest(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="COLL")
        self.u1 = User.objects.create(username="do2")
        self.u2 = User.objects.create(username="ck2")

    def _fino_a_check_in_corso(self):
        s = SuggestionCorner.objects.create(
            reparto_provenienza=self.reparto, opportunity="Flusso CHECK.",
        )
        s.notifica_sms_team()
        s.classifica(SuggestionCorner.StatoSMS.SMS_SI)
        d = datetime.date.today() + datetime.timedelta(days=10)
        s.definisci_plan(incaricato=self.u1, controllore=self.u2,
                         data_limite_esecuzione=d, data_limite_controllo=d)
        s.avvia_do()
        s.completa_do(SuggestionCorner.EsitoAttivita.SI)
        s.avvia_check()
        s.save()
        return s

    def test_check_positivo(self):
        s = self._fino_a_check_in_corso()
        s.check_positivo(check_testo="Verificato ok.")
        s.save()
        self.assertEqual(s.stato, "CHECK_COMPLETATO")
        self.assertEqual(s.esito_check, "POSITIVO")
        self.assertTrue(s.check_eseguito)
        self.assertIsNotNone(s.data_esecuzione_check)

    def test_check_negativo_riapre_do(self):
        s = self._fino_a_check_in_corso()
        s.check_negativo()
        s.save()
        self.assertEqual(s.stato, "DO_IN_CORSO")
        self.assertEqual(s.esito_check, "NEGATIVO")
        self.assertFalse(s.do_eseguito)
        self.assertEqual(s.esito_do, "")

    def test_check_rinviato_self_loop_nuova_data(self):
        s = self._fino_a_check_in_corso()
        nuova = datetime.date.today() + datetime.timedelta(days=45)
        s.check_rinviato(nuova_data_limite_controllo=nuova)
        s.save()
        self.assertEqual(s.stato, "CHECK_IN_CORSO")
        self.assertEqual(s.esito_check, "RINVIATO")
        self.assertEqual(s.data_limite_controllo, nuova)


class SuggestionCornerActChiusuraTest(TestCase):
    def setUp(self):
        self.reparto = Reparto.objects.create(nome="FIN")
        self.u1 = User.objects.create(username="do3")
        self.u2 = User.objects.create(username="ck3")

    def _fino_a_check_completato(self, vuoi_act=False):
        s = SuggestionCorner.objects.create(
            reparto_provenienza=self.reparto, opportunity="Flusso ACT.",
            vuoi_inserire_act=vuoi_act,
        )
        s.notifica_sms_team()
        s.classifica(SuggestionCorner.StatoSMS.SMS_SI)
        d = datetime.date.today() + datetime.timedelta(days=10)
        s.definisci_plan(incaricato=self.u1, controllore=self.u2,
                         data_limite_esecuzione=d, data_limite_controllo=d)
        s.avvia_do()
        s.completa_do(SuggestionCorner.EsitoAttivita.SI)
        s.avvia_check()
        s.check_positivo()
        s.save()
        return s

    def test_chiudi_diretto_senza_act(self):
        s = self._fino_a_check_completato(vuoi_act=False)
        s.chiudi()
        s.save()
        self.assertEqual(s.stato, "CHIUSA")

    def test_inserisci_act_poi_chiudi(self):
        s = self._fino_a_check_completato(vuoi_act=True)
        s.inserisci_act()
        s.save()
        self.assertEqual(s.stato, "ACT_INSERITO")
        s.chiudi()
        s.save()
        self.assertEqual(s.stato, "CHIUSA")

    def test_inserisci_act_bloccato_se_non_richiesto(self):
        from django_fsm import TransitionNotAllowed
        s = self._fino_a_check_completato(vuoi_act=False)
        with self.assertRaises(TransitionNotAllowed):
            s.inserisci_act()

    def test_storico_completo_del_ciclo(self):
        s = self._fino_a_check_completato(vuoi_act=True)
        s.inserisci_act()
        s.chiudi()
        s.save()
        # notifica_sms_team, classifica, definisci_plan, avvia_do, completa_do,
        # avvia_check, check_positivo, inserisci_act, chiudi = 9 transizioni
        self.assertEqual(s.storico.count(), 9)


class SuggestionCornerProtectedTest(TestCase):
    def test_assegnazione_diretta_stato_vietata(self):
        reparto = Reparto.objects.create(nome="PROT")
        s = SuggestionCorner.objects.create(
            reparto_provenienza=reparto, opportunity="Protected.",
        )
        with self.assertRaises(AttributeError):
            s.stato = "CHIUSA"

    def test_ciclo_do_rifatto_poi_positivo(self):
        reparto = Reparto.objects.create(nome="CICLO")
        u1 = User.objects.create(username="ck_do")
        u2 = User.objects.create(username="ck_ck")
        s = SuggestionCorner.objects.create(
            reparto_provenienza=reparto, opportunity="Ciclo con rework.",
        )
        s.notifica_sms_team()
        s.classifica(SuggestionCorner.StatoSMS.SMS_SI)
        d = datetime.date.today() + datetime.timedelta(days=10)
        s.definisci_plan(incaricato=u1, controllore=u2,
                         data_limite_esecuzione=d, data_limite_controllo=d)
        s.avvia_do()
        s.completa_do(SuggestionCorner.EsitoAttivita.NO)
        s.do_da_rifare(nuova_data_limite_esecuzione=d)
        s.completa_do(SuggestionCorner.EsitoAttivita.SI)
        s.avvia_check()
        s.check_positivo()
        s.chiudi()
        s.save()
        self.assertEqual(s.stato, "CHIUSA")


class SuggestionCornerReminderResetTest(TestCase):
    """Verifica che le transizioni di loop-back (do_da_rifare, check_rinviato,
    check_negativo) resettino i flag latch sollecito/escalation quando
    rinnovano una scadenza, altrimenti i solleciti futuri resterebbero
    permanentemente soppressi (sessione 5)."""

    def setUp(self):
        self.reparto = Reparto.objects.create(nome="REMIND")
        self.u1 = User.objects.create(username="remind_do")
        self.u2 = User.objects.create(username="remind_ck")

    def _fino_a_do_completato_no(self):
        s = SuggestionCorner.objects.create(
            reparto_provenienza=self.reparto, opportunity="Flusso reminder DO.",
        )
        s.notifica_sms_team()
        s.classifica(SuggestionCorner.StatoSMS.SMS_SI)
        d = datetime.date.today() + datetime.timedelta(days=10)
        s.definisci_plan(incaricato=self.u1, controllore=self.u2,
                         data_limite_esecuzione=d, data_limite_controllo=d)
        s.avvia_do()
        s.completa_do(SuggestionCorner.EsitoAttivita.NO)
        s.save()
        return s

    def _fino_a_check_in_corso(self):
        s = SuggestionCorner.objects.create(
            reparto_provenienza=self.reparto, opportunity="Flusso reminder CHECK.",
        )
        s.notifica_sms_team()
        s.classifica(SuggestionCorner.StatoSMS.SMS_SI)
        d = datetime.date.today() + datetime.timedelta(days=10)
        s.definisci_plan(incaricato=self.u1, controllore=self.u2,
                         data_limite_esecuzione=d, data_limite_controllo=d)
        s.avvia_do()
        s.completa_do(SuggestionCorner.EsitoAttivita.SI)
        s.avvia_check()
        s.save()
        return s

    def test_do_da_rifare_resetta_i_solleciti_do(self):
        s = self._fino_a_do_completato_no()
        s.sollecito_do_30 = True
        s.sollecito_do_15 = True
        s.sollecito_do_5 = True
        s.escalation_do_inviata = True
        nuova = datetime.date.today() + datetime.timedelta(days=30)
        s.do_da_rifare(nuova_data_limite_esecuzione=nuova)
        s.save()
        self.assertFalse(s.sollecito_do_30)
        self.assertFalse(s.sollecito_do_15)
        self.assertFalse(s.sollecito_do_5)
        self.assertFalse(s.escalation_do_inviata)
        self.assertEqual(s.data_limite_esecuzione, nuova)

    def test_check_rinviato_resetta_i_solleciti_check(self):
        s = self._fino_a_check_in_corso()
        s.sollecito_check_30 = True
        s.sollecito_check_15 = True
        s.sollecito_check_5 = True
        s.escalation_check_inviata = True
        nuova = datetime.date.today() + datetime.timedelta(days=45)
        s.check_rinviato(nuova_data_limite_controllo=nuova)
        s.save()
        self.assertFalse(s.sollecito_check_30)
        self.assertFalse(s.sollecito_check_15)
        self.assertFalse(s.sollecito_check_5)
        self.assertFalse(s.escalation_check_inviata)
        self.assertEqual(s.data_limite_controllo, nuova)

    def test_check_negativo_resetta_tutti_i_solleciti_e_la_scadenza_do(self):
        s = self._fino_a_check_in_corso()
        s.sollecito_do_30 = True
        s.sollecito_do_15 = True
        s.sollecito_do_5 = True
        s.escalation_do_inviata = True
        s.sollecito_check_30 = True
        s.sollecito_check_15 = True
        s.sollecito_check_5 = True
        s.escalation_check_inviata = True
        s.check_negativo()
        s.save()
        self.assertFalse(s.sollecito_do_30)
        self.assertFalse(s.sollecito_do_15)
        self.assertFalse(s.sollecito_do_5)
        self.assertFalse(s.escalation_do_inviata)
        self.assertFalse(s.sollecito_check_30)
        self.assertFalse(s.sollecito_check_15)
        self.assertFalse(s.sollecito_check_5)
        self.assertFalse(s.escalation_check_inviata)
        self.assertIsNone(s.data_limite_esecuzione)
        self.assertEqual(s.stato, "DO_IN_CORSO")
