from __future__ import annotations

import importlib

from django.apps import apps
from django.test import TestCase

from .models import CategoriaDPI

migrazione = importlib.import_module("dpi.migrations.0013_icona_vie_respiratorie")


class IconaVieRespiratorieTest(TestCase):
    def test_solo_respiratorie_con_icona_predefinita(self):
        resp = CategoriaDPI.objects.create(nome="Protezione vie respiratorie", icona_emoji="vest")
        maschere = CategoriaDPI.objects.create(nome="Maschere antipolvere", icona_emoji="🦺")
        scelta = CategoriaDPI.objects.create(nome="Semimaschera filtri", icona_emoji="shield")
        tuta = CategoriaDPI.objects.create(nome="Abbigliamento protettivo", icona_emoji="vest")

        migrazione.assegna_respiratore(apps, None)

        for categoria, attesa in ((resp, "mask"), (maschere, "mask"), (scelta, "shield"), (tuta, "vest")):
            categoria.refresh_from_db()
            self.assertEqual(categoria.icona_emoji, attesa, categoria.nome)
