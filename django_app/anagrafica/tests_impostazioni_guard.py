"""Guardia eliminazione cataloghi Impostazioni (Fase 3): ciò che è in uso si
disattiva (non si elimina), per preservare lo storico."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from datetime import date

from django.core.files.uploadedfile import SimpleUploadedFile

from .models import (
    CartellaDocumentoDipendente,
    DipendenteQualifica,
    DipendenteRuoloOperativo,
    DocumentoDipendente,
    RuoloOperativo,
    TipoQualifica,
)


class DeleteGuardTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("guard", "guard@e.it", "pwd12345")
        self.client.force_login(self.admin)

    def test_qualifica_in_uso_viene_disattivata(self):
        t = TipoQualifica.objects.create(nome="Saldatore", is_active=True)
        DipendenteQualifica.objects.create(legacy_anagrafica_id=1, tipo=t)
        self.client.post(reverse("anagrafica:tipo_qualifica_delete", args=[t.id]))
        t.refresh_from_db()
        self.assertFalse(t.is_active)                                   # disattivata
        self.assertTrue(TipoQualifica.objects.filter(pk=t.pk).exists())  # NON eliminata

    def test_qualifica_non_in_uso_viene_eliminata(self):
        t = TipoQualifica.objects.create(nome="Inutile", is_active=True)
        self.client.post(reverse("anagrafica:tipo_qualifica_delete", args=[t.id]))
        self.assertFalse(TipoQualifica.objects.filter(pk=t.pk).exists())  # eliminata

    def test_ruolo_operativo_in_uso_viene_disattivato(self):
        r = RuoloOperativo.objects.create(nome="Preposto", is_active=True)
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=1, ruolo=r)
        self.client.post(reverse("anagrafica:ruolo_operativo_delete", args=[r.id]))
        r.refresh_from_db()
        self.assertFalse(r.is_active)
        self.assertTrue(RuoloOperativo.objects.filter(pk=r.pk).exists())


class FolderRetentionTests(TestCase):
    """Container manager Documenti: i documenti manuali ereditano la retention della cartella."""

    def test_documento_eredita_retention_cartella(self):
        cart = CartellaDocumentoDipendente.objects.create(nome="Comunicazioni", retention_anni=2)
        doc = DocumentoDipendente.objects.create(
            legacy_anagrafica_id=1, tipo=DocumentoDipendente.Tipo.MANUALE, cartella=cart,
            file=SimpleUploadedFile("x.txt", b"x"),
        )
        self.assertIsNotNone(doc.retention_until)
        self.assertEqual(doc.retention_until.year, date.today().year + 2)

    def test_documento_senza_cartella_usa_default(self):
        doc = DocumentoDipendente.objects.create(
            legacy_anagrafica_id=1, tipo=DocumentoDipendente.Tipo.MANUALE,
            file=SimpleUploadedFile("y.txt", b"y"),
        )
        self.assertEqual(doc.retention_until.year, date.today().year + 10)
