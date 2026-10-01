"""Copilota per valutare le richieste DPI: storico, proposta dell'AI (mockata) e apprendimento."""
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from ai_assistant.models import AiProposta
from core.models import UserOnboarding
from dpi.ai_richiesta import contesto, storico_richiesta
from dpi.models import CategoriaDPI, ConsegnaDPI, RichiestaDPI, StatoRichiesta

CHAT = "ai_assistant.services.chat_with_ollama"


class _Base(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(username="dpi-ai", password="pass12345", email="d@x.it")
        self.client.force_login(self.admin)
        self.guanti = CategoriaDPI.objects.create(nome="Guanti antitaglio", icona_emoji="G", is_active=True, vita_utile_giorni=90)
        self.oggi = timezone.localdate()

    def _richiesta(self, persona=101, stato=StatoRichiesta.INVIATA, reparto="Montaggio", note="", motivazione="Guanti rotti"):
        return RichiestaDPI.objects.create(categoria=self.guanti, richiedente_legacy_id=persona, richiedente_nome=f"Persona {persona}",
                                           richiedente_reparto=reparto, stato=stato, note_gestione=note, motivazione=motivazione)

    def _consegnata(self, persona=101, giorni_fa=10, reparto="Montaggio"):
        r = self._richiesta(persona, StatoRichiesta.CONSEGNATA, reparto)
        ConsegnaDPI.objects.create(richiesta=r, data_consegna=self.oggi - timedelta(days=giorni_fa))
        return r


class StoricoTests(_Base):
    def test_consegna_recente_doppione_e_rifiuti_passati(self):
        self._consegnata(giorni_fa=20)
        self._richiesta(stato=StatoRichiesta.APPROVATA)
        self._richiesta(persona=7, stato=StatoRichiesta.RIFIUTATA, note="Ultima consegna da meno di un mese, guanti ancora integri")
        nuova = self._richiesta()
        fatti = storico_richiesta(nuova)
        testi = " ".join(s["testo"] for s in fatti["segnali"])
        self.assertIn("20 giorni fa: la durata prevista è 90 giorni (22% usata)", testi)
        self.assertIn("già 1 altra richiesta aperta", testi)
        self.assertEqual(fatti["motivi_rifiuto"], ["Ultima consegna da meno di un mese, guanti ancora integri"])
        testo_ai = contesto(nuova, fatti)
        self.assertNotIn("Persona 101", testo_ai)  # al modello non arrivano nomi
        self.assertIn("reparto Montaggio", testo_ai)

    def test_consumo_sopra_la_media_del_reparto(self):
        for persona in (1, 2, 3):
            self._consegnata(persona=persona, giorni_fa=200)
        for giorni in (300, 200, 120):
            self._consegnata(persona=101, giorni_fa=giorni)
        testi = " ".join(s["testo"] for s in storico_richiesta(self._richiesta())["segnali"])
        self.assertIn("3 consegne contro una media di 1.5 nel reparto Montaggio", testi)
        self.assertIn("la durata prevista (90 giorni) è superata", testi)


class PaginaTests(_Base):
    def test_storico_in_pagina_proposta_e_decisione_imparata(self):
        self._consegnata(giorni_fa=20)
        richiesta = self._richiesta()
        page = self.client.get(reverse("dpi:gestione_detail", args=[richiesta.pk]))
        self.assertContains(page, "Prima di decidere")
        self.assertContains(page, "22% usata")
        risposta = SimpleNamespace(content='{"decisione": "chiedere_info", "messaggio": "Ci spieghi cosa è successo ai guanti?", "motivazione": "consegna recente"}')
        with patch(CHAT, return_value=risposta) as chat:
            r = self.client.post(reverse("dpi:copilota_richiesta", args=[richiesta.pk]))
        self.assertContains(r, "Proposta: Chiedere informazioni")
        self.assertContains(r, 'data-dpi-ai-copia="testo-comm"')
        self.assertNotIn("Persona 101", chat.call_args.kwargs["runtime_context"])
        richiesta.refresh_from_db()
        self.assertEqual(richiesta.stato, StatoRichiesta.INVIATA)  # proporre non decide
        self.client.post(reverse("dpi:approva", args=[richiesta.pk]), {"nota": "Ok, sostituiti"})
        p = AiProposta.objects.get(modulo="dpi")
        self.assertEqual((p.esito, p.decisione), (AiProposta.SCARTATA, {"decisione": "approvare"}))

    def test_ai_spenta_e_risposta_non_valida(self):
        richiesta = self._richiesta()
        with patch(CHAT, side_effect=RuntimeError("giù")):
            r = self.client.post(reverse("dpi:copilota_richiesta", args=[richiesta.pk]))
        self.assertContains(r, "L'AI locale non ha risposto")
        with patch(CHAT, return_value=SimpleNamespace(content='{"decisione": "regalare"}')):
            r = self.client.post(reverse("dpi:copilota_richiesta", args=[richiesta.pk]))
        self.assertContains(r, "non ha dato una proposta chiara")
        self.assertFalse(AiProposta.objects.exists())

    def test_chi_non_approva_non_vede_il_copilota(self):
        richiesta = self._richiesta()
        user = get_user_model().objects.create_user(username="dpi-no", password="pass12345")
        UserOnboarding.objects.update_or_create(user=user, defaults={"completed": True, "skipped": False})
        self.client.force_login(user)
        with patch("core.middleware.resolve_acl_access", return_value={"allowed": True}):
            r = self.client.post(reverse("dpi:copilota_richiesta", args=[richiesta.pk]))
        self.assertEqual(r.status_code, 403)
