"""Guardia eliminazione cataloghi Impostazioni (Fase 3): ciò che è in uso si
disattiva (non si elimina), per preservare lo storico."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import (
    DipendenteQualifica,
    DipendenteRuoloOperativo,
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
