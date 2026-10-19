"""Destinatari della mail del controllo OP: anteprima, persone aggiunte in copia.

Le persone aggiuntive ricevono la stessa mail con il link di decisione: si accettano
solo indirizzi di persone in anagrafica. Dati sintetici.
"""
from __future__ import annotations

import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from anomalie import controllo_service as cs
from anomalie.quality_models import AnomaliaBlocco, AnomaliaControllo, AnomaliaSegnalazioneMeta
from anomalie.tests_controllo import OP, LegacyTableMixin, _salva_finta

User = get_user_model()
PROMEMORIA = 15  # default di Configurazione → Notifiche

PERSONE = [
    # (nome, cognome, email login, email notifica, attivo)
    ("Mario", "Rossi", "m.rossi", "mario.rossi@example.local", 1),
    ("Anna", "Verdi", "a.verdi", "anna.verdi@example.local", 1),
    ("Senza", "Mail", "s.mail", "", 1),
    ("Ex", "Cessato", "e.cessato", "ex.cessato@example.local", 0),
]

CC_CAR = (
    {"email": "cc@example.local", "display": "Capocommessa Test", "role": "CC"},
    {"email": "car@example.local", "display": "CAR Test", "role": "CAR"},
)


class AnagraficaMixin:
    def crea_anagrafica(self):
        from core.legacy_utils import legacy_table_columns

        legacy_table_columns.cache_clear()
        self.addCleanup(legacy_table_columns.cache_clear)
        self._anag_creata = "anagrafica_dipendenti" not in connection.introspection.table_names()
        with connection.cursor() as cur:
            if self._anag_creata:
                cur.execute(
                    "CREATE TABLE anagrafica_dipendenti (id INTEGER PRIMARY KEY AUTOINCREMENT, aliasusername TEXT, "
                    "nome TEXT, cognome TEXT, mansione TEXT, reparto TEXT, email TEXT, email_notifica TEXT, "
                    "utente_id INTEGER, attivo INTEGER DEFAULT 1)"
                )
            for nome, cognome, login, notifica, attivo in PERSONE:
                cur.execute(
                    "INSERT INTO anagrafica_dipendenti (nome, cognome, email, email_notifica, attivo) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    [nome, cognome, login, notifica, attivo],
                )

    def elimina_anagrafica(self):
        if self._anag_creata:
            with connection.cursor() as cur:
                cur.execute("DROP TABLE anagrafica_dipendenti")


class PersoneServiceTests(AnagraficaMixin, TestCase):
    def setUp(self):
        self.crea_anagrafica()

    def tearDown(self):
        self.elimina_anagrafica()

    def test_ricerca_per_nome_e_email_solo_con_email_di_notifica(self):
        self.assertEqual(cs.cerca_persone("rossi"), [{"email": "mario.rossi@example.local", "nome": "ROSSI MARIO"}])
        self.assertEqual([p["email"] for p in cs.cerca_persone("anna.verdi@")], ["anna.verdi@example.local"])
        self.assertEqual(cs.cerca_persone("Senza"), [])
        self.assertEqual(cs.cerca_persone("cessato"), [])
        self.assertIsNone(cs.persona_da_email("ex.cessato@example.local"))
        self.assertEqual(cs.cerca_persone("r"), [])

    def test_normalizza_rilegge_dall_anagrafica_e_rifiuta_gli_sconosciuti(self):
        validi, rifiutati = cs.normalizza_destinatari_extra([
            {"email": "MARIO.ROSSI@example.local", "nome": "Nome inventato"},
            "anna.verdi@example.local",
            "mario.rossi@example.local",  # doppione
            "esterno@altrodominio.example",
        ])
        self.assertEqual(validi, [
            {"email": "mario.rossi@example.local", "nome": "ROSSI MARIO"},
            {"email": "anna.verdi@example.local", "nome": "VERDI ANNA"},
        ])
        self.assertEqual(rifiutati, ["esterno@altrodominio.example"])

    def test_altro_capocommessa_dalla_lista_configurata(self):
        with patch("anomalie.views._load_anomalie_lists",
                   return_value={"capi_commessa": ["Verdi Anna", "mario  rossi", "Non In Anagrafica", "Cessato Ex"]}):
            self.assertEqual(cs.capi_commessa_persone(), [
                {"email": "mario.rossi@example.local", "nome": "ROSSI MARIO"},
                {"email": "anna.verdi@example.local", "nome": "VERDI ANNA"},
            ])


@override_settings(LEGACY_AUTH_ENABLED=False, SETUP_WIZARD_REQUIRED=False, SECURE_SSL_REDIRECT=False)
class DestinatariApiTests(AnagraficaMixin, LegacyTableMixin, TestCase):
    def setUp(self):
        self.crea_tabella()
        self.crea_anagrafica()
        self.user = User.objects.create_superuser(username="ctl-dest", password="pass12345", email="op@example.local")
        self.client.force_login(self.user)
        self._patches = [
            patch("anomalie.views._can_edit_anomalie_for_op", return_value=True),
            patch.object(cs, "_destinatari", return_value=CC_CAR),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.elimina_anagrafica()
        self.elimina_tabella()

    def post(self, name, body, pk=None):
        url = reverse(name, args=[pk]) if pk else reverse(name)
        return self.client.post(url, data=json.dumps(body), content_type="application/json")

    def test_anteprima_destinatari_prima_di_aprire_il_controllo(self):
        r = self.client.get(reverse("api_anomalie_controllo_destinatari"), {"op_id": OP})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["destinatari"]["to"], "Capocommessa Test")
        self.assertEqual(r.json()["destinatari"]["cc_email"], "car@example.local")

    def test_anteprima_mostra_le_liste_di_configurazione(self):
        liste = {"conferma_aggiornamenti": ["anna.verdi@example.local", "qualita@example.local"],
                 "rdc_segnalazione": ["rdc@example.local"]}
        with patch("anomalie.mail_action_service._resolve_lista_config", side_effect=lambda k: liste.get(k, [])):
            d = self.client.get(reverse("api_anomalie_controllo_destinatari"), {"op_id": OP}).json()["destinatari"]
        self.assertEqual(d["riepilogo"], [
            {"email": "anna.verdi@example.local", "nome": "VERDI ANNA"},
            {"email": "qualita@example.local", "nome": "qualita@example.local"},
        ])
        self.assertEqual(d["riepilogo_rdc"], [{"email": "rdc@example.local", "nome": "rdc@example.local"}])

    def test_anteprima_negata_senza_permesso_sull_op(self):
        with patch("anomalie.views._can_edit_anomalie_for_op", return_value=False):
            r = self.client.get(reverse("api_anomalie_controllo_destinatari"), {"op_id": OP})
        self.assertEqual(r.status_code, 403)

    def test_ricerca_persone(self):
        r = self.client.get(reverse("api_anomalie_controllo_persone"), {"q": "verdi"})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["results"], [{"email": "anna.verdi@example.local", "nome": "VERDI ANNA"}])

    def test_apri_con_persone_in_copia_e_modifica_successiva(self):
        r = self.post("api_anomalie_controllo_apri", {
            "op_id": OP, "fase": "Collaudo", "destinatari_extra": [{"email": "mario.rossi@example.local"}],
        })
        self.assertEqual(r.status_code, 200, r.content)
        cid = r.json()["controllo"]["id"]
        self.assertEqual(r.json()["controllo"]["destinatari_extra"], [{"email": "mario.rossi@example.local", "nome": "ROSSI MARIO"}])

        r = self.post("api_anomalie_controllo_impostazioni", {"destinatari_extra": ["anna.verdi@example.local"]}, cid)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(AnomaliaControllo.objects.get(pk=cid).destinatari_extra,
                         [{"email": "anna.verdi@example.local", "nome": "VERDI ANNA"}])
        d = self.client.get(reverse("api_anomalie_controllo_dettaglio", args=[cid])).json()
        self.assertEqual(d["destinatari"]["extra"], [{"email": "anna.verdi@example.local", "nome": "VERDI ANNA"}])

    def test_nuovi_controlli_sempre_a_fine_controllo(self):
        r = self.post("api_anomalie_controllo_apri", {"op_id": OP, "fase": "Collaudo", "mail_mode": "subito"})
        self.assertEqual(r.json()["controllo"]["mail_mode"], "fine")
        cid = r.json()["controllo"]["id"]
        self.post("api_anomalie_controllo_impostazioni", {"mail_mode": "subito"}, cid)
        self.assertEqual(AnomaliaControllo.objects.get(pk=cid).mail_mode, "fine")

    def test_lista_capicommessa_via_api(self):
        with patch.object(cs, "capi_commessa_persone", return_value=[{"email": "x@example.local", "nome": "X"}]):
            r = self.client.get(reverse("api_anomalie_controllo_persone"), {"ruolo": "capocommessa"})
        self.assertEqual(r.json()["results"], [{"email": "x@example.local", "nome": "X"}])

    def test_indirizzo_non_in_anagrafica_rifiutato(self):
        r = self.post("api_anomalie_controllo_apri", {
            "op_id": OP, "fase": "Collaudo", "destinatari_extra": ["esterno@altrodominio.example"],
        })
        self.assertEqual(r.status_code, 400)
        self.assertIn("esterno@altrodominio.example", r.json()["error"])
        self.assertFalse(AnomaliaControllo.objects.exists())


@override_settings(
    LEGACY_AUTH_ENABLED=False, SETUP_WIZARD_REQUIRED=False, SECURE_SSL_REDIRECT=False,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", SITE_URL="https://hub.example.local",
)
class MailConCopiaTests(LegacyTableMixin, TestCase):
    def setUp(self):
        self.crea_tabella()
        self.user = User.objects.create_user(username="ctl-copia", password="pass12345")
        self.controllo = AnomaliaControllo.objects.create(
            op_id=OP, fase="Lavorazione", operatore=self.user, operatore_display="Operatore Test",
            destinatari_extra=[
                {"email": "mario.rossi@example.local", "nome": "ROSSI MARIO"},
                {"email": "CAR@example.local", "nome": "Doppione del CAR"},
            ],
        )
        blocco = AnomaliaBlocco.objects.create(
            controllo=self.controllo, ordine=1, fase="Lavorazione", seriali=["LCN00001"], seriale_label="LCN00001",
        )
        r = _salva_finta(None, {"op_id": OP, "sn": "LCN00001", "desc": "Graffio", "avanzamento": "In attesa"})
        AnomaliaSegnalazioneMeta.objects.create(
            anomalia_id=r["local_id"], fase="Lavorazione", controllo=self.controllo, blocco=blocco,
        )
        cs.accoda_notifica(self.controllo, [r["local_id"]])

    def tearDown(self):
        self.elimina_tabella()

    def test_persone_aggiunte_in_copia_senza_doppioni(self):
        with patch.object(cs, "_destinatari", return_value=CC_CAR), \
                patch("anomalie.mail_action_service.send_anomalie_update_confirmation", return_value=True):
            esito = cs.invia_mail_controllo(self.controllo)
        self.assertTrue(esito["sent"])
        self.assertEqual(esito["extra"], ["ROSSI MARIO"])
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["cc@example.local"])
        self.assertEqual(mail.outbox[0].cc, ["car@example.local", "mario.rossi@example.local"])


@override_settings(
    LEGACY_AUTH_ENABLED=False, SETUP_WIZARD_REQUIRED=False, SECURE_SSL_REDIRECT=False,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", SITE_URL="https://hub.example.local",
)
class PromemoriaControlloreTests(LegacyTableMixin, TestCase):
    def setUp(self):
        from core.models import Profile

        self.crea_tabella()
        self.user = User.objects.create_user(username="ctl-prom", password="pass12345", email="controllore@example.local")
        Profile.objects.create(user=self.user, legacy_user_id=9701)
        self.controllo = AnomaliaControllo.objects.create(
            op_id=OP, fase="Collaudo", operatore=self.user, operatore_display="Controllore Test",
        )
        blocco = AnomaliaBlocco.objects.create(
            controllo=self.controllo, ordine=1, fase="Collaudo", seriali=["LCN00009"], seriale_label="LCN00009",
        )
        r = _salva_finta(None, {"op_id": OP, "sn": "LCN00009", "desc": "Foro fuori quota", "avanzamento": "In attesa"})
        AnomaliaSegnalazioneMeta.objects.create(
            anomalia_id=r["local_id"], fase="Collaudo", controllo=self.controllo, blocco=blocco,
        )
        cs.accoda_notifica(self.controllo, [r["local_id"]])

    def tearDown(self):
        self.elimina_tabella()

    def fermo_da(self, minuti):
        AnomaliaControllo.objects.filter(pk=self.controllo.pk).update(
            ultimo_salvataggio_at=timezone.now() - timedelta(minutes=minuti))

    def test_promemoria_dopo_15_minuti_una_volta_per_pausa(self):
        from core.models import Notifica

        self.assertEqual(self.controllo.mail_mode, "fine")
        with patch.object(cs, "invia_mail_controllo") as invio:
            self.fermo_da(PROMEMORIA - 2)
            self.assertEqual(cs.flush_controlli()["controlli_promemoria"], 0)
            self.fermo_da(PROMEMORIA + 1)
            self.assertEqual(cs.flush_controlli()["controlli_promemoria"], 1)
            self.assertEqual(cs.flush_controlli()["controlli_promemoria"], 0)  # niente doppioni
            invio.assert_not_called()  # la mail al capocommessa aspetta il controllore
        n = Notifica.objects.get(legacy_user_id=9701, tipo=cs.TIPO_NOTIFICA_PROMEMORIA)
        self.assertIn("Termina controllo", n.messaggio)
        self.assertIn("nuova-segnalazione?op_id=OP/2026/0042", n.url_azione)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["controllore@example.local"])
        self.assertIn("Foro fuori quota", mail.outbox[0].body)
        self.assertIn("https://hub.example.local/gestione-anomalie/nuova-segnalazione?op_id=", mail.outbox[0].body)
        self.assertIn("partirà da sola 1 ora dopo", mail.outbox[0].body)

        # Un nuovo salvataggio riarma il promemoria.
        cs.accoda_notifica(self.controllo, [])
        self.controllo.refresh_from_db()
        self.assertIsNone(self.controllo.promemoria_at)

    def test_niente_promemoria_a_controllo_terminato(self):
        AnomaliaControllo.objects.filter(pk=self.controllo.pk).update(terminato_at=timezone.now())
        self.fermo_da(PROMEMORIA + 1)
        with patch.object(cs, "invia_mail_controllo", return_value={"sent": True}):
            esito = cs.flush_controlli()
        self.assertEqual(esito["controlli_promemoria"], 0)
        self.assertEqual(esito["controlli_inviati"], 1)


@override_settings(LEGACY_AUTH_ENABLED=False, SETUP_WIZARD_REQUIRED=False, SECURE_SSL_REDIRECT=False)
class BozzaAutomaticaTests(LegacyTableMixin, TestCase):
    def setUp(self):
        self.crea_tabella()
        self.user = User.objects.create_superuser(username="ctl-bozza", password="pass12345", email="b@example.local")
        self.client.force_login(self.user)
        self._patches = [
            patch("anomalie.views._can_edit_anomalie_for_op", return_value=True),
            patch("anomalie.views._salva_riga_anomalia", side_effect=_salva_finta),
            patch("anomalie.controllo_views._sync_scheda"),
            patch("anomalie.controllo_service._allegati", return_value=[]),
            patch("anomalie.controllo_service.stati_superficie_configurati", return_value=False),
        ]
        for p in self._patches:
            p.start()
        r = self.post("api_anomalie_controllo_apri", {"op_id": OP, "fase": "Collaudo"})
        self.cid = r.json()["controllo"]["id"]

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.elimina_tabella()

    def post(self, name, body, pk=None):
        url = reverse(name, args=[pk]) if pk else reverse(name)
        return self.client.post(url, data=json.dumps(body), content_type="application/json")

    def test_bozza_salvata_ripresa_e_svuotata_dal_salvataggio_del_blocco(self):
        bozza = {"bloccoId": None, "voci": ["LCN00001"], "stati": [],
                 "anomalie": [{"localId": None, "testo": "Graffio in corso di scrittura", "tutti": True, "sel": [], "allegati": 1}]}
        r = self.post("api_anomalie_controllo_bozza", {"bozza": bozza}, self.cid)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()["bozza_at"])
        d = self.client.get(reverse("api_anomalie_controllo_dettaglio", args=[self.cid])).json()
        self.assertEqual(d["controllo"]["bozza"], bozza)

        r = self.post("api_anomalie_controllo_blocco", {
            "seriali": ["LCN00001"], "anomalie": [{"testo": "Graffio"}],
        }, self.cid)
        self.assertEqual(r.status_code, 200, r.content)
        c = AnomaliaControllo.objects.get(pk=self.cid)
        self.assertEqual(c.bozza, {})
        self.assertIsNone(c.bozza_at)

    def test_bozza_vuota_cancella_e_troppo_grande_rifiutata(self):
        self.post("api_anomalie_controllo_bozza", {"bozza": {"voci": ["LCN00001"]}}, self.cid)
        self.post("api_anomalie_controllo_bozza", {"bozza": {}}, self.cid)
        self.assertEqual(AnomaliaControllo.objects.get(pk=self.cid).bozza, {})
        r = self.post("api_anomalie_controllo_bozza", {"bozza": {"testo": "x" * (cs.MAX_BOZZA_BYTES + 1)}}, self.cid)
        self.assertEqual(r.status_code, 413)

    def test_bozza_solo_del_proprio_controllo(self):
        altro = User.objects.create_user(username="ctl-altro", password="pass12345")
        self.client.force_login(altro)
        r = self.post("api_anomalie_controllo_bozza", {"bozza": {"voci": ["X"]}}, self.cid)
        self.assertEqual(r.status_code, 403)
