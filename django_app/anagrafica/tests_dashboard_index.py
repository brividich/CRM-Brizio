"""Dashboard Anagrafica (`anagrafica:index`) — «Cose da gestire» e fascia «Vai a».

Il punto dolente che questi test presidiano è uno: il numero mostrato in dashboard
e la lista che quel numero apre devono venire dalla stessa fonte. Un contatore che
dice 2 e uno scadenzario che ne elenca 3 è il difetto che ha portato a rimuovere i
widget duplicati — non va reintrodotto da un'altra porta.
"""

from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import UserOnboarding

from .models import (
    AnagraficaVisiteMedichePermission,
    DipendenteQualifica,
    TipoQualifica,
    TipoVisitaMedica,
    VisitaMedica,
)
from .tests import _ensure_anagrafica_table


def _pill(url_name: str) -> str:
    """Marcatore della pill nella fascia «Vai a».

    Cercare il solo URL non basta: la subnav del modulo elenca ogni voce a
    prescindere dai permessi (la navigazione non è un confine di sicurezza), quindi
    un `assertContains(url)` passerebbe anche con la fascia vuota.
    """
    return f'hr-goto-pill" href="{reverse(url_name)}"'


def _utente_operativo(username: str) -> User:
    """Utente non-superuser che ha già fatto il primo accesso.

    Senza il record UserOnboarding completato, il middleware dirotta ogni pagina
    sul wizard di onboarding e il test misurerebbe quel redirect, non la view.
    """
    user = User.objects.create_user(
        username=username, email=f"{username}@x.local", password="x"
    )
    UserOnboarding.objects.create(user=user, completed=True)
    return user


class CoseDaGestireTests(TestCase):
    """Le righe azionabili della dashboard e il loro accordo con lo scadenzario."""

    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()
        cls.admin = User.objects.create_superuser(
            username="dash_admin", email="dash_admin@x.local", password="x"
        )
        cls.tipo_qual = TipoQualifica.objects.create(nome="Carrellista")

    def setUp(self):
        self.client.force_login(self.admin)
        self.oggi = timezone.localdate()

    def _qualifica(self, legacy_id: int, giorni: int):
        return DipendenteQualifica.objects.create(
            legacy_anagrafica_id=legacy_id,
            tipo=self.tipo_qual,
            data_scadenza=self.oggi + timedelta(days=giorni),
        )

    def test_nessuna_scadenza_nessuna_riga(self):
        resp = self.client.get(reverse("anagrafica:index"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["cose_da_gestire"], [])
        self.assertContains(resp, "Nessuna scadenza entro i prossimi 60 giorni")

    def test_qualifiche_scadute_e_in_scadenza_righe_separate(self):
        self._qualifica(301, -10)
        self._qualifica(302, -3)
        self._qualifica(303, 20)
        resp = self.client.get(reverse("anagrafica:index"))
        righe = {r["titolo"]: r for r in resp.context["cose_da_gestire"]}

        self.assertEqual(righe["Qualifiche scadute"]["count"], 2)
        self.assertTrue(righe["Qualifiche scadute"]["urgente"])
        self.assertEqual(righe["Qualifiche in scadenza (60 giorni)"]["count"], 1)
        self.assertFalse(righe["Qualifiche in scadenza (60 giorni)"]["urgente"])

    def test_scadenza_oltre_60_giorni_non_e_una_cosa_da_gestire(self):
        self._qualifica(304, 90)
        resp = self.client.get(reverse("anagrafica:index"))
        self.assertEqual(resp.context["cose_da_gestire"], [])

    def test_le_scadute_precedono_le_in_scadenza(self):
        self._qualifica(305, 20)
        self._qualifica(306, -1)
        resp = self.client.get(reverse("anagrafica:index"))
        titoli = [r["titolo"] for r in resp.context["cose_da_gestire"]]
        self.assertEqual(titoli, ["Qualifiche scadute", "Qualifiche in scadenza (60 giorni)"])

    def test_il_conteggio_coincide_con_lo_scadenzario_che_apre(self):
        """Il contratto vero del blocco: cliccando la riga si trovano ESATTAMENTE
        le voci che la riga aveva contato."""
        self._qualifica(307, -10)
        self._qualifica(308, -3)
        self._qualifica(309, 20)

        resp = self.client.get(reverse("anagrafica:index"))
        riga = next(
            r for r in resp.context["cose_da_gestire"] if r["titolo"] == "Qualifiche scadute"
        )

        elenco = self.client.get(riga["url"])
        self.assertEqual(elenco.status_code, 200)
        self.assertEqual(elenco.context["totale"], riga["count"])

    def test_riga_urgente_punta_allo_scadenzario_filtrato(self):
        self._qualifica(310, -5)
        resp = self.client.get(reverse("anagrafica:index"))
        riga = resp.context["cose_da_gestire"][0]
        self.assertEqual(
            riga["url"],
            reverse("anagrafica:scadenzario") + "?tipo=qualifica&stato=scaduta",
        )


class CoseDaGestireGatingTests(TestCase):
    """Il gating per sorgente vive in `_build_scadenzario_voci`: la dashboard non
    deve poter far trapelare, nemmeno come conteggio, dati che l'utente non vede."""

    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()
        cls.utente = _utente_operativo("dash_user")
        cls.tipo_visita = TipoVisitaMedica.objects.create(nome="Visita periodica", durata_mesi=12)

    def setUp(self):
        # Default del singleton = ADMIN: un utente normale non vede le visite mediche.
        AnagraficaVisiteMedichePermission.get_instance()
        VisitaMedica.objects.create(
            legacy_anagrafica_id=401,
            tipo=self.tipo_visita,
            data_svolgimento=timezone.localdate() - timedelta(days=400),  # scaduta
        )

    @override_settings(LEGACY_AUTH_ENABLED=False)
    def test_visite_mediche_non_contate_per_chi_non_puo_vederle(self):
        self.client.force_login(self.utente)
        resp = self.client.get(reverse("anagrafica:index"))
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.context["can_view_visite"])
        titoli = [r["titolo"] for r in resp.context["cose_da_gestire"]]
        self.assertNotIn("Visite mediche scadute", titoli)
        self.assertNotContains(resp, "Visite mediche scadute")

    def test_visite_mediche_contate_per_chi_puo_vederle(self):
        admin = User.objects.create_superuser(
            username="dash_admin2", email="dash_admin2@x.local", password="x"
        )
        self.client.force_login(admin)
        resp = self.client.get(reverse("anagrafica:index"))
        righe = {r["titolo"]: r for r in resp.context["cose_da_gestire"]}
        self.assertEqual(righe["Visite mediche scadute"]["count"], 1)


class VaiAiSottomoduliTests(TestCase):
    """La fascia «Vai a» espone i sottomoduli che altrimenti stanno solo nei
    dropdown della subnav. Non è un confine di sicurezza (le view restano gated),
    ma non ha senso offrire una porta che si apre su un rifiuto."""

    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()
        cls.admin = User.objects.create_superuser(
            username="goto_admin", email="goto_admin@x.local", password="x"
        )
        cls.utente = _utente_operativo("goto_user")

    @override_settings(LEGACY_AUTH_ENABLED=False)
    def test_link_sempre_disponibili_per_ogni_autenticato(self):
        self.client.force_login(self.utente)
        resp = self.client.get(reverse("anagrafica:index"))
        self.assertContains(resp, _pill("anagrafica:organigramma"))
        self.assertContains(resp, _pill("anagrafica:qualifiche_dashboard"))
        self.assertContains(resp, _pill("anagrafica:ex_dipendenti_list"))
        self.assertContains(resp, _pill("anagrafica:scadenzario"))

    @override_settings(LEGACY_AUTH_ENABLED=False)
    def test_sottomoduli_hr_nascosti_a_chi_non_ha_il_permesso(self):
        self.client.force_login(self.utente)
        resp = self.client.get(reverse("anagrafica:index"))
        self.assertFalse(resp.context["can_view_hr"])
        self.assertNotContains(resp, _pill("anagrafica:onboarding_list"))
        self.assertNotContains(resp, _pill("anagrafica:documenti_list"))
        self.assertNotContains(resp, _pill("anagrafica:visite_mediche_dashboard"))

    def test_sottomoduli_hr_visibili_a_chi_ha_il_permesso(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("anagrafica:index"))
        self.assertTrue(resp.context["can_view_hr"])
        self.assertContains(resp, _pill("anagrafica:onboarding_list"))
        self.assertContains(resp, _pill("anagrafica:documenti_list"))
        self.assertContains(resp, _pill("anagrafica:visite_mediche_dashboard"))
