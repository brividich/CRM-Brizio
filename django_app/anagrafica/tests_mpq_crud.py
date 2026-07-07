"""MOD.128 MPQ — gestione (CRUD) processi/clienti/abilitazioni/certificati.

Test delle viste di scrittura (gated ``anagrafica.mpq.manage``): CRUD processo,
anagrafica clienti/enti, abilitazioni persona×processo (interni + esterni),
certificazioni individuali, riferimenti. Dati fittizi (no PII).
"""
from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .models import (
    AbilitazioneProcesso,
    CertificazioneIndividuale,
    ClienteQualificante,
    ProcessoQualificato,
    RiferimentoProcesso,
)
from .tests import _ensure_anagrafica_table, _ensure_utenti_table

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class MpqCrudBase(TestCase):
    def setUp(self):
        _ensure_anagrafica_table()
        _ensure_utenti_table()
        self.manager = User.objects.create_superuser(
            username="mpq-mgr", email="mgr@example.com", password="pass12345")
        self.client.force_login(self.manager)
        self.cli = ClienteQualificante.objects.create(nome="Cliente A")
        self.proc = ProcessoQualificato.objects.create(nome="Processo X", cliente=self.cli)


class MpqAclManageTests(MpqCrudBase):
    def test_utente_senza_manage_negato(self):
        user = User.objects.create_user(
            username="plain", email="p@example.com", password="pass12345")
        self.client.force_login(user)
        resp = self.client.get(reverse("anagrafica:mpq_processo_create"))
        self.assertEqual(resp.status_code, 302)


class MpqProcessoCrudTests(MpqCrudBase):
    def test_create_form_ok(self):
        resp = self.client.get(reverse("anagrafica:mpq_processo_create"))
        self.assertEqual(resp.status_code, 200)

    def test_create_post(self):
        resp = self.client.post(reverse("anagrafica:mpq_processo_create"), {
            "cliente": self.cli.id, "nome": "Nuovo Processo", "regime": "SPECIALE",
            "tipo_validita": "ILLIMITATA", "personale_modalita": "NOMINALE",
            "stato": "ATTIVO",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(ProcessoQualificato.objects.filter(nome="Nuovo Processo").exists())

    def test_edit_post(self):
        resp = self.client.post(
            reverse("anagrafica:mpq_processo_edit", args=[self.proc.id]), {
                "cliente": self.cli.id, "nome": "Processo Rinominato", "regime": "NADCAP",
                "tipo_validita": "ILLIMITATA", "personale_modalita": "NOMINALE",
                "stato": "ATTIVO",
            })
        self.assertEqual(resp.status_code, 302)
        self.proc.refresh_from_db()
        self.assertEqual(self.proc.nome, "Processo Rinominato")
        self.assertEqual(self.proc.regime, "NADCAP")

    def test_delete_post(self):
        resp = self.client.post(reverse("anagrafica:mpq_processo_delete", args=[self.proc.id]))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(ProcessoQualificato.objects.filter(pk=self.proc.id).exists())


class MpqClienteCrudTests(MpqCrudBase):
    def test_lista_ok(self):
        resp = self.client.get(reverse("anagrafica:mpq_cliente_list"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Cliente A")

    def test_create_post(self):
        resp = self.client.post(reverse("anagrafica:mpq_cliente_create"), {
            "nome": "Ente Nuovo", "tipo": "ENTE_ACCREDITAMENTO", "is_active": "on"})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(ClienteQualificante.objects.filter(nome="Ente Nuovo").exists())


class MpqAbilitazioneCrudTests(MpqCrudBase):
    def test_add_interno(self):
        resp = self.client.post(
            reverse("anagrafica:mpq_abilitazione_add", args=[self.proc.id]), {
                "tipo_persona": "interno", "dipendente": "42",
                "stato": "ATTIVA", "is_qualificato": "on", "is_controllore": "on",
            })
        self.assertEqual(resp.status_code, 302)
        ab = AbilitazioneProcesso.objects.get(processo=self.proc, legacy_anagrafica_id=42)
        self.assertTrue(ab.is_controllore)
        self.assertFalse(ab.is_esterno)

    def test_add_esterno(self):
        resp = self.client.post(
            reverse("anagrafica:mpq_abilitazione_add", args=[self.proc.id]), {
                "tipo_persona": "esterno", "nominativo_esterno": "Qualificatore Esterno",
                "stato": "ATTIVA", "is_qualificato": "on",
            })
        self.assertEqual(resp.status_code, 302)
        ab = AbilitazioneProcesso.objects.get(
            processo=self.proc, nominativo_esterno="Qualificatore Esterno")
        self.assertTrue(ab.is_esterno)
        self.assertEqual(ab.legacy_anagrafica_id, 0)

    def test_add_esterno_senza_nome_invalido(self):
        resp = self.client.post(
            reverse("anagrafica:mpq_abilitazione_add", args=[self.proc.id]), {
                "tipo_persona": "esterno", "nominativo_esterno": "", "stato": "ATTIVA",
            })
        self.assertEqual(resp.status_code, 200)  # form ri-renderizzato con errore
        self.assertFalse(AbilitazioneProcesso.objects.filter(processo=self.proc).exists())

    def test_delete(self):
        ab = AbilitazioneProcesso.objects.create(legacy_anagrafica_id=5, processo=self.proc)
        resp = self.client.post(reverse("anagrafica:mpq_abilitazione_delete", args=[ab.id]))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(AbilitazioneProcesso.objects.filter(pk=ab.id).exists())


class MpqCertRiferimentoTests(MpqCrudBase):
    def setUp(self):
        super().setUp()
        self.ab = AbilitazioneProcesso.objects.create(legacy_anagrafica_id=5, processo=self.proc)

    def test_cert_add(self):
        resp = self.client.post(
            reverse("anagrafica:mpq_certificazione_add", args=[self.ab.id]), {
                "schema": "ITA", "numero": "999/2", "stato": "ATTIVA"})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(CertificazioneIndividuale.objects.filter(
            abilitazione=self.ab, schema="ITA").exists())

    def test_riferimento_add(self):
        resp = self.client.post(
            reverse("anagrafica:mpq_riferimento_add", args=[self.proc.id]), {
                "codice": "COP001", "tipo": "APPROVAZIONE"})
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(RiferimentoProcesso.objects.filter(
            processo=self.proc, codice="COP001").exists())


class MpqQuickAddTests(MpqCrudBase):
    """Crea-al-volo (JSON) di corso/visita/DPI dal form processo."""

    def test_quickadd_visita(self):
        resp = self.client.post(
            reverse("anagrafica:mpq_quickadd_visita"), {"nome": "Visita Nuova", "durata_mesi": "24"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        from .models import TipoVisitaMedica
        v = TipoVisitaMedica.objects.get(nome="Visita Nuova")
        self.assertEqual(v.durata_mesi, 24)
        self.assertEqual(data["id"], v.pk)

    def test_quickadd_dpi(self):
        resp = self.client.post(reverse("anagrafica:mpq_quickadd_dpi"), {"nome": "Guanti Nuovi"})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["ok"])
        from dpi.models import CategoriaDPI
        self.assertTrue(CategoriaDPI.objects.filter(nome="Guanti Nuovi").exists())

    def test_quickadd_corso(self):
        from .models import TrainingCourse, TrainingPlan
        plan = TrainingPlan.objects.create(codice="PLQA", nome="Piano QA")
        resp = self.client.post(
            reverse("anagrafica:mpq_quickadd_corso"),
            {"titolo": "Corso Nuovo", "durata_ore_teorica": "2",
             "validita_mesi": "12", "piano": str(plan.pk)})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertIn("edit_url", data)  # link per completare la bozza
        c = TrainingCourse.objects.get(titolo="Corso Nuovo")
        self.assertEqual(c.validita_mesi, 12)
        self.assertEqual(c.piano_id, plan.pk)   # piano scelto rispettato
        self.assertEqual(c.stato, "BOZZA")      # nasce incompleto → bozza

    def test_quickadd_nome_vuoto_400(self):
        resp = self.client.post(reverse("anagrafica:mpq_quickadd_visita"), {"nome": ""})
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(resp.json()["ok"])

    def test_quickadd_negato_senza_manage(self):
        from dpi.models import CategoriaDPI
        u = User.objects.create_user(username="qa-plain", email="qa@example.com", password="pass12345")
        self.client.force_login(u)
        resp = self.client.post(reverse("anagrafica:mpq_quickadd_dpi"), {"nome": "X Negato"})
        # negato (302 redirect middleware o 403 gate in-view); comunque NON creato
        self.assertIn(resp.status_code, (302, 403))
        self.assertFalse(CategoriaDPI.objects.filter(nome="X Negato").exists())
