"""Visite «a richiesta»: nessuna scadenza, non sono un rinnovo.

Dati sintetici: id e nomi inventati, nessun dato reale.
"""
from datetime import timedelta

from django.urls import reverse

from core.models import AuditLog
from .models import VisitaMedica
from .services.visite import annota_storico, ultime_visite_correnti_ids
from .tests_visite_robustezza import _Base


class VisitaARichiestaTests(_Base):
    def _visita(self, giorni_fa, **extra):
        return VisitaMedica.objects.create(
            legacy_anagrafica_id=9101, tipo=self.tipo_altro,
            data_svolgimento=self.oggi - timedelta(days=giorni_fa), **extra,
        )

    def test_a_richiesta_non_ha_scadenza(self):
        v = self._visita(800, a_richiesta=True)
        self.assertIsNone(v.data_scadenza)
        self.assertFalse(v.is_scaduta)

    def test_non_prende_il_posto_della_periodica(self):
        periodica = self._visita(200)
        richiesta = self._visita(30, a_richiesta=True)
        correnti = ultime_visite_correnti_ids([9101])
        self.assertIn(periodica.pk, correnti)
        self.assertNotIn(richiesta.pk, correnti)
        storico = {v.pk: v for v in annota_storico(list(VisitaMedica.objects.filter(legacy_anagrafica_id=9101)))}
        self.assertIsNone(storico[periodica.pk].sostituita_da)
        self.assertIsNone(storico[richiesta.pk].sostituita_da)

    def test_sola_visita_a_richiesta_non_e_scaduta_in_dashboard(self):
        self._visita(800, a_richiesta=True)
        resp = self.client.get(reverse("anagrafica:visite_mediche_dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["kpi_scadute"], 0)

    def test_segna_in_blocco(self):
        a = self._visita(800)
        b = self._visita(400, scadenza_medico=self.oggi - timedelta(days=10))
        self.assertTrue(a.is_scaduta)
        resp = self.client.post(reverse("anagrafica:visite_mediche_segna_a_richiesta"),
                                {"visita_ids": [a.pk, b.pk]})
        self.assertEqual(resp.status_code, 302)
        for v in (a, b):
            v.refresh_from_db()
            self.assertTrue(v.a_richiesta)
            self.assertIsNone(v.data_scadenza)
            self.assertIsNone(v.scadenza_medico)
        self.assertEqual(AuditLog.objects.filter(azione="VISITA_MEDICA_A_RICHIESTA").count(), 2)

    def test_segna_in_blocco_senza_permesso(self):
        from django.contrib.auth import get_user_model

        a = self._visita(800)
        utente = get_user_model().objects.create_user(username="vr_base", password="x")
        self.client.force_login(utente)
        resp = self.client.post(reverse("anagrafica:visite_mediche_segna_a_richiesta"), {"visita_ids": [a.pk]})
        self.assertIn(resp.status_code, (302, 403))
        a.refresh_from_db()
        self.assertFalse(a.a_richiesta)

    def test_form_rifiuta_richiamo_con_a_richiesta(self):
        resp = self.client.post(
            reverse("anagrafica:dipendente_visita_add", args=[9101]),
            {"tipo": self.tipo_altro.pk, "data_svolgimento": (self.oggi - timedelta(days=3)).isoformat(),
             "esito": "IDONEO", "a_richiesta": "1",
             "scadenza_medico": (self.oggi + timedelta(days=300)).isoformat()},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(VisitaMedica.objects.filter(legacy_anagrafica_id=9101).exists())

    def test_form_registra_a_richiesta(self):
        self.client.post(
            reverse("anagrafica:dipendente_visita_add", args=[9101]),
            {"tipo": self.tipo_altro.pk, "data_svolgimento": (self.oggi - timedelta(days=3)).isoformat(),
             "esito": "IDONEO", "a_richiesta": "1"},
        )
        v = VisitaMedica.objects.get(legacy_anagrafica_id=9101)
        self.assertTrue(v.a_richiesta)
        self.assertIsNone(v.data_scadenza)
