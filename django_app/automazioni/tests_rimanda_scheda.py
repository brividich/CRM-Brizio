"""«Rimanda la scheda» dalle pagine di dettaglio: passa dal flusso Automazioni."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import UserOnboarding

from .managed_flows import assicura_installati
from .models import EmailInviata, ManagedFlow

User = get_user_model()


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
                   SITE_URL="https://hub.example.test", DEFAULT_FROM_EMAIL="hub@example.test")
class RimandaSchedaTests(TestCase):
    def setUp(self):
        assicura_installati()
        self.admin = User.objects.create_superuser("rim_admin", "rim@example.com", "synthetic")
        UserOnboarding.objects.update_or_create(user=self.admin, defaults={"completed": True})
        self.client.force_login(self.admin)

    def _accendi(self, codice, acceso=True):
        rule = ManagedFlow.objects.get(code=codice).rule
        rule.is_active, rule.is_draft = acceso, False
        rule.save(update_fields=["is_active", "is_draft"])
        return rule

    def test_diario_preposto_rimanda_dal_flusso(self):
        from diario_preposto.models import SegnalazionePreposto

        s = SegnalazionePreposto.objects.create(
            titolo="Scaffale instabile", data_segnalazione=timezone.now(), descrizione="Ripiano piegato",
            preposto="Preposto Sintetico", chi_segnala="Operatore Sintetico",
        )
        rule = self._accendi("diario_preposto_scheda")
        dettaglio = reverse("diario_preposto:dettaglio", args=[s.pk])
        self.assertContains(self.client.get(dettaglio), reverse("diario_preposto:rimanda_scheda", args=[s.pk]))
        r = self.client.post(reverse("diario_preposto:rimanda_scheda", args=[s.pk]))
        self.assertRedirects(r, dettaglio, fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("rspp@", mail.outbox[0].to[0])
        self.assertEqual(EmailInviata.objects.get().regola_id, rule.pk)

    def test_diario_preposto_flusso_spento_non_manda(self):
        from diario_preposto.models import SegnalazionePreposto

        s = SegnalazionePreposto.objects.create(titolo="T", data_segnalazione=timezone.now(), descrizione="D",
                                                preposto="P", chi_segnala="C")
        self._accendi("diario_preposto_scheda", False)
        r = self.client.post(reverse("diario_preposto:rimanda_scheda", args=[s.pk]), follow=True)
        self.assertContains(r, "Il flusso è spento")
        self.assertEqual(len(mail.outbox), 0)

    def test_segnalazione_sicurezza_rimanda_dal_flusso(self):
        from rilevazione_incidenti.models import RilevazioneIncidente

        inc = RilevazioneIncidente.objects.create(
            nominativo="Dipendente Sintetico", tipologia_scheda="Near Miss", reparto="Reparto Test",
            descrizione_avvenimento="Caduta di un attrezzo",
        )
        rule = self._accendi("sicurezza_scheda_segnalazione")
        dettaglio = reverse("rilevazione_incidenti:dettaglio", kwargs={"sp_id": inc.pk})
        with patch("rilevazione_incidenti.views._can_manage_rspp", return_value=True):
            self.assertContains(self.client.get(dettaglio),
                                reverse("rilevazione_incidenti:rimanda_scheda", kwargs={"sp_id": inc.pk}))
            r = self.client.post(reverse("rilevazione_incidenti:rimanda_scheda", kwargs={"sp_id": inc.pk}))
        self.assertRedirects(r, dettaglio, fetch_redirect_response=False)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(EmailInviata.objects.get().regola_id, rule.pk)

    def test_non_gestore_non_puo_rimandare(self):
        from rilevazione_incidenti.models import RilevazioneIncidente

        inc = RilevazioneIncidente.objects.create(nominativo="X", tipologia_scheda="Near Miss", reparto="R",
                                                  descrizione_avvenimento="D")
        self._accendi("sicurezza_scheda_segnalazione")
        utente = User.objects.create_user("rim_user", "user@example.com", "synthetic")
        UserOnboarding.objects.update_or_create(user=utente, defaults={"completed": True})
        self.client.force_login(utente)
        with patch("rilevazione_incidenti.views._can_manage_rspp", return_value=False):
            r = self.client.post(reverse("rilevazione_incidenti:rimanda_scheda", kwargs={"sp_id": inc.pk}))
        self.assertIn(r.status_code, (302, 403))
        self.assertEqual(len(mail.outbox), 0)
