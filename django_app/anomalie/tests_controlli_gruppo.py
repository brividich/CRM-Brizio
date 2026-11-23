"""Controlli condivisi: elenco «da riprendere» su tutti gli OP e «Partecipa» (stesso controllo insieme, 22/11/2026)."""
from __future__ import annotations

import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from anomalie import controllo_service as cs
from anomalie.quality_models import AnomaliaControllo, AnomaliaControlloPartecipante
from core.models import AccessGroup, AccessGroupMembership, Notifica, Profile

User = get_user_model()
BOZZA = {"voci": ["LCN00054"], "anomalie": [{"testo": "Dentatura OT"}, {"testo": "Diametro fuori quota"}]}


@override_settings(LEGACY_AUTH_ENABLED=False, SETUP_WIZARD_REQUIRED=False, SECURE_SSL_REDIRECT=False)
class _GruppoBase(TestCase):
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


@override_settings(LEGACY_AUTH_ENABLED=False, SETUP_WIZARD_REQUIRED=False, SECURE_SSL_REDIRECT=False)
class ControlliGruppoQualitaTests(_GruppoBase):
    def test_appartenenza_al_gruppo(self):
        self.assertTrue(cs.nel_gruppo_qualita(self.anna))
        self.assertFalse(cs.nel_gruppo_qualita(self.esterno))

    def test_elenco_da_riprendere_su_tutti_gli_op(self):
        self.client.force_login(self.luca)
        with patch("anomalie.views._can_create_anomalie_for_op", return_value=True):
            j = self.client.get(reverse("api_anomalie_controlli_sospesi")).json()
        self.assertEqual([r["id"] for r in j["controlli"]], [self.controllo.pk])
        riga = j["controlli"][0]
        self.assertEqual((riga["mio"], riga["partecipo"], riga["terminato"]), (False, False, False))
        self.assertEqual((riga["persone"], riga["anomalie_in_bozza"]), (["Anna Bianchi"], 2))

    def test_senza_permesso_sull_op_non_vede_e_non_partecipa(self):
        self.client.force_login(self.esterno)
        with patch("anomalie.views._can_create_anomalie_for_op", return_value=False):
            j = self.client.get(reverse("api_anomalie_controlli_sospesi")).json()
            self.assertEqual(j["controlli"], [])
            r = self.client.get(reverse("api_anomalie_controllo_dettaglio", args=[self.controllo.pk]))
            self.assertEqual(r.status_code, 403)
            r = self._post(reverse("api_anomalie_controllo_prendi", args=[self.controllo.pk]))
            self.assertEqual(r.status_code, 403)
        self.assertFalse(AnomaliaControlloPartecipante.objects.exists())

    def test_aperti_anche_salvati_si_terminati_vecchi_o_tutti_chiusi_no(self):
        salvato = AnomaliaControllo.objects.create(op_id="OP/1", fase="F", operatore=self.anna, bozza={},
                                                   operatore_display="Anna Bianchi")
        AnomaliaControllo.objects.create(op_id="OP/2", fase="F", operatore=self.anna, bozza=BOZZA,
                                         terminato_at=timezone.now(), operatore_display="Anna Bianchi")
        AnomaliaControllo.objects.create(op_id="OP/3", fase="F", operatore=self.anna, bozza=BOZZA,
                                         terminato_at=timezone.now() - timedelta(days=10), operatore_display="Anna Bianchi")
        self.client.force_login(self.luca)
        with patch("anomalie.views._can_create_anomalie_for_op", return_value=True):
            j = self.client.get(reverse("api_anomalie_controlli_sospesi")).json()
        # OP/2 è terminato senza anomalie aperte, OP/3 da più di 7 giorni: non compaiono.
        self.assertEqual([r["id"] for r in j["controlli"]], [salvato.pk, self.controllo.pk])

    def test_il_collega_legge_ma_non_scrive_prima_di_partecipare(self):
        self.client.force_login(self.luca)
        r = self.client.get(reverse("api_anomalie_controllo_dettaglio", args=[self.controllo.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["mio"])
        r = self._post(reverse("api_anomalie_controllo_bozza", args=[self.controllo.pk]), {"bozza": {}})
        self.assertEqual(r.status_code, 403)
        self.assertIn("«Partecipa»", r.json()["error"])
        self.controllo.refresh_from_db()
        self.assertEqual(self.controllo.bozza, BOZZA)

    def test_partecipa_lavorano_insieme_ognuno_con_la_sua_bozza(self):
        self.client.force_login(self.luca)
        with patch("anomalie.views._current_user_identity", return_value={"name": "Luca Verdi"}):
            r = self._post(reverse("api_anomalie_controllo_prendi", args=[self.controllo.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["controllo"]["bozza"], {})  # la bozza di Anna resta sua
        self.controllo.refresh_from_db()
        self.assertEqual(self.controllo.operatore_id, self.anna.pk)  # nessuno perde il controllo
        self.assertTrue(AnomaliaControlloPartecipante.objects.filter(controllo=self.controllo, user=self.luca).exists())
        self.assertTrue(self.controllo.passaggi[-1]["partecipa"])
        self.assertIn("Luca Verdi si è unito al tuo controllo", Notifica.objects.get(legacy_user_id=9101).messaggio)
        # Luca scrive il suo blocco; Anna continua con il suo.
        mio = {"voci": ["LCN00060"], "anomalie": [{"testo": "Graffio"}]}
        r = self._post(reverse("api_anomalie_controllo_bozza", args=[self.controllo.pk]), {"bozza": mio})
        self.assertEqual(r.status_code, 200)
        self.client.force_login(self.anna)
        r = self._post(reverse("api_anomalie_controllo_bozza", args=[self.controllo.pk]), {"bozza": BOZZA})
        self.assertEqual(r.status_code, 200)
        self.controllo.refresh_from_db()
        self.assertEqual(self.controllo.bozza, BOZZA)
        self.assertEqual(AnomaliaControlloPartecipante.objects.get(user=self.luca).bozza, mio)
        # Ognuno vede chi sta scrivendo e su quali S/N.
        d = self.client.get(reverse("api_anomalie_controllo_dettaglio", args=[self.controllo.pk])).json()
        luca = next(p for p in d["controllo"]["partecipanti"] if p["nome"] == "Luca Verdi")
        self.assertEqual((luca["scrive"], luca["seriali"], luca["mio"]), (True, ["LCN00060"], False))
        self.assertTrue(next(p for p in d["controllo"]["partecipanti"] if p["mio"])["presente"])

    def test_lo_termina_chiunque_e_gli_altri_ricevono_l_avviso(self):
        AnomaliaControlloPartecipante.objects.create(controllo=self.controllo, user=self.luca, nome="Luca Verdi")
        self.client.force_login(self.luca)
        with patch("anomalie.views._current_user_identity", return_value={"name": "Luca Verdi"}):
            r = self._post(reverse("api_anomalie_controllo_termina", args=[self.controllo.pk]))
        self.assertEqual(r.status_code, 200, r.content)
        self.controllo.refresh_from_db()
        self.assertIsNotNone(self.controllo.terminato_at)
        self.assertEqual(self.controllo.bozza, BOZZA)  # il blocco non salvato di Anna resta in bozza
        self.assertIn("Luca Verdi ha terminato il controllo", Notifica.objects.get(legacy_user_id=9101).messaggio)
        self.assertFalse(Notifica.objects.filter(legacy_user_id=9102).exists())

    def test_prendere_un_terminato_non_si_puo(self):
        AnomaliaControllo.objects.filter(pk=self.controllo.pk).update(terminato_at=timezone.now())
        self.client.force_login(self.luca)
        r = self._post(reverse("api_anomalie_controllo_prendi", args=[self.controllo.pk]))
        self.assertEqual(r.status_code, 409)


@override_settings(LEGACY_AUTH_ENABLED=False, SETUP_WIZARD_REQUIRED=False, SECURE_SSL_REDIRECT=False)
class RiapriControlloTests(_GruppoBase):
    """Il turno dopo aggiunge i seriali rimasti: niente limite di giorni e un controllo
    terminato con anomalie ancora aperte si riapre (20/11/2026)."""

    def _metti_anomalia(self, controllo, anomalia_id):
        from anomalie.quality_models import AnomaliaBlocco, AnomaliaSegnalazioneMeta

        blocco = AnomaliaBlocco.objects.create(controllo=controllo, ordine=1, fase=controllo.fase,
                                               seriali=["LCN00001"], seriale_label="LCN00001")
        AnomaliaSegnalazioneMeta.objects.create(anomalia_id=anomalia_id, fase=controllo.fase,
                                                controllo=controllo, blocco=blocco)

    def _termina(self, aperte: bool):
        AnomaliaControllo.objects.filter(pk=self.controllo.pk).update(terminato_at=timezone.now(), bozza={})
        self.controllo.refresh_from_db()
        self._metti_anomalia(self.controllo, 501)
        righe = {501: {"id": 501, "chiudere": not aperte}}
        p = patch("anomalie.controllo_service.carica_righe", side_effect=lambda ids: {i: righe[i] for i in ids if i in righe})
        p.start()
        self.addCleanup(p.stop)

    def test_conta_le_anomalie_aperte(self):
        self._termina(aperte=True)
        self.assertEqual(cs.anomalie_aperte_per_controllo([self.controllo]), {self.controllo.pk: 1})
        self.assertTrue(cs.riapribile(self.controllo))

    def test_controllo_vecchio_resta_da_riprendere(self):
        AnomaliaControllo.objects.filter(pk=self.controllo.pk).update(created_at=timezone.now() - timedelta(days=60))
        self.client.force_login(self.luca)
        with patch("anomalie.views._can_create_anomalie_for_op", return_value=True):
            j = self.client.get(reverse("api_anomalie_controlli_sospesi")).json()
        self.assertEqual([r["id"] for r in j["controlli"]], [self.controllo.pk])

    def test_il_collega_riapre_un_terminato_con_anomalie_aperte(self):
        self._termina(aperte=True)
        self.client.force_login(self.luca)
        with patch("anomalie.views._current_user_identity", return_value={"name": "Luca Verdi"}):
            r = self._post(reverse("api_anomalie_controllo_prendi", args=[self.controllo.pk]))
        self.assertEqual(r.status_code, 200, r.content)
        self.assertFalse(r.json()["controllo"]["terminato"])
        self.controllo.refresh_from_db()
        self.assertIsNone(self.controllo.terminato_at)
        self.assertEqual(self.controllo.operatore_id, self.anna.pk)
        self.assertTrue(AnomaliaControlloPartecipante.objects.filter(controllo=self.controllo, user=self.luca).exists())
        self.assertTrue(self.controllo.passaggi[-1]["riaperto"])
        self.assertIn("Luca Verdi ha riaperto e si è unito al tuo controllo", Notifica.objects.get(legacy_user_id=9101).messaggio)

    def test_chi_lo_aveva_lo_riapre_senza_avvisi(self):
        self._termina(aperte=True)
        self.client.force_login(self.anna)
        with patch("anomalie.views._current_user_identity", return_value={"name": "Anna Bianchi"}):
            r = self._post(reverse("api_anomalie_controllo_prendi", args=[self.controllo.pk]))
        self.assertEqual(r.status_code, 200, r.content)
        self.controllo.refresh_from_db()
        self.assertIsNone(self.controllo.terminato_at)
        self.assertFalse(Notifica.objects.filter(legacy_user_id=9101).exists())

    def test_terminato_con_tutto_chiuso_non_si_riapre(self):
        self._termina(aperte=False)
        self.client.force_login(self.luca)
        r = self._post(reverse("api_anomalie_controllo_prendi", args=[self.controllo.pk]))
        self.assertEqual(r.status_code, 409)
        self.controllo.refresh_from_db()
        self.assertIsNotNone(self.controllo.terminato_at)

    def test_chi_apre_segnalazioni_sull_op_vede_e_riapre_anche_fuori_dal_gruppo(self):
        self._termina(aperte=True)
        self.client.force_login(self.esterno)
        with patch("anomalie.views._can_create_anomalie_for_op", return_value=True):
            j = self.client.get(reverse("api_anomalie_controlli"), {"op_id": "OP/2026/4545"}).json()
            self.assertEqual([(c["id"], c["terminato"], c["anomalie_aperte"]) for c in j["controlli"]],
                             [(self.controllo.pk, True, 1)])
            r = self._post(reverse("api_anomalie_controllo_prendi", args=[self.controllo.pk]))
        self.assertEqual(r.status_code, 200, r.content)

    def test_elenco_dell_op_non_propone_terminati_tutti_chiusi(self):
        self._termina(aperte=False)
        self.client.force_login(self.esterno)
        with patch("anomalie.views._can_create_anomalie_for_op", return_value=True):
            j = self.client.get(reverse("api_anomalie_controlli"), {"op_id": "OP/2026/4545"}).json()
        self.assertEqual(j["controlli"], [])
