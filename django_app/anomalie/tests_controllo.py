"""Controllo OP a blocchi di seriali: seriali, API del controllo, mail al capocommessa
e pagina di decisione raggiunta dalla mail.

La tabella legacy ``anomalie`` è creata in SQLite; ``_salva_riga_anomalia`` (che su
SQL Server usa SCOPE_IDENTITY) è sostituita da un inserimento equivalente.
Dati sintetici.
"""
from __future__ import annotations

import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.db import connection
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from anomalie import controllo_service as cs
from anomalie.quality_models import AnomaliaBlocco, AnomaliaControllo, AnomaliaSegnalazioneMeta
from anomalie.seriali import conta_pezzi, espandi_seriale_composito, etichetta_blocco, normalizza_voci

User = get_user_model()
OP = "OP/2026/0042"


class SerialiTests(SimpleTestCase):
    def test_range_espanso_con_zeri(self):
        self.assertEqual(
            espandi_seriale_composito("LCN00008-LCN00010"),
            ["LCN00008", "LCN00009", "LCN00010"],
        )

    def test_range_abbreviato(self):
        self.assertEqual(espandi_seriale_composito("LCN00008-10"), ["LCN00008", "LCN00009", "LCN00010"])

    def test_lista_con_range_e_suffisso_pezzi(self):
        tokens = espandi_seriale_composito("LCN00001, LCN00005-LCN00006 (3 pezzi)")
        self.assertEqual(tokens, ["LCN00001", "LCN00005", "LCN00006"])

    def test_prefissi_diversi_non_sono_un_range(self):
        self.assertEqual(espandi_seriale_composito("LCN00001-ABC00003"), ["LCN00001-ABC00003"])

    def test_range_troppo_ampio_resta_testo(self):
        self.assertEqual(espandi_seriale_composito("A1-A5000"), ["A1-A5000"])

    def test_etichetta_e_conteggio(self):
        voci = normalizza_voci(["LCN00005 - LCN00010", "lcn00005-lcn00010", "LCN00020"])
        self.assertEqual(voci, ["LCN00005-LCN00010", "LCN00020"])
        self.assertEqual(conta_pezzi(voci), 7)
        self.assertEqual(etichetta_blocco(voci), "LCN00005-LCN00010, LCN00020 (7 pezzi)")
        self.assertEqual(etichetta_blocco(["LCN00001"]), "LCN00001")

    def test_descrizione_con_stato_superficie(self):
        testo = cs.componi_descrizione("Graffio sulla flangia", ["Finito trattato"])
        self.assertEqual(cs.separa_descrizione(testo), (["Finito trattato"], "Graffio sulla flangia"))
        self.assertEqual(cs.separa_descrizione("Solo testo"), ([], "Solo testo"))

    def test_riga_gestita(self):
        self.assertFalse(cs.riga_gestita({"avanzamento": "In attesa"}))
        self.assertTrue(cs.riga_gestita({"avanzamento": "Accetto lo stato"}))
        self.assertTrue(cs.riga_gestita({"avanzamento": "In attesa", "aprire_rdc": 1}))
        self.assertTrue(cs.riga_gestita({"avanzamento": "", "note_capocommessa": "rilavorare"}))


class InsertIdTests(SimpleTestCase):
    """Su SQL Server l'id si legge nello stesso batch; i trigger possono anteporre result set."""

    class _Cursor:
        def __init__(self, sets):
            self.sets = sets
            self.i = 0
            self.sql = ""

        def execute(self, sql, params):
            self.sql = sql

        @property
        def description(self):
            cols = self.sets[self.i][0]
            return [(c,) for c in cols] if cols else None

        def fetchone(self):
            return self.sets[self.i][1]

        def nextset(self):
            self.i += 1
            return self.i < len(self.sets)

    def _run(self, sets):
        from anomalie import views

        cur = self._Cursor(sets)
        with patch.object(views, "connections") as conns:
            conns.__getitem__.return_value.vendor = "microsoft"
            return views._insert_anomalia_return_id(cur, "[descrizione]", "%s", ["x"]), cur.sql

    def test_id_letto_nello_stesso_batch(self):
        local_id, sql = self._run([(["nuova_anomalia_id"], (42,))])
        self.assertEqual(local_id, 42)
        self.assertIn("OUTPUT INSERTED.id INTO @nuove_anomalie", sql)
        self.assertNotIn("SCOPE_IDENTITY", sql)

    def test_result_set_dei_trigger_ignorati(self):
        local_id, _ = self._run([(["coda_id"], (999,)), (None, None), (["nuova_anomalia_id"], (7,))])
        self.assertEqual(local_id, 7)

    def test_nessun_id(self):
        local_id, _ = self._run([(None, None)])
        self.assertIsNone(local_id)


class LegacyTableMixin:
    def crea_tabella(self):
        with connection.cursor() as cur:
            cur.execute(
                "CREATE TABLE anomalie (id INTEGER PRIMARY KEY AUTOINCREMENT, ex_op_nominativo TEXT, seriale TEXT, "
                "descrizione TEXT, note_capocommessa TEXT, aprire_rdc INTEGER, numero_rdc TEXT, "
                "segnalare_cliente INTEGER, chiudere INTEGER, avanzamento TEXT, pezzo_recuperato INTEGER)"
            )

    def elimina_tabella(self):
        with connection.cursor() as cur:
            cur.execute("DROP TABLE anomalie")

    def riga(self, anomalia_id):
        with connection.cursor() as cur:
            cur.execute(
                "SELECT id, seriale, descrizione, avanzamento, aprire_rdc, segnalare_cliente, note_capocommessa,"
                " numero_rdc FROM anomalie WHERE id = %s",
                [anomalia_id],
            )
            r = cur.fetchone()
        keys = ["id", "seriale", "descrizione", "avanzamento", "aprire_rdc", "segnalare_cliente",
                "note_capocommessa", "numero_rdc"]
        return dict(zip(keys, r)) if r else None

    def set_riga(self, anomalia_id, **campi):
        sets = ", ".join(f"{k} = %s" for k in campi)
        with connection.cursor() as cur:
            cur.execute(f"UPDATE anomalie SET {sets} WHERE id = %s", [*campi.values(), anomalia_id])


def _salva_finta(request, data, *, notifica_debounce=True):
    """Equivalente SQLite di ``views._salva_riga_anomalia``."""
    item = str(data.get("item_id") or "")
    with connection.cursor() as cur:
        if item.startswith("local:"):
            local_id = int(item.split(":", 1)[1])
            cur.execute(
                "UPDATE anomalie SET seriale = %s, descrizione = %s, avanzamento = %s WHERE id = %s",
                [data.get("sn"), data.get("desc"), data.get("avanzamento"), local_id],
            )
            return {"success": True, "local_id": local_id, "item_id": item, "created": False}
        cur.execute(
            "INSERT INTO anomalie (ex_op_nominativo, seriale, descrizione, note_capocommessa, aprire_rdc,"
            " segnalare_cliente, chiudere, avanzamento) VALUES (%s, %s, %s, '', 0, 0, 0, %s)",
            [data.get("op_id"), data.get("sn"), data.get("desc"), data.get("avanzamento")],
        )
        cur.execute("SELECT MAX(id) FROM anomalie")
        local_id = int(cur.fetchone()[0])
    return {"success": True, "local_id": local_id, "item_id": f"local:{local_id}", "created": True}


@override_settings(LEGACY_AUTH_ENABLED=False, SETUP_WIZARD_REQUIRED=False, SECURE_SSL_REDIRECT=False)
class ControlloApiTests(LegacyTableMixin, TestCase):
    def setUp(self):
        self.crea_tabella()
        self.user = User.objects.create_superuser(username="ctl-op", password="pass12345", email="op@example.local")
        self.client.force_login(self.user)
        self._patches = [
            patch("anomalie.views._can_edit_anomalie_for_op", return_value=True),
            patch("anomalie.views._salva_riga_anomalia", side_effect=_salva_finta),
            patch("anomalie.controllo_views._sync_scheda"),
            patch("anomalie.controllo_service._allegati", return_value=[]),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.elimina_tabella()

    def post(self, name, body, pk=None):
        url = reverse(name, args=[pk]) if pk else reverse(name)
        return self.client.post(url, data=json.dumps(body), content_type="application/json")

    def apri(self, mail_mode="subito"):
        r = self.post("api_anomalie_controllo_apri", {"op_id": OP, "fase": "Collaudo finale", "mail_mode": mail_mode})
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()["controllo"]["id"]

    def test_apri_richiede_fase(self):
        r = self.post("api_anomalie_controllo_apri", {"op_id": OP, "fase": " "})
        self.assertEqual(r.status_code, 400)

    def test_blocco_crea_una_riga_per_anomalia(self):
        cid = self.apri()
        r = self.post("api_anomalie_controllo_blocco", {
            "seriali": ["LCN00005-LCN00007", "LCN00020"],
            "stato_superficie": ["Finito trattato"],
            "anomalie": [{"testo": "Graffio sul diametro esterno"}, {"testo": "Foro fuori quota"}],
        }, cid)
        self.assertEqual(r.status_code, 200, r.content)
        data = r.json()
        ids = [x["local_id"] for x in data["risultati"]]
        self.assertEqual(len(ids), 2)
        for local_id in ids:
            row = self.riga(local_id)
            self.assertEqual(row["seriale"], "LCN00005-LCN00007, LCN00020 (4 pezzi)")
            self.assertTrue(row["descrizione"].startswith("Stato superficie: Finito trattato\n\n"))
        metas = AnomaliaSegnalazioneMeta.objects.filter(anomalia_id__in=ids).order_by("ordine_nel_blocco")
        self.assertEqual([m.ordine_nel_blocco for m in metas], [1, 2])
        self.assertTrue(all(m.controllo_id == cid and m.fase == "Collaudo finale" for m in metas))
        controllo = AnomaliaControllo.objects.get(pk=cid)
        self.assertEqual(controllo.da_notificare, ids)
        blocco = data["controllo"]["blocchi"][0]
        self.assertEqual([a["testo"] for a in blocco["anomalie"]], ["Graffio sul diametro esterno", "Foro fuori quota"])

    def test_blocco_senza_seriali_o_testo_rifiutato(self):
        cid = self.apri()
        r = self.post("api_anomalie_controllo_blocco", {"seriali": [], "anomalie": [{"testo": "x"}]}, cid)
        self.assertEqual(r.status_code, 400)
        r = self.post("api_anomalie_controllo_blocco", {"seriali": ["LCN00001"], "anomalie": [{"testo": ""}]}, cid)
        self.assertEqual(r.status_code, 400)

    def test_riapertura_aggiunge_anomalia_senza_duplicare(self):
        cid = self.apri()
        r = self.post("api_anomalie_controllo_blocco", {"seriali": ["LCN00001"], "anomalie": [{"testo": "Bava"}]}, cid)
        first = r.json()["risultati"][0]["local_id"]
        blocco_id = r.json()["blocco_id"]
        r = self.post("api_anomalie_controllo_blocco", {
            "blocco_id": blocco_id, "seriali": ["LCN00001"],
            "anomalie": [{"local_id": first, "testo": "Bava"}, {"testo": "Ammaccatura"}],
        }, cid)
        self.assertEqual(r.status_code, 200, r.content)
        risultati = r.json()["risultati"]
        self.assertTrue(risultati[0].get("invariata"))
        self.assertEqual(AnomaliaSegnalazioneMeta.objects.filter(blocco_id=blocco_id).count(), 2)
        with connection.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM anomalie")
            self.assertEqual(cur.fetchone()[0], 2)

    def test_anomalia_gestita_blocca_seriali_e_testo(self):
        cid = self.apri()
        r = self.post("api_anomalie_controllo_blocco", {"seriali": ["LCN00001"], "anomalie": [{"testo": "Bava"}]}, cid)
        first = r.json()["risultati"][0]["local_id"]
        blocco_id = r.json()["blocco_id"]
        self.set_riga(first, avanzamento="Accetto lo stato")
        r = self.post("api_anomalie_controllo_blocco", {
            "blocco_id": blocco_id, "seriali": ["LCN00002"], "anomalie": [{"local_id": first, "testo": "Bava"}],
        }, cid)
        self.assertEqual(r.status_code, 409)
        r = self.post("api_anomalie_controllo_blocco", {
            "blocco_id": blocco_id, "seriali": ["LCN00001"], "anomalie": [{"local_id": first, "testo": "Bava grande"}],
        }, cid)
        self.assertEqual(r.status_code, 409)
        self.assertEqual(self.riga(first)["avanzamento"], "Accetto lo stato")

    def test_controllo_di_altro_operatore_negato(self):
        cid = self.apri()
        altro = User.objects.create_user(username="altro", password="pass12345")
        controllo = AnomaliaControllo.objects.get(pk=cid)
        controllo.operatore = altro
        controllo.save()
        # Il superuser può intervenire su ogni controllo: la verifica vale per gli altri utenti.
        from core.models import UserOnboarding
        self.user.is_superuser = False
        self.user.save()
        UserOnboarding.objects.update_or_create(user=self.user, defaults={"completed": True, "skipped": False})
        self.client.force_login(self.user)
        with patch("core.middleware.resolve_acl_access", return_value={"allowed": True}):
            r = self.post("api_anomalie_controllo_blocco", {"seriali": ["LCN00001"], "anomalie": [{"testo": "x"}]}, cid)
        self.assertEqual(r.status_code, 403)

    def test_termina_a_fine_controllo_manda_una_mail(self):
        cid = self.apri(mail_mode="fine")
        self.post("api_anomalie_controllo_blocco", {"seriali": ["LCN00001"], "anomalie": [{"testo": "A"}]}, cid)
        self.post("api_anomalie_controllo_blocco", {"seriali": ["LCN00002-LCN00003"], "anomalie": [{"testo": "B"}, {"testo": "C"}]}, cid)
        with patch("anomalie.controllo_service.invia_mail_controllo", return_value={"sent": True, "to": "CC", "n": 3}) as invio:
            r = self.post("api_anomalie_controllo_termina", {}, cid)
        self.assertEqual(r.status_code, 200)
        invio.assert_called_once()
        self.assertEqual(len(invio.call_args.args[0].da_notificare), 3)
        self.assertIsNotNone(AnomaliaControllo.objects.get(pk=cid).terminato_at)

    def test_elenco_controlli_riprendibili(self):
        cid = self.apri()
        r = self.client.get(reverse("api_anomalie_controlli"), {"op_id": OP})
        self.assertEqual(r.status_code, 200)
        self.assertEqual([c["id"] for c in r.json()["controlli"]], [cid])
        self.assertIn("Collaudo finale", r.json()["fasi"])


@override_settings(
    LEGACY_AUTH_ENABLED=False, SETUP_WIZARD_REQUIRED=False, SECURE_SSL_REDIRECT=False,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", SITE_URL="https://hub.example.local",
)
class ControlloMailTests(LegacyTableMixin, TestCase):
    def setUp(self):
        self.crea_tabella()
        self.user = User.objects.create_user(username="ctl-mail", password="pass12345")
        self.controllo = AnomaliaControllo.objects.create(
            op_id=OP, fase="Lavorazione", operatore=self.user, operatore_display="Operatore Test",
        )
        self.blocco = AnomaliaBlocco.objects.create(
            controllo=self.controllo, ordine=1, fase="Lavorazione", seriali=["LCN00001-LCN00002"],
            seriale_label="LCN00001-LCN00002 (2 pezzi)",
        )
        self.ids = []
        for testo in ("Graffio", "Bava"):
            r = _salva_finta(None, {"op_id": OP, "sn": self.blocco.seriale_label, "desc": testo, "avanzamento": "In attesa"})
            AnomaliaSegnalazioneMeta.objects.create(
                anomalia_id=r["local_id"], fase="Lavorazione", controllo=self.controllo, blocco=self.blocco,
            )
            self.ids.append(r["local_id"])
        self._patches = [
            patch.object(cs, "_destinatari", return_value=(
                {"email": "cc@example.local", "display": "Capocommessa Test", "role": "CC"},
                {"email": "car@example.local", "display": "CAR Test", "role": "CAR"},
            )),
            patch("anomalie.mail_action_service.send_anomalie_update_confirmation", return_value=True),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.elimina_tabella()

    def test_invio_con_link_e_raggruppamento(self):
        cs.accoda_notifica(self.controllo, self.ids)
        esito = cs.invia_mail_controllo(self.controllo)
        self.assertTrue(esito["sent"])
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.to, ["cc@example.local"])
        self.assertEqual(msg.cc, ["car@example.local"])
        self.assertIn("/gestione-anomalie/mail-action/", msg.body)
        self.assertIn("S/N LCN00001-LCN00002 (2 pezzi)", msg.body)
        self.assertIn("Fase Lavorazione", msg.body)
        self.controllo.refresh_from_db()
        self.assertEqual(self.controllo.da_notificare, [])
        from anomalie.mail_action_models import AnomaliaMailActionToken
        token = AnomaliaMailActionToken.objects.get()
        self.assertEqual(sorted(token.anomalie_ids), sorted(self.ids))
        self.assertEqual(token.action, "aggiorna_avanzamento")

    def test_errore_destinatari_resta_in_coda(self):
        cs.accoda_notifica(self.controllo, self.ids)
        with patch.object(cs, "_destinatari", return_value=(None, None)):
            esito = cs.invia_mail_controllo(self.controllo)
        self.assertFalse(esito["sent"])
        self.controllo.refresh_from_db()
        self.assertEqual(self.controllo.da_notificare, self.ids)
        self.assertEqual(self.controllo.mail_tentativi, 1)
        self.assertTrue(self.controllo.mail_errore)

    def test_flush_rispetta_modalita(self):
        cs.accoda_notifica(self.controllo, self.ids)
        with patch.object(cs, "invia_mail_controllo", return_value={"sent": True}) as invio:
            AnomaliaControllo.objects.filter(pk=self.controllo.pk).update(
                ultimo_salvataggio_at=timezone.now() - timedelta(minutes=1))
            cs.flush_controlli()
            invio.assert_not_called()  # subito: debounce non ancora scaduto
            AnomaliaControllo.objects.filter(pk=self.controllo.pk).update(
                ultimo_salvataggio_at=timezone.now() - timedelta(minutes=10))
            cs.flush_controlli()
            self.assertEqual(invio.call_count, 1)
            AnomaliaControllo.objects.filter(pk=self.controllo.pk).update(mail_mode="fine")
            invio.reset_mock()
            cs.flush_controlli()
            invio.assert_not_called()  # fine: aspetta «Termina controllo»
            AnomaliaControllo.objects.filter(pk=self.controllo.pk).update(
                ultimo_salvataggio_at=timezone.now() - timedelta(minutes=cs.FINE_TIMEOUT_MINUTI + 1))
            cs.flush_controlli()
            self.assertEqual(invio.call_count, 1)  # rete di sicurezza dopo l'inattività

    def test_gruppi_per_blocco(self):
        rows = [
            {"id": self.ids[0], "seriale": "x", "descrizione": "Stato superficie: Con sovrametallo\n\nGraffio"},
            {"id": 999, "seriale": "SN-LIBERO", "descrizione": "Riga senza controllo"},
            {"id": self.ids[1], "seriale": "x", "descrizione": "Bava"},
        ]
        gruppi = cs.gruppi_per_blocco(rows)
        self.assertEqual(len(gruppi), 2)
        self.assertEqual(gruppi[0]["titolo"], "LCN00001-LCN00002 (2 pezzi)")
        self.assertEqual([r["id"] for r in gruppi[0]["righe"]], self.ids)
        self.assertEqual(gruppi[0]["righe"][0]["testo"], "Graffio")
        self.assertEqual(gruppi[0]["righe"][0]["stato_superficie"], "Con sovrametallo")


@override_settings(LEGACY_AUTH_ENABLED=False, SETUP_WIZARD_REQUIRED=False, SECURE_SSL_REDIRECT=False)
class MailActionDecisioneTests(LegacyTableMixin, TestCase):
    """La pagina della mail aggiorna solo le anomalie che il capocommessa ha salvato."""

    def setUp(self):
        self.crea_tabella()
        self.ids = []
        for testo, rdc in (("Graffio", 0), ("Bava", 1)):
            r = _salva_finta(None, {"op_id": OP, "sn": "LCN00001", "desc": testo, "avanzamento": "In attesa"})
            self.ids.append(r["local_id"])
        self.set_riga(self.ids[1], aprire_rdc=1, numero_rdc="RDC-7", note_capocommessa="già decisa")
        from anomalie.mail_action_models import AnomaliaMailActionToken
        self.token = AnomaliaMailActionToken.objects.create(
            recipient_email="cc@example.local", recipient_display="Capocommessa Test", op_id=OP,
            anomalie_ids=self.ids, anomalie_snapshot=[], action="aggiorna_avanzamento",
            expires_at=timezone.now() + timedelta(hours=24),
        )
        self._patches = [
            patch("core.legacy_utils.legacy_table_columns", return_value={
                "id", "ex_op_nominativo", "seriale", "descrizione", "note_capocommessa", "avanzamento",
                "aprire_rdc", "numero_rdc", "segnalare_cliente", "chiudere", "pezzo_recuperato",
            }),
            patch("anomalie.mail_action_service.send_anomalie_update_confirmation", return_value=True),
            patch("anomalie.views._list_attachments_for_local", return_value=[]),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.elimina_tabella()

    def test_get_mostra_flag_e_note_correnti(self):
        r = self.client.get(reverse("anomalie_mail_action", kwargs={"token": self.token.token}))
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn(f'id="rdc-{self.ids[1]}" checked', html)
        self.assertIn("RDC-7", html)
        self.assertIn("già decisa", html)
        self.assertIn("Da decidere", html)

    def test_post_non_azzera_le_anomalie_non_toccate(self):
        payload = {str(self.ids[0]): {
            "avanzamento": "Azione di recupero", "note": "Rilavorare in reparto",
            "aprire_rdc": False, "segnalare": False, "chiudere": False, "numero_rdc": "",
        }}
        r = self.client.post(
            reverse("anomalie_mail_action", kwargs={"token": self.token.token}),
            {"aggiornamenti_json": json.dumps(payload), "note": ""},
        )
        self.assertIn(r.status_code, (301, 302))
        toccata = self.riga(self.ids[0])
        self.assertEqual(toccata["avanzamento"], "Azione di recupero")
        self.assertEqual(toccata["note_capocommessa"], "Rilavorare in reparto")
        intatta = self.riga(self.ids[1])
        self.assertEqual(intatta["aprire_rdc"], 1)
        self.assertEqual(intatta["numero_rdc"], "RDC-7")
        self.assertEqual(intatta["note_capocommessa"], "già decisa")
        self.assertEqual(intatta["avanzamento"], "In attesa")

    def test_post_salva_numero_rdc(self):
        payload = {str(self.ids[0]): {"avanzamento": "Apertura ORE/RIPI", "note": "", "aprire_rdc": True,
                                      "segnalare": False, "chiudere": True, "numero_rdc": "RDC-12"}}
        self.client.post(
            reverse("anomalie_mail_action", kwargs={"token": self.token.token}),
            {"aggiornamenti_json": json.dumps(payload)},
        )
        row = self.riga(self.ids[0])
        self.assertEqual(row["aprire_rdc"], 1)
        self.assertEqual(row["numero_rdc"], "RDC-12")
