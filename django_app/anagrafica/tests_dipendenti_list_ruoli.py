"""Ruoli ricoperti mostrati sotto il nome nell'elenco dipendenti.

Il test lavora sull'helper ``ruoli_ricoperti_map`` e non sulla view: l'elenco
dipendenti legge le persone dal DB legacy, che nei test non c'è, mentre la
regola da proteggere (quali ruoli sono «ricoperti» e in che ordine) vive tutta
sui modelli Django.
"""
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from anagrafica.models import DipendenteRuoloOperativo, RuoloOperativo
from anagrafica.views import ruoli_ricoperti_map

User = get_user_model()


class RuoliRicopertiMapTests(TestCase):
    def setUp(self):
        self.preposto = RuoloOperativo.objects.create(nome="Preposto")
        self.operatore = RuoloOperativo.objects.create(nome="Operatore CNC")
        self.dismesso = RuoloOperativo.objects.create(nome="Ruolo dismesso", is_active=False)

    def _assegna(self, legacy_id, ruolo, **extra):
        return DipendenteRuoloOperativo.objects.create(
            legacy_anagrafica_id=legacy_id, ruolo=ruolo, **extra
        )

    def test_mostra_tutti_i_ruoli_col_principale_in_testa(self):
        # "Preposto" verrebbe dopo "Operatore CNC" in ordine alfabetico: è il
        # flag principale a portarlo davanti.
        self._assegna(138, self.operatore)
        self._assegna(138, self.preposto, tipologia=DipendenteRuoloOperativo.TIPOLOGIA_PRINCIPALE)

        voci = ruoli_ricoperti_map([138])[138]
        self.assertEqual([v["nome"] for v in voci], ["Preposto", "Operatore CNC"])
        self.assertEqual([v["principale"] for v in voci], [True, False])

    def test_esclude_assegnazioni_concluse_e_ruoli_disattivati(self):
        ieri = timezone.localdate() - timedelta(days=1)
        self._assegna(139, self.operatore, data_fine=ieri)
        self._assegna(139, self.dismesso)
        self._assegna(139, self.preposto)

        self.assertEqual([v["nome"] for v in ruoli_ricoperti_map([139])[139]], ["Preposto"])

    def test_ruolo_con_fine_futura_e_ancora_ricoperto(self):
        domani = timezone.localdate() + timedelta(days=1)
        self._assegna(140, self.preposto, data_fine=domani)

        self.assertEqual([v["nome"] for v in ruoli_ricoperti_map([140])[140]], ["Preposto"])

    def test_senza_id_nessuna_query(self):
        self.assertEqual(ruoli_ricoperti_map([]), {})
        self.assertEqual(ruoli_ricoperti_map([0, None]), {})

    def test_dipendente_senza_ruoli_non_e_in_mappa(self):
        self._assegna(141, self.preposto)

        mappa = ruoli_ricoperti_map([141, 142])
        self.assertIn(141, mappa)
        self.assertNotIn(142, mappa)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class DipendentiListRuoliRenderTests(TestCase):
    """L'elenco mostra i ruoli sotto il nome.

    Le persone arrivano dal DB legacy, che nei test non c'è: si sostituisce la
    sola sorgente delle righe, lasciando in piedi view e template veri.
    """

    def setUp(self):
        self.admin = User.objects.create_superuser("dip-ruoli", "dip-ruoli@test.local", "x")
        self.client.force_login(self.admin)
        ruolo = RuoloOperativo.objects.create(nome="Responsabile Controllo")
        DipendenteRuoloOperativo.objects.create(
            legacy_anagrafica_id=138,
            ruolo=ruolo,
            tipologia=DipendenteRuoloOperativo.TIPOLOGIA_PRINCIPALE,
        )

    def _get(self):
        righe = [{
            "id": 138, "utente_id": 0, "nome": "Derya", "cognome": "Aksoy",
            "reparto": "AGG/MONT", "mansione": "", "matricola": "0138",
            "aliasusername": "d.aksoy", "email_notifica": "", "attivo": True,
        }]
        patches = (
            mock.patch("anagrafica.views._dipendenti_base_rows", return_value=righe),
            mock.patch("anagrafica.views._cessati_legacy_ids", return_value=set()),
            mock.patch(
                "anagrafica.views.count_anagrafica_statuses",
                return_value={"active": 1, "inactive": 0},
            ),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        return self.client.get(reverse("anagrafica:dipendenti_list"))

    def test_ruolo_principale_reso_sotto_il_nome(self):
        resp = self._get()
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('class="fmd-role fmd-role-main"', body)
        self.assertIn("Responsabile Controllo", body)

    def test_username_e_matricola_restano_cercabili_dal_filtro_live(self):
        body = self._get().content.decode()
        self.assertIn('class="fmd-sr-only">d.aksoy 0138<', body)

    def test_nessun_commento_di_template_finisce_a_video(self):
        # Il commento `{# #}` di Django vale per UNA riga sola: scritto su due,
        # la prima finisce stampata nella cella accanto al nome.
        body = self._get().content.decode()
        self.assertNotIn("Termini della ricerca", body)
        self.assertNotIn("{#", body)
