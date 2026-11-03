"""Test del form pubblico anonimo (sessione 4, §5)."""
from __future__ import annotations

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from anagrafica.models import AreaAziendale, Reparto
from suggestion_corner.models import SuggestionCorner


class FormPubblicoTest(TestCase):
    def setUp(self):
        cache.clear()
        self.reparto = Reparto.objects.create(nome="TORNI")
        self.area = AreaAziendale.objects.create(nome="IT", reparto=self.reparto)
        self.url = reverse("suggestion_corner:nuova")

    def test_get_pubblico_anonimo_200(self):
        # Nessun login: la route è esente dal gate (MIDDLEWARE_EXEMPT_PREFIXES).
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)

    def test_home_richiede_login_ma_nuova_no(self):
        # Contrasto: la home è protetta, il form pubblico no.
        resp_home = self.client.get(reverse("suggestion_corner:home"))
        self.assertEqual(resp_home.status_code, 302)
        resp_nuova = self.client.get(self.url)
        self.assertEqual(resp_nuova.status_code, 200)

    def test_post_valida_crea_segnalazione_in_da_classificare(self):
        resp = self.client.post(self.url, {
            "reparto_provenienza": self.reparto.pk,
            "opportunity": "Migliorare l'illuminazione.",
            "modo": "identificato",
            "segnalante_nome": "Mario Prova",
        })
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(SuggestionCorner.objects.count(), 1)
        seg = SuggestionCorner.objects.get()
        self.assertEqual(seg.stato, "DA_CLASSIFICARE")
        self.assertTrue(seg.da_portale)
        self.assertFalse(seg.anonima)
        self.assertIsNone(seg.created_by)  # senza login: resta il nome dichiarato
        self.assertEqual(seg.segnalante_nome, "Mario Prova")

    def test_anonima_flag(self):
        self.client.post(self.url, {
            "reparto_provenienza": self.reparto.pk,
            "opportunity": "Segnalazione anonima.",
            "modo": "anonimo",
            "segnalante_nome": "Nome scritto per sbaglio",
        })
        seg = SuggestionCorner.objects.get()
        self.assertTrue(seg.anonima)
        self.assertIsNone(seg.created_by)
        self.assertEqual(seg.segnalante_nome, "")  # anonima: il nome non si salva

    def test_honeypot_scarta_silenziosamente(self):
        resp = self.client.post(self.url, {
            "reparto_provenienza": self.reparto.pk,
            "opportunity": "Spam bot.",
            "website": "http://spam.example",
        })
        self.assertEqual(resp.status_code, 200)  # finto successo
        self.assertEqual(SuggestionCorner.objects.count(), 0)  # nessuna creazione

    def test_post_solo_area_crea_e_deduce_reparto(self):
        resp = self.client.post(self.url, {
            "area_provenienza": self.area.pk,
            "opportunity": "Segnalazione da area IT.",
            "modo": "anonimo",
        })
        self.assertEqual(resp.status_code, 200)
        seg = SuggestionCorner.objects.get()
        self.assertEqual(seg.area_provenienza, self.area)
        self.assertEqual(seg.reparto_provenienza, self.reparto)  # padre dedotto

    def test_form_invalido_non_crea(self):
        resp = self.client.post(self.url, {"opportunity": ""})
        self.assertEqual(resp.status_code, 200)  # ri-render con errori
        self.assertEqual(SuggestionCorner.objects.count(), 0)

    def test_post_senza_provenienza_non_crea(self):
        # Né reparto né area → form invalido (regola "almeno uno").
        resp = self.client.post(self.url, {"opportunity": "Manca la provenienza.", "modo": "anonimo"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(SuggestionCorner.objects.count(), 0)

    def test_rate_limit_per_ip(self):
        payload = {"reparto_provenienza": self.reparto.pk, "opportunity": "x", "modo": "anonimo"}
        # IP non di loopback: da 127.0.0.1 (richieste via IIS senza proxy fidato)
        # vale solo il limite globale, non quello per IP.
        for _ in range(5):
            self.client.post(self.url, payload, REMOTE_ADDR="10.0.0.20")
        resp = self.client.post(self.url, payload, REMOTE_ADDR="10.0.0.20")  # 6° oltre il limite
        self.assertEqual(resp.status_code, 429)
