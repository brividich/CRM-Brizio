"""Scheda qualita' anomalie + registro NC automatico (ISO 9001 §10.2) + proposta AI.

La tabella legacy `anomalie` e' creata in SQLite nel test; colonne e P/N sono patchati
(legacy_table_columns ha una cache che sopravvive ai rollback). L'AI e' sempre mockata.
"""
from __future__ import annotations

import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.urls import reverse

from anomalie import ai_copilota
from anomalie import automazioni_service as auto
from anomalie import mail_action_service as svc
from anomalie import qualita_service as qs
from anomalie.quality_models import AnomaliaSchedaQualita as Scheda
from anomalie.quality_models import AnomaliaTipoDifetto
from gestione_specifiche.models import RegistroOFI

User = get_user_model()

COLS = {
    "id", "ex_op_nominativo", "seriale", "descrizione", "note_capocommessa", "aprire_rdc",
    "numero_rdc", "segnalare_cliente", "chiudere", "avanzamento", "created_datetime",
}
PN = {"op/a": "PN-X", "op/b": "PN-X", "op/c": "PN-Y"}
CFG = {"nc_registro_attivo": True, "ricorrenza_n": 3, "ricorrenza_giorni": 30}


class QualitaBase(TestCase):
    def setUp(self):
        with connection.cursor() as cur:
            cur.execute(
                "CREATE TABLE anomalie (id INTEGER PRIMARY KEY, ex_op_nominativo TEXT, seriale TEXT, "
                "descrizione TEXT, note_capocommessa TEXT, aprire_rdc INTEGER, numero_rdc TEXT, "
                "segnalare_cliente INTEGER, chiudere INTEGER, avanzamento TEXT, created_datetime TEXT)"
            )
        self._patches = [
            patch.object(auto, "_anomalie_cols", return_value=COLS),
            patch.object(svc, "_fetch_pn_for_ops",
                         side_effect=lambda ops: {o.lower(): PN.get(o.lower(), "") for o in ops}),
            patch("anomalie.escalation_config.get_escalation_config", return_value=dict(CFG)),
        ]
        for p in self._patches:
            p.start()
        self._id = 0
        self.fuori_tol = AnomaliaTipoDifetto.objects.get(codice="fuori-tolleranza")
        self.graffi = AnomaliaTipoDifetto.objects.get(codice="difetto-superficiale")

    def tearDown(self):
        for p in self._patches:
            p.stop()
        with connection.cursor() as cur:
            cur.execute("DROP TABLE anomalie")

    def add(self, op="OP/A", *, desc="quota fuori tolleranza sul foro", rdc=False, cliente=False,
            avanzamento="In attesa", created="2026-09-20 08:00:00"):
        self._id += 1
        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO anomalie VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                [self._id, op, f"SN{self._id}", desc, "", int(rdc), "", int(cliente), 0,
                 avanzamento, created],
            )
        return self._id


class SchedaTests(QualitaBase):
    def test_protocollo_progressivo_per_anno_e_istantanea_op(self):
        a = qs.sync_da_anomalia(self.add(created="2025-12-30 10:00:00"))
        b = qs.sync_da_anomalia(self.add())
        c = qs.sync_da_anomalia(self.add("OP/C"))
        self.assertEqual(a.protocollo, "NC-2025-0001")
        self.assertEqual((b.protocollo, c.protocollo), ("NC-2026-0001", "NC-2026-0002"))
        self.assertEqual((b.op_titolo, b.part_number, b.origine), ("OP/A", "PN-X", Scheda.Origine.PRODUZIONE))
        self.assertEqual(c.part_number, "PN-Y")

    def test_disposizione_dedotta_ma_mai_sopra_la_scelta_manuale(self):
        s = qs.sync_da_anomalia(self.add(avanzamento="Accetto lo stato"))
        self.assertEqual(s.disposizione, Scheda.Disposizione.USO_TALE)
        self.assertTrue(s.disposizione_auto)
        self.assertEqual(qs.applica_modifiche(s, {"disposizione": "SCARTO"}), [])
        with connection.cursor() as cur:
            cur.execute("UPDATE anomalie SET aprire_rdc = 1 WHERE id = %s", [s.anomalia_id])
        s = qs.sync_da_anomalia(s.anomalia_id)
        self.assertEqual(s.disposizione, Scheda.Disposizione.SCARTO)
        self.assertFalse(s.disposizione_auto)

    def test_validazione_modifiche(self):
        s = qs.sync_da_anomalia(self.add())
        self.assertTrue(qs.applica_modifiche(s, {"gravita": "ENORME"}))
        self.assertTrue(qs.applica_modifiche(s, {"quantita_nc": 2, "quantita_scartata": 5}))
        self.assertTrue(qs.applica_modifiche(s, {"tipo_difetto": 999999}))
        self.assertEqual(qs.applica_modifiche(s, {
            "tipo_difetto": self.fuori_tol.pk, "gravita": "minore", "quantita_nc": "4", "quantita_scartata": "1",
        }), [])
        s.refresh_from_db()
        self.assertEqual((s.tipo_difetto_id, s.gravita, s.quantita_nc, s.quantita_scartata),
                         (self.fuori_tol.pk, "MINORE", 4, 1))


class RegistroNcTests(QualitaBase):
    def test_anomalia_minore_resta_fuori_dal_registro(self):
        s = qs.sync_da_anomalia(self.add())
        self.assertIsNone(s.registro_nc_id)
        self.assertEqual(RegistroOFI.objects.count(), 0)

    def test_segnalata_al_cliente_crea_nc_una_sola_volta(self):
        s = qs.sync_da_anomalia(self.add(cliente=True))
        voce = s.registro_nc
        self.assertIsNotNone(voce)
        self.assertEqual((voce.tipo, voce.modulo_origine, voce.ref), ("NC", "anomalie", s.protocollo))
        self.assertEqual(s.gravita, Scheda.Gravita.MAGGIORE)
        self.assertEqual(voce.priorita, "ALTA")
        self.assertFalse(voce.reminder_attivo)
        self.assertIn("segnalata al cliente", voce.opportunita)
        self.assertEqual(voce.content_type.model_class(), Scheda)
        qs.sync_da_anomalia(s.anomalia_id)
        qs.sync_da_anomalia(s.anomalia_id)
        voce.refresh_from_db()
        self.assertEqual(RegistroOFI.objects.count(), 1)
        self.assertNotIn(s.protocollo, voce.note)

    def test_stesso_evento_si_aggancia_alla_nc_aperta(self):
        a = qs.sync_da_anomalia(self.add(rdc=True))
        b = qs.sync_da_anomalia(self.add(rdc=True))
        self.assertEqual(a.registro_nc_id, b.registro_nc_id)
        self.assertEqual(RegistroOFI.objects.count(), 1)
        self.assertIn(b.protocollo, RegistroOFI.objects.get().note)
        # NC chiusa: un nuovo caso apre una nuova voce.
        RegistroOFI.objects.update(fase=RegistroOFI.FASE_CHIUSO)
        c = qs.sync_da_anomalia(self.add(rdc=True))
        self.assertNotEqual(c.registro_nc_id, a.registro_nc_id)

    def test_difetto_ricorrente_sullo_stesso_pn(self):
        schede = []
        for op in ("OP/A", "OP/B", "OP/A"):
            s = qs.sync_da_anomalia(self.add(op))
            qs.applica_modifiche(s, {"tipo_difetto": self.fuori_tol.pk, "gravita": "MINORE"})
            qs.valuta_registro_nc(s, qs.legacy_row(s.anomalia_id))
            schede.append(s)
        self.assertIsNone(schede[0].registro_nc_id)
        self.assertIsNone(schede[1].registro_nc_id)
        voce = schede[2].registro_nc
        self.assertIsNotNone(voce)
        self.assertIn("ricorrente", voce.opportunita)
        self.assertEqual(voce.priorita, "MEDIA")

    def test_interruttore_spento(self):
        with patch("anomalie.escalation_config.get_escalation_config",
                   return_value={**CFG, "nc_registro_attivo": False}):
            s = qs.sync_da_anomalia(self.add(cliente=True))
        self.assertIsNone(s.registro_nc_id)


class ParetoTests(QualitaBase):
    def test_conteggi_e_filtro(self):
        ids = []
        for tipo in (self.fuori_tol, self.fuori_tol, self.graffi):
            s = qs.sync_da_anomalia(self.add())
            qs.applica_modifiche(s, {"tipo_difetto": tipo.pk})
            ids.append(s.anomalia_id)
        qs.sync_da_anomalia(self.add())  # non classificata
        p = qs.pareto()
        self.assertEqual((p["totale"], p["classificate"]), (4, 3))
        self.assertEqual(p["per_difetto"][0], {"label": self.fuori_tol.nome, "n": 2, "cum_pct": 50.0})
        self.assertEqual(p["per_difetto"][-1]["cum_pct"], 100.0)
        self.assertEqual(qs.pareto(ids[2:3])["per_difetto"], [{"label": self.graffi.nome, "n": 1, "cum_pct": 100.0}])


class CopilotaQualitaTests(QualitaBase):
    def _tipi(self):
        return list(AnomaliaTipoDifetto.objects.values_list("id", "nome"))

    def test_proposta_validata_sul_catalogo(self):
        fake = json.dumps({"tipo_difetto": self.graffi.nome.upper(), "gravita": "maggiore",
                           "causa_probabile": "urto in movimentazione"})
        with patch.object(ai_copilota, "_chiama_ai", return_value=fake):
            out = ai_copilota.proponi_classificazione_qualita(
                descrizione="graffio sulla faccia", tipi_difetto=self._tipi(), gravita=Scheda.Gravita.choices)
        self.assertEqual((out["tipo_difetto"], out["gravita"], out["fonte"]), (self.graffi.pk, "MAGGIORE", "ai"))
        self.assertIn("movimentazione", out["causa_probabile"])

    def test_ai_offline_ripiega_sui_casi_simili(self):
        s = qs.sync_da_anomalia(self.add(desc="bava sul bordo del foro filettato"))
        qs.applica_modifiche(s, {"tipo_difetto": self.graffi.pk})
        with patch.object(ai_copilota, "_chiama_ai", return_value=""):
            out = ai_copilota.proponi_classificazione_qualita(
                descrizione="bava sul foro filettato", part_number="PN-X",
                tipi_difetto=self._tipi(), gravita=Scheda.Gravita.choices)
        self.assertFalse(out["ai_disponibile"])
        self.assertEqual((out["tipo_difetto"], out["fonte"]), (self.graffi.pk, "simili"))
        self.assertEqual(out["simili"][0]["protocollo"], s.protocollo)
        self.assertEqual(out["gravita"], "")


@patch("anomalie.views._has_table", return_value=True)
class ApiQualitaTests(QualitaBase):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser(username="q-admin", password="pass12345", email="q@x.it")
        self.url = reverse("api_anomalie_qualita")

    def test_get_crea_scheda_e_post_salva(self, _ht):
        self.client.force_login(self.admin)
        aid = self.add(cliente=True)
        r = self.client.get(self.url, {"local_id": f"local:{aid}"})
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()
        self.assertTrue(d["success"])
        self.assertTrue(d["scheda"]["protocollo"].startswith("NC-2026-"))
        self.assertTrue(any(t["value"] == self.fuori_tol.pk for t in d["scelte"]["tipi_difetto"]))
        r = self.client.post(self.url, data=json.dumps({
            "local_id": aid, "tipo_difetto": self.fuori_tol.pk, "gravita": "CRITICA", "disposizione": "SCARTO",
        }), content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        scheda = r.json()["scheda"]
        self.assertEqual((scheda["gravita"], scheda["disposizione"]), ("CRITICA", "SCARTO"))
        self.assertIsNotNone(scheda["registro_nc"])

    def test_errori(self, _ht):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(self.url).status_code, 400)
        self.assertEqual(self.client.get(self.url, {"local_id": 999}).status_code, 404)
        aid = self.add()
        r = self.client.post(self.url, data=json.dumps({"local_id": aid, "origine": "MARTE"}),
                             content_type="application/json")
        self.assertEqual(r.status_code, 400)

    def test_utente_senza_permessi(self, _ht):
        user = User.objects.create_user(username="q-op", password="pass12345")
        self.client.force_login(user)
        aid = self.add()
        with patch("anomalie.views._can_view_anomalie_for_op", return_value=False):
            self.assertEqual(self.client.get(self.url, {"local_id": aid}).status_code, 403)
        with patch("anomalie.views._can_view_anomalie_for_op", return_value=True), \
                patch("anomalie.views._can_edit_anomalie_for_op", return_value=False):
            r = self.client.post(self.url, data=json.dumps({"local_id": aid, "gravita": "MINORE"}),
                                 content_type="application/json")
        self.assertEqual(r.status_code, 403)
        r = self.client.post(reverse("api_anomalie_qualita_copilota"),
                             data=json.dumps({"local_id": aid}), content_type="application/json")
        self.assertEqual(r.status_code, 403)


class ConfigTabQualitaTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="q-cfg", password="pass12345", email="c@x.it")
        self.client.force_login(self.admin)
        self.url = reverse("anomalie_configurazione_page")

    def test_catalogo_crea_rinomina_disattiva(self):
        r = self.client.post(self.url, {"action": "save_tipo_difetto", "nome": "Ovalizzazione foro", "famiglia": "Dimensionale"})
        self.assertEqual(r.status_code, 302)
        t = AnomaliaTipoDifetto.objects.get(nome="Ovalizzazione foro")
        self.assertEqual(t.codice, "ovalizzazione-foro")
        self.client.post(self.url, {"action": "save_tipo_difetto", "nome": "Altro"})  # doppione
        self.assertEqual(AnomaliaTipoDifetto.objects.filter(nome__iexact="altro").count(), 1)
        self.client.post(self.url, {"action": "toggle_tipo_difetto", "tipo_id": t.pk})
        t.refresh_from_db()
        self.assertFalse(t.attivo)
        r = self.client.get(self.url, {"tab": "qualita"})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Catalogo tipi difetto")
        self.assertContains(r, "Ovalizzazione foro")
        self.assertNotContains(r, "{#")
