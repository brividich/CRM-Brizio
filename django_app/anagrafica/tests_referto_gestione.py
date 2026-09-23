"""Regressioni per la scheda di gestione del singolo referto sanitario."""
import tempfile
from datetime import date

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import AuditLog

from .models import DocumentoDipendente, TipoVisitaMedica, VisitaMedica

_PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


class RefertoGestioneTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="referto_admin", email="referto_admin@example.test", password="test"
        )
        self.utente = get_user_model().objects.create_user(
            username="referto_utente", password="test"
        )
        tipo = TipoVisitaMedica.objects.create(nome="Visita sintetica", durata_mesi=12)
        self.visita = VisitaMedica.objects.create(
            legacy_anagrafica_id=91234, tipo=tipo, data_svolgimento=date(2024, 3, 4)
        )
        self.referto = DocumentoDipendente.objects.create(
            legacy_anagrafica_id=91234,
            tipo=DocumentoDipendente.Tipo.VISITA_MEDICA_REFERTO,
            file="referto-sintetico.pdf",
            nome_originale="referto-sintetico.pdf",
            oggetto_riferimento_tipo="anagrafica.visitamedica",
            oggetto_riferimento_id=self.visita.pk,
        )
        self.visita.referto_documento = self.referto
        self.visita.save(update_fields=["referto_documento"])
        self.url = reverse("anagrafica:referto_gestione", args=[self.referto.pk])

    # ── accesso ──────────────────────────────────────────────────────────────

    def test_senza_permesso_visite_niente_scheda(self):
        self.client.force_login(self.utente)
        response = self.client.get(self.url)
        # Il diniego arriva dal gate in-view (403) o dal middleware ACL (302 su
        # «accesso negato»): entrambi valgono, la scheda non deve rendersi.
        self.assertIn(response.status_code, (302, 403))

    def test_documento_non_referto_non_ha_scheda(self):
        manuale = DocumentoDipendente.objects.create(
            legacy_anagrafica_id=91234,
            tipo=DocumentoDipendente.Tipo.MANUALE,
            file="contratto.pdf",
        )
        self.client.force_login(self.admin)
        response = self.client.get(reverse("anagrafica:referto_gestione", args=[manuale.pk]))
        self.assertEqual(response.status_code, 404)

    def test_scheda_mostra_visita_e_ruolo(self):
        self.client.force_login(self.admin)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Referto principale")
        self.assertContains(response, "Visita sintetica")
        self.assertContains(response, reverse("anagrafica:documento_download", args=[self.referto.pk]))

    def test_scheda_visita_linka_la_gestione_del_referto(self):
        self.client.force_login(self.admin)
        response = self.client.get(
            reverse("anagrafica:visita_medica_dettaglio", args=[self.visita.pk])
        )
        self.assertContains(response, self.url)

    # ── metadati ─────────────────────────────────────────────────────────────

    def test_metadati_aggiornati_con_audit_prima_dopo(self):
        self.client.force_login(self.admin)
        response = self.client.post(self.url, {
            "azione": "metadati",
            "nome_originale": "referto-oculistico-2024.pdf",
            "descrizione": "Referto oculistico marzo 2024",
            "retention_until": "2035-03-04",
            "motivo": "Nome file corretto",
        })
        self.assertRedirects(response, self.url)
        self.referto.refresh_from_db()
        self.assertEqual(self.referto.nome_originale, "referto-oculistico-2024.pdf")
        self.assertEqual(self.referto.descrizione, "Referto oculistico marzo 2024")
        self.assertEqual(self.referto.retention_until, date(2035, 3, 4))
        audit = AuditLog.objects.get(azione="REFERTO_MODIFICATO")
        self.assertEqual(audit.oggetto_id, str(self.referto.pk))
        self.assertEqual(audit.dettaglio["prima"]["nome_originale"], "referto-sintetico.pdf")
        self.assertEqual(audit.dettaglio["dopo"]["nome_originale"], "referto-oculistico-2024.pdf")
        self.assertEqual(audit.dettaglio["visita_id"], self.visita.pk)

    def test_nome_file_vuoto_rifiutato(self):
        self.client.force_login(self.admin)
        response = self.client.post(self.url, {"azione": "metadati", "nome_originale": "  "})
        self.assertEqual(response.status_code, 200)
        self.referto.refresh_from_db()
        self.assertEqual(self.referto.nome_originale, "referto-sintetico.pdf")
        self.assertFalse(AuditLog.objects.filter(azione="REFERTO_MODIFICATO").exists())

    # ── sostituzione file ────────────────────────────────────────────────────

    def test_sostituzione_file_aggiorna_record_e_audit(self):
        self.client.force_login(self.admin)
        with tempfile.TemporaryDirectory() as radice:
            with override_settings(ANAGRAFICA_PRIVATE_ROOT=radice):
                response = self.client.post(self.url, {
                    "azione": "sostituisci",
                    "motivo": "Scansione illeggibile",
                    "file": SimpleUploadedFile("nuovo-referto.pdf", _PDF, content_type="application/pdf"),
                })
                self.assertRedirects(response, self.url)
                self.referto.refresh_from_db()
                self.assertEqual(self.referto.nome_originale, "nuovo-referto.pdf")
                self.assertEqual(self.referto.dimensione_bytes, len(_PDF))
                self.assertNotEqual(self.referto.file.name, "referto-sintetico.pdf")
        audit = AuditLog.objects.get(azione="REFERTO_SOSTITUITO")
        self.assertEqual(audit.dettaglio["prima"]["nome_originale"], "referto-sintetico.pdf")
        self.assertEqual(audit.dettaglio["dopo"]["nome_originale"], "nuovo-referto.pdf")
        self.assertEqual(audit.dettaglio["motivo"], "Scansione illeggibile")

    def test_sostituzione_formato_non_ammesso_rifiutata(self):
        self.client.force_login(self.admin)
        response = self.client.post(self.url, {
            "azione": "sostituisci",
            "file": SimpleUploadedFile("referto.exe", b"MZ", content_type="application/octet-stream"),
        })
        self.assertEqual(response.status_code, 200)
        self.referto.refresh_from_db()
        self.assertEqual(self.referto.file.name, "referto-sintetico.pdf")
        self.assertFalse(AuditLog.objects.filter(azione="REFERTO_SOSTITUITO").exists())

    # ── aggancio alla visita ─────────────────────────────────────────────────

    def test_imposta_come_secondario_sposta_la_fk(self):
        self.client.force_login(self.admin)
        response = self.client.post(self.url, {"azione": "secondario"})
        self.assertRedirects(response, self.url)
        self.visita.refresh_from_db()
        self.assertIsNone(self.visita.referto_documento_id)
        self.assertEqual(self.visita.referto_documento_secondario_id, self.referto.pk)
        self.assertEqual(
            AuditLog.objects.get(azione="REFERTO_RUOLO_CAMBIATO").dettaglio["ruolo"], "secondario"
        )

    def test_scollega_richiede_motivo(self):
        self.client.force_login(self.admin)
        response = self.client.post(self.url, {"azione": "scollega", "motivo": " "})
        self.assertEqual(response.status_code, 200)
        self.visita.refresh_from_db()
        self.assertEqual(self.visita.referto_documento_id, self.referto.pk)
        self.assertFalse(AuditLog.objects.filter(azione="REFERTO_SCOLLEGATO").exists())

    def test_scollega_conserva_il_documento_senza_visita(self):
        self.client.force_login(self.admin)
        response = self.client.post(self.url, {
            "azione": "scollega", "motivo": "Attribuito alla visita sbagliata",
        })
        self.assertRedirects(response, self.url)
        self.visita.refresh_from_db()
        self.referto.refresh_from_db()
        self.assertIsNone(self.visita.referto_documento_id)
        self.assertEqual(self.referto.oggetto_riferimento_tipo, "")
        self.assertIsNone(self.referto.oggetto_riferimento_id)
        self.assertTrue(DocumentoDipendente.objects.filter(pk=self.referto.pk).exists())
        audit = AuditLog.objects.get(azione="REFERTO_SCOLLEGATO")
        self.assertEqual(audit.dettaglio["visita_id"], self.visita.pk)

    # ── eliminazione ─────────────────────────────────────────────────────────

    def test_eliminazione_richiede_motivo(self):
        self.client.force_login(self.admin)
        response = self.client.post(self.url, {"azione": "elimina", "motivo": ""})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(DocumentoDipendente.objects.filter(pk=self.referto.pk).exists())
        self.assertFalse(AuditLog.objects.filter(azione="REFERTO_ELIMINATO").exists())

    def test_eliminazione_registra_motivo_e_libera_la_visita(self):
        referto_pk = self.referto.pk
        self.client.force_login(self.admin)
        response = self.client.post(self.url, {
            "azione": "elimina", "motivo": "Referto caricato sul dipendente sbagliato",
        })
        self.assertRedirects(
            response, reverse("anagrafica:visita_medica_dettaglio", args=[self.visita.pk])
        )
        self.assertFalse(DocumentoDipendente.objects.filter(pk=referto_pk).exists())
        self.visita.refresh_from_db()
        self.assertIsNone(self.visita.referto_documento_id)
        self.assertTrue(VisitaMedica.objects.filter(pk=self.visita.pk).exists())
        audit = AuditLog.objects.get(azione="REFERTO_ELIMINATO")
        self.assertEqual(audit.dettaglio["motivo"], "Referto caricato sul dipendente sbagliato")
        self.assertEqual(audit.dettaglio["visita_id"], self.visita.pk)
        self.assertEqual(audit.oggetto_id, str(referto_pk))

    def test_utente_senza_grant_non_elimina(self):
        self.client.force_login(self.utente)
        response = self.client.post(self.url, {"azione": "elimina", "motivo": "Prova"})
        self.assertIn(response.status_code, (302, 403))
        self.assertTrue(DocumentoDipendente.objects.filter(pk=self.referto.pk).exists())

    # ── accessi ──────────────────────────────────────────────────────────────

    def test_download_del_referto_aggancia_audit_al_record(self):
        self.client.force_login(self.admin)
        self.client.get(reverse("anagrafica:documento_download", args=[self.referto.pk]))
        audit = AuditLog.objects.get(azione="DOCUMENTO_DIPENDENTE_DOWNLOAD")
        self.assertEqual(audit.oggetto_tipo, DocumentoDipendente._meta.label_lower)
        self.assertEqual(audit.oggetto_id, str(self.referto.pk))

    def test_scheda_elenca_accessi_nuovi_e_storici(self):
        AuditLog.objects.create(
            azione="DOCUMENTO_DIPENDENTE_DOWNLOAD", modulo="anagrafica",
            utente_display="Chi Legge Nuovo",
            oggetto_tipo=DocumentoDipendente._meta.label_lower,
            oggetto_id=str(self.referto.pk),
        )
        AuditLog.objects.create(
            azione="DOCUMENTO_DIPENDENTE_DOWNLOAD", modulo="anagrafica",
            utente_display="Chi Legge Storico",
            dettaglio={"dettaglio": f"Download documento #{self.referto.pk} (VISITA_MEDICA_REFERTO) di dipendente #91234"},
        )
        self.client.force_login(self.admin)
        response = self.client.get(self.url)
        self.assertContains(response, "Chi Legge Nuovo")
        self.assertContains(response, "Chi Legge Storico")
        self.assertEqual(response.context["accessi_count"], 2)
