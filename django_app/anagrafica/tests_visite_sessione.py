"""Test per la sessione visite mediche "consona" e la coerenza delle scadenze.

Spec:  docs/superpowers/specs/2026-07-15-visite-mediche-sessione-design.md
Piano: docs/superpowers/plans/2026-07-15-visite-mediche-sessione-scadenze.md
"""
from __future__ import annotations

import json
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.backends.signed_cookies import SessionStore
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import RequestFactory, TestCase
from django.utils import timezone

from .models import (
    DipendenteAnagraficaAziendale,
    DipendenteRuoloOperativo,
    DocumentoDipendente,
    RuoloOperativo,
    TipoVisitaMedica,
    VisitaMedica,
)
from .services.visite import ultime_visite_correnti_ids

User = get_user_model()


class UltimeVisiteCorrentiIdsTests(TestCase):
    def setUp(self):
        self.tipo = TipoVisitaMedica.objects.create(nome="Periodica corrente", durata_mesi=12)
        self.tipo_b = TipoVisitaMedica.objects.create(nome="Audiometria corrente", durata_mesi=24)
        self.oggi = timezone.localdate()

    def test_ultima_per_coppia_dipendente_tipo(self):
        VisitaMedica.objects.create(
            legacy_anagrafica_id=1, tipo=self.tipo,
            data_svolgimento=self.oggi - timedelta(days=400),
        )
        recente = VisitaMedica.objects.create(
            legacy_anagrafica_id=1, tipo=self.tipo,
            data_svolgimento=self.oggi - timedelta(days=10),
        )
        altro_tipo = VisitaMedica.objects.create(
            legacy_anagrafica_id=1, tipo=self.tipo_b,
            data_svolgimento=self.oggi - timedelta(days=200),
        )
        self.assertEqual(ultime_visite_correnti_ids(), {recente.pk, altro_tipo.pk})

    def test_retrodatata_inserita_dopo_non_diventa_corrente(self):
        recente = VisitaMedica.objects.create(
            legacy_anagrafica_id=2, tipo=self.tipo,
            data_svolgimento=self.oggi - timedelta(days=5),
        )
        # Inserita DOPO (pk maggiore) ma con data più vecchia: non deve vincere.
        VisitaMedica.objects.create(
            legacy_anagrafica_id=2, tipo=self.tipo,
            data_svolgimento=self.oggi - timedelta(days=500),
        )
        self.assertEqual(ultime_visite_correnti_ids(), {recente.pk})

    def test_spareggio_stessa_data_vince_pk_maggiore(self):
        VisitaMedica.objects.create(
            legacy_anagrafica_id=3, tipo=self.tipo,
            data_svolgimento=self.oggi - timedelta(days=30),
        )
        seconda = VisitaMedica.objects.create(
            legacy_anagrafica_id=3, tipo=self.tipo,
            data_svolgimento=self.oggi - timedelta(days=30),
        )
        self.assertEqual(ultime_visite_correnti_ids(), {seconda.pk})

    def test_filtri_legacy_ids_e_tipo_ids(self):
        v1 = VisitaMedica.objects.create(
            legacy_anagrafica_id=4, tipo=self.tipo,
            data_svolgimento=self.oggi - timedelta(days=10),
        )
        v2 = VisitaMedica.objects.create(
            legacy_anagrafica_id=5, tipo=self.tipo_b,
            data_svolgimento=self.oggi - timedelta(days=10),
        )
        self.assertEqual(ultime_visite_correnti_ids(legacy_ids=[4]), {v1.pk})
        self.assertEqual(ultime_visite_correnti_ids(tipo_ids=[self.tipo_b.pk]), {v2.pk})


class DashboardScadenzeConfermateTests(TestCase):
    """Dopo la registrazione di una nuova visita la vecchia scadenza è
    "confermata": non deve più comparire come scaduta nella dashboard."""

    def setUp(self):
        self.user_super = User.objects.create_superuser(
            username="su-visite-dash", email="su-visite-dash@test.local", password="x"
        )
        self.tipo = TipoVisitaMedica.objects.create(nome="Periodica coerenza", durata_mesi=12)
        self.oggi = timezone.localdate()

    def _dashboard_body(self) -> str:
        from .views import visite_mediche_dashboard
        rf = RequestFactory()
        request = rf.get("/anagrafica/visite-mediche/")
        request.user = self.user_super
        request.session = SessionStore()
        request._messages = FallbackStorage(request)
        resp = visite_mediche_dashboard(request)
        self.assertEqual(resp.status_code, 200)
        return resp.content.decode("utf-8", errors="ignore")

    def test_scadenza_superata_sparisce_dopo_nuova_visita(self):
        # Visita del 10-03-2024 → scadenza 10-03-2025 (passata).
        VisitaMedica.objects.create(
            legacy_anagrafica_id=70, tipo=self.tipo,
            data_svolgimento=date(2024, 3, 10),
        )
        body = self._dashboard_body()
        # Da sola è la visita corrente: la scadenza vecchia compare sia nella
        # tabella "scadute o in scadenza" sia nel log "ultime registrazioni".
        self.assertGreaterEqual(body.count("10-03-2025"), 2)

        # Rinnovo: la vecchia riga resta SOLO nel log "ultime registrazioni"
        # (storico delle registrazioni), non più tra scadute/KPI/per-tipo.
        VisitaMedica.objects.create(
            legacy_anagrafica_id=70, tipo=self.tipo,
            data_svolgimento=self.oggi - timedelta(days=5),
        )
        body = self._dashboard_body()
        self.assertEqual(body.count("10-03-2025"), 1)


class DigestVisiteCorrentiTests(TestCase):
    def test_digest_esclude_righe_superate(self):
        from io import StringIO
        from django.core.management import call_command

        tipo = TipoVisitaMedica.objects.create(nome="Digest corrente", durata_mesi=12)
        oggi = timezone.localdate()
        # Riga vecchia: scadrebbe tra ~20 giorni (dentro la finestra 60gg)...
        VisitaMedica.objects.create(
            legacy_anagrafica_id=90, tipo=tipo,
            data_svolgimento=oggi - timedelta(days=345),
        )
        # ...ma è stata rinnovata ieri: la corrente scade tra ~1 anno.
        VisitaMedica.objects.create(
            legacy_anagrafica_id=90, tipo=tipo,
            data_svolgimento=oggi - timedelta(days=1),
        )
        out = StringIO()
        call_command("send_visite_mediche_digest", "--dry-run", stdout=out)
        self.assertIn("Nessuna visita medica in scadenza", out.getvalue())


class CandidatiSessioneTests(TestCase):
    def setUp(self):
        self.oggi = timezone.localdate()
        self.ruolo = RuoloOperativo.objects.create(nome="Verniciatore")
        self.tipo = TipoVisitaMedica.objects.create(nome="Vernici", durata_mesi=12)
        self.tipo.ruoli_operativi.add(self.ruolo)

    def _candidati(self, tipo=None):
        from .views import _build_candidati_sessione
        return _build_candidati_sessione(tipo or self.tipo, self.oggi)

    def _candidati_ids(self, tipo=None):
        return {c["legacy_id"] for c in self._candidati(tipo)}

    def test_mai_effettuata_proposta_per_ruolo(self):
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=20, ruolo=self.ruolo)
        cand = self._candidati()
        self.assertEqual({c["legacy_id"] for c in cand}, {20})
        self.assertEqual(cand[0]["origine"], "ruolo")
        self.assertEqual(cand[0]["status"], "mai_effettuata")

    def test_cessato_escluso(self):
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=21, ruolo=self.ruolo)
        DipendenteAnagraficaAziendale.objects.create(
            legacy_anagrafica_id=21,
            data_cessazione=self.oggi - timedelta(days=30),
        )
        self.assertEqual(self._candidati_ids(), set())

    def test_abilitato_processo_mod128_incluso(self):
        from .models_mpq import (
            AbilitazioneProcesso, ClienteQualificante, ProcessoQualificato,
        )
        cliente = ClienteQualificante.objects.create(nome="Cliente MPQ test")
        proc = ProcessoQualificato.objects.create(nome="Saldatura speciale", cliente=cliente)
        proc.visite_richieste.add(self.tipo)
        AbilitazioneProcesso.objects.create(legacy_anagrafica_id=22, processo=proc)
        cand = [c for c in self._candidati() if c["legacy_id"] == 22]
        self.assertEqual(len(cand), 1)
        self.assertEqual(cand[0]["origine"], "processo")

    def test_ruolo_configurato_senza_assegnatari_non_degrada_a_storico(self):
        # Il tipo HA un ruolo collegato ma nessuno lo possiede: chi ha solo
        # storico (senza ruolo) NON va proposto.
        VisitaMedica.objects.create(
            legacy_anagrafica_id=33, tipo=self.tipo,
            data_svolgimento=self.oggi - timedelta(days=400),
        )
        self.assertEqual(self._candidati_ids(), set())

    def test_tipo_senza_vincoli_propone_solo_storico(self):
        tipo_libero = TipoVisitaMedica.objects.create(nome="Libera", durata_mesi=12)
        VisitaMedica.objects.create(
            legacy_anagrafica_id=40, tipo=tipo_libero,
            data_svolgimento=self.oggi - timedelta(days=400),
        )
        cand = self._candidati(tipo_libero)
        self.assertEqual({c["legacy_id"] for c in cand}, {40})
        self.assertEqual(cand[0]["origine"], "storico")
        self.assertEqual(cand[0]["data_scadenza"], cand[0]["ultima_visita"].data_scadenza)

    def test_visita_senza_scadenza_non_riproposta(self):
        tipo0 = TipoVisitaMedica.objects.create(nome="Una tantum", durata_mesi=0)
        tipo0.ruoli_operativi.add(self.ruolo)
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=50, ruolo=self.ruolo)
        VisitaMedica.objects.create(
            legacy_anagrafica_id=50, tipo=tipo0,
            data_svolgimento=self.oggi - timedelta(days=1000),
        )
        self.assertEqual(self._candidati_ids(tipo0), set())

    def test_visita_valida_oltre_soglia_non_proposta(self):
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=51, ruolo=self.ruolo)
        VisitaMedica.objects.create(
            legacy_anagrafica_id=51, tipo=self.tipo,
            data_svolgimento=self.oggi - timedelta(days=10),
        )
        self.assertEqual(self._candidati_ids(), set())


class ApiCercaDipendenteTests(TestCase):
    def setUp(self):
        from .tests import _ensure_anagrafica_table
        _ensure_anagrafica_table()
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM anagrafica_dipendenti")
            cursor.execute(
                "INSERT INTO anagrafica_dipendenti (aliasusername, nome, cognome, attivo)"
                " VALUES (%s, %s, %s, %s)",
                ["m.verdi", "Marco", "Verdi", 1],
            )
            cursor.execute(
                "SELECT id FROM anagrafica_dipendenti WHERE aliasusername = %s",
                ["m.verdi"],
            )
            self.legacy_id = int(cursor.fetchone()[0])
        self.user_super = User.objects.create_superuser(
            username="su-api-visite", email="su-api-visite@test.local", password="x"
        )
        self.ruolo = RuoloOperativo.objects.create(nome="Carrellista")
        self.tipo = TipoVisitaMedica.objects.create(nome="Carrelli", durata_mesi=12)
        self.tipo.ruoli_operativi.add(self.ruolo)

    def _get(self, **params):
        from .views import visite_mediche_api_cerca_dipendente
        rf = RequestFactory()
        request = rf.get("/anagrafica/visite-mediche/api/cerca-dipendente/", params)
        request.user = self.user_super
        resp = visite_mediche_api_cerca_dipendente(request)
        return json.loads(resp.content)

    def test_flag_pertinente_false_se_tipo_non_richiesto(self):
        data = self._get(q="verdi", tipo_id=str(self.tipo.pk))
        self.assertEqual(len(data["results"]), 1)
        self.assertFalse(data["results"][0]["pertinente"])

    def test_flag_pertinente_true_se_ruolo_collegato(self):
        DipendenteRuoloOperativo.objects.create(
            legacy_anagrafica_id=self.legacy_id, ruolo=self.ruolo,
        )
        data = self._get(q="verdi", tipo_id=str(self.tipo.pk))
        self.assertTrue(data["results"][0]["pertinente"])

    def test_tipo_senza_vincoli_sempre_pertinente(self):
        tipo_libero = TipoVisitaMedica.objects.create(nome="Libera api", durata_mesi=12)
        data = self._get(q="verdi", tipo_id=str(tipo_libero.pk))
        self.assertTrue(data["results"][0]["pertinente"])

    def test_cessato_escluso_dalla_ricerca(self):
        DipendenteAnagraficaAziendale.objects.create(
            legacy_anagrafica_id=self.legacy_id,
            data_cessazione=timezone.localdate() - timedelta(days=10),
        )
        data = self._get(q="verdi", tipo_id=str(self.tipo.pk))
        self.assertEqual(data["results"], [])


class SessioneBatchPostTests(TestCase):
    def setUp(self):
        self.user_super = User.objects.create_superuser(
            username="su-batch-visite", email="su-batch-visite@test.local", password="x"
        )
        self.oggi = timezone.localdate()
        self.ruolo = RuoloOperativo.objects.create(nome="Molatore")
        self.tipo = TipoVisitaMedica.objects.create(nome="Molatura", durata_mesi=12)
        self.tipo.ruoli_operativi.add(self.ruolo)
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=60, ruolo=self.ruolo)

    def _post(self, data):
        from .views import visite_mediche_nuova_sessione
        rf = RequestFactory()
        request = rf.post("/anagrafica/visite-mediche/nuova-sessione/", data)
        request.user = self.user_super
        request.session = SessionStore()
        request._messages = FallbackStorage(request)
        return visite_mediche_nuova_sessione(request)

    def _base_step2(self, **extra):
        data = {
            "step": "2",
            "tipo_id": str(self.tipo.pk),
            "data_svolgimento": (self.oggi - timedelta(days=1)).isoformat(),
            "medico_competente": "Dr. Test",
            "dipendenti_selezionati": ["60"],
            "esito_60": "IDONEO",
            "prescrizioni_60": "DPI UDITO",
            "note_60": "nota di prova",
        }
        data.update(extra)
        return data

    def test_creazione_con_prescrizioni_e_note_separate(self):
        resp = self._post(self._base_step2())
        self.assertEqual(resp.status_code, 302)
        v = VisitaMedica.objects.get(legacy_anagrafica_id=60)
        self.assertEqual(v.prescrizioni, "DPI UDITO")
        self.assertEqual(v.note, "nota di prova")
        self.assertEqual(v.medico_competente, "Dr. Test")

    def test_doppione_stessa_data_saltato(self):
        self._post(self._base_step2())
        self._post(self._base_step2())
        self.assertEqual(
            VisitaMedica.objects.filter(legacy_anagrafica_id=60).count(), 1,
        )

    def test_data_futura_respinta(self):
        self._post(self._base_step2(
            data_svolgimento=(self.oggi + timedelta(days=3)).isoformat(),
        ))
        self.assertEqual(VisitaMedica.objects.count(), 0)

    def test_referto_per_riga_creato_e_agganciato(self):
        pdf = SimpleUploadedFile(
            "referto.pdf", b"%PDF-1.4 stub", content_type="application/pdf",
        )
        self._post(self._base_step2(referto_60=pdf))
        v = VisitaMedica.objects.get(legacy_anagrafica_id=60)
        self.assertIsNotNone(v.referto_documento_id)
        self.assertEqual(
            v.referto_documento.tipo, DocumentoDipendente.Tipo.VISITA_MEDICA_REFERTO,
        )
        self.assertEqual(v.referto_documento.legacy_anagrafica_id, 60)


class SessioneStep2RenderTests(TestCase):
    def setUp(self):
        self.user_super = User.objects.create_superuser(
            username="su-render-visite", email="su-render-visite@test.local", password="x"
        )
        self.oggi = timezone.localdate()
        self.ruolo = RuoloOperativo.objects.create(nome="Fonditore")
        self.tipo = TipoVisitaMedica.objects.create(nome="Fonderia", durata_mesi=12)
        self.tipo.ruoli_operativi.add(self.ruolo)
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=80, ruolo=self.ruolo)
        VisitaMedica.objects.create(
            legacy_anagrafica_id=80, tipo=self.tipo,
            data_svolgimento=self.oggi - timedelta(days=400),
        )

    def test_step2_mostra_nuove_colonne_e_campi(self):
        from .views import visite_mediche_nuova_sessione
        rf = RequestFactory()
        request = rf.post("/anagrafica/visite-mediche/nuova-sessione/", {
            "step": "1",
            "tipo_id": str(self.tipo.pk),
            "data_svolgimento": self.oggi.isoformat(),
            "medico_competente": "",
        })
        request.user = self.user_super
        request.session = SessionStore()
        request._messages = FallbackStorage(request)
        resp = visite_mediche_nuova_sessione(request)
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode("utf-8", errors="ignore")
        self.assertIn("Scadenza attuale", body)
        self.assertIn('name="prescrizioni_80"', body)
        self.assertIn('name="note_80"', body)
        self.assertIn('name="referto_80"', body)
        self.assertIn('enctype="multipart/form-data"', body)
        self.assertIn("Nuova scadenza", body)
        self.assertIn("Ruolo", body)  # badge origine


class VisitaSessioneModelTests(TestCase):
    def setUp(self):
        self.oggi = timezone.localdate()
        self.tipo = TipoVisitaMedica.objects.create(nome="Giornata VDT", durata_mesi=12)

    def test_crea_sessione_e_collega_visita(self):
        from .models import VisitaSessione
        sess = VisitaSessione.objects.create(
            data_svolgimento=self.oggi, medico_competente="Dr. Test",
        )
        v = VisitaMedica.objects.create(
            legacy_anagrafica_id=1, tipo=self.tipo,
            data_svolgimento=self.oggi, sessione=sess,
        )
        self.assertEqual(v.sessione_id, sess.pk)
        self.assertEqual(list(sess.visite.all()), [v])

    def test_elimina_sessione_conserva_visite(self):
        from .models import VisitaSessione
        sess = VisitaSessione.objects.create(
            data_svolgimento=self.oggi, medico_competente="Dr. Test",
        )
        v = VisitaMedica.objects.create(
            legacy_anagrafica_id=2, tipo=self.tipo,
            data_svolgimento=self.oggi, sessione=sess,
        )
        sess.delete()
        v.refresh_from_db()
        self.assertIsNone(v.sessione_id)  # SET_NULL: la visita resta


class CandidatiGiornataTests(TestCase):
    def setUp(self):
        self.oggi = timezone.localdate()
        self.ruolo = RuoloOperativo.objects.create(nome="Multi")
        self.tipo_a = TipoVisitaMedica.objects.create(nome="VDT", durata_mesi=12)
        self.tipo_b = TipoVisitaMedica.objects.create(nome="Rumore", durata_mesi=12)
        self.tipo_a.ruoli_operativi.add(self.ruolo)
        self.tipo_b.ruoli_operativi.add(self.ruolo)
        # legacy 30 ha il ruolo → entrambi i tipi dovuti (mai effettuati)
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=30, ruolo=self.ruolo)

    def _giornata(self, tipo_id=None):
        from .views import _build_candidati_giornata
        return _build_candidati_giornata(self.oggi, tipo_id=tipo_id)

    def test_persona_con_due_tipi_dovuti_due_righe(self):
        righe = [r for r in self._giornata() if r["legacy_id"] == 30]
        self.assertEqual(len(righe), 2)
        self.assertEqual({r["tipo"].nome for r in righe}, {"VDT", "Rumore"})

    def test_filtro_tipo_id_limita_a_un_tipo(self):
        righe = self._giornata(tipo_id=self.tipo_a.pk)
        self.assertTrue(all(r["tipo"].pk == self.tipo_a.pk for r in righe))
        self.assertEqual({r["legacy_id"] for r in righe}, {30})

    def test_preselect_su_scaduta_e_in_scadenza(self):
        VisitaMedica.objects.create(
            legacy_anagrafica_id=30, tipo=self.tipo_a,
            data_svolgimento=self.oggi - timedelta(days=400),
        )
        riga_a = next(r for r in self._giornata(tipo_id=self.tipo_a.pk) if r["legacy_id"] == 30)
        self.assertEqual(riga_a["status"], "scaduta")
        self.assertTrue(riga_a["preselect"])

    def test_cessato_escluso(self):
        DipendenteAnagraficaAziendale.objects.create(
            legacy_anagrafica_id=30,
            data_cessazione=self.oggi - timedelta(days=10),
        )
        self.assertEqual(self._giornata(), [])


class SessioniHubTests(TestCase):
    def setUp(self):
        self.user_super = User.objects.create_superuser(
            username="su-hub", email="su-hub@test.local", password="x"
        )
        self.oggi = timezone.localdate()
        self.ruolo = RuoloOperativo.objects.create(nome="HubR")
        self.tipo = TipoVisitaMedica.objects.create(nome="HubT", durata_mesi=12)
        self.tipo.ruoli_operativi.add(self.ruolo)
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=77, ruolo=self.ruolo)
        VisitaMedica.objects.create(
            legacy_anagrafica_id=77, tipo=self.tipo,
            data_svolgimento=self.oggi - timedelta(days=400),  # scaduta
        )

    def test_hub_mostra_proposta_e_deeplink(self):
        from .views import visite_mediche_sessioni
        rf = RequestFactory()
        request = rf.get("/anagrafica/visite-mediche/sessioni/")
        request.user = self.user_super
        request.session = SessionStore()
        request._messages = FallbackStorage(request)
        resp = visite_mediche_sessioni(request)
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn("HubT", body)
        self.assertIn(f"nuova-sessione/?tipo={self.tipo.pk}", body)


class SessioneDetailTests(TestCase):
    def setUp(self):
        self.user_super = User.objects.create_superuser(
            username="su-det", email="su-det@test.local", password="x"
        )
        self.oggi = timezone.localdate()
        self.tipo = TipoVisitaMedica.objects.create(nome="DetT", durata_mesi=12)

    def _mk_sess(self):
        from .models import VisitaSessione
        sess = VisitaSessione.objects.create(data_svolgimento=self.oggi, medico_competente="Dr. Det")
        VisitaMedica.objects.create(
            legacy_anagrafica_id=88, tipo=self.tipo,
            data_svolgimento=self.oggi, sessione=sess,
        )
        return sess

    def test_dettaglio_render(self):
        from .views import visite_mediche_sessione_detail
        sess = self._mk_sess()
        rf = RequestFactory()
        request = rf.get(f"/anagrafica/visite-mediche/sessioni/{sess.pk}/")
        request.user = self.user_super
        request.session = SessionStore()
        request._messages = FallbackStorage(request)
        resp = visite_mediche_sessione_detail(request, sess.pk)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Dr. Det", resp.content.decode())

    def test_aggiungi_partecipante_crea_visita_nella_sessione(self):
        from .views import visite_mediche_sessione_partecipante_add
        sess = self._mk_sess()
        rf = RequestFactory()
        request = rf.post(
            f"/anagrafica/visite-mediche/sessioni/{sess.pk}/partecipante/aggiungi/",
            {"legacy_id": "99", "tipo_id": str(self.tipo.pk), "esito": "IDONEO"},
        )
        request.user = self.user_super
        request.session = SessionStore()
        request._messages = FallbackStorage(request)
        resp = visite_mediche_sessione_partecipante_add(request, sess.pk)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            VisitaMedica.objects.filter(legacy_anagrafica_id=99, sessione=sess).exists()
        )

    def test_elimina_sessione_conserva_visite(self):
        from .views import visite_mediche_sessione_delete
        from .models import VisitaSessione
        sess = self._mk_sess()
        rf = RequestFactory()
        request = rf.post(f"/anagrafica/visite-mediche/sessioni/{sess.pk}/elimina/")
        request.user = self.user_super
        request.session = SessionStore()
        request._messages = FallbackStorage(request)
        visite_mediche_sessione_delete(request, sess.pk)
        self.assertFalse(VisitaSessione.objects.filter(pk=sess.pk).exists())
        self.assertTrue(VisitaMedica.objects.filter(legacy_anagrafica_id=88).exists())


class GiornataPostTests(TestCase):
    def setUp(self):
        self.user_super = User.objects.create_superuser(
            username="su-giornata", email="su-giornata@test.local", password="x"
        )
        self.oggi = timezone.localdate()
        self.ruolo = RuoloOperativo.objects.create(nome="MultiG")
        self.tipo_a = TipoVisitaMedica.objects.create(nome="VDT-G", durata_mesi=12)
        self.tipo_b = TipoVisitaMedica.objects.create(nome="Rumore-G", durata_mesi=12)
        self.tipo_a.ruoli_operativi.add(self.ruolo)
        self.tipo_b.ruoli_operativi.add(self.ruolo)
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=41, ruolo=self.ruolo)

    def _post(self, data):
        from .views import visite_mediche_nuova_sessione
        rf = RequestFactory()
        request = rf.post("/anagrafica/visite-mediche/nuova-sessione/", data)
        request.user = self.user_super
        request.session = SessionStore()
        request._messages = FallbackStorage(request)
        return visite_mediche_nuova_sessione(request)

    def test_giornata_crea_sessione_e_visite_di_tipi_misti(self):
        from .models import VisitaSessione
        a, b = self.tipo_a.pk, self.tipo_b.pk
        data = {
            "data_svolgimento": (self.oggi - timedelta(days=1)).isoformat(),
            "medico_competente": "Dr. Giornata", "luogo": "Infermeria",
            f"sel_41_{a}": "1", f"esito_41_{a}": "IDONEO",
            f"prescrizioni_41_{a}": "DPI", f"note_41_{a}": "",
            f"sel_41_{b}": "1", f"esito_41_{b}": "IDONEO",
            f"prescrizioni_41_{b}": "", f"note_41_{b}": "",
        }
        resp = self._post(data)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(VisitaSessione.objects.count(), 1)
        sess = VisitaSessione.objects.get()
        self.assertEqual(sess.medico_competente, "Dr. Giornata")
        self.assertEqual(sess.visite.count(), 2)
        self.assertEqual({v.tipo_id for v in sess.visite.all()}, {a, b})

    def test_data_futura_respinta_nessuna_sessione(self):
        from .models import VisitaSessione
        a = self.tipo_a.pk
        self._post({
            "data_svolgimento": (self.oggi + timedelta(days=3)).isoformat(),
            "medico_competente": "X",
            f"sel_41_{a}": "1", f"esito_41_{a}": "IDONEO",
        })
        self.assertEqual(VisitaSessione.objects.count(), 0)
        self.assertEqual(VisitaMedica.objects.count(), 0)

    def test_doppione_saltato(self):
        a = self.tipo_a.pk
        VisitaMedica.objects.create(
            legacy_anagrafica_id=41, tipo=self.tipo_a,
            data_svolgimento=self.oggi - timedelta(days=1),
        )
        self._post({
            "data_svolgimento": (self.oggi - timedelta(days=1)).isoformat(),
            "medico_competente": "X",
            f"sel_41_{a}": "1", f"esito_41_{a}": "IDONEO",
        })
        self.assertEqual(
            VisitaMedica.objects.filter(legacy_anagrafica_id=41, tipo=self.tipo_a).count(), 1
        )


class CandidatiHtmxTests(TestCase):
    def setUp(self):
        self.user_super = User.objects.create_superuser(
            username="su-htmx", email="su-htmx@test.local", password="x"
        )
        self.user_plain = User.objects.create_user(
            username="plain-htmx", email="plain-htmx@test.local", password="x"
        )
        self.oggi = timezone.localdate()
        self.ruolo = RuoloOperativo.objects.create(nome="HtmxR")
        self.tipo = TipoVisitaMedica.objects.create(nome="HtmxT", durata_mesi=12)
        self.tipo.ruoli_operativi.add(self.ruolo)
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=55, ruolo=self.ruolo)

    def _get(self, user, **params):
        from .views import visite_mediche_candidati
        rf = RequestFactory()
        request = rf.get("/anagrafica/visite-mediche/candidati/", params)
        request.user = user
        request.session = SessionStore()
        return visite_mediche_candidati(request)

    def test_403_senza_permesso(self):
        from .models import AnagraficaVisiteMedichePermission
        perm = AnagraficaVisiteMedichePermission.get_instance()
        perm.accesso = AnagraficaVisiteMedichePermission.ACCESSO_ADMIN
        perm.save()
        resp = self._get(self.user_plain, tipo=str(self.tipo.pk))
        self.assertEqual(resp.status_code, 403)

    def test_rende_righe_per_tipo(self):
        resp = self._get(self.user_super, tipo=str(self.tipo.pk))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn(f'name="sel_55_{self.tipo.pk}"', body)
        self.assertIn("HtmxT", body)


class GiornataRenderTests(TestCase):
    def setUp(self):
        self.user_super = User.objects.create_superuser(
            username="su-grender", email="su-grender@test.local", password="x"
        )
        self.oggi = timezone.localdate()
        self.ruolo = RuoloOperativo.objects.create(nome="GRR")
        self.tipo = TipoVisitaMedica.objects.create(nome="GRT", durata_mesi=12)
        self.tipo.ruoli_operativi.add(self.ruolo)
        DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=66, ruolo=self.ruolo)
        VisitaMedica.objects.create(
            legacy_anagrafica_id=66, tipo=self.tipo,
            data_svolgimento=self.oggi - timedelta(days=400),
        )

    def _get(self, **params):
        from .views import visite_mediche_nuova_sessione
        rf = RequestFactory()
        request = rf.get("/anagrafica/visite-mediche/nuova-sessione/", params)
        request.user = self.user_super
        request.session = SessionStore()
        request._messages = FallbackStorage(request)
        return visite_mediche_nuova_sessione(request)

    def test_pagina_ha_form_multipart_e_htmx(self):
        resp = self._get()
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('enctype="multipart/form-data"', body)
        self.assertIn("visite-mediche/candidati", body)
        self.assertIn("Giornata visite", body)

    def test_deeplink_tipo_rende_candidati_server_side(self):
        resp = self._get(tipo=str(self.tipo.pk))
        body = resp.content.decode()
        self.assertIn(f'name="sel_66_{self.tipo.pk}"', body)


class ScadenzarioRinnovoVisiteTests(TestCase):
    def setUp(self):
        from .tests import _ensure_anagrafica_table
        _ensure_anagrafica_table()
        self.user_super = User.objects.create_superuser(
            username="su-scad-rin", email="su-scad-rin@test.local", password="x"
        )
        self.oggi = timezone.localdate()
        self.tipo = TipoVisitaMedica.objects.create(nome="ScadRinT", durata_mesi=12)
        VisitaMedica.objects.create(
            legacy_anagrafica_id=111, tipo=self.tipo,
            data_svolgimento=self.oggi - timedelta(days=400),  # scaduta
        )

    def test_voce_visita_porta_tipo_id(self):
        from .views import _build_scadenzario_voci
        from django.test import RequestFactory
        rf = RequestFactory()
        request = rf.get("/anagrafica/scadenzario/")
        request.user = self.user_super
        voci = _build_scadenzario_voci(request, filtro_tipo="visita", filtro_stato="", filtro_reparto="")
        vis = [v for v in voci if v["kind"] == "visita"]
        self.assertTrue(vis)
        self.assertEqual(vis[0]["tipo_id"], self.tipo.pk)

    def test_gruppo_visita_ha_pulsante_rinnovo(self):
        from django.urls import reverse
        self.client.force_login(self.user_super)
        resp = self.client.get(reverse("anagrafica:scadenzario"), {"tipo": "visita"})
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn(f"nuova-sessione/?tipo={self.tipo.pk}", body)
