"""Automazioni aggiuntive anomalie: ricorrenza P/N, RDC senza numero, digest, OP completato.

La tabella legacy `anomalie` viene creata in SQLite dentro il test; colonne, P/N e
destinatari sono patchati (legacy_table_columns ha una cache che sopravvive ai rollback).
"""
from __future__ import annotations

import datetime as dt
from unittest.mock import patch

from django.core import mail
from django.db import connection
from django.test import TestCase, override_settings

from anomalie import automazioni_service as auto
from anomalie import mail_action_service as svc
from anomalie.automation_models import AnomalieAutomazioneMarker
from core.models import Notifica

COLS = {
    "id", "ex_op_nominativo", "seriale", "descrizione", "aprire_rdc", "numero_rdc",
    "chiudere", "avanzamento", "created_datetime", "modified_datetime",
}
PN = {"op/a": "PN-X", "op/b": "PN-X", "op/c": "PN-Y"}
NOW = dt.datetime(2026, 9, 28, 6, 10, tzinfo=dt.timezone.utc)  # lunedi'


def _utc_naive(days_ago: float) -> str:
    return (NOW - dt.timedelta(days=days_ago)).replace(tzinfo=None).isoformat(sep=" ")


@override_settings(DEFAULT_FROM_EMAIL="hub@example.com", SITE_URL="https://hub.example")
class AutomazioniBase(TestCase):
    def setUp(self):
        with connection.cursor() as cur:
            cur.execute(
                "CREATE TABLE anomalie (id INTEGER PRIMARY KEY, ex_op_nominativo TEXT, seriale TEXT, "
                "descrizione TEXT, aprire_rdc INTEGER, numero_rdc TEXT, chiudere INTEGER, avanzamento TEXT, "
                "created_datetime TEXT, modified_datetime TEXT)"
            )
        self._patches = [
            patch.object(auto, "_anomalie_cols", return_value=COLS),
            patch.object(svc, "_fetch_pn_for_ops", side_effect=lambda ops: {o.lower(): PN.get(o.lower(), "") for o in ops}),
            patch.object(auto, "_supervisori", return_value=["qualita@example.com"]),
            patch.object(svc, "_resolve_lista_rdc_segnalazione", return_value=[]),
            patch("automazioni.services._resolve_op_recipients",
                  return_value=[{"email": "cc@example.com", "display": "Capo Commessa", "role": "CC"}]),
        ]
        for p in self._patches:
            p.start()
        self._id = 0

    def tearDown(self):
        for p in self._patches:
            p.stop()
        with connection.cursor() as cur:
            cur.execute("DROP TABLE anomalie")

    def add(self, op, *, days_ago=1.0, mod_days_ago=None, chiusa=False, rdc=False, numero="", avanzamento="In attesa", sn="SN"):
        self._id += 1
        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO anomalie VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                [self._id, op, f"{sn}{self._id}", f"difetto {self._id}", int(rdc), numero, int(chiusa),
                 avanzamento, _utc_naive(days_ago), _utc_naive(days_ago if mod_days_ago is None else mod_days_ago)],
            )
        return self._id


class RicorrenzaPnTests(AutomazioniBase):
    def test_soglia_raggiunta_una_sola_mail_per_finestra(self):
        self.add("OP/A", days_ago=3)
        self.add("OP/A", days_ago=2)
        self.add("OP/B", days_ago=1)  # stesso P/N su un altro OP
        self.add("OP/C", days_ago=1)  # altro P/N
        groups = auto.find_ricorrenze_pn(soglia_n=3, giorni=30, now=NOW)
        self.assertEqual([(g["pn"], g["n"]) for g in groups], [("PN-X", 3)])

        self.assertEqual(auto.notify_ricorrenze_pn(soglia_n=3, giorni=30, now=NOW), 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("PN-X", mail.outbox[0].subject)
        self.assertEqual(auto.notify_ricorrenze_pn(soglia_n=3, giorni=30, now=NOW), 0)
        self.assertEqual(len(mail.outbox), 1)

    def test_fuori_finestra_non_conta(self):
        self.add("OP/A", days_ago=40)
        self.add("OP/A", days_ago=2)
        self.add("OP/B", days_ago=1)
        self.assertEqual(auto.find_ricorrenze_pn(soglia_n=3, giorni=30, now=NOW), [])


class RdcSenzaNumeroTests(AutomazioniBase):
    def test_solo_aperte_senza_numero_oltre_soglia(self):
        self.add("OP/A", days_ago=5, rdc=True)
        self.add("OP/A", days_ago=5, rdc=True, numero="RDC-12")
        self.add("OP/B", days_ago=1, rdc=True)
        self.add("OP/C", days_ago=9, rdc=True, chiusa=True)
        rows = auto.find_rdc_senza_numero(giorni=3, now=NOW)
        self.assertEqual([(r["op_id"], r["n_anomalie"], r["pn"]) for r in rows], [("OP/A", 1, "PN-X")])

    def test_promemoria_creati_e_chiusi_quando_risolti(self):
        rows = [{"op_id": "OP/A", "n_anomalie": 1, "giorni_max": 5}]
        with patch.object(svc, "_resolve_op_cc_car_legacy_ids", return_value=[(7, "Capo")]):
            self.assertEqual(auto.sync_rdc_reminders(rows), 1)
            self.assertEqual(auto.sync_rdc_reminders(rows), 0)  # idempotente
            auto.sync_rdc_reminders([])
        self.assertFalse(Notifica.objects.filter(tipo=auto.TIPO_REMINDER_RDC, letta=False).exists())


class DigestTests(AutomazioniBase):
    def test_kpi_e_un_invio_per_settimana(self):
        self.add("OP/A", days_ago=2)                                  # nuova, in attesa < 24h? no: 48h
        self.add("OP/A", days_ago=20, mod_days_ago=1, chiusa=True)     # chiusa nella settimana
        self.add("OP/B", days_ago=10, rdc=True, avanzamento="Accetto lo stato")
        d = auto.build_digest(soglia_ore=24, now=NOW)
        self.assertEqual((d["nuove"], d["chiuse"], d["aperte"], d["in_attesa_oltre"], d["rdc_senza_numero"]),
                         (1, 1, 2, 1, 1))
        self.assertEqual(d["tempo_medio_giorni"], 19.0)
        self.assertEqual(d["top_pn"], [("PN-X", 1)])

        self.assertTrue(auto.send_digest(soglia_ore=24, now=NOW))
        self.assertFalse(auto.send_digest(soglia_ore=24, now=NOW))
        self.assertEqual(len(mail.outbox), 1)


class OpCompletatoTests(AutomazioniBase):
    def test_mail_solo_quando_tutte_chiuse_e_una_volta(self):
        self.add("OP/A", chiusa=True)
        self.add("OP/A", chiusa=True)
        self.add("OP/B", chiusa=True)
        self.add("OP/B", chiusa=False)
        self.assertEqual(auto.notify_op_completati(["OP/A", "OP/B"], now=NOW), 1)
        self.assertEqual(mail.outbox[0].to, ["cc@example.com"])
        self.assertIn("report?op_id=OP%2FA", mail.outbox[0].body)
        self.assertEqual(auto.notify_op_completati(["OP/A"], now=NOW), 0)

    def test_nuova_anomalia_chiusa_rinotifica(self):
        self.add("OP/A", chiusa=True)
        auto.notify_op_completati(["OP/A"], now=NOW)
        self.add("OP/A", chiusa=True)
        self.assertEqual(auto.notify_op_completati(["OP/A"], now=NOW), 1)

    def test_sweep_guarda_solo_op_recenti(self):
        self.add("OP/A", days_ago=30, chiusa=True)      # storico: mai notificato in massa
        self.add("OP/B", days_ago=5, mod_days_ago=0.5, chiusa=True)
        with patch("django.utils.timezone.now", return_value=NOW):
            self.assertEqual(auto.notify_op_completati(now=NOW), 1)
        self.assertIn("OP/B", mail.outbox[0].subject)


DEC_COLS = {
    "id", "ex_op_nominativo", "seriale", "descrizione", "aprire_rdc", "numero_rdc", "chiudere",
    "avanzamento", "note_capocommessa", "segnalare_cliente", "created_by_user_id",
}
OPERATORI = {11: ("op11@example.com", "ROSSI MARIO"), 12: ("", "BIANCHI LUCA"), 99: ("capo@example.com", "CAPO")}


@override_settings(DEFAULT_FROM_EMAIL="hub@example.com", SITE_URL="https://hub.example")
class DecisioniOperatoreTests(TestCase):
    """Automazione «decisioni del capocommessa all'operatore»."""

    def setUp(self):
        with connection.cursor() as cur:
            cur.execute(
                "CREATE TABLE anomalie (id INTEGER PRIMARY KEY, ex_op_nominativo TEXT, seriale TEXT, "
                "descrizione TEXT, aprire_rdc INTEGER, numero_rdc TEXT, chiudere INTEGER, avanzamento TEXT, "
                "note_capocommessa TEXT, segnalare_cliente INTEGER, created_by_user_id INTEGER)"
            )
        self.cfg = {"decisioni_operatore_attivo": True, "op_completato_attivo": False}
        self._patches = [
            patch.object(auto, "_anomalie_cols", return_value=DEC_COLS),
            patch.object(auto, "contatto_operatore", side_effect=lambda uid: OPERATORI.get(int(uid), ("", ""))),
            patch.object(svc, "_fetch_pn_for_ops", side_effect=lambda ops: {o.lower(): "PN-X" for o in ops}),
            patch("anomalie.escalation_config.get_escalation_config", side_effect=lambda: self.cfg),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        with connection.cursor() as cur:
            cur.execute("DROP TABLE anomalie")

    def add(self, pk, autore, *, avanzamento="In attesa", rdc=False, numero="", segnalare=False, note="", chiusa=False):
        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO anomalie VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                [pk, "OP/A", f"LCN{pk:05d}", f"Stato superficie: Graffi\n\ndifetto {pk}", int(rdc), numero,
                 int(chiusa), avanzamento, note, int(segnalare), autore],
            )

    def test_raggruppa_per_operatore_e_salta_non_decise_e_proprie(self):
        self.add(1, 11, avanzamento="Rilavorare", rdc=True, numero="RDC-7", note="sostituire")
        self.add(2, 11, avanzamento="In attesa")                 # nessuna decisione
        self.add(3, 12, segnalare=True)                          # decisione: segnalare
        self.add(4, 11, avanzamento="Accetto lo stato")          # modificata dall'autore stesso
        updates = [{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4, "modified_by_legacy_id": 11}]
        piano = auto.prepara_decisioni_operatore("OP/A", updates, deciso_da_legacy_id=99)
        per_uid = {g["legacy_uid"]: g for g in piano}
        self.assertEqual(sorted(per_uid), [11, 12])
        self.assertEqual(per_uid[11]["righe"], [["LCN00001", "difetto 1", "Rilavorare · Aprire RDC n° RDC-7", "sostituire"]])
        self.assertEqual(per_uid[12]["righe"][0][2], "In attesa · Segnalare al cliente")

    def test_mail_e_notifica_all_operatore(self):
        self.add(1, 11, avanzamento="Rilavorare", note="sostituire")
        self.add(2, 12, chiusa=True)
        piano = auto.prepara_decisioni_operatore("OP/A", [{"id": 1}, {"id": 2}], deciso_da_email="capo@example.com")
        self.assertEqual(auto.invia_decisioni_operatore("OP/A", piano, deciso_da="Capo Commessa"), 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["op11@example.com"])
        self.assertIn("OP/A", mail.outbox[0].subject)
        self.assertIn("Rilavorare", mail.outbox[0].body)
        self.assertIn("/gestione-anomalie?op=OP/A", mail.outbox[0].body)
        # Senza email di notifica resta la notifica nel portale.
        self.assertEqual(
            sorted(Notifica.objects.filter(tipo=auto.TIPO_NOTIFICA_DECISIONE).values_list("legacy_user_id", flat=True)),
            [11, 12],
        )

    def test_capocommessa_autore_non_si_autonotifica(self):
        self.add(1, 99, avanzamento="Rilavorare")
        self.assertEqual(auto.prepara_decisioni_operatore("OP/A", [{"id": 1}], deciso_da_email="CAPO@example.com"), [])

    def test_disattivata(self):
        self.cfg["decisioni_operatore_attivo"] = False
        self.add(1, 11, avanzamento="Rilavorare")
        self.assertEqual(auto.prepara_decisioni_operatore("OP/A", [{"id": 1}]), [])

    def test_flush_portale_operatore_fuori_dal_riepilogo(self):
        from anomalie.mail_action_models import AnomaliaPendingNotification

        self.add(1, 11, avanzamento="Rilavorare")
        AnomaliaPendingNotification.objects.create(
            op_id="OP/A", op_nominativo="OP/A", last_modified_by="Capo Commessa",
            last_modified_at=dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc),
            updates_snapshot=[{"id": 1, "seriale": "LCN00001", "avanzamento": "Rilavorare",
                               "modified_by": "Capo Commessa", "modified_by_legacy_id": 99}],
        )
        with (
            patch("core.legacy_utils.legacy_table_columns", return_value=DEC_COLS),
            patch.object(svc, "_resolve_lista_fissa_conferma", return_value=["qualita@example.com"]),
            patch.object(svc, "_resolve_lista_rdc_segnalazione", return_value=[]),
            patch("automazioni.services._resolve_op_recipients", return_value=[]),
        ):
            out = svc.flush_pending_update_notifications(threshold_minutes=5)
        self.assertEqual((out["sent"], out["decisioni_operatore"]), (1, 1))
        destinatari = [m.to for m in mail.outbox]
        self.assertIn(["qualita@example.com"], destinatari)      # riepilogo senza l'operatore
        self.assertIn(["op11@example.com"], destinatari)         # mail dedicata
        self.assertIn("Capo Commessa", mail.outbox[1].body)


class DecisioniOperatoreConfigPageTests(TestCase):
    def test_voce_in_configurazione_accesa_di_default(self):
        from django.contrib.auth import get_user_model
        from django.urls import reverse

        admin = get_user_model().objects.create_superuser("anom-cfg", "anom-cfg@test.local", "pass12345")
        self.client.force_login(admin)
        html = self.client.get(reverse("anomalie_configurazione_page")).content.decode()
        self.assertIn('id="auto_decisioni_operatore_attivo"', html)
        self.assertIn("decisioni_operatore_attivo: true", html)
        self.assertIn("['auto_decisioni_operatore_attivo', 'decisioni_operatore_attivo', 'bool', true]", html)
        self.assertNotIn("{#", html)


class PromemoriaEscalationFixTests(TestCase):
    def test_promemoria_di_op_gestiti_vengono_chiusi(self):
        Notifica.objects.create(legacy_user_id=7, tipo="anomalia_da_gestire", messaggio="x",
                                url_azione="/gestione-anomalie?op=OP/OLD")
        with patch.object(svc, "_resolve_op_cc_car_legacy_ids", return_value=[(7, "Capo")]):
            svc.create_dashboard_reminders(
                [{"op_id": "OP/NEW", "n_anomalie": 1, "ore_max": 2, "over_threshold": False}], soglia_ore=24,
            )
        aperte = list(Notifica.objects.filter(tipo="anomalia_da_gestire", letta=False).values_list("url_azione", flat=True))
        self.assertEqual(aperte, ["/gestione-anomalie?op=OP/NEW"])


@override_settings(DEFAULT_FROM_EMAIL="hub@example.com")
class TaskEscalationTests(TestCase):
    CFG = {
        "attivo": True, "soglia_ore": 24, "ora_invio": 8, "cadenza_label": "",
        "ricorrenza_attivo": False, "ricorrenza_n": 3, "ricorrenza_giorni": 30,
        "rdc_attivo": False, "rdc_giorni": 3, "digest_attivo": False, "op_completato_attivo": False,
    }

    def _run(self, **patches):
        from anomalie.tasks import run_anomalie_escalation
        # 06:10 UTC = 08:10 a Roma (ora legale), lunedi'
        with (
            patch("anomalie.escalation_config.get_escalation_config", return_value=dict(self.CFG)),
            patch("django.utils.timezone.now", return_value=NOW),
            patch.object(svc, "create_dashboard_reminders", return_value=0) as reminders,
            patch.object(svc, "send_escalation_resoconto", return_value=True) as send,
        ):
            if "fetch_error" in patches:
                with patch.object(svc, "_fetch_op_da_controllare", side_effect=RuntimeError("db giu")):
                    return run_anomalie_escalation.__wrapped__(), reminders, send
            with patch.object(svc, "_fetch_op_da_controllare", return_value=[{"op_id": "OP/A", "over_threshold": True}]):
                return run_anomalie_escalation.__wrapped__(), reminders, send

    def test_resoconto_una_volta_al_giorno(self):
        out, _r, send = self._run()
        self.assertTrue(out["email_sent"])
        out2, _r2, send2 = self._run()
        self.assertFalse(out2["email_sent"])
        send2.assert_not_called()

    def test_db_illeggibile_non_tocca_i_promemoria(self):
        out, reminders, send = self._run(fetch_error=True)
        reminders.assert_not_called()
        send.assert_not_called()
        self.assertEqual(out["op_da_controllare"], 0)
