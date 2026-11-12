"""Controlli condivisi nel gruppo qualità: in sospeso visibili ai colleghi, «Prendi in carico» (03/11/2026)."""
from __future__ import annotations

import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from anomalie import controllo_service as cs
from anomalie.quality_models import AnomaliaControllo
from core.models import AccessGroup, AccessGroupMembership, Notifica, Profile

User = get_user_model()
BOZZA = {"voci": ["LCN00054"], "anomalie": [{"testo": "Dentatura OT"}, {"testo": "Diametro fuori quota"}]}


@override_settings(LEGACY_AUTH_ENABLED=False, SETUP_WIZARD_REQUIRED=False, SECURE_SSL_REDIRECT=False)
class ControlliGruppoQualitaTests(TestCase):
    def setUp(self):
        # Accesso alla pagina concesso (lo decide l'ACL, qui non in esame); l'organigramma non aggiunge ruoli.
        for p in (patch("core.permessi.organigramma.profili_da_organigramma", return_value=[]),
                  patch("core.middleware.resolve_acl_access", return_value={"allowed": True})):
            p.start()
            self.addCleanup(p.stop)
        cq = AccessGroup.objects.create(code="controllo_qualita_t", label="Controllo qualità", preset="controllo-qualita")
        self.anna = self._utente("cq-anna", 9101, cq)
        self.luca = self._utente("cq-luca", 9102, cq)
        self.esterno = self._utente("prod-mario", 9103, None)
        self.controllo = AnomaliaControllo.objects.create(
            op_id="OP/2026/4545", fase="Collaudo", operatore=self.anna, operatore_display="Anna Bianchi",
            bozza=BOZZA, bozza_at=timezone.now() - timedelta(hours=10),
        )

    def _utente(self, username, legacy_id, gruppo):
        from core.models import UserOnboarding

        user = User.objects.create_user(username=username, password="pass12345")
        Profile.objects.create(user=user, legacy_user_id=legacy_id)
        UserOnboarding.objects.create(user=user, completed=True, completed_at=timezone.now())
        if gruppo is not None:
            AccessGroupMembership.objects.create(group=gruppo, legacy_user_id=legacy_id)
        return user

    def _post(self, url, body=None):
        return self.client.post(url, data=json.dumps(body or {}), content_type="application/json")

    def test_appartenenza_al_gruppo(self):
        self.assertTrue(cs.nel_gruppo_qualita(self.anna))
        self.assertFalse(cs.nel_gruppo_qualita(self.esterno))

    def test_il_collega_vede_i_controlli_in_sospeso_del_gruppo(self):
        self.client.force_login(self.luca)
        j = self.client.get(reverse("api_anomalie_controlli_sospesi")).json()
        self.assertTrue(j["gruppo"])
        self.assertEqual([r["id"] for r in j["controlli"]], [self.controllo.pk])
        riga = j["controlli"][0]
        self.assertFalse(riga["mio"])
        self.assertEqual((riga["operatore"], riga["anomalie_in_bozza"]), ("Anna Bianchi", 2))

    def test_chi_non_e_nel_gruppo_vede_solo_i_suoi(self):
        self.client.force_login(self.esterno)
        j = self.client.get(reverse("api_anomalie_controlli_sospesi")).json()
        self.assertEqual((j["gruppo"], j["controlli"]), (False, []))
        r = self.client.get(reverse("api_anomalie_controllo_dettaglio", args=[self.controllo.pk]))
        self.assertEqual(r.status_code, 403)
        r = self._post(reverse("api_anomalie_controllo_prendi", args=[self.controllo.pk]))
        self.assertEqual(r.status_code, 403)
        self.controllo.refresh_from_db()
        self.assertEqual(self.controllo.operatore_id, self.anna.pk)

    def test_terminati_o_senza_niente_in_sospeso_non_compaiono(self):
        AnomaliaControllo.objects.create(op_id="OP/1", fase="F", operatore=self.anna, bozza={},
                                         operatore_display="Anna Bianchi")
        AnomaliaControllo.objects.create(op_id="OP/2", fase="F", operatore=self.anna, bozza=BOZZA,
                                         terminato_at=timezone.now(), operatore_display="Anna Bianchi")
        self.client.force_login(self.luca)
        j = self.client.get(reverse("api_anomalie_controlli_sospesi")).json()
        self.assertEqual([r["id"] for r in j["controlli"]], [self.controllo.pk])

    def test_il_collega_legge_ma_non_scrive_prima_di_prenderlo(self):
        self.client.force_login(self.luca)
        r = self.client.get(reverse("api_anomalie_controllo_dettaglio", args=[self.controllo.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["mio"])
        r = self._post(reverse("api_anomalie_controllo_bozza", args=[self.controllo.pk]), {"bozza": {}})
        self.assertEqual(r.status_code, 403)
        self.assertIn("in carico a Anna Bianchi", r.json()["error"])
        self.controllo.refresh_from_db()
        self.assertEqual(self.controllo.bozza, BOZZA)

    def test_prendi_in_carico_passa_il_controllo_e_lo_traccia(self):
        self.client.force_login(self.luca)
        with patch("anomalie.views._current_user_identity", return_value={"name": "Luca Verdi"}):
            r = self._post(reverse("api_anomalie_controllo_prendi", args=[self.controllo.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["controllo"]["bozza"], BOZZA)  # la bozza passa con il controllo
        self.controllo.refresh_from_db()
        self.assertEqual((self.controllo.operatore_id, self.controllo.operatore_display), (self.luca.pk, "Luca Verdi"))
        self.assertEqual([(p["da"], p["a"]) for p in self.controllo.passaggi], [("Anna Bianchi", "Luca Verdi")])
        avviso = Notifica.objects.get(legacy_user_id=9101)
        self.assertIn("Luca Verdi ha preso in carico", avviso.messaggio)
        # Ora scrive il collega; chi lo aveva non può più sovrascrivere la bozza.
        r = self._post(reverse("api_anomalie_controllo_bozza", args=[self.controllo.pk]), {"bozza": BOZZA})
        self.assertEqual(r.status_code, 200)
        self.client.force_login(self.anna)
        r = self._post(reverse("api_anomalie_controllo_bozza", args=[self.controllo.pk]), {"bozza": {}})
        self.assertEqual(r.status_code, 403)
        self.assertIn("in carico a Luca Verdi", r.json()["error"])

    def test_prendere_un_terminato_non_si_puo(self):
        AnomaliaControllo.objects.filter(pk=self.controllo.pk).update(terminato_at=timezone.now())
        self.client.force_login(self.luca)
        r = self._post(reverse("api_anomalie_controllo_prendi", args=[self.controllo.pk]))
        self.assertEqual(r.status_code, 409)
