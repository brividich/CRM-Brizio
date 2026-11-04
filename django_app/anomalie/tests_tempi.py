"""Tempi delle anomalie (giorni lavorativi) ed esiti: risposta del cliente, azione effettuata.

Tabella legacy ``anomalie`` in SQLite con le colonne che servono; ``SELECT TOP 1`` e'
SQL Server, quindi le letture del modulo passano da un equivalente SQLite. Dati sintetici.
"""
from __future__ import annotations

import tempfile
from datetime import datetime
from datetime import timezone as dt_timezone
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from anomalie import tempi_service as ts
from anomalie import views as av
from anomalie.quality_models import AnomaliaEsito, AnomaliaSchedaQualita

User = get_user_model()
OP = "OP/2026/0077"
_COLS = {"id", "ex_op_nominativo", "seriale", "descrizione", "note_capocommessa", "aprire_rdc", "numero_rdc",
         "segnalare_cliente", "chiudere", "avanzamento", "created_datetime"}


def _utc(*args):
    return datetime(*args, tzinfo=dt_timezone.utc)


@patch("anomalie.tempi_service.orario", return_value=(8, 18))
class GiorniLavorativiTests(SimpleTestCase):
    """Ore lavorate con l'orario 08:00-18:00 (1 giorno lavorativo = 10 h)."""

    def test_weekend_e_fuori_orario_non_contano(self, _o):
        # Venerdi 06/11/2026 18:00 (ora di Roma = UTC+1) → lunedi 09/11 09:00: solo 08-09 di lunedi.
        self.assertEqual(ts.ore_lavorate(_utc(2026, 11, 6, 17), _utc(2026, 11, 9, 8)), 1.0)
        self.assertEqual(ts.giorni_lavorativi(_utc(2026, 11, 6, 17), _utc(2026, 11, 9, 8)), 0.1)

    def test_notte_non_conta(self, _o):
        # Lunedi 20:00 → martedi 10:00: 2 h (08-10 di martedi).
        self.assertEqual(ts.ore_lavorate(_utc(2026, 11, 9, 19), _utc(2026, 11, 10, 9)), 2.0)

    def test_festivo_non_conta(self, _o):
        # Gio 24/12 12:00 → lun 28/12 12:00: 6 h del 24, Natale e Santo Stefano esclusi, 4 h del 28.
        self.assertEqual(ts.ore_lavorate(_utc(2026, 12, 24, 11), _utc(2026, 12, 28, 11)), 10.0)
        self.assertEqual(ts.giorni_lavorativi(_utc(2026, 12, 24, 11), _utc(2026, 12, 28, 11)), 1.0)

    def test_estremi(self, _o):
        self.assertIsNone(ts.giorni_lavorativi(None, _utc(2026, 11, 9, 8)))
        self.assertEqual(ts.giorni_lavorativi(_utc(2026, 11, 9, 8), _utc(2026, 11, 9, 7)), 0.0)

    def test_etichette(self, _o):
        self.assertEqual(ts.etichetta_durata(None), "—")
        self.assertEqual(ts.etichetta_durata(0.05), "meno di 1 h")
        self.assertEqual(ts.etichetta_durata(0.35), "3,5 h")
        self.assertEqual(ts.etichetta_durata(1.5), "15 h · 1,5 gg")
        self.assertEqual(ts.etichetta_durata(10.0), "100 h · 10 gg")
        self.assertEqual(ts.etichetta_orario(), "ore lavorate 08:00–18:00, giorni lavorativi")


class AggiornaTempiTests(TestCase):
    def setUp(self):
        self.scheda = AnomaliaSchedaQualita.objects.create(anomalia_id=501, op_titolo=OP)

    def _riga(self, **campi):
        return {"avanzamento": "In attesa", "chiudere": 0, "segnalare_cliente": 0, "note_capocommessa": "", **campi}

    def test_prima_decisione_e_chiusura(self):
        t1, t2, t3 = _utc(2026, 11, 9, 8), _utc(2026, 11, 10, 8), _utc(2026, 11, 11, 8)
        ts.aggiorna_tempi(self.scheda, self._riga(), adesso=t1)
        self.assertIsNone(self.scheda.prima_decisione_il)
        ts.aggiorna_tempi(self.scheda, self._riga(avanzamento="Azione di recupero"), adesso=t1)
        self.assertEqual((self.scheda.prima_decisione_il, self.scheda.primo_avanzamento), (t1, "Azione di recupero"))
        ts.aggiorna_tempi(self.scheda, self._riga(avanzamento="Accetto lo stato", chiudere=1), adesso=t2)
        self.assertEqual(self.scheda.prima_decisione_il, t1)  # la prima decisione non si sposta
        self.assertEqual(self.scheda.chiusa_il, t2)
        ts.aggiorna_tempi(self.scheda, self._riga(avanzamento="In attesa"), adesso=t3)  # riaperta
        self.assertIsNone(self.scheda.chiusa_il)

    def test_attesa_cliente(self):
        t1, t2, t3 = _utc(2026, 11, 9, 8), _utc(2026, 11, 11, 8), _utc(2026, 11, 12, 8)
        ts.aggiorna_tempi(self.scheda, self._riga(avanzamento=ts.AVANZAMENTO_RISPOSTA_CLIENTE, segnalare_cliente=1), adesso=t1)
        self.assertEqual(self.scheda.attesa_cliente_dal, t1)
        ts.aggiorna_tempi(self.scheda, self._riga(avanzamento="Azione di recupero", segnalare_cliente=1), adesso=t2)
        self.assertEqual(self.scheda.risposta_cliente_il, t2)
        # Nuova richiesta al cliente: riparte l'attesa.
        ts.aggiorna_tempi(self.scheda, self._riga(avanzamento=ts.AVANZAMENTO_RISPOSTA_CLIENTE, segnalare_cliente=1), adesso=t3)
        self.assertEqual((self.scheda.attesa_cliente_dal, self.scheda.risposta_cliente_il), (t3, None))

    def test_serve_azione_per_chiudere(self):
        self.assertFalse(ts.serve_azione_per_chiudere(501))
        self.scheda.primo_avanzamento = "Azione di recupero"
        self.scheda.save()
        self.assertTrue(ts.serve_azione_per_chiudere(501))
        self.scheda.azione_effettuata_il = timezone.now()
        self.scheda.save()
        self.assertFalse(ts.serve_azione_per_chiudere(501))

    def test_tempi_e_riepilogo(self):
        self.scheda.prima_decisione_il = _utc(2026, 11, 10, 8)
        self.scheda.chiusa_il = _utc(2026, 11, 13, 8)
        self.scheda.save()
        with patch("anomalie.tempi_service.orario", return_value=(8, 18)):
            tempi = ts.tempi_anomalia(creata_il=_utc(2026, 11, 9, 8), scheda=self.scheda, adesso=_utc(2026, 11, 20, 8))
            aperta = ts.tempi_anomalia(creata_il=_utc(2026, 11, 2, 8), scheda=None, adesso=_utc(2026, 11, 20, 8))
        # Lun 09:00 → mar 09:00 = 9 h + 1 h; lun 09:00 → ven 09:00 = 9 + 10 + 10 + 10 + 1.
        self.assertEqual(tempi["risposta"], {"ore": 10.0, "giorni": 1.0, "in_corso": False})
        self.assertEqual(tempi["risoluzione"], {"ore": 40.0, "giorni": 4.0, "in_corso": False})
        self.assertIsNone(tempi["attesa_cliente"])
        with patch("anomalie.tempi_service.soglie", return_value={"risposta": 2, "risoluzione": 10}),                 patch("anomalie.tempi_service.orario", return_value=(8, 18)):
            kpi = ts.riepilogo({1: tempi, 2: aperta}, gruppi={1: "MARIO ROSSI", 2: "MARIO ROSSI"})
        ris = kpi["metriche"]["risoluzione"]
        self.assertEqual((ris["conclusi"], ris["in_corso"], ris["mediana"], ris["entro_soglia_pct"]), (1, 1, 4.0, 100))
        self.assertEqual(ris["oltre_soglia_aperti"], 1)  # 14 gg lavorativi > 10
        self.assertEqual(kpi["per_capocommessa"][0]["anomalie"], 2)
        self.assertEqual(ris["mediana_testo"], "40 h · 4 gg")


def _fetch_sqlite(sql, params=None):
    with connection.cursor() as cur:
        cur.execute(sql.replace("SELECT TOP 1 ", "SELECT "), params or [])
        nomi = [c[0] for c in cur.description]
        return [dict(zip(nomi, r)) for r in cur.fetchall()]


@override_settings(LEGACY_AUTH_ENABLED=False, SETUP_WIZARD_REQUIRED=False, SECURE_SSL_REDIRECT=False)
class EsitiApiTests(TestCase):
    def setUp(self):
        with connection.cursor() as cur:
            cur.execute(
                "CREATE TABLE anomalie (id INTEGER PRIMARY KEY AUTOINCREMENT, ex_op_nominativo TEXT, seriale TEXT, "
                "descrizione TEXT, note_capocommessa TEXT, aprire_rdc INTEGER, numero_rdc TEXT, segnalare_cliente INTEGER, "
                "chiudere INTEGER, avanzamento TEXT, created_datetime TEXT)"
            )
            cur.execute("INSERT INTO anomalie (ex_op_nominativo, seriale, descrizione, chiudere, avanzamento, created_datetime) "
                        "VALUES (%s, 'LCN00001', 'Graffio', 0, 'Azione di recupero', '2026-11-09 08:00:00')", [OP])
            self.aid = cur.lastrowid
        self.tmp = tempfile.TemporaryDirectory()
        self.user = User.objects.create_superuser(username="esiti", password="pass12345", email="es@example.local")
        self.client.force_login(self.user)
        AnomaliaSchedaQualita.objects.create(anomalia_id=self.aid, op_titolo=OP, primo_avanzamento="Azione di recupero",
                                             prima_decisione_il=timezone.now())
        self.puo = True
        self._patches = [
            patch("anomalie.views._has_table", return_value=True),
            patch("anomalie.views.legacy_table_columns", return_value=_COLS),
            patch("anomalie.views._fetch_all_dict", side_effect=_fetch_sqlite),
            patch("anomalie.views._can_riaprire_anomalia", side_effect=lambda *a: self.puo),
            patch("anomalie.views._can_view_anomalie_for_op", return_value=True),
            patch("anomalie.views._anomalie_attachments_root", return_value=Path(self.tmp.name)),
            patch("anomalie.views._mark_attachment_pending"),
            patch("anomalie.qualita_service.legacy_row", side_effect=lambda i: (_fetch_sqlite(
                "SELECT * FROM anomalie WHERE id = %s", [i]) or [None])[0]),
            patch("anomalie.nc_service.aggancia_a_nc"),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.tmp.cleanup()
        with connection.cursor() as cur:
            cur.execute("DROP TABLE anomalie")

    def _riga(self):
        return _fetch_sqlite("SELECT * FROM anomalie WHERE id = %s", [self.aid])[0]

    def _post(self, **dati):
        return self.client.post(reverse("api_anomalie_esito"), {"local_id": self.aid, **dati})

    def test_dettaglio_tempi_ed_esiti(self):
        r = self.client.get(reverse("api_anomalie_esiti"), {"local_id": self.aid})
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertTrue(d["serve_azione"])
        self.assertTrue(d["can_registrare"])
        self.assertIn("risoluzione", [t["chiave"] for t in d["tempi"]])
        # Percorso: segnalata e decisa fatte, azione effettuata in corso, chiusa da fare.
        self.assertEqual([(p["chiave"], p["stato"]) for p in d["percorso"]],
                         [("segnalata", "fatto"), ("decisa", "fatto"), ("azione", "attuale"), ("chiusa", "da_fare")])
        self.assertEqual(d["percorso"][1]["dettaglio"], "Azione di recupero")

    def test_rilavorato_chiede_riverifica_per_chiudere(self):
        r = self._post(tipo="AZIONE", azione="Rilavorato", chiudi="1")
        self.assertEqual(r.status_code, 400)
        self.assertIn("riverificato", r.json()["error"])
        self.assertFalse(self._riga()["chiudere"])

    def test_azione_chiude_con_allegato_mail(self):
        mail = SimpleUploadedFile("risposta.msg", b"mail di prova", content_type="application/vnd.ms-outlook")
        r = self._post(tipo="AZIONE", azione="Rilavorato", riverificato="1", chiudi="1", testo="Ripresa la quota", files=mail)
        self.assertEqual(r.status_code, 200, r.content)
        self.assertTrue(r.json()["chiusa"])
        self.assertEqual(self._riga()["chiudere"], 1)
        esito = AnomaliaEsito.objects.get(anomalia_id=self.aid)
        self.assertEqual((esito.azione, esito.riverificato, len(esito.allegati)), ("Rilavorato", True, 1))
        self.assertTrue((Path(self.tmp.name) / str(self.aid) / esito.allegati[0]).is_file())
        scheda = AnomaliaSchedaQualita.objects.get(anomalia_id=self.aid)
        self.assertIsNotNone(scheda.azione_effettuata_il)
        self.assertIsNotNone(scheda.chiusa_il)
        self.assertFalse(ts.serve_azione_per_chiudere(self.aid))
        percorso = self.client.get(reverse("api_anomalie_esiti"), {"local_id": self.aid}).json()["percorso"]
        self.assertTrue(all(p["stato"] == "fatto" for p in percorso))
        self.assertEqual(percorso[2]["dettaglio"], "Rilavorato · riverificato")

    def test_risposta_cliente(self):
        self.assertEqual(self._post(tipo="RISPOSTA_CLIENTE").status_code, 400)
        r = self._post(tipo="RISPOSTA_CLIENTE", testo="Il cliente accetta la quota 0,2")
        self.assertEqual(r.status_code, 200)
        self.assertIsNotNone(AnomaliaSchedaQualita.objects.get(anomalia_id=self.aid).risposta_cliente_il)
        self.assertFalse(self._riga()["chiudere"])

    def test_formato_non_ammesso(self):
        exe = SimpleUploadedFile("programma.exe", b"MZ", content_type="application/octet-stream")
        r = self._post(tipo="RISPOSTA_CLIENTE", testo="", files=exe)
        self.assertEqual(r.status_code, 400)
        self.assertFalse(AnomaliaEsito.objects.exists())

    def test_solo_gli_incaricati(self):
        self.puo = False
        self.assertEqual(self._post(tipo="AZIONE", azione="Scartato").status_code, 403)

    def test_chiusura_bloccata_senza_azione(self):
        request = RequestFactory().post("/api/anomalie/salva")
        request.user = self.user
        with patch("anomalie.views._can_edit_anomalie_for_op", return_value=True), \
                patch("anomalie.views.get_legacy_user", return_value=None), \
                patch("anomalie.views._decisione_su_propria_anomalia", return_value=""):
            esito = av._salva_riga_anomalia(request, {
                "item_id": f"local:{self.aid}", "op_id": OP, "avanzamento": "Accetto lo stato", "chiudere": True,
            })
        self.assertFalse(esito["success"])
        self.assertEqual(esito["error"], ts.MSG_SERVE_AZIONE)

    def test_statistiche_tempi(self):
        with patch("anomalie.views._capocommessa_per_op", return_value={OP.lower(): "MARIO ROSSI"}):
            t = av._tempi_statistiche([{"id": self.aid, "created_datetime": "2026-11-09 08:00:00", "ex_op_nominativo": OP}])
        self.assertEqual(t["per_capocommessa"][0]["nome"], "MARIO ROSSI")
        self.assertEqual(t["unita"], "ore lavorate 08:00–18:00, giorni lavorativi")
        self.assertEqual(t["ore_giorno"], 10)
