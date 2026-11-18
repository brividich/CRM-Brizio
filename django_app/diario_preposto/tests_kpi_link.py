"""Tessere del cruscotto del Diario preposto: ognuna apre l'elenco ?vista=... con lo stesso numero."""
from __future__ import annotations

import shutil
import tempfile
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import UserOnboarding

from .cruscotto import VISTE, filtra_vista
from .models import SegnalazioneAllegato, SegnalazionePreposto


class CruscottoKpiLinkTests(TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="dp-kpi-")
        self._override = override_settings(DIARIO_PREPOSTO_PRIVATE_ROOT=self._tmp)
        self._override.enable()
        self.admin = get_user_model().objects.create_superuser(username="dp-kpi", email="k@example.com", password="x")
        UserOnboarding.objects.create(user=self.admin, completed=True, completed_at=timezone.now())
        self.client.force_login(self.admin)
        adesso = timezone.now()
        for giorni, preposto in ((0, "Verdi"), (3, "Verdi"), (12, "Rossi"), (45, "Verdi"), (400, "Rossi")):
            s = SegnalazionePreposto.objects.create(
                titolo=f"Fatto {giorni}", data_segnalazione=adesso - timedelta(days=giorni),
                descrizione="x", preposto=preposto, chi_segnala=preposto, creato_da=self.admin,
            )
            if giorni == 3:
                SegnalazioneAllegato.objects.create(segnalazione=s, nome_file="a.txt", file="x/a.txt")

    def tearDown(self):
        self._override.disable()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_ogni_tessera_conta_le_righe_della_sua_vista(self):
        url = reverse("diario_preposto:lista")
        for filtri in ({}, {"preposto": "Verdi"}):
            r = self.client.get(url, filtri)
            c = r.context["cruscotto"]
            mappa = {"7g": c["ultimi_7"], "30g": c["ultimi_30"], "mese": c["mese_corrente"],
                     "senza_allegati": c["senza_allegati"], "ritardo": c["in_ritardo"]}
            self.assertEqual(set(mappa), set(VISTE))
            for vista, atteso in mappa.items():
                elenco = self.client.get(url, {**filtri, "vista": vista})
                self.assertEqual(elenco.context["vista"], vista)
                self.assertEqual(elenco.context["totale"], atteso, f"{vista} {filtri}")
                # Le tessere non cambiano con la vista: contano il registro filtrato.
                self.assertEqual(elenco.context["cruscotto"]["totale"], c["totale"])
            self.assertContains(r, "vista=senza_allegati#dp-elenco")

    def test_vista_sconosciuta_ignorata(self):
        qs = SegnalazionePreposto.objects.attive()
        self.assertEqual(filtra_vista(qs, "boh").count(), qs.count())
        r = self.client.get(reverse("diario_preposto:lista"), {"vista": "boh"})
        self.assertEqual(r.context["vista"], "")
