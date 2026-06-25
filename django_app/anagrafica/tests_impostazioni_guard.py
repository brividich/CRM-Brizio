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
    Reparto,
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


class SubfolderTests(TestCase):
    """Sottocartelle documenti: creazione, unicità per livello, guardia eliminazione."""

    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("sub", "sub@e.it", "pwd12345")
        self.client.force_login(self.admin)

    def test_crea_sottocartella(self):
        root = CartellaDocumentoDipendente.objects.create(nome="HR")
        self.client.post(reverse("anagrafica:cartella_documento_create"),
                         {"nome": "Contratti", "parent": str(root.id), "ordine": "0", "retention_anni": "10"})
        sub = CartellaDocumentoDipendente.objects.get(nome="Contratti")
        self.assertEqual(sub.parent_id, root.id)

    def test_stesso_nome_parent_diversi_ok(self):
        a = CartellaDocumentoDipendente.objects.create(nome="A")
        b = CartellaDocumentoDipendente.objects.create(nome="B")
        CartellaDocumentoDipendente.objects.create(nome="2025", parent=a)
        CartellaDocumentoDipendente.objects.create(nome="2025", parent=b)  # non deve sollevare
        self.assertEqual(CartellaDocumentoDipendente.objects.filter(nome="2025").count(), 2)

    def test_delete_bloccato_se_ha_figlie(self):
        root = CartellaDocumentoDipendente.objects.create(nome="Radice")
        CartellaDocumentoDipendente.objects.create(nome="Figlia", parent=root)
        self.client.post(reverse("anagrafica:cartella_documento_delete", args=[root.id]))
        self.assertTrue(CartellaDocumentoDipendente.objects.filter(pk=root.id).exists())  # non eliminata


class TargetingTests(TestCase):
    """Targeting cartelle: applicabilità per reparto/ruolo (vuoto = universale)."""

    def test_universale_sempre_applicabile(self):
        c = CartellaDocumentoDipendente.objects.create(nome="Generale")
        self.assertTrue(c.si_applica("Produzione", set()))

    def test_match_reparto_case_insensitive(self):
        c = CartellaDocumentoDipendente.objects.create(nome="Solo Produzione")
        c.reparti.add(Reparto.objects.create(nome="Produzione"))
        self.assertTrue(c.si_applica("produzione", set()))   # case-insensitive
        self.assertFalse(c.si_applica("Ufficio", set()))

    def test_match_ruolo_operativo(self):
        c = CartellaDocumentoDipendente.objects.create(nome="Solo Preposti")
        r = RuoloOperativo.objects.create(nome="Preposto")
        c.ruoli_operativi.add(r)
        self.assertTrue(c.si_applica("", {r.id}))
        self.assertFalse(c.si_applica("", {99999}))


class DocumentMoveTests(TestCase):
    """Spostamento documento tra cartelle dall'archivio (container manager)."""

    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("mover", "mv@e.it", "pwd12345")
        self.client.force_login(self.admin)

    def test_sposta_documento_tra_cartelle(self):
        c1 = CartellaDocumentoDipendente.objects.create(nome="A")
        c2 = CartellaDocumentoDipendente.objects.create(nome="B")
        doc = DocumentoDipendente.objects.create(
            legacy_anagrafica_id=1, tipo=DocumentoDipendente.Tipo.MANUALE, cartella=c1,
            file=SimpleUploadedFile("z.txt", b"z"),
        )
        self.client.post(reverse("anagrafica:documento_sposta", args=[doc.id]), {"cartella": str(c2.id)})
        doc.refresh_from_db()
        self.assertEqual(doc.cartella_id, c2.id)

    def test_sposta_documento_a_senza_cartella(self):
        c1 = CartellaDocumentoDipendente.objects.create(nome="A")
        doc = DocumentoDipendente.objects.create(
            legacy_anagrafica_id=1, tipo=DocumentoDipendente.Tipo.MANUALE, cartella=c1,
            file=SimpleUploadedFile("z2.txt", b"z"),
        )
        self.client.post(reverse("anagrafica:documento_sposta", args=[doc.id]), {"cartella": "__nessuna__"})
        doc.refresh_from_db()
        self.assertIsNone(doc.cartella_id)
