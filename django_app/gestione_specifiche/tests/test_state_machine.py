"""Test F2 — macchina a stati (django-fsm-2), audit immutabile, guardie, ACL."""
from __future__ import annotations

from datetime import date
from unittest.mock import patch

from dateutil.relativedelta import relativedelta
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import RequestFactory, TestCase
from django_fsm import TransitionNotAllowed

from gestione_specifiche import constants as C
from gestione_specifiche.models import MOD133, EventoSpecifica, Specifica

User = get_user_model()


class FSMBase(TestCase):
    def setUp(self):
        self.comp = User.objects.create_user("compilatore", password="x")
        self.appr = User.objects.create_user("approvatore", password="x")

    def _porta_in_validita(self, codice="SP", revisione="0", revisione_precedente=None):
        spec = Specifica.objects.create(
            codice=codice, revisione=revisione, titolo="T",
            revisione_precedente=revisione_precedente,
        )
        spec.avvia_flow_down(attore=self.comp)
        spec.save()
        mod = spec.mod133
        mod.compilatore = self.comp
        mod.approvatore = self.appr
        mod.esito = C.ESITO_APPROVATO
        mod.save()
        spec.approva_flow_down(attore=self.appr)
        spec.save()
        return spec


class HappyPathTests(FSMBase):
    def test_s1_s2_s3_e_data_verifica(self):
        spec = Specifica.objects.create(codice="SP-100", titolo="T")
        self.assertEqual(spec.stato, C.STATO_BOZZA)

        spec.avvia_flow_down(attore=self.comp)
        spec.save()
        self.assertEqual(spec.stato, C.STATO_FLOW_DOWN)
        self.assertTrue(MOD133.objects.filter(specifica=spec).exists())

        mod = spec.mod133
        mod.compilatore = self.comp
        mod.approvatore = self.appr
        mod.esito = C.ESITO_APPROVATO
        mod.save()

        spec.approva_flow_down(attore=self.appr)
        spec.save()
        self.assertEqual(spec.stato, C.STATO_IN_VALIDITA)
        attesa = date.today() + relativedelta(months=6)
        self.assertEqual(spec.data_verifica, attesa)

    def test_un_solo_evento_per_transizione(self):
        spec = Specifica.objects.create(codice="SP-101", titolo="T")
        self.assertEqual(spec.eventi.count(), 0)
        spec.avvia_flow_down(attore=self.comp)
        spec.save()
        self.assertEqual(spec.eventi.count(), 1)
        evt = spec.eventi.first()
        self.assertEqual(evt.stato_da, C.STATO_BOZZA)
        self.assertEqual(evt.stato_a, C.STATO_FLOW_DOWN)
        self.assertEqual(evt.trigger, "avvia_flow_down")
        self.assertIn("snapshot", evt.payload)


class GuardieTests(FSMBase):
    def test_approva_fallisce_se_esito_non_approvato(self):
        spec = Specifica.objects.create(codice="SP-110", titolo="T")
        spec.avvia_flow_down(attore=self.comp)
        spec.save()
        mod = spec.mod133
        mod.compilatore = self.comp
        mod.approvatore = self.appr
        mod.esito = C.ESITO_RESPINTO
        mod.save()
        with self.assertRaises(ValidationError):
            spec.approva_flow_down(attore=self.appr)
        spec = Specifica.objects.get(pk=spec.pk)  # re-fetch (FSMField protected: no refresh_from_db)
        self.assertEqual(spec.stato, C.STATO_FLOW_DOWN)  # stato invariato
        self.assertEqual(spec.eventi.filter(trigger="approva_flow_down").count(), 0)

    def test_approva_fallisce_se_compilatore_uguale_approvatore(self):
        spec = Specifica.objects.create(codice="SP-111", titolo="T")
        spec.avvia_flow_down(attore=self.comp)
        spec.save()
        mod = spec.mod133
        mod.compilatore = self.comp
        mod.approvatore = self.comp  # stesso utente
        mod.esito = C.ESITO_APPROVATO
        mod.save()
        with self.assertRaises(ValidationError):
            spec.approva_flow_down(attore=self.comp)
        spec = Specifica.objects.get(pk=spec.pk)  # re-fetch (FSMField protected: no refresh_from_db)
        self.assertEqual(spec.stato, C.STATO_FLOW_DOWN)


class SuperamentoRevisioneTests(FSMBase):
    def test_revisione_precedente_superata_automaticamente(self):
        prev = self._porta_in_validita(codice="SP-200", revisione="0")
        self.assertEqual(prev.stato, C.STATO_IN_VALIDITA)
        new = self._porta_in_validita(codice="SP-200", revisione="1", revisione_precedente=prev)
        prev = Specifica.objects.get(pk=prev.pk)  # re-fetch (FSMField protected: no refresh_from_db)
        self.assertEqual(new.stato, C.STATO_IN_VALIDITA)
        self.assertEqual(prev.stato, C.STATO_SUPERATO)
        # la transizione di superamento ha generato un evento su prev
        self.assertTrue(prev.eventi.filter(stato_a=C.STATO_SUPERATO).exists())


class SospensioneTests(FSMBase):
    def test_sospendi_ripristina_da_s3(self):
        spec = self._porta_in_validita(codice="SP-300")
        spec.sospendi(attore=self.comp, motivo="riesame", data=date.today())
        spec.save()
        self.assertEqual(spec.stato, C.STATO_SOSPESO)
        self.assertEqual(spec.stato_precedente, C.STATO_IN_VALIDITA)
        spec.ripristina(attore=self.comp, motivo="ok")
        spec.save()
        self.assertEqual(spec.stato, C.STATO_IN_VALIDITA)

    def test_sospendi_ripristina_da_s2(self):
        spec = Specifica.objects.create(codice="SP-301", titolo="T")
        spec.avvia_flow_down(attore=self.comp)
        spec.save()
        spec.sospendi(attore=self.comp, motivo="m", data=date.today())
        spec.save()
        self.assertEqual(spec.stato, C.STATO_SOSPESO)
        self.assertEqual(spec.stato_precedente, C.STATO_FLOW_DOWN)
        spec.ripristina(attore=self.comp, motivo="ok")
        spec.save()
        self.assertEqual(spec.stato, C.STATO_FLOW_DOWN)

    def test_sospendi_richiede_motivo(self):
        spec = self._porta_in_validita(codice="SP-302")
        with self.assertRaises(ValidationError):
            spec.sospendi(attore=self.comp, motivo="", data=date.today())
        with self.assertRaises(ValidationError):
            spec.sospendi(attore=self.comp, motivo="x", data=None)


class AnnullaTests(FSMBase):
    def test_annulla_da_bozza_e_flow_down(self):
        s1 = Specifica.objects.create(codice="SP-400", titolo="T")
        s1.annulla(attore=self.comp, motivo="non più valida")
        s1.save()
        self.assertEqual(s1.stato, C.STATO_ANNULLATO)

        s2 = Specifica.objects.create(codice="SP-401", titolo="T")
        s2.avvia_flow_down(attore=self.comp)
        s2.save()
        s2.annulla(attore=self.comp, motivo="errata")
        s2.save()
        self.assertEqual(s2.stato, C.STATO_ANNULLATO)

    def test_annulla_richiede_motivo(self):
        s = Specifica.objects.create(codice="SP-402", titolo="T")
        with self.assertRaises(ValidationError):
            s.annulla(attore=self.comp, motivo="")


class DuplicatoTests(FSMBase):
    def test_marca_duplicato_richiede_master_e_motivo(self):
        s = Specifica.objects.create(codice="SP-500", titolo="T")
        # senza master -> errore (anche con motivo)
        with self.assertRaises(ValidationError):
            s.marca_duplicato(attore=self.comp, motivo="doppione")
        master = Specifica.objects.create(codice="SP-MASTER", titolo="T")
        s.master = master
        # con master ma senza motivo -> errore (Matrice T2: master + motivo)
        with self.assertRaises(ValidationError):
            s.marca_duplicato(attore=self.comp, motivo="")
        # con master + motivo -> ok
        s.marca_duplicato(attore=self.comp, motivo="doppione del master")
        s.save()
        self.assertEqual(s.stato, C.STATO_DUPLICATO)


class ErroreTecnicoTests(FSMBase):
    def test_errore_tecnico_e_ripristino(self):
        spec = self._porta_in_validita(codice="SP-600")
        spec.errore_tecnico(attore=self.comp, errore={"msg": "import rotto"})
        spec.save()
        self.assertEqual(spec.stato, C.STATO_ERRORE_TECNICO)
        self.assertEqual(spec.stato_pre_errore, C.STATO_IN_VALIDITA)  # slot dedicato all'errore (M2)
        spec.ripristina_da_errore(attore=self.comp)
        spec.save()
        self.assertEqual(spec.stato, C.STATO_IN_VALIDITA)

    def test_errore_tecnico_richiede_payload(self):
        spec = Specifica.objects.create(codice="SP-601", titolo="T")
        with self.assertRaises(ValidationError):
            spec.errore_tecnico(attore=self.comp, errore=None)

    def test_errore_durante_sospensione_non_intrappola(self):
        # M2: S3 -> sospendi -> S5 -> errore -> S9 -> ripristina_da_errore -> S5 -> ripristina -> S3.
        # Con slot separati (stato_precedente vs stato_pre_errore) i due percorsi non si calpestano.
        spec = self._porta_in_validita(codice="SP-602")
        spec.sospendi(attore=self.comp, motivo="riesame", data=date.today())
        spec.save()
        self.assertEqual(spec.stato, C.STATO_SOSPESO)
        spec.errore_tecnico(attore=self.comp, errore={"msg": "glitch"})
        spec.save()
        self.assertEqual(spec.stato, C.STATO_ERRORE_TECNICO)
        spec.ripristina_da_errore(attore=self.comp)
        spec.save()
        self.assertEqual(spec.stato, C.STATO_SOSPESO)  # torna alla sospensione, NON intrappolata
        spec.ripristina(attore=self.comp, motivo="ok")
        spec.save()
        self.assertEqual(spec.stato, C.STATO_IN_VALIDITA)  # slot sospensione intatto -> torna in S3


class TransizioniIllegaliTests(FSMBase):
    def test_approva_da_bozza_non_consentita(self):
        spec = Specifica.objects.create(codice="SP-700", titolo="T")
        with self.assertRaises(TransitionNotAllowed):
            spec.approva_flow_down(attore=self.appr)

    def test_avvia_due_volte_non_consentito(self):
        spec = Specifica.objects.create(codice="SP-701", titolo="T")
        spec.avvia_flow_down(attore=self.comp)
        spec.save()
        with self.assertRaises(TransitionNotAllowed):
            spec.avvia_flow_down(attore=self.comp)


class AclTests(TestCase):
    def test_superuser_consentito(self):
        from core.acl import user_can_modulo_action

        su = User.objects.create_superuser("root", "r@x.it", "x")
        req = RequestFactory().get("/gestione-specifiche/")
        req.user = su
        self.assertTrue(user_can_modulo_action(req, "gestione_specifiche", "gs_view"))

    def test_utente_senza_permesso_negato(self):
        from core.acl import user_can_modulo_action

        u = User.objects.create_user("nessuno", password="x")
        req = RequestFactory().get("/gestione-specifiche/")
        req.user = u
        with patch("core.legacy_utils.get_legacy_user", return_value=None):
            self.assertFalse(user_can_modulo_action(req, "gestione_specifiche", "gs_view"))
