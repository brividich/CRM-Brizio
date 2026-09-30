"""Allegati ticket dal campo: QR pubblico dell'asset, pagina web e validazione MAN.

Coperti qui:
  * dal QR pubblico (senza login) si allegano foto/PDF SOLO ai ticket aperti
    dell'asset di quel token: ticket di altre macchine o chiusi sono rifiutati;
  * ogni file caricato da chi non gestisce il ticket nasce DA_VALIDARE, con
    traccia nel ticket, audit e notifica in-app al team gestore;
  * solo il gestore del tipo valida/rifiuta (rifiuto sempre motivato);
  * honeypot, tetto anti-abuso e interruttore di emergenza del QR pubblico;
  * la landing pubblica mostra i ticket aperti senza dati del richiedente.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from assets.models import Asset
from core.models import AuditLog, Notifica, UserOnboarding
from core.upload_mime import UploadMimeValidationError

from .models import (
    OrigineAllegato,
    PrioritaTicket,
    StatoTicket,
    StatoValidazioneAllegato,
    Ticket,
    TicketAllegato,
    TicketCommento,
    TicketImpostazioni,
    TipoTicket,
)

User = get_user_model()

_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _complete_onboarding(user) -> None:
    UserOnboarding.objects.update_or_create(
        user=user,
        defaults={"completed": True, "skipped": False, "completed_at": timezone.now()},
    )


def _png(name: str = "rapportino.png") -> SimpleUploadedFile:
    return SimpleUploadedFile(name, _PNG, content_type="image/png")


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class _Base(TestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        root = Path.cwd() / "django_app" / ".tmp_tests"
        root.mkdir(parents=True, exist_ok=True)
        self.private_root = root / f"tickets-allegati-{uuid4().hex}"
        self.private_root.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.private_root, ignore_errors=True)
        override = override_settings(TICKETS_PRIVATE_ROOT=self.private_root, MEDIA_ROOT=self.private_root)
        override.enable()
        self.addCleanup(override.disable)
        mime = patch("tickets.allegati.validate_extension_and_mime", return_value="image/png")
        mime.start()
        self.addCleanup(mime.stop)

        self.asset = Asset.objects.create(asset_tag="AST-QR-TKT-1", name="Tornio QR")
        self.other_asset = Asset.objects.create(asset_tag="AST-QR-TKT-2", name="Fresa QR")
        self.ticket = self._ticket(self.asset, titolo="Perdita olio mandrino")
        self.other_ticket = self._ticket(self.other_asset, titolo="Rumore fresa")

        self.gestore = User.objects.create_user(username="man-gestore", password="x", email="man.gestore@example.com")
        self.operatore = User.objects.create_user(username="operatore", password="x", email="operatore@example.com")
        for u in (self.gestore, self.operatore):
            _complete_onboarding(u)
        TicketImpostazioni.objects.update_or_create(
            tipo=TipoTicket.MAN,
            defaults={
                "acl_gestione": [self.gestore.username],
                "team_gestori": [{"nome": "Gestore MAN", "email": self.gestore.email}],
            },
        )

    def _ticket(self, asset, *, titolo: str, stato: str = StatoTicket.APERTA) -> Ticket:
        return Ticket.objects.create(
            tipo=TipoTicket.MAN,
            titolo=titolo,
            descrizione="Descrizione sintetica",
            categoria="MACCHINARIO",
            priorita=PrioritaTicket.MEDIA,
            stato=stato,
            asset=asset,
            richiedente_nome="Richiedente Sintetico",
            richiedente_email="richiedente@example.com",
        )

    def _qr_upload_url(self, ticket, token=None) -> str:
        return reverse(
            "assets:asset_qr_ticket_upload",
            kwargs={"public_qr_token": token or self.asset.public_qr_token, "ticket_id": ticket.pk},
        )

    def _qr_post(self, ticket, **extra):
        data = {"nome": "Mario Tecnico", "ditta": "Ditta Esterna Srl", "tipo_documento": "RAPPORTINO", "file": _png()}
        data.update(extra)
        return self.client.post(self._qr_upload_url(ticket), data)


class QrPubblicoUploadTests(_Base):
    def test_anonimo_allega_rapportino_al_ticket_aperto_della_macchina(self):
        with patch("core.notifiche.legacy_user_ids_for_email", return_value=[4242]):
            response = self._qr_post(self.ticket, descrizione="Sostituita guarnizione")

        self.assertEqual(response.status_code, 302)
        self.assertIn(self.asset.public_qr_token, response["Location"])
        allegato = TicketAllegato.objects.get(ticket=self.ticket)
        self.assertEqual(allegato.stato_validazione, StatoValidazioneAllegato.DA_VALIDARE)
        self.assertEqual(allegato.origine, OrigineAllegato.QR)
        self.assertEqual(allegato.uploaded_by_nome, "Mario Tecnico")
        self.assertEqual(allegato.uploaded_by_ditta, "Ditta Esterna Srl")
        self.assertEqual(allegato.tipo_documento, "RAPPORTINO")
        self.assertEqual(allegato.descrizione, "Sostituita guarnizione")
        self.assertTrue((self.private_root / allegato.file.name).exists())
        self.assertTrue(TicketCommento.objects.filter(ticket=self.ticket, testo__icontains="QR code").exists())
        self.assertTrue(AuditLog.objects.filter(azione="ticket_allegato_qr", dettaglio__esito="success").exists())
        self.assertTrue(Notifica.objects.filter(legacy_user_id=4242, tipo="ticket_allegato").exists())

    def test_ticket_di_un_altra_macchina_e_rifiutato(self):
        response = self._qr_post(self.other_ticket)

        self.assertEqual(response.status_code, 404)
        self.assertFalse(TicketAllegato.objects.exists())
        denied = AuditLog.objects.filter(azione="ticket_allegato_qr").order_by("-id").first()
        self.assertEqual(denied.dettaglio.get("motivo"), "ticket_not_in_asset")

    def test_ticket_chiuso_non_accetta_allegati(self):
        chiuso = self._ticket(self.asset, titolo="Chiuso", stato=StatoTicket.CHIUSO)

        response = self._qr_post(chiuso)

        self.assertEqual(response.status_code, 302)
        self.assertFalse(TicketAllegato.objects.exists())

    def test_nome_obbligatorio_e_honeypot(self):
        self._qr_post(self.ticket, nome="")
        self._qr_post(self.ticket, sito_web="http://spam.example")

        self.assertFalse(TicketAllegato.objects.exists())

    def test_get_non_ammesso_e_token_disabilitato(self):
        self.assertEqual(self.client.get(self._qr_upload_url(self.ticket)).status_code, 404)
        Asset.objects.filter(pk=self.asset.pk).update(public_qr_enabled=False)
        self.assertEqual(self._qr_post(self.ticket).status_code, 404)
        self.assertFalse(TicketAllegato.objects.exists())

    @override_settings(ASSETS_QR_PUBLIC_TICKET_UPLOAD=False)
    def test_interruttore_di_emergenza(self):
        self.assertEqual(self._qr_post(self.ticket).status_code, 404)
        landing = self.client.get(
            reverse("assets:asset_qr_public_landing", kwargs={"public_qr_token": self.asset.public_qr_token})
        )
        self.assertNotContains(landing, "Allega rapportino")

    def test_tetto_anti_abuso(self):
        with patch("tickets.allegati.QR_RATE_LIMIT_IP", 1):
            self._qr_post(self.ticket)
            self._qr_post(self.ticket, file=_png("secondo.png"))

        self.assertEqual(TicketAllegato.objects.count(), 1)
        self.assertTrue(AuditLog.objects.filter(azione="ticket_allegato_qr", dettaglio__motivo="rate_limited").exists())

    def test_file_non_ammesso_scartato(self):
        with patch(
            "tickets.allegati.validate_extension_and_mime",
            side_effect=UploadMimeValidationError("tipo MIME non consentito"),
        ):
            self._qr_post(self.ticket, file=SimpleUploadedFile("x.exe", b"MZ", content_type="application/octet-stream"))

        self.assertFalse(TicketAllegato.objects.exists())

    def test_landing_pubblica_mostra_ticket_aperti_senza_richiedente(self):
        chiuso = self._ticket(self.asset, titolo="Ticket ormai chiuso", stato=StatoTicket.CHIUSO)
        response = self.client.get(
            reverse("assets:asset_qr_public_landing", kwargs={"public_qr_token": self.asset.public_qr_token})
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.ticket.numero_ticket)
        self.assertContains(response, "Perdita olio mandrino")
        self.assertContains(response, self._qr_upload_url(self.ticket))
        self.assertNotContains(response, "Richiedente Sintetico")
        self.assertNotContains(response, chiuso.numero_ticket)
        self.assertNotContains(response, "Rumore fresa")
        # Con il form POST la policy resta dentro l'origine (no-referrer => Origin: null => CSRF KO).
        self.assertEqual(response["Referrer-Policy"], "same-origin")
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow, noarchive")

    def test_csrf_attivo_sul_form_pubblico(self):
        from django.test import Client

        client = Client(enforce_csrf_checks=True)
        response = client.post(self._qr_upload_url(self.ticket), {"nome": "Mario Tecnico", "file": _png()})

        # core.views.csrf_failure: cookie mancante => redirect di recupero, mai l'upload.
        self.assertIn(response.status_code, (302, 403))
        self.assertFalse(TicketAllegato.objects.exists())


class PaginaWebUploadTests(_Base):
    def test_operatore_allega_a_ticket_di_asset_da_validare(self):
        self.client.force_login(self.operatore)
        response = self.client.post(
            reverse("tickets:carica_allegati", args=[self.ticket.pk]),
            {"file": _png(), "tipo_documento": "FOTO", "next": "/assets/qr/AST-QR-TKT-1/"},
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], "/assets/qr/AST-QR-TKT-1/")
        allegato = TicketAllegato.objects.get(ticket=self.ticket)
        self.assertEqual(allegato.stato_validazione, StatoValidazioneAllegato.DA_VALIDARE)
        self.assertEqual(allegato.origine, OrigineAllegato.PORTALE)

    def test_redirect_esterno_ignorato(self):
        self.client.force_login(self.operatore)
        response = self.client.post(
            reverse("tickets:carica_allegati", args=[self.ticket.pk]),
            {"file": _png(), "next": "https://evil.example/"},
        )
        self.assertNotIn("evil.example", response["Location"])

    def test_ticket_senza_asset_di_altri_e_negato(self):
        senza_asset = self._ticket(None, titolo="Senza asset")
        self.client.force_login(self.operatore)

        response = self.client.post(reverse("tickets:carica_allegati", args=[senza_asset.pk]), {"file": _png()})

        self.assertEqual(response.status_code, 403)
        self.assertFalse(TicketAllegato.objects.exists())

    def test_caricato_dal_gestore_e_gia_validato(self):
        self.client.force_login(self.gestore)
        self.client.post(reverse("tickets:carica_allegati", args=[self.ticket.pk]), {"file": _png()})

        self.assertEqual(
            TicketAllegato.objects.get(ticket=self.ticket).stato_validazione, StatoValidazioneAllegato.VALIDATO
        )


class ValidazioneTests(_Base):
    def setUp(self):
        super().setUp()
        self._qr_post(self.ticket)
        self.allegato = TicketAllegato.objects.get(ticket=self.ticket)

    def _valida(self, esito: str, nota: str = ""):
        return self.client.post(
            reverse("tickets:valida_allegato", args=[self.allegato.pk]), {"esito": esito, "nota": nota}
        )

    def test_gestore_valida(self):
        self.client.force_login(self.gestore)
        self._valida("VALIDATO")

        self.allegato.refresh_from_db()
        self.assertEqual(self.allegato.stato_validazione, StatoValidazioneAllegato.VALIDATO)
        self.assertEqual(self.allegato.validato_da_nome, self.gestore.username)
        self.assertIsNotNone(self.allegato.validato_at)
        self.assertTrue(AuditLog.objects.filter(azione="ticket_allegato_validazione").exists())

    def test_rifiuto_richiede_motivo(self):
        self.client.force_login(self.gestore)
        self._valida("RIFIUTATO")
        self.allegato.refresh_from_db()
        self.assertEqual(self.allegato.stato_validazione, StatoValidazioneAllegato.DA_VALIDARE)

        self._valida("RIFIUTATO", "Foto illeggibile, rifare la scansione")
        self.allegato.refresh_from_db()
        self.assertEqual(self.allegato.stato_validazione, StatoValidazioneAllegato.RIFIUTATO)
        self.assertEqual(self.allegato.nota_validazione, "Foto illeggibile, rifare la scansione")

    def test_non_gestore_non_valida(self):
        self.client.force_login(self.operatore)
        response = self._valida("VALIDATO")

        self.assertEqual(response.status_code, 403)
        self.allegato.refresh_from_db()
        self.assertEqual(self.allegato.stato_validazione, StatoValidazioneAllegato.DA_VALIDARE)

    def test_gestione_mostra_coda_e_filtro(self):
        self.client.force_login(self.gestore)
        lista = self.client.get(reverse("tickets:gestione_list"), {"tipo": "MAN", "allegati": "da_validare"})
        self.assertEqual(lista.status_code, 200)
        self.assertContains(lista, self.ticket.numero_ticket)
        self.assertNotContains(lista, self.other_ticket.numero_ticket)
        self.assertEqual(lista.context["n_allegati_da_validare"], 1)

        dettaglio = self.client.get(reverse("tickets:gestione_detail", args=[self.ticket.pk]))
        self.assertContains(dettaglio, reverse("tickets:valida_allegato", args=[self.allegato.pk]))
