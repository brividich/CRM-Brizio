"""Test timeline 'umanizzata': nasconde auto_approvazione, mostra data_approvazione."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from gestione_specifiche import constants as C
from gestione_specifiche.models import AutoApprovazioneConfig, MOD133, Specifica
from gestione_specifiche.timeline import eventi_umanizzati

User = get_user_model()


class TimelineUmanizzataTest(TestCase):
    def setUp(self):
        self.su = User.objects.create_superuser("tl_su", "s@x.it", "x")
        self.mso = User.objects.create_user("tl_mso", "m@x.it", "x", first_name="Mario", last_name="MSO")
        self.client.force_login(self.su)
        cfg = AutoApprovazioneConfig.get_config()
        cfg.attiva = True
        cfg.approvatore = self.mso
        cfg.save()
        self.spec = Specifica.objects.create(codice="TL-1", titolo="T")
        self.spec.avvia_flow_down(attore=self.su)
        self.spec.save()
        self.client.post(reverse("gestione_specifiche:mod133_chiudi", args=[self.spec.pk]), {"vai": "approva"})
        self.mod = MOD133.objects.get(specifica=self.spec)

    def test_helper_esclude_auto_e_annota_ts_display(self):
        eventi = eventi_umanizzati(self.spec, self.mod)
        trigger = [e.trigger for e in eventi]
        self.assertNotIn("auto_approvazione", trigger)
        appr = next(e for e in eventi if e.trigger == "approva_flow_down")
        # la riga di approvazione mostra la data fittizia (documento), non il timestamp reale
        self.assertEqual(appr.ts_display, self.mod.data_approvazione)
        self.assertNotEqual(appr.ts_display, appr.timestamp)

    def test_dettaglio_non_espone_auto_approvazione(self):
        r = self.client.get(reverse("gestione_specifiche:dettaglio", args=[self.spec.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "auto_approvazione")

    def test_scheda_storico_non_espone_auto_approvazione(self):
        r = self.client.get(reverse("gestione_specifiche:scheda_storico", args=[self.spec.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, "auto_approvazione")

    def test_dettaglio_mostra_approvato_il(self):
        r = self.client.get(reverse("gestione_specifiche:dettaglio", args=[self.spec.pk]))
        self.assertContains(r, "Approvato il")
