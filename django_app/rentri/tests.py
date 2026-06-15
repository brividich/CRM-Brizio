from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import UserOnboarding

from .models import RegistroRifiuti

User = get_user_model()


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class RentriWriteAuthorizationTests(TestCase):
    """SEC-PREPROD-02 (M3): scrittura del registro RENTRI riservata ai gestori."""

    def setUp(self):
        self.basic = User.objects.create_user(
            username="rentri-basic", email="rentri-basic@example.com", password="pwd12345",
        )
        UserOnboarding.objects.create(
            user=self.basic, completed=True, completed_at=timezone.now(),
        )
        self.admin = User.objects.create_superuser(
            username="rentri-admin", email="rentri-admin@example.com", password="pwd12345",
        )

    def test_basic_user_cannot_create_via_carico(self):
        self.client.force_login(self.basic)
        response = self.client.post(
            reverse("rentri_carico"),
            data='{"data": "2026-05-01"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(RegistroRifiuti.objects.count(), 0)

    def test_admin_can_create_via_carico(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("rentri_carico"),
            data='{"data": "2026-05-01"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(RegistroRifiuti.objects.filter(tipo="C").count(), 1)

    def test_basic_user_cannot_modify(self):
        registro = RegistroRifiuti.objects.create(tipo="C", data=date(2026, 5, 1))
        self.client.force_login(self.basic)
        response = self.client.post(
            reverse("rentri_modifica", args=[registro.pk]),
            data='{"data": "2026-06-01"}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 403)

    def test_basic_user_cannot_delete(self):
        registro = RegistroRifiuti.objects.create(tipo="C", data=date(2026, 5, 1))
        self.client.force_login(self.basic)
        response = self.client.post(reverse("rentri_elimina", args=[registro.pk]))
        self.assertEqual(response.status_code, 403)
        self.assertTrue(RegistroRifiuti.objects.filter(pk=registro.pk).exists())

    def test_admin_can_delete(self):
        registro = RegistroRifiuti.objects.create(tipo="C", data=date(2026, 5, 1))
        self.client.force_login(self.admin)
        response = self.client.post(reverse("rentri_elimina", args=[registro.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(RegistroRifiuti.objects.filter(pk=registro.pk).exists())

    def test_delete_rejects_get(self):
        registro = RegistroRifiuti.objects.create(tipo="C", data=date(2026, 5, 1))
        self.client.force_login(self.admin)
        response = self.client.get(reverse("rentri_elimina", args=[registro.pk]))
        self.assertEqual(response.status_code, 405)
        self.assertTrue(RegistroRifiuti.objects.filter(pk=registro.pk).exists())

    def test_basic_user_cannot_import_confirm(self):
        self.client.force_login(self.basic)
        response = self.client.post(reverse("rentri_import_confirm"))
        self.assertEqual(response.status_code, 403)

    def test_basic_user_cannot_trigger_sync_pull(self):
        self.client.force_login(self.basic)
        response = self.client.post(reverse("rentri_api_sync_pull"))
        self.assertEqual(response.status_code, 403)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class RentriScadenzarioTests(TestCase):
    """#7 — scadenzario adempimenti RENTRI (FIR mancanti / da comunicare / bozze)."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="rentri-sc", email="rentri-sc@example.com", password="pwd12345",
        )
        UserOnboarding.objects.create(
            user=self.user, completed=True, completed_at=timezone.now(),
        )
        self.client.force_login(self.user)
        # scarico senza FIR → finisce in "FIR mancante"
        self.fir_mancante = RegistroRifiuti.objects.create(
            tipo="O", data=date(2026, 5, 1), salva=True, rentri_si_no=True, arrivo_fir="",
        )
        # scarico CON FIR → NON deve comparire tra i FIR mancanti
        RegistroRifiuti.objects.create(
            tipo="O", data=date(2026, 5, 2), salva=True, rentri_si_no=True, arrivo_fir="FIR-2026-1",
        )
        # carico senza FIR → escluso (il FIR riguarda gli scarichi)
        RegistroRifiuti.objects.create(tipo="C", data=date(2026, 5, 3), salva=True, arrivo_fir="")
        # consolidato ma non trasmesso → "da comunicare"
        self.da_comunicare = RegistroRifiuti.objects.create(
            tipo="C", data=date(2026, 5, 4), salva=True, rentri_si_no=False, arrivo_fir="x",
        )
        # bozza non salvata → "bozze"
        self.bozza = RegistroRifiuti.objects.create(
            tipo="C", data=date(2026, 5, 5), salva=False, arrivo_fir="x",
        )

    def _bucket(self, sections, key):
        return next(s for s in sections if s["key"] == key)

    def test_buckets_classify_records(self):
        from rentri.views import _scadenzario_buckets

        sections = _scadenzario_buckets(date(2026, 6, 1))
        fir_pks = [r["pk"] for r in self._bucket(sections, "fir")["rows"]]
        com_pks = [r["pk"] for r in self._bucket(sections, "comunicare")["rows"]]
        boz_pks = [r["pk"] for r in self._bucket(sections, "bozze")["rows"]]

        self.assertEqual(fir_pks, [self.fir_mancante.pk])
        self.assertIn(self.da_comunicare.pk, com_pks)
        self.assertIn(self.bozza.pk, boz_pks)

    def test_page_renders(self):
        response = self.client.get(reverse("rentri_scadenzario"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Scadenzario adempimenti RENTRI")
        self.assertContains(response, "FIR mancante")

    def test_csv_export(self):
        response = self.client.get(reverse("rentri_scadenzario"), {"export": "csv"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response["Content-Type"])
        body = response.content.decode("utf-8-sig")
        self.assertIn("Adempimento", body)
        self.assertIn("FIR mancante", body)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class RentriGiacenzeTests(TestCase):
    """R1 — giacenze per CER + semaforo deposito temporaneo."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="rentri-gi", email="rentri-gi@example.com", password="pwd12345",
        )
        UserOnboarding.objects.create(
            user=self.user, completed=True, completed_at=timezone.now(),
        )
        self.admin = User.objects.create_superuser(
            username="rentri-gi-admin", email="rentri-gi-admin@example.com", password="pwd12345",
        )

    def _g(self, codice):
        from rentri.giacenze import giacenze_per_cer
        return next(g for g in giacenze_per_cer() if g.codice == codice)

    def test_giacenza_carico_meno_scarico(self):
        RegistroRifiuti.objects.create(tipo="C", data=date(2026, 1, 5), codice="150106", quantita=100)
        RegistroRifiuti.objects.create(tipo="M", data=date(2026, 2, 5), codice="150106", quantita=30)
        g = self._g("150106")
        self.assertEqual(g.entrate, 100)
        self.assertEqual(g.uscite, 30)
        self.assertEqual(g.giacenza, 70)
        self.assertTrue(g.aperta)

    def test_rettifica_riduce_giacenza(self):
        RegistroRifiuti.objects.create(tipo="C", data=date(2026, 1, 5), codice="160601", quantita=50)
        RegistroRifiuti.objects.create(tipo="R", data=date(2026, 2, 5), codice="160601", quantita=20)
        self.assertEqual(self._g("160601").giacenza, 30)

    def test_scarico_originale_non_muove_giacenza(self):
        RegistroRifiuti.objects.create(tipo="C", data=date(2026, 1, 5), codice="170405", quantita=80)
        RegistroRifiuti.objects.create(tipo="O", data=date(2026, 2, 5), codice="170405", quantita=80)
        # O è pianificato: la giacenza resta pari al solo carico
        self.assertEqual(self._g("170405").giacenza, 80)

    def test_pericoloso_flag(self):
        RegistroRifiuti.objects.create(
            tipo="C", data=date(2026, 1, 5), codice="150202", quantita=10, pericolosita="HP04",
        )
        self.assertTrue(self._g("150202").pericoloso)

    def test_semaforo_oltre_soglia(self):
        vecchio = timezone.localdate() - timedelta(days=120)
        RegistroRifiuti.objects.create(tipo="C", data=vecchio, codice="080111", quantita=40)
        from rentri.giacenze import soglie_deposito
        g = self._g("080111")
        self.assertGreaterEqual(g.giorni_giacenza, 120)
        self.assertEqual(g.tono(soglie_deposito()), "rosso")

    def test_giacenza_azzerata_e_chiusa(self):
        RegistroRifiuti.objects.create(tipo="C", data=date(2026, 1, 5), codice="200101", quantita=25)
        RegistroRifiuti.objects.create(tipo="M", data=date(2026, 2, 5), codice="200101", quantita=25)
        from rentri.giacenze import soglie_deposito
        g = self._g("200101")
        self.assertFalse(g.aperta)
        self.assertIsNone(g.giorni_giacenza)
        self.assertEqual(g.tono(soglie_deposito()), "chiuso")

    def test_view_renders(self):
        RegistroRifiuti.objects.create(tipo="C", data=date(2026, 1, 5), codice="150106", quantita=100)
        self.client.force_login(self.user)
        response = self.client.get(reverse("rentri_giacenze"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Giacenze per CER")
        self.assertContains(response, "150106")

    def test_view_csv_export(self):
        RegistroRifiuti.objects.create(tipo="C", data=date(2026, 1, 5), codice="150106", quantita=100)
        self.client.force_login(self.user)
        response = self.client.get(reverse("rentri_giacenze"), {"export": "csv"})
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/csv", response["Content-Type"])
        body = response.content.decode("utf-8-sig")
        self.assertIn("Codice EER", body)
        self.assertIn("150106", body)

    def test_provider_include_deposito(self):
        vecchio = timezone.localdate() - timedelta(days=100)
        RegistroRifiuti.objects.create(tipo="C", data=vecchio, codice="080111", quantita=40)
        from dashboard.scadenze_providers import ScadenzeContext, collect_rentri

        req = RequestFactory().get("/")
        req.user = self.admin
        items = collect_rentri(ScadenzeContext.build(req))
        depositi = [it for it in items if it.kind == "deposito"]
        self.assertTrue(any(it.soggetto == "080111" for it in depositi))
