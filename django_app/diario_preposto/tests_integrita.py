"""Integrità del Diario preposto: eliminazione con motivo, ripristino, impronta
degli allegati, validazione «tutto o niente», modifiche concorrenti, storico."""
from __future__ import annotations

import shutil
import tempfile
from datetime import datetime, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import AuditLog, ChecklistEsecuzione, UserOnboarding

from .forms import SegnalazioneForm
from .models import SegnalazioneAllegato, SegnalazionePreposto, impronta_file


def _dt(year, month, day, hour=9):
    return timezone.make_aware(datetime(year, month, day, hour, 0), timezone.get_current_timezone())


def _valid_mime(*_args, **_kwargs):
    return "text/plain"


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class DiarioIntegritaTests(TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="dp-integrita-")
        self._override = override_settings(DIARIO_PREPOSTO_PRIVATE_ROOT=self._tmp)
        self._override.enable()
        User = get_user_model()
        self.admin = User.objects.create_superuser(username="dp-gestore", email="g@example.com", password="x")
        self.utente = User.objects.create_user(username="dp-preposto", email="p@example.com", password="x")
        for u in (self.admin, self.utente):
            UserOnboarding.objects.create(user=u, completed=True, completed_at=timezone.now())
        self.segnalazione = SegnalazionePreposto.objects.create(
            titolo="Carrello senza cintura",
            data_segnalazione=_dt(2026, 10, 1),
            descrizione="Reparto 2",
            creato_da=self.utente,
        )

    def tearDown(self):
        self._override.disable()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _allegato(self, contenuto=b"prova originale", nome="prova.txt"):
        sha, size = impronta_file(SimpleUploadedFile(nome, contenuto))
        return SegnalazioneAllegato.objects.create(
            segnalazione=self.segnalazione, nome_file=nome,
            file=SimpleUploadedFile(nome, contenuto, content_type="text/plain"),
            sha256=sha, dimensione=size,
        )

    # ── Eliminazione / ripristino ─────────────────────────────────────────
    def test_elimina_senza_motivo_non_elimina(self):
        self.client.force_login(self.utente)
        resp = self.client.post(reverse("diario_preposto:elimina", args=[self.segnalazione.pk]), {"motivo": ""})
        self.assertRedirects(resp, reverse("diario_preposto:dettaglio", args=[self.segnalazione.pk]),
                             fetch_redirect_response=False)
        self.segnalazione.refresh_from_db()
        self.assertFalse(self.segnalazione.is_eliminata)

    def test_elimina_archivia_record_e_allegati(self):
        allegato = self._allegato()
        self.client.force_login(self.utente)
        self.client.post(reverse("diario_preposto:elimina", args=[self.segnalazione.pk]),
                         {"motivo": "Inserita due volte"})
        self.segnalazione.refresh_from_db()
        self.assertTrue(self.segnalazione.is_eliminata)
        self.assertEqual(self.segnalazione.motivo_eliminazione, "Inserita due volte")
        self.assertEqual(self.segnalazione.eliminata_da, self.utente)
        self.assertTrue(SegnalazioneAllegato.objects.filter(pk=allegato.pk).exists())
        self.assertTrue(allegato.file.storage.exists(allegato.file.name))
        # Fuori dal registro e, per chi non gestisce il modulo, non esiste piu'.
        lista = self.client.get(reverse("diario_preposto:lista"))
        self.assertNotContains(lista, "Carrello senza cintura")
        self.assertEqual(self.client.get(reverse("diario_preposto:dettaglio", args=[self.segnalazione.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("diario_preposto:modifica", args=[self.segnalazione.pk])).status_code, 404)
        self.assertEqual(
            self.client.get(reverse("diario_preposto:allegato_download", args=[allegato.pk])).status_code, 404)

    def test_codice_non_riusato_dopo_eliminazione(self):
        codice = self.segnalazione.codice_identificativo
        self.segnalazione.eliminata_il = timezone.now()
        self.segnalazione.save()
        nuova = SegnalazionePreposto.objects.create(titolo="Altra", data_segnalazione=_dt(2026, 10, 2), descrizione="x")
        self.assertNotEqual(nuova.codice_identificativo, codice)

    def test_gestore_vede_eliminate_e_ripristina(self):
        self.segnalazione.eliminata_il = timezone.now()
        self.segnalazione.motivo_eliminazione = "Errore"
        self.segnalazione.save()
        self.client.force_login(self.admin)
        lista = self.client.get(reverse("diario_preposto:lista") + "?eliminate=1")
        self.assertContains(lista, "Carrello senza cintura")
        det = self.client.get(reverse("diario_preposto:dettaglio", args=[self.segnalazione.pk]))
        self.assertContains(det, "Segnalazione eliminata")
        self.assertContains(det, "Ripristina")
        self.client.post(reverse("diario_preposto:ripristina", args=[self.segnalazione.pk]))
        self.segnalazione.refresh_from_db()
        self.assertFalse(self.segnalazione.is_eliminata)
        self.assertEqual(self.segnalazione.motivo_eliminazione, "")

    def test_ripristina_negato_a_chi_non_gestisce(self):
        self.segnalazione.eliminata_il = timezone.now()
        self.segnalazione.save()
        self.client.force_login(self.utente)
        resp = self.client.post(reverse("diario_preposto:ripristina", args=[self.segnalazione.pk]))
        self.assertEqual(resp.status_code, 403)
        self.segnalazione.refresh_from_db()
        self.assertTrue(self.segnalazione.is_eliminata)

    def test_lista_utente_normale_ignora_filtro_eliminate(self):
        self.segnalazione.eliminata_il = timezone.now()
        self.segnalazione.save()
        self.client.force_login(self.utente)
        lista = self.client.get(reverse("diario_preposto:lista") + "?eliminate=1")
        self.assertNotContains(lista, "Carrello senza cintura")

    def test_export_excel_esclude_eliminate(self):
        from io import BytesIO

        from openpyxl import load_workbook

        SegnalazionePreposto.objects.create(titolo="Visibile", data_segnalazione=_dt(2026, 10, 3), descrizione="y")
        self.segnalazione.eliminata_il = timezone.now()
        self.segnalazione.save()
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("diario_preposto:export_excel"))
        ws = load_workbook(BytesIO(resp.content)).active
        titoli = [ws.cell(row=r, column=3).value for r in range(2, ws.max_row + 1)]
        self.assertEqual(titoli, ["Visibile"])

    # ── Allegati: impronta e rimozione ────────────────────────────────────
    @patch("diario_preposto.views.validate_extension_and_mime", side_effect=_valid_mime)
    def test_upload_registra_impronta_e_autore(self, _m):
        self.client.force_login(self.utente)
        resp = self.client.post(reverse("diario_preposto:api_allegato_upload"), {
            "segnalazione_id": self.segnalazione.pk,
            "file": SimpleUploadedFile("nota.txt", b"ciao", content_type="text/plain"),
        })
        self.assertEqual(resp.status_code, 200)
        allegato = SegnalazioneAllegato.objects.get()
        import hashlib
        self.assertEqual(allegato.sha256, hashlib.sha256(b"ciao").hexdigest())
        self.assertEqual(allegato.dimensione, 4)
        self.assertEqual(allegato.caricato_da, self.utente)
        self.assertTrue(AuditLog.objects.filter(
            azione="allegato_aggiunto", oggetto_id=str(self.segnalazione.pk)).exists())

    @patch("diario_preposto.views.validate_extension_and_mime", side_effect=_valid_mime)
    def test_upload_su_segnalazione_eliminata_rifiutato(self, _m):
        self.segnalazione.eliminata_il = timezone.now()
        self.segnalazione.save()
        self.client.force_login(self.admin)
        resp = self.client.post(reverse("diario_preposto:api_allegato_upload"), {
            "segnalazione_id": self.segnalazione.pk,
            "file": SimpleUploadedFile("nota.txt", b"ciao", content_type="text/plain"),
        })
        self.assertEqual(resp.status_code, 404)
        self.assertFalse(SegnalazioneAllegato.objects.exists())

    def test_download_verifica_impronta(self):
        allegato = self._allegato()
        self.client.force_login(self.admin)
        url = reverse("diario_preposto:allegato_download", args=[allegato.pk])
        ok = self.client.get(url)
        self.assertEqual(ok.status_code, 200)
        # Niente ok.close(): emetterebbe request_finished e chiuderebbe la connessione del test.
        self.assertEqual(b"".join(ok.streaming_content), b"prova originale")
        for closable in ok._resource_closers:
            closable()
        # File alterato sul disco: il download viene bloccato e tracciato.
        SegnalazioneAllegato.objects.filter(pk=allegato.pk).update(sha256="0" * 64)
        ko = self.client.get(url)
        self.assertEqual(ko.status_code, 409)
        self.assertTrue(AuditLog.objects.filter(
            azione="download_allegato", dettaglio__esito="integrita_ko").exists())

    def test_rimozione_allegato_archivia_file(self):
        allegato = self._allegato()
        self.client.force_login(self.utente)
        resp = self.client.post(reverse("diario_preposto:api_allegato_delete"), {"allegato_id": allegato.pk})
        self.assertEqual(resp.json(), {"ok": True})
        allegato.refresh_from_db()
        self.assertIsNotNone(allegato.rimosso_il)
        self.assertEqual(allegato.rimosso_da, self.utente)
        self.assertTrue(allegato.file.storage.exists(allegato.file.name))
        self.assertEqual(list(self.segnalazione.allegati_attivi()), [])
        # Seconda rimozione: non trovato, nessun effetto.
        resp2 = self.client.post(reverse("diario_preposto:api_allegato_delete"), {"allegato_id": allegato.pk})
        self.assertEqual(resp2.status_code, 404)
        # Archiviato: lo scarica solo chi gestisce il modulo.
        url = reverse("diario_preposto:allegato_download", args=[allegato.pk])
        self.assertEqual(self.client.get(url).status_code, 404)

    # ── Validazione «tutto o niente» e date ───────────────────────────────
    def test_nuovo_con_file_non_valido_non_salva_nulla(self):
        self.client.force_login(self.utente)
        prima = SegnalazionePreposto.objects.count()
        resp = self.client.post(reverse("diario_preposto:nuovo"), {
            "data_segnalazione": "2026-10-05T10:00",
            "titolo": "Con file sbagliato",
            "descrizione": "x",
            "allegati": [SimpleUploadedFile("virus.exe", b"MZ", content_type="application/octet-stream")],
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Nessun dato salvato")
        self.assertEqual(SegnalazionePreposto.objects.count(), prima)
        self.assertFalse(SegnalazioneAllegato.objects.exists())

    def test_data_nel_futuro_rifiutata(self):
        futuro = timezone.localtime(timezone.now() + timedelta(days=2)).strftime("%Y-%m-%dT%H:%M")
        form = SegnalazioneForm(data={"data_segnalazione": futuro, "titolo": "T", "descrizione": "D"})
        self.assertFalse(form.is_valid())
        self.assertIn("data_segnalazione", form.errors)

    def test_titolo_solo_spazi_rifiutato(self):
        form = SegnalazioneForm(data={"data_segnalazione": "2026-10-05T10:00", "titolo": "   ", "descrizione": "D"})
        self.assertFalse(form.is_valid())
        self.assertIn("titolo", form.errors)

    # ── Modifiche concorrenti ─────────────────────────────────────────────
    def test_modifica_concorrente_rifiutata(self):
        self.client.force_login(self.utente)
        url = reverse("diario_preposto:modifica", args=[self.segnalazione.pk])
        versione_letta = self.segnalazione.updated_at.isoformat()
        # Un collega salva nel frattempo.
        SegnalazionePreposto.objects.filter(pk=self.segnalazione.pk).update(
            descrizione="Versione del collega", updated_at=timezone.now() + timedelta(seconds=5))
        resp = self.client.post(url, {
            "data_segnalazione": "2026-10-01T09:00", "titolo": "Mia versione",
            "descrizione": "La mia", "versione": versione_letta,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "qualcun altro ha modificato")
        self.segnalazione.refresh_from_db()
        self.assertEqual(self.segnalazione.descrizione, "Versione del collega")

    def test_modifica_con_versione_corrente_salva_e_compare_nello_storico(self):
        self.client.force_login(self.utente)
        url = reverse("diario_preposto:modifica", args=[self.segnalazione.pk])
        form_page = self.client.get(url)
        versione = form_page.context["form"].initial["versione"]
        resp = self.client.post(url, {
            "data_segnalazione": "2026-10-01T09:00", "titolo": "Titolo corretto",
            "descrizione": "Reparto 2", "versione": versione,
        })
        self.assertRedirects(resp, reverse("diario_preposto:dettaglio", args=[self.segnalazione.pk]),
                             fetch_redirect_response=False)
        self.segnalazione.refresh_from_db()
        self.assertEqual(self.segnalazione.titolo, "Titolo corretto")
        det = self.client.get(reverse("diario_preposto:dettaglio", args=[self.segnalazione.pk]))
        self.assertContains(det, "Storia della segnalazione")
        self.assertContains(det, "Modificata: titolo")

    # ── Ispezioni ─────────────────────────────────────────────────────────
    def test_ispezione_senza_utente_legacy_non_usa_id_django(self):
        self.client.force_login(self.utente)
        self.client.get(reverse("diario_preposto:ispezioni"))
        resp = self.client.post(reverse("diario_preposto:ispezione_nuova"), {"area": "CNC"})
        self.assertRedirects(resp, reverse("diario_preposto:ispezioni"), fetch_redirect_response=False)
        esecuzione = ChecklistEsecuzione.objects.get(tipo_checklist="preposto_ispezione")
        self.assertEqual(esecuzione.legacy_user_id, 0)
        self.assertEqual(esecuzione.eseguita_da_id, 0)

    def test_guida_pagina_e_pdf(self):
        self.client.force_login(self.utente)
        self.assertContains(self.client.get(reverse("diario_preposto:guida")), "Eliminare e ripristinare")
        pdf = self.client.get(reverse("diario_preposto:guida") + "?formato=pdf")
        self.assertEqual(pdf["Content-Type"], "application/pdf")
