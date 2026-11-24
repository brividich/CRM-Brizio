"""Documenti asset: sposta, conteggi, rinomina cartella, ZIP, scadenza."""

from __future__ import annotations

import io
import zipfile
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from assets.models import Asset, AssetCategory, AssetCategoryDocumentFolder, AssetDocument, AssetDocumentFolder
from assets.services.documenti_asset import stato_scadenza
from assets.tests import _workspace_temporary_directory
from core.models import UserOnboarding


class DocumentiPlusTests(TestCase):
    def setUp(self):
        self._tmp = _workspace_temporary_directory("assets-docplus-")
        tmpdir = self._tmp.__enter__()
        self.addCleanup(self._tmp.__exit__, None, None, None)
        o = override_settings(MEDIA_ROOT=tmpdir)
        o.enable()
        self.addCleanup(o.disable)
        cat = AssetCategory.objects.create(code="doc-x", label="Doc X", is_active=True)
        AssetCategoryDocumentFolder.objects.create(category=cat, name="Verbali", slug="verbali", order=1)
        self.asset = Asset.objects.create(name="Compressore Y", asset_type=Asset.TYPE_OTHER, asset_category=cat)
        self.cartella = AssetDocumentFolder.objects.create(asset=self.asset, name="Foto", slug="foto")
        self.d1 = self._doc("verbali", "a.pdf")
        self.d2 = self._doc("verbali", "b.pdf", cartella="2026")
        user = get_user_model().objects.create_superuser(username="docplus", email="d@example.com", password="x")
        UserOnboarding.objects.update_or_create(user=user, defaults={"completed": True})
        self.client.force_login(user)
        self.url = reverse("assets:asset_view", args=[self.asset.id])

    def _doc(self, categoria, nome, cartella=""):
        return AssetDocument.objects.create(
            asset=self.asset, category=categoria, original_name=nome, relative_folder=cartella,
            file=SimpleUploadedFile(nome, b"%PDF-1.4 " + nome.encode(), content_type="application/pdf"),
        )

    def test_conteggi_e_ricerca_in_pagina(self):
        html = self.client.get(self.url).content.decode()
        self.assertIn("data-doc-cerca", html)
        self.assertIn('data-doc-tab-n>2<', html)
        self.assertIn(reverse("assets:asset_document_folder_zip", args=[self.asset.id, "verbali"]), html)

    def test_sposta(self):
        self.client.post(self.url, {"action": "sposta_documenti", "destinazione": "foto", "document_ids": [self.d1.id]})
        self.d1.refresh_from_db()
        self.assertEqual(self.d1.category, "foto")
        self.client.post(self.url, {"action": "sposta_documenti", "destinazione": "inesistente", "document_ids": [self.d2.id]})
        self.d2.refresh_from_db()
        self.assertEqual(self.d2.category, "verbali")

    def test_rinomina_cartella_asset(self):
        self.client.post(self.url, {"action": "rinomina_cartella_asset", "folder_id": self.cartella.id, "folder_name": "Foto impianto"})
        self.cartella.refresh_from_db()
        self.assertEqual(self.cartella.name, "Foto impianto")
        self.assertEqual(self.cartella.slug, "foto")

    def test_zip(self):
        r = self.client.get(reverse("assets:asset_document_folder_zip", args=[self.asset.id, "verbali"]))
        self.assertEqual(r.status_code, 200)
        nomi = sorted(zipfile.ZipFile(io.BytesIO(r.content)).namelist())
        self.assertEqual(nomi, ["2026/b.pdf", "a.pdf"])
        vuota = self.client.get(reverse("assets:asset_document_folder_zip", args=[self.asset.id, "foto"]))
        self.assertEqual(vuota.status_code, 404)

    def test_scadenza(self):
        oggi = timezone.localdate()
        domani = oggi + timedelta(days=10)
        self.client.post(self.url, {"action": "scadenza_documento", "document_id": self.d1.id, "data_scadenza": domani.isoformat()})
        self.d1.refresh_from_db()
        self.assertEqual(self.d1.data_scadenza, domani)
        self.assertIn("In scadenza", self.client.get(self.url).content.decode())
        self.client.post(self.url, {"action": "scadenza_documento", "document_id": self.d1.id, "data_scadenza": ""})
        self.d1.refresh_from_db()
        self.assertIsNone(self.d1.data_scadenza)
        self.assertEqual(stato_scadenza(oggi - timedelta(days=1), oggi), "scaduto")
        self.assertEqual(stato_scadenza(oggi + timedelta(days=90), oggi), "valido")
        self.assertEqual(stato_scadenza(None, oggi), "")


class ScadenzeDuplicaSdsTicketTests(DocumentiPlusTests):
    def test_documento_nello_scadenzario(self):
        from assets.services import deadline_feed as feed

        oggi = timezone.localdate()
        AssetDocument.objects.filter(pk=self.d1.pk).update(data_scadenza=oggi + timedelta(days=5))
        righe = [r for r in feed.collect(start=oggi, end=oggi + timedelta(days=60)) if r.kind == feed.KIND_DOCUMENT]
        self.assertEqual([r.key for r in righe], [f"doc-{self.d1.pk}"])
        self.assertEqual(righe[0].state, feed.STATE_DUE_SOON)
        pagina = self.client.get(reverse("assets:maintenance_scadenze") + "?plan_type=documents&window=90")
        self.assertEqual(pagina.status_code, 200)
        self.assertContains(pagina, "a.pdf")

    def test_nuovo_asset_come_questo(self):
        self.asset.manufacturer = "Atlas"
        self.asset.save(update_fields=["manufacturer"])
        url = reverse("assets:asset_create") + f"?da_asset={self.asset.id}"
        form = self.client.get(url).context["form"]
        self.assertEqual(form.initial["manufacturer"], "Atlas")
        self.assertEqual(form.initial["asset_category"], self.asset.asset_category_id)
        from assets.views.asset_crud import _copia_cartelle_documento

        nuovo = Asset.objects.create(name="Compressore Z", asset_type=Asset.TYPE_OTHER, asset_category=self.asset.asset_category)
        self.assertEqual(_copia_cartelle_documento(self.asset, nuovo), 1)
        self.assertTrue(AssetDocumentFolder.objects.filter(asset=nuovo, slug="foto").exists())
        self.assertFalse(AssetDocument.objects.filter(asset=nuovo).exists())

    def test_stato_sds_per_prodotti(self):
        from assets.services.documenti_asset import stato_sds_per_prodotti
        from schede_sicurezza.models import ProdottoChimico

        p = ProdottoChimico.objects.create(nome="Sgrassante prova")
        self.assertEqual(stato_sds_per_prodotti([p.pk])[p.pk]["codice"], "mancante")

    def test_ticket_chiuso_nello_storico_tecnico(self):
        from tickets.models import StatoTicket, Ticket, TicketIntervento, TipoTicket

        t = Ticket.objects.create(tipo=TipoTicket.MAN, titolo="Perdita aria", descrizione="x", categoria="ALTRO",
                                  richiedente_nome="Prova", asset=self.asset, stato=StatoTicket.CHIUSO,
                                  closed_at=timezone.now())
        TicketIntervento.objects.create(ticket=t, data_inizio=timezone.now(), descrizione_lavoro="Sostituito raccordo")
        righe = self.client.get(self.url).context["timeline_tech_rows"]
        riga = next(r for r in righe if r["tipo"] == "ticket")
        self.assertEqual(riga["dettaglio"], "Sostituito raccordo")
        self.assertTrue(riga["url"])
