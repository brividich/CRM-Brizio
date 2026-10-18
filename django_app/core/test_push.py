"""Notifiche push (core.push, core.views_push) e preferenze canali.

Chiavi VAPID generate al volo, endpoint sintetici: nessuna rete (requests.post
sempre sostituito)."""
from __future__ import annotations

import base64
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from core import push
from core.legacy_models import UtenteLegacy
from core.models import Notifica, NotificaCanali, Profile, PushIscrizione, UserOnboarding

CHIAVE = push.genera_chiave_privata()
FCM = "https://fcm.googleapis.com/fcm/send/abc123-sintetico"
MOZ = "https://updates.push.services.mozilla.com/wpush/v2/sintetico"


def _b64d(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


class _Resp:
    def __init__(self, status):
        self.status_code = status


class EndpointAmmessoTests(SimpleTestCase):
    def test_servizi_push_noti(self):
        for url in (
            FCM,
            MOZ,
            "https://wns2-par02p.notify.windows.com/w/?token=sintetico",
            "https://web.push.apple.com/QGsintetico",
        ):
            with self.subTest(url=url):
                self.assertTrue(push.endpoint_ammesso(url))

    def test_rifiuta_tutto_il_resto(self):
        for url in (
            "http://fcm.googleapis.com/fcm/send/x",          # niente https
            "https://fcm.googleapis.com.evil.example/x",       # suffisso finto
            "https://evilfcm.googleapis.com.example/x",
            "https://fcm.googleapis.com@evil.example/x",       # userinfo: l'host vero è evil.example
            "https://user:pw@fcm.googleapis.com/x",           # credenziali nell'URL
            "https://fcm.googleapis.com:8443/x",              # porta non standard
            "https://192.168.1.10/x",
            "https://intranet.local/x",
            "",
            "javascript:alert(1)",
        ):
            with self.subTest(url=url):
                self.assertFalse(push.endpoint_ammesso(url))


@override_settings(VAPID_PRIVATE_KEY=CHIAVE, VAPID_SUBJECT="mailto:it@example.com")
class VapidTests(SimpleTestCase):
    def test_chiave_pubblica_punto_non_compresso(self):
        self.assertTrue(push.push_configurato())
        raw = _b64d(push.chiave_pubblica())
        self.assertEqual(len(raw), 65)
        self.assertEqual(raw[0], 4)

    def test_header_vapid_firmato_e_verificabile(self):
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature

        header = push._vapid_header(FCM)
        self.assertTrue(header.startswith("vapid t="))
        token = header.split("t=", 1)[1].split(",", 1)[0]
        k = header.split("k=", 1)[1]
        self.assertEqual(k, push.chiave_pubblica())
        h, p, s = token.split(".")
        claims = json.loads(_b64d(p))
        self.assertEqual(claims["aud"], "https://fcm.googleapis.com")
        self.assertEqual(claims["sub"], "mailto:it@example.com")
        sig = _b64d(s)
        pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), _b64d(k))
        der = encode_dss_signature(int.from_bytes(sig[:32], "big"), int.from_bytes(sig[32:], "big"))
        pub.verify(der, f"{h}.{p}".encode(), ec.ECDSA(hashes.SHA256()))  # solleva se non valida

    @override_settings(VAPID_PRIVATE_KEY="")
    def test_senza_chiave_push_spente(self):
        self.assertFalse(push.push_configurato())
        self.assertEqual(push.chiave_pubblica(), "")

    @override_settings(VAPID_PRIVATE_KEY="non-una-chiave!!")
    def test_chiave_rotta_push_spente(self):
        self.assertFalse(push.push_configurato())


def _utente(username="pushuser"):
    user = get_user_model().objects.create_user(username=username, password="pw", email=f"{username}@example.com")
    legacy = UtenteLegacy.objects.create(nome=f"Sintetico {username}", email=f"{username}@example.com", password="x", attivo=True)
    Profile.objects.create(user=user, legacy_user_id=legacy.id, legacy_ruolo="utente")
    from django.utils import timezone

    UserOnboarding.objects.create(user=user, completed=True, completed_at=timezone.now())
    return user, legacy


@override_settings(VAPID_PRIVATE_KEY=CHIAVE)
class InvioSegnaleTests(TestCase):
    def setUp(self):
        self.user, self.legacy = _utente()
        self.iscr = PushIscrizione.objects.create(
            user=self.user, endpoint=FCM, endpoint_hash=push.endpoint_hash(FCM), dispositivo="Chrome su Android",
        )

    def test_201_ok_corpo_vuoto(self):
        with patch("requests.post", return_value=_Resp(201)) as post:
            self.assertTrue(push.invia_segnale(self.iscr))
        args, kwargs = post.call_args
        self.assertEqual(args[0], FCM)
        self.assertEqual(kwargs["data"], b"")          # nessun contenuto esce
        self.assertIn("vapid t=", kwargs["headers"]["Authorization"])
        self.assertFalse(kwargs["allow_redirects"])
        self.iscr.refresh_from_db()
        self.assertIsNotNone(self.iscr.ultimo_invio_ok)

    def test_410_disattiva(self):
        with patch("requests.post", return_value=_Resp(410)):
            self.assertFalse(push.invia_segnale(self.iscr))
        self.iscr.refresh_from_db()
        self.assertFalse(self.iscr.attiva)

    def test_errori_ripetuti_disattivano(self):
        with patch("requests.post", return_value=_Resp(500)):
            for _ in range(push.MAX_ERRORI_CONSECUTIVI):
                push.invia_segnale(self.iscr)
        self.iscr.refresh_from_db()
        self.assertFalse(self.iscr.attiva)

    def test_endpoint_non_ammesso_mai_chiamato(self):
        PushIscrizione.objects.filter(pk=self.iscr.pk).update(endpoint="https://intranet.local/x")
        self.iscr.refresh_from_db()
        with patch("requests.post") as post:
            self.assertFalse(push.invia_segnale(self.iscr))
        post.assert_not_called()


@override_settings(VAPID_PRIVATE_KEY=CHIAVE)
class NotificaCreataTests(TestCase):
    def setUp(self):
        self.user, self.legacy = _utente()
        PushIscrizione.objects.create(user=self.user, endpoint=FCM, endpoint_hash=push.endpoint_hash(FCM))

    def test_accoda_solo_per_categoria_scelta(self):
        NotificaCanali.objects.create(user=self.user, push_categorie=["scadenzari"])
        with patch("core.push._accoda") as accoda:
            self.assertTrue(push.notifica_creata(self.legacy.id, "dpi_scadenza"))      # scadenzari
            self.assertFalse(push.notifica_creata(self.legacy.id, "assenza_approvata"))  # assenze
        accoda.assert_called_once_with(self.user.id)

    def test_nessuna_preferenza_nessuna_push(self):
        with patch("core.push._accoda") as accoda:
            self.assertFalse(push.notifica_creata(self.legacy.id, "dpi_scadenza"))
        accoda.assert_not_called()

    def test_invia_notifica_crea_campanella_e_accoda_push(self):
        from core.notifiche import invia_notifica

        NotificaCanali.objects.create(user=self.user, push_categorie=["scadenzari"])
        with patch("core.push._accoda") as accoda:
            invia_notifica(self.legacy.id, "dpi_scadenza", "DPI sintetico in scadenza", "/dpi/1/")
        self.assertTrue(Notifica.objects.filter(legacy_user_id=self.legacy.id, tipo="dpi_scadenza").exists())
        accoda.assert_called_once_with(self.user.id)

    def test_categoria_spenta_dall_utente_niente_push(self):
        from core.notifiche import invia_notifica

        NotificaCanali.objects.create(user=self.user, push_categorie=["scadenzari"])
        UserOnboarding.objects.filter(user=self.user).update(notifiche_config={"scadenzari": False})
        with patch("core.push._accoda") as accoda:
            invia_notifica(self.legacy.id, "dpi_scadenza", "DPI sintetico", "/dpi/1/")
        accoda.assert_not_called()
        self.assertFalse(Notifica.objects.filter(legacy_user_id=self.legacy.id).exists())

    @override_settings(VAPID_PRIVATE_KEY="")
    def test_server_senza_chiave_niente_push(self):
        NotificaCanali.objects.create(user=self.user, push_categorie=["scadenzari"])
        with patch("core.push._accoda") as accoda:
            self.assertFalse(push.notifica_creata(self.legacy.id, "dpi_scadenza"))
        accoda.assert_not_called()


@override_settings(VAPID_PRIVATE_KEY=CHIAVE)
class PushApiTests(TestCase):
    def setUp(self):
        from django.core.cache import cache

        cache.clear()  # il flag «prova» è per id utente, e gli id si riusano fra test
        self.user, self.legacy = _utente()
        self.client.force_login(self.user)

    def _post(self, name, body):
        return self.client.post(reverse(name), data=json.dumps(body), content_type="application/json")

    def test_anonimo_riceve_json_401(self):
        self.client.logout()
        for name in ("api_push_iscrizione", "api_push_revoca", "api_push_prova"):
            with self.subTest(name=name):
                resp = self._post(name, {"endpoint": FCM})
                self.assertEqual(resp.status_code, 401)
                self.assertEqual(resp["Content-Type"], "application/json")
        resp = self.client.get(reverse("api_push_ultime"), HTTP_ACCEPT="application/json")
        self.assertEqual(resp.status_code, 401)

    def test_iscrizione_e_revoca(self):
        resp = self._post("api_push_iscrizione", {"endpoint": FCM})
        self.assertEqual(resp.status_code, 200, resp.content)
        iscr = PushIscrizione.objects.get(user=self.user)
        self.assertEqual(iscr.endpoint_hash, push.endpoint_hash(FCM))
        # Seconda volta: stessa riga, niente doppioni.
        self._post("api_push_iscrizione", {"endpoint": FCM})
        self.assertEqual(PushIscrizione.objects.filter(user=self.user).count(), 1)
        resp = self._post("api_push_revoca", {"endpoint": FCM})
        self.assertEqual(resp.json()["tolte"], 1)
        self.assertFalse(PushIscrizione.objects.filter(user=self.user).exists())

    def test_endpoint_non_ammesso_400(self):
        resp = self._post("api_push_iscrizione", {"endpoint": "https://intranet.local/rubami"})
        self.assertEqual(resp.status_code, 400)
        self.assertFalse(PushIscrizione.objects.exists())

    def test_revoca_per_id_solo_dei_propri(self):
        altro, _ = _utente("altro")
        sua = PushIscrizione.objects.create(user=altro, endpoint=MOZ, endpoint_hash=push.endpoint_hash(MOZ))
        resp = self._post("api_push_revoca", {"id": sua.id})
        self.assertEqual(resp.json()["tolte"], 0)
        self.assertTrue(PushIscrizione.objects.filter(pk=sua.pk).exists())

    def test_stesso_browser_passa_all_utente_collegato(self):
        altro, _ = _utente("altro")
        PushIscrizione.objects.create(user=altro, endpoint=FCM, endpoint_hash=push.endpoint_hash(FCM))
        self._post("api_push_iscrizione", {"endpoint": FCM})
        self.assertEqual(PushIscrizione.objects.get(endpoint_hash=push.endpoint_hash(FCM)).user_id, self.user.id)

    @override_settings(VAPID_PRIVATE_KEY="")
    def test_server_senza_chiave_409(self):
        resp = self._post("api_push_iscrizione", {"endpoint": FCM})
        self.assertEqual(resp.status_code, 409)

    def test_ultime_mostra_l_ultima_non_letta_con_url_interno(self):
        Notifica.objects.create(legacy_user_id=self.legacy.id, tipo="dpi_scadenza", messaggio="Prima", url_azione="/dpi/1/")
        Notifica.objects.create(legacy_user_id=self.legacy.id, tipo="ticket_sla", messaggio="Seconda",
                                url_azione="https://evil.example/phish")
        data = self.client.get(reverse("api_push_ultime")).json()
        self.assertTrue(data["ok"])
        self.assertTrue(data["messaggio"].startswith("Seconda"))
        self.assertIn("+1 altre", data["messaggio"])
        self.assertEqual(data["url"], "/notifiche/")  # url esterno mai propagato
        self.assertEqual(data["non_lette"], 2)
        # Leggere non segna niente come letto.
        self.assertEqual(Notifica.objects.filter(legacy_user_id=self.legacy.id, letta=False).count(), 2)

    def test_prova_mostra_testo_di_prova_su_ogni_dispositivo(self):
        PushIscrizione.objects.create(user=self.user, endpoint=FCM, endpoint_hash=push.endpoint_hash(FCM))
        with patch("requests.post", return_value=_Resp(201)):
            resp = self._post("api_push_prova", {})
        self.assertTrue(resp.json()["ok"])
        data = self.client.get(reverse("api_push_ultime")).json()
        self.assertIn("prova", data["titolo"])

    def test_service_worker(self):
        resp = self.client.get(reverse("push_service_worker"))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp["Content-Type"].startswith("application/javascript"))
        self.assertEqual(resp["Service-Worker-Allowed"], "/")
        body = resp.content.decode()
        self.assertIn("/api/notifiche/push/ultime/", body)
        self.assertNotIn("{{", body)


@override_settings(VAPID_PRIVATE_KEY=CHIAVE)
class ImpostazioniCanaliTests(TestCase):
    def setUp(self):
        self.user, self.legacy = _utente()
        self.client.force_login(self.user)

    def test_pagina_mostra_push_e_riepilogo(self):
        resp = self.client.get(reverse("notifiche_impostazioni"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Notifiche push su telefono e PC")
        self.assertContains(resp, "Riepilogo scadenze via mail")
        self.assertContains(resp, push.chiave_pubblica())
        self.assertNotContains(resp, CHIAVE)  # la privata non esce mai

    def test_salva_push_solo_per_categorie_accese_e_riepilogo(self):
        resp = self.client.post(reverse("notifiche_impostazioni"), {
            "notifiche_scadenzari": "1", "push_scadenzari": "1",
            "push_ticket": "1",                     # categoria spenta: push ignorata
            "digest_scadenze": "1", "digest_giorni": "30",
        })
        self.assertEqual(resp.status_code, 302)
        canali = NotificaCanali.objects.get(user=self.user)
        self.assertEqual(canali.push_categorie, ["scadenzari"])
        self.assertTrue(canali.digest_scadenze)
        self.assertEqual(canali.digest_giorni, 30)

    def test_giorni_non_validi_tornano_a_7(self):
        self.client.post(reverse("notifiche_impostazioni"), {"digest_scadenze": "1", "digest_giorni": "365"})
        self.assertEqual(NotificaCanali.objects.get(user=self.user).digest_giorni, 7)

    @override_settings(VAPID_PRIVATE_KEY="")
    def test_senza_chiave_avviso(self):
        resp = self.client.get(reverse("notifiche_impostazioni"))
        self.assertContains(resp, "non sono ancora attive sul server")

    def test_pagina_personale_condivisa_acl(self):
        # Pagina con i soli dati dell'utente: aperta a chi ha fatto l'accesso.
        from core.middleware import is_acl_shared_path

        self.assertTrue(is_acl_shared_path(reverse("notifiche_impostazioni")))
        self.assertTrue(is_acl_shared_path(reverse("push_service_worker")))
        self.assertTrue(is_acl_shared_path(reverse("api_push_ultime")))
