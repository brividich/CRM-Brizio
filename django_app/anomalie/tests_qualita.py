"""Scheda qualita' per S/N, NC per OP (ISO 9001 §10.2) e proposta AI.

La tabella legacy `anomalie` e' creata in SQLite nel test; colonne, P/N e CC/CAR sono
patchati (legacy_table_columns ha una cache che sopravvive ai rollback). AI mockata.
"""
from __future__ import annotations

import datetime as dt
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from anomalie import ai_copilota
from anomalie import automazioni_service as auto
from anomalie import mail_action_service as svc
from anomalie import nc_service
from anomalie import qualita_service as qs
from anomalie.quality_models import AnomaliaNC as NC
from anomalie.quality_models import AnomaliaNCAzione
from anomalie.quality_models import AnomaliaSchedaQualita as Scheda
from anomalie.quality_models import AnomaliaTipoDifetto
from core.models import Notifica, SiteConfig, UserOnboarding

User = get_user_model()

COLS = {
    "id", "ex_op_nominativo", "seriale", "descrizione", "note_capocommessa", "aprire_rdc",
    "numero_rdc", "segnalare_cliente", "chiudere", "avanzamento", "created_datetime",
}
PN = {"op/a": "PN-X", "op/b": "PN-X", "op/c": "PN-Y"}


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
            patch("automazioni.services._resolve_op_recipients", return_value=[
                {"email": "", "display": "Luca Bianchi", "role": "CC"},
                {"email": "", "display": "Anna Verdi", "role": "CAR"},
            ]),
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
            avanzamento="In attesa", chiusa=False, created="2026-09-20 08:00:00"):
        self._id += 1
        with connection.cursor() as cur:
            cur.execute(
                "INSERT INTO anomalie VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                [self._id, op, f"SN{self._id}", desc, "", int(rdc), "", int(cliente), int(chiusa),
                 avanzamento, created],
            )
        return self._id

    def set_row(self, anomalia_id, **campi):
        sets = ", ".join(f"{k} = %s" for k in campi)
        with connection.cursor() as cur:
            cur.execute(f"UPDATE anomalie SET {sets} WHERE id = %s", [*campi.values(), anomalia_id])


class SchedaTests(QualitaBase):
    def test_istantanea_op_e_campi_dedotti(self):
        s = qs.sync_da_anomalia(self.add(avanzamento="Accetto lo stato", cliente=True))
        self.assertEqual((s.op_titolo, s.part_number, s.origine), ("OP/A", "PN-X", Scheda.Origine.PRODUZIONE))
        self.assertEqual((s.disposizione, s.gravita), (Scheda.Disposizione.USO_TALE, Scheda.Gravita.MAGGIORE))

    def test_disposizione_manuale_non_viene_sovrascritta(self):
        s = qs.sync_da_anomalia(self.add(avanzamento="Accetto lo stato"))
        self.assertEqual(qs.applica_modifiche(s, {"disposizione": "SCARTO"}), [])
        self.set_row(s.anomalia_id, aprire_rdc=1)
        s = qs.sync_da_anomalia(s.anomalia_id)
        self.assertEqual((s.disposizione, s.disposizione_auto), (Scheda.Disposizione.SCARTO, False))

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


class NcPerOpTests(QualitaBase):
    def test_una_nc_per_op_alla_prima_anomalia(self):
        a = qs.sync_da_anomalia(self.add("OP/A", created="2025-12-30 10:00:00"))
        b = qs.sync_da_anomalia(self.add("OP/A"))
        c = qs.sync_da_anomalia(self.add("OP/C"))
        self.assertEqual(a.nc_id, b.nc_id)
        self.assertNotEqual(a.nc_id, c.nc_id)
        self.assertEqual((a.nc.protocollo, c.nc.protocollo), ("NC-2025-0001", "NC-2026-0001"))
        self.assertEqual((a.nc.capocommessa, a.nc.car, a.nc.part_number), ("Luca Bianchi", "Anna Verdi", "PN-X"))
        self.assertEqual(a.nc.eventi.filter(tipo="anomalia").count(), 2)

    def test_nc_chiusa_nuova_anomalia_apre_ricaduta(self):
        a = qs.sync_da_anomalia(self.add("OP/A"))
        nc_service.chiudi(a.nc, user=None, note="ok")
        b = qs.sync_da_anomalia(self.add("OP/A"))
        self.assertNotEqual(a.nc_id, b.nc_id)
        self.assertEqual(b.nc.precedente_id, a.nc_id)
        # la vecchia anomalia resta sulla NC chiusa
        a.refresh_from_db()
        self.assertEqual(a.nc.stato, NC.Stato.CHIUSA)

    def test_stato_calcolato_da_sezioni_e_avanzamento(self):
        s = qs.sync_da_anomalia(self.add())
        nc = s.nc
        self.assertEqual(nc.stato, NC.Stato.APERTA)
        self.set_row(s.anomalia_id, avanzamento="Azione di recupero")  # il capocommessa gestisce
        self.assertEqual(nc_service.ricalcola_stato(nc), NC.Stato.CONTENIMENTO)
        nc.causa_radice = "utensile usurato"
        nc.save()
        self.assertEqual(nc_service.ricalcola_stato(nc), NC.Stato.ANALISI)
        azione = AnomaliaNCAzione.objects.create(nc=nc, descrizione="cambio utensile ogni 200 pezzi")
        self.assertEqual(nc_service.ricalcola_stato(nc), NC.Stato.AZIONI)
        azione.stato = AnomaliaNCAzione.Stato.FATTA
        azione.save()
        self.assertEqual(nc_service.ricalcola_stato(nc), NC.Stato.VERIFICA)
        self.assertTrue(nc.eventi.filter(tipo="stato").exists())


class ChiusuraConfigTests(TestCase):
    def test_regole_chiusura(self):
        self.assertEqual(nc_service.get_chiusura_mode(), nc_service.CHIUSURA_GESTORI)
        self.assertTrue(nc_service.puo_chiudere(gestore=True, capocommessa=False, modifica_op=False))
        self.assertFalse(nc_service.puo_chiudere(gestore=False, capocommessa=True, modifica_op=True))
        nc_service.set_chiusura_mode(nc_service.CHIUSURA_GESTORI_CC)
        self.assertTrue(nc_service.puo_chiudere(gestore=False, capocommessa=True, modifica_op=True))
        self.assertFalse(nc_service.puo_chiudere(gestore=False, capocommessa=False, modifica_op=True))
        nc_service.set_chiusura_mode(nc_service.CHIUSURA_MODIFICA)
        self.assertTrue(nc_service.puo_chiudere(gestore=False, capocommessa=False, modifica_op=True))
        self.assertFalse(nc_service.set_chiusura_mode("TUTTI"))


class PromemoriaAzioniTests(QualitaBase):
    def test_promemoria_una_volta_al_giorno(self):
        nc = qs.sync_da_anomalia(self.add()).nc
        oggi = timezone.localdate()
        AnomaliaNCAzione.objects.create(nc=nc, descrizione="scaduta", responsabile_legacy_id=7,
                                        scadenza=oggi - dt.timedelta(days=1))
        AnomaliaNCAzione.objects.create(nc=nc, descrizione="lontana", responsabile_legacy_id=7,
                                        scadenza=oggi + dt.timedelta(days=30))
        AnomaliaNCAzione.objects.create(nc=nc, descrizione="senza responsabile", scadenza=oggi)
        self.assertEqual(nc_service.notifica_azioni_in_scadenza(oggi=oggi), 1)
        self.assertEqual(nc_service.notifica_azioni_in_scadenza(oggi=oggi), 0)
        n = Notifica.objects.get(tipo=nc_service.TIPO_NOTIFICA_AZIONE)
        self.assertEqual(n.legacy_user_id, 7)
        self.assertIn("scaduta", n.messaggio)


class ParetoTests(QualitaBase):
    def test_conteggi_e_filtro(self):
        ids = []
        for tipo in (self.fuori_tol, self.fuori_tol, self.graffi):
            s = qs.sync_da_anomalia(self.add())
            qs.applica_modifiche(s, {"tipo_difetto": tipo.pk})
            ids.append(s.anomalia_id)
        qs.sync_da_anomalia(self.add("OP/C"))  # non classificata
        p = qs.pareto()
        self.assertEqual((p["totale"], p["classificate"], p["nc"]), (4, 3, 2))
        self.assertEqual(p["per_difetto"][0], {"label": self.fuori_tol.nome, "n": 2, "cum_pct": 50.0})
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

    def test_ai_offline_ripiega_sui_casi_simili(self):
        s = qs.sync_da_anomalia(self.add(desc="bava sul bordo del foro filettato"))
        qs.applica_modifiche(s, {"tipo_difetto": self.graffi.pk})
        with patch.object(ai_copilota, "_chiama_ai", return_value=""):
            out = ai_copilota.proponi_classificazione_qualita(
                descrizione="bava sul foro filettato", part_number="PN-X",
                tipi_difetto=self._tipi(), gravita=Scheda.Gravita.choices)
        self.assertEqual((out["tipo_difetto"], out["fonte"]), (self.graffi.pk, "simili"))
        self.assertEqual(out["simili"][0]["protocollo"], s.nc.protocollo)


@patch("anomalie.views._has_table", return_value=True)
class ApiQualitaTests(QualitaBase):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser(username="q-admin", password="pass12345", email="q@x.it")
        self.url = reverse("api_anomalie_qualita")

    def test_get_crea_scheda_e_nc_post_salva(self, _ht):
        self.client.force_login(self.admin)
        aid = self.add(cliente=True)
        r = self.client.get(self.url, {"local_id": f"local:{aid}"})
        self.assertEqual(r.status_code, 200, r.content)
        d = r.json()
        self.assertTrue(d["scheda"]["nc"]["protocollo"].startswith("NC-2026-"))
        self.assertTrue(any(t["value"] == self.fuori_tol.pk for t in d["scelte"]["tipi_difetto"]))
        r = self.client.post(self.url, data=json.dumps({
            "local_id": aid, "tipo_difetto": self.fuori_tol.pk, "gravita": "CRITICA", "disposizione": "SCARTO",
        }), content_type="application/json")
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual((r.json()["scheda"]["gravita"], r.json()["scheda"]["disposizione"]), ("CRITICA", "SCARTO"))

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


class NcPagineTests(QualitaBase):
    def setUp(self):
        super().setUp()
        self.admin = User.objects.create_superuser(username="nc-admin", password="pass12345", email="n@x.it")
        self.nc = qs.sync_da_anomalia(self.add()).nc
        self.url = reverse("anomalie_nc_dettaglio", args=[self.nc.pk])

    def post(self, **dati):
        return self.client.post(self.url, dati)

    def test_lista_dettaglio_e_sezioni(self):
        self.client.force_login(self.admin)
        r = self.client.get(reverse("anomalie_nc_lista"))
        self.assertContains(r, self.nc.protocollo)
        r = self.client.get(self.url)
        self.assertContains(r, "Contenimento immediato")
        self.assertContains(r, "Analisi delle cause")
        self.assertNotContains(r, "{#")
        self.assertEqual(self.post(action="contenimento", contenimento="Pezzi segregati").status_code, 302)
        self.post(action="analisi", analisi_metodo="CINQUE_PERCHE", perche_1="usura", causa_radice="utensile usurato")
        self.post(action="azione_nuova", descrizione="Cambio utensile programmato", scadenza="2026-10-10")
        self.nc.refresh_from_db()
        self.assertEqual(self.nc.stato, NC.Stato.AZIONI)
        self.assertEqual(self.nc.analisi_perche[0], "usura")
        azione = self.nc.azioni.get()
        self.post(action="azione_aggiorna", azione_id=azione.pk, stato="FATTA", esito="fatto")
        self.nc.refresh_from_db()
        self.assertEqual(self.nc.stato, NC.Stato.VERIFICA)
        # verifica positiva da chi puo' chiudere (gestore) => chiusa
        self.post(action="verifica", verifica_esito="EFFICACE", verifica_note="nessun nuovo scarto")
        self.nc.refresh_from_db()
        self.assertEqual(self.nc.stato, NC.Stato.CHIUSA)
        # chiusa: sola lettura
        self.post(action="contenimento", contenimento="modifica tardiva")
        self.nc.refresh_from_db()
        self.assertEqual(self.nc.contenimento, "Pezzi segregati")
        self.post(action="riapri", motivo="ricontrollo")
        self.nc.refresh_from_db()
        self.assertNotEqual(self.nc.stato, NC.Stato.CHIUSA)
        r = self.client.get(reverse("anomalie_nc_pdf", args=[self.nc.pk]))
        self.assertEqual(r["Content-Type"], "application/pdf")
        self.assertTrue(r.content.startswith(b"%PDF"))

    @patch("core.middleware.resolve_acl_access", return_value={"allowed": True})
    def test_capocommessa_compila_ma_non_chiude_di_default(self, _acl):
        user = User.objects.create_user(username="nc-cc", password="pass12345")
        UserOnboarding.objects.update_or_create(user=user, defaults={"completed": True, "skipped": False})
        self.client.force_login(user)
        with patch("anomalie.views._can_view_anomalie_for_op", return_value=True), \
                patch("anomalie.views._can_edit_anomalie_for_op", return_value=True), \
                patch("anomalie.views._op_role_codes_for_current_user", return_value=["CC"]):
            self.assertEqual(self.post(action="contenimento", contenimento="segregati").status_code, 302)
            self.assertEqual(self.post(action="chiudi").status_code, 403)
            SiteConfig.set(nc_service.KEY_CHIUSURA, nc_service.CHIUSURA_GESTORI_CC, "test")
            self.assertEqual(self.post(action="chiudi").status_code, 302)
        self.nc.refresh_from_db()
        self.assertEqual(self.nc.stato, NC.Stato.CHIUSA)

    @patch("core.middleware.resolve_acl_access", return_value={"allowed": True})
    def test_senza_permessi(self, _acl):
        user = User.objects.create_user(username="nc-no", password="pass12345")
        UserOnboarding.objects.update_or_create(user=user, defaults={"completed": True, "skipped": False})
        self.client.force_login(user)
        with patch("anomalie.views._can_view_anomalie_for_op", return_value=False):
            self.assertEqual(self.client.get(self.url).status_code, 403)
        with patch("anomalie.views._can_view_anomalie_for_op", return_value=True), \
                patch("anomalie.views._can_edit_anomalie_for_op", return_value=False):
            self.assertEqual(self.post(action="contenimento", contenimento="x").status_code, 403)


class ConfigTabQualitaTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username="q-cfg", password="pass12345", email="c@x.it")
        self.client.force_login(self.admin)
        self.url = reverse("anomalie_configurazione_page")

    def test_catalogo_e_opzione_chiusura(self):
        r = self.client.post(self.url, {"action": "save_tipo_difetto", "nome": "Ovalizzazione foro", "famiglia": "Dimensionale"})
        self.assertEqual(r.status_code, 302)
        t = AnomaliaTipoDifetto.objects.get(nome="Ovalizzazione foro")
        self.assertEqual(t.codice, "ovalizzazione-foro")
        self.client.post(self.url, {"action": "save_tipo_difetto", "nome": "Altro"})  # doppione
        self.assertEqual(AnomaliaTipoDifetto.objects.filter(nome__iexact="altro").count(), 1)
        self.client.post(self.url, {"action": "toggle_tipo_difetto", "tipo_id": t.pk})
        t.refresh_from_db()
        self.assertFalse(t.attivo)
        self.client.post(self.url, {"action": "save_nc_chiusura", "nc_chiusura": nc_service.CHIUSURA_MODIFICA})
        self.assertEqual(nc_service.get_chiusura_mode(), nc_service.CHIUSURA_MODIFICA)
        r = self.client.get(self.url, {"tab": "qualita"})
        self.assertContains(r, "Catalogo tipi difetto")
        self.assertContains(r, "Chi pu&ograve; chiudere una NC")
        self.assertNotContains(r, "{#")
