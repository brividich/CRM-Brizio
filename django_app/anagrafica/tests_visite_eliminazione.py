"""Regressioni per la rimozione motivata delle visite errate."""
from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import AuditLog
from .models import DocumentoDipendente, TipoVisitaMedica, VisitaMedica


class VisitaMedicaEliminazioneTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="visite_admin", email="visite_admin@example.test", password="test"
        )
        self.utente = get_user_model().objects.create_user(
            username="visite_utente", password="test"
        )
        tipo = TipoVisitaMedica.objects.create(nome="Visita sintetica", durata_mesi=12)
        self.visita = VisitaMedica.objects.create(
            legacy_anagrafica_id=81234, tipo=tipo, data_svolgimento=date(2020, 1, 10)
        )
        self.url = reverse("anagrafica:visita_medica_elimina", args=[self.visita.pk])

    def test_senza_permesso_non_elimina(self):
        self.client.force_login(self.utente)
        self.client.post(self.url, {"motivo": "Import errato"})
        self.assertTrue(VisitaMedica.objects.filter(pk=self.visita.pk).exists())
        self.assertFalse(AuditLog.objects.filter(azione="VISITA_MEDICA_ELIMINATA").exists())

    def test_motivo_obbligatorio(self):
        self.client.force_login(self.admin)
        response = self.client.post(self.url, {"motivo": "   "})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(VisitaMedica.objects.filter(pk=self.visita.pk).exists())
        self.assertFalse(AuditLog.objects.filter(azione="VISITA_MEDICA_ELIMINATA").exists())

    def test_dashboard_mostra_azione_all_utente_abilitato(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("anagrafica:visite_mediche_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.url)

    def test_eliminazione_registra_motivo_e_identificativi(self):
        self.client.force_login(self.admin)
        response = self.client.post(self.url, {"motivo": "Riga del file importata per errore"})
        self.assertRedirects(response, reverse("anagrafica:visite_mediche_dashboard"))
        self.assertFalse(VisitaMedica.objects.filter(pk=self.visita.pk).exists())
        audit = AuditLog.objects.get(azione="VISITA_MEDICA_ELIMINATA")
        self.assertEqual(audit.dettaglio["motivo"], "Riga del file importata per errore")
        self.assertEqual(audit.dettaglio["visita_id"], self.visita.pk)
        self.assertEqual(audit.oggetto_id, str(self.visita.pk))

    def test_referto_collegato_resta_nel_fascicolo_senza_riferimento_alla_visita(self):
        referto = DocumentoDipendente.objects.create(
            legacy_anagrafica_id=self.visita.legacy_anagrafica_id,
            tipo=DocumentoDipendente.Tipo.VISITA_MEDICA_REFERTO,
            file="referto-sintetico.pdf",
            oggetto_riferimento_tipo="anagrafica.visitamedica",
            oggetto_riferimento_id=self.visita.pk,
        )
        self.visita.referto_documento = referto
        self.visita.save(update_fields=["referto_documento"])
        self.client.force_login(self.admin)
        confirm = self.client.get(self.url)
        self.assertContains(confirm, "1 referto")
        response = self.client.post(self.url, {"motivo": "Import errato"})
        self.assertRedirects(response, reverse("anagrafica:visite_mediche_dashboard"))
        self.assertFalse(VisitaMedica.objects.filter(pk=self.visita.pk).exists())
        referto.refresh_from_db()
        self.assertEqual(referto.oggetto_riferimento_tipo, "")
        self.assertIsNone(referto.oggetto_riferimento_id)
        self.assertEqual(referto.legacy_anagrafica_id, 81234)
        self.assertEqual(
            AuditLog.objects.get(azione="VISITA_MEDICA_ELIMINATA").dettaglio["referti_conservati_ids"],
            [referto.pk],
        )

    def test_due_referti_fk_senza_riferimento_generico_restano(self):
        referti = [DocumentoDipendente.objects.create(
            legacy_anagrafica_id=81234,
            tipo=DocumentoDipendente.Tipo.VISITA_MEDICA_REFERTO,
            file=f"referto-sintetico-{indice}.pdf",
        ) for indice in (1, 2)]
        self.visita.referto_documento, self.visita.referto_documento_secondario = referti
        self.visita.save(update_fields=["referto_documento", "referto_documento_secondario"])
        self.client.force_login(self.admin)
        self.client.post(self.url, {"motivo": "Import errato"})
        self.assertFalse(VisitaMedica.objects.filter(pk=self.visita.pk).exists())
        self.assertEqual(DocumentoDipendente.objects.filter(pk__in=[d.pk for d in referti]).count(), 2)
        self.assertEqual(
            AuditLog.objects.get(azione="VISITA_MEDICA_ELIMINATA").dettaglio["referti_conservati_ids"],
            sorted(d.pk for d in referti),
        )

    def test_audit_non_scrivibile_impedisce_eliminazione(self):
        referto = DocumentoDipendente.objects.create(
            legacy_anagrafica_id=81234,
            tipo=DocumentoDipendente.Tipo.VISITA_MEDICA_REFERTO,
            file="referto-sintetico.pdf",
            oggetto_riferimento_tipo="anagrafica.visitamedica",
            oggetto_riferimento_id=self.visita.pk,
        )
        self.client.force_login(self.admin)
        with patch("core.models.AuditLog.objects.create", side_effect=RuntimeError("audit non disponibile")):
            self.client.post(self.url, {"motivo": "Import errato"})
        self.assertTrue(VisitaMedica.objects.filter(pk=self.visita.pk).exists())
        referto.refresh_from_db()
        self.assertEqual(referto.oggetto_riferimento_id, self.visita.pk)

    def test_vecchio_endpoint_non_cancella_senza_motivo(self):
        self.client.force_login(self.admin)
        url = reverse("anagrafica:dipendente_visita_delete", args=[81234, self.visita.pk])
        response = self.client.post(url)
        self.assertRedirects(response, self.url)
        self.assertTrue(VisitaMedica.objects.filter(pk=self.visita.pk).exists())
