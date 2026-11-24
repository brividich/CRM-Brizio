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

    def _giornata(self, dati):
        return self.client.post(reverse("anagrafica:visite_mediche_nuova_sessione"),
                                {"azione": "a_richiesta", "tipo": str(self.tipo_altro.pk), **dati})

    def test_giornata_segna_ultima_visita_senza_crearne(self):
        vecchia = self._visita(1200)
        ultima = self._visita(400, scadenza_medico=self.oggi - timedelta(days=10))
        self.assertTrue(ultima.is_scaduta)
        resp = self._giornata({f"sel_9101_{self.tipo_altro.pk}": "1", "sel_9102_%d" % self.tipo_altro.pk: "1"})
        self.assertRedirects(resp, reverse("anagrafica:visite_mediche_nuova_sessione") + f"?tipo={self.tipo_altro.pk}",
                             fetch_redirect_response=False)
        self.assertEqual(VisitaMedica.objects.count(), 2)  # nessuna visita nuova, nessuna sessione
        ultima.refresh_from_db()
        vecchia.refresh_from_db()
        self.assertTrue(ultima.a_richiesta)
        self.assertIsNone(ultima.data_scadenza)
        self.assertIsNone(ultima.scadenza_medico)
        self.assertFalse(vecchia.a_richiesta)
        self.assertEqual(AuditLog.objects.filter(azione="VISITA_MEDICA_A_RICHIESTA").count(), 1)

    def test_giornata_senza_data_valida_non_registra(self):
        self._visita(800)
        resp = self._giornata({f"sel_9101_{self.tipo_altro.pk}": "1", "data_svolgimento": ""})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(VisitaMedica.objects.filter(a_richiesta=True).count(), 1)

    def test_giornata_senza_permesso(self):
        from django.contrib.auth import get_user_model

        a = self._visita(800)
        self.client.force_login(get_user_model().objects.create_user(username="vr_base", password="x"))
        self._giornata({f"sel_9101_{self.tipo_altro.pk}": "1"})
        a.refresh_from_db()
        self.assertFalse(a.a_richiesta)

    def test_pagina_giornata_mostra_il_pulsante(self):
        self._visita(800)
        resp = self.client.get(reverse("anagrafica:visite_mediche_nuova_sessione") + f"?tipo={self.tipo_altro.pk}")
        self.assertContains(resp, 'value="a_richiesta"')
        self.assertContains(resp, "Segna come a richiesta")

    def test_dashboard_senza_caselle(self):
        self._visita(800)
        resp = self.client.get(reverse("anagrafica:visite_mediche_dashboard"))
        self.assertNotContains(resp, "Segna come a richiesta")

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
