"""Spostamenti organizzativi: periodo unico, attivazione differita, idoneità.

Copre le tre garanzie del modulo:

- uno spostamento è **un atto solo** (reparto + area + mansione + ruolo con la
  stessa decorrenza) e chiude il precedente;
- una decorrenza futura resta **programmata**: i campi vivi del dipendente non
  si toccano finché non arriva la data, e li allinea il task;
- al cambio parte la **verifica di idoneità** su competenze, DPI e visite, il
  cui esito viene fotografato sull'assegnazione.
"""
from __future__ import annotations

import datetime

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import (
    AreaAziendale, DipendenteAnagraficaAziendale, DipendenteAssegnazione,
    DipendenteCambiamentoOrganizzativo, Mansione, Reparto, RuoloAziendale,
)
from .tests import _ensure_anagrafica_table

User = get_user_model()


def _oggi():
    return timezone.localdate()


def _fra(giorni: int):
    return _oggi() + datetime.timedelta(days=giorni)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class StatoAssegnazioneTests(TestCase):
    """Lo stato è derivato dalle date: programmata / in corso / conclusa."""

    def _ass(self, inizio, fine=None):
        return DipendenteAssegnazione.objects.create(
            legacy_anagrafica_id=2001, data_inizio=inizio, data_fine=fine, reparto="UT",
        )

    def test_decorrenza_futura_e_programmata(self):
        a = self._ass(_fra(24))
        self.assertEqual(a.stato, DipendenteAssegnazione.STATO_PROGRAMMATA)
        self.assertEqual(a.stato_label, "Programmata")
        self.assertTrue(a.is_programmata)
        self.assertFalse(a.is_in_corso)

    def test_periodo_aperto_gia_decorso_e_in_corso(self):
        a = self._ass(_fra(-10))
        self.assertEqual(a.stato, DipendenteAssegnazione.STATO_IN_CORSO)
        self.assertTrue(a.is_in_corso)

    def test_periodo_chiuso_nel_passato_e_concluso(self):
        a = self._ass(_fra(-60), fine=_fra(-10))
        self.assertEqual(a.stato, DipendenteAssegnazione.STATO_CONCLUSA)

    def test_periodo_che_contiene_oggi_e_in_corso(self):
        a = self._ass(_fra(-10), fine=_fra(10))
        self.assertTrue(a.is_in_corso)

    def test_chiudi_aperta_chiude_al_giorno_prima(self):
        vecchia = self._ass(_fra(-30))
        DipendenteAssegnazione.chiudi_aperta(2001, _fra(-5))
        vecchia.refresh_from_db()
        self.assertEqual(vecchia.data_fine, _fra(-6))

    def test_chiusura_retroattiva_non_produce_fine_prima_dell_inizio(self):
        vecchia = self._ass(_fra(-5))
        DipendenteAssegnazione.chiudi_aperta(2001, _fra(-30))
        vecchia.refresh_from_db()
        self.assertEqual(vecchia.data_fine, vecchia.data_inizio)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class VerificaIdoneitaTests(TestCase):
    """L'escalation su competenze / DPI / visite mediche."""

    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()

    def test_mansione_vuota_non_produce_requisiti(self):
        from .services.assegnazioni import verifica_idoneita
        esito = verifica_idoneita(2101, "")
        self.assertEqual(esito["esito"], DipendenteAssegnazione.IDONEITA_NA)
        self.assertEqual(esito["gap"], [])

    def test_mansione_con_corso_obbligatorio_mai_frequentato_da_gap(self):
        from .models_formazione import TrainingCourse, TrainingPlan, TrainingRequirementRule
        from .services.assegnazioni import verifica_idoneita

        mansione = Mansione.objects.create(nome="Tornitore")
        piano = TrainingPlan.objects.create(codice="PS", nome="Piano sicurezza")
        corso = TrainingCourse.objects.create(
            piano=piano, codice="C1", titolo="Uso tornio", durata_ore_teorica=8,
        )
        TrainingRequirementRule.objects.create(
            corso=corso, mansione=mansione, is_active=True, is_mandatory=True,
        )

        esito = verifica_idoneita(2102, "Tornitore")
        self.assertEqual(esito["esito"], DipendenteAssegnazione.IDONEITA_WARN)
        self.assertEqual(esito["label"], "Abilitazione parziale")
        self.assertIn("Corso: Uso tornio", esito["mancanti"])
        self.assertIn("Uso tornio", esito["per_dominio"]["formazione"])

    def test_gap_raggruppato_per_dominio_con_scaduti_marcati(self):
        from .services.assegnazioni import _raggruppa_per_dominio
        gruppi = _raggruppa_per_dominio(
            scaduti=["DPI: Guanti antitaglio"],
            mancanti=["Corso: Primo soccorso", "Visita: Sorveglianza"],
        )
        self.assertEqual(gruppi["dpi"], ["Guanti antitaglio (scaduto)"])
        self.assertEqual(gruppi["formazione"], ["Primo soccorso"])
        self.assertEqual(gruppi["visite"], ["Sorveglianza"])

    def test_verifica_fail_open_se_il_calcolo_esplode(self):
        """Un errore nel calcolo non deve impedire di registrare lo spostamento."""
        from unittest.mock import patch
        from .services.assegnazioni import verifica_idoneita
        with patch(
            "anagrafica.services.conformita.stato_conformita",
            side_effect=RuntimeError("boom"),
        ):
            esito = verifica_idoneita(2103, "Tornitore")
        self.assertEqual(esito["label"], "Da verificare")
        self.assertEqual(esito["gap"], [])


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class SpostamentoViewTests(TestCase):
    """Il form unico di spostamento nella card Anagrafica aziendale."""

    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()
        cls.admin = User.objects.create_superuser(
            username="sposta_admin", email="sposta_admin@x.local", password="x"
        )

    def setUp(self):
        self.client.force_login(self.admin)
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM anagrafica_dipendenti")
            cursor.execute(
                "INSERT INTO anagrafica_dipendenti (aliasusername, nome, cognome, reparto, mansione, attivo) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                ["m.spost", "Mario", "Spost", "CNC", "Operatore CNC", 1],
            )
            cursor.execute(
                "SELECT id FROM anagrafica_dipendenti WHERE aliasusername = %s", ["m.spost"]
            )
            self.legacy_id = int(cursor.fetchone()[0])
        self.rep_torni = Reparto.objects.create(nome="TORNI", caporeparto_legacy_id=777)
        Reparto.objects.create(nome="CNC")
        self.area = AreaAziendale.objects.create(nome="IN1", reparto=self.rep_torni)
        RuoloAziendale.objects.create(nome="Capoturno")

    def _legacy(self, campo):
        with connection.cursor() as cur:
            cur.execute(f"SELECT {campo} FROM anagrafica_dipendenti WHERE id = %s", [self.legacy_id])
            return (cur.fetchone() or [None])[0]

    def _post(self, **extra):
        payload = {"reparto": "TORNI", "mansione": "Tornitore", "ruolo_aziendale": "Capoturno"}
        payload.update(extra)
        return self.client.post(
            reverse("anagrafica:dipendente_assegnazione_create", args=[self.legacy_id]),
            payload,
        )

    # ── Spostamento immediato ──────────────────────────────────────────────
    def test_decorrenza_odierna_applica_subito_i_campi_vivi(self):
        resp = self._post(data_inizio=_oggi().isoformat(), area_aziendale=str(self.area.pk))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self._legacy("reparto"), "TORNI")
        self.assertEqual(self._legacy("mansione"), "Tornitore")
        az = DipendenteAnagraficaAziendale.objects.get(legacy_anagrafica_id=self.legacy_id)
        self.assertEqual(az.area, "TORNI")
        self.assertEqual(az.area_aziendale_id, self.area.pk)
        self.assertEqual(az.ruolo_aziendale, "Capoturno")

    def test_spostamento_immediato_e_marcato_attivato(self):
        self._post(data_inizio=_oggi().isoformat())
        a = DipendenteAssegnazione.objects.get(legacy_anagrafica_id=self.legacy_id)
        self.assertIsNotNone(a.attivata_il)
        self.assertTrue(a.is_in_corso)

    def test_i_quattro_campi_stanno_in_una_sola_assegnazione(self):
        self._post(data_inizio=_oggi().isoformat(), area_aziendale=str(self.area.pk))
        assegnazioni = DipendenteAssegnazione.objects.filter(legacy_anagrafica_id=self.legacy_id)
        self.assertEqual(assegnazioni.count(), 1)
        a = assegnazioni.first()
        self.assertEqual(
            (a.reparto, a.area_aziendale_id, a.mansione, a.ruolo_aziendale),
            ("TORNI", self.area.pk, "Tornitore", "Capoturno"),
        )

    # ── Spostamento programmato ────────────────────────────────────────────
    def test_decorrenza_futura_non_tocca_i_campi_vivi(self):
        """Il bug segnalato: registrando «dal 31-08» il dipendente restava a CNC
        solo nello storico, ma il campo vivo passava subito a TORNI."""
        self._post(data_inizio=_fra(24).isoformat())
        self.assertEqual(self._legacy("reparto"), "CNC")
        self.assertEqual(self._legacy("mansione"), "Operatore CNC")

    def test_decorrenza_futura_resta_programmata_e_non_attivata(self):
        self._post(data_inizio=_fra(24).isoformat())
        a = DipendenteAssegnazione.objects.get(legacy_anagrafica_id=self.legacy_id)
        self.assertTrue(a.is_programmata)
        self.assertIsNone(a.attivata_il)

    def test_task_attiva_lo_spostamento_quando_la_data_arriva(self):
        self._post(data_inizio=_fra(5).isoformat())
        a = DipendenteAssegnazione.objects.get(legacy_anagrafica_id=self.legacy_id)

        # Il task non tocca nulla finché la decorrenza è nel futuro.
        from .services.assegnazioni import attiva_programmate_scadute
        self.assertEqual(attiva_programmate_scadute()["attivate"], 0)
        self.assertEqual(self._legacy("reparto"), "CNC")

        # Arrivata la data, allinea i campi vivi.
        DipendenteAssegnazione.objects.filter(pk=a.pk).update(data_inizio=_oggi())
        self.assertEqual(attiva_programmate_scadute()["attivate"], 1)
        self.assertEqual(self._legacy("reparto"), "TORNI")
        self.assertEqual(self._legacy("mansione"), "Tornitore")

    def test_attivazione_e_idempotente(self):
        self._post(data_inizio=_oggi().isoformat())
        from .services.assegnazioni import attiva_programmate_scadute
        self.assertEqual(attiva_programmate_scadute()["attivate"], 0)

    def test_log_per_campo_usa_la_decorrenza_non_la_data_di_attivazione(self):
        """Se il task gira in ritardo, la decorrenza formale resta quella giusta."""
        self._post(data_inizio=_fra(3).isoformat())
        a = DipendenteAssegnazione.objects.get(legacy_anagrafica_id=self.legacy_id)
        decorrenza = _fra(3)
        DipendenteAssegnazione.objects.filter(pk=a.pk).update(data_inizio=decorrenza)

        from .services.assegnazioni import attiva_assegnazione
        a.refresh_from_db()
        a.data_inizio = _fra(-2)  # decorrenza passata: il task è in ritardo di 2 giorni
        a.save(update_fields=["data_inizio"])
        attiva_assegnazione(a)

        log = DipendenteCambiamentoOrganizzativo.objects.filter(
            legacy_anagrafica_id=self.legacy_id,
            tipo=DipendenteCambiamentoOrganizzativo.TIPO_REPARTO,
            valore_nuovo="TORNI",
        ).first()
        self.assertIsNotNone(log)
        self.assertEqual(log.data_effetto, _fra(-2))

    # ── Concatenamento ─────────────────────────────────────────────────────
    def test_secondo_spostamento_chiude_il_primo(self):
        self._post(data_inizio=_fra(-30).isoformat())
        self._post(reparto="CNC", mansione="Operatore CNC", data_inizio=_oggi().isoformat())
        periodi = list(
            DipendenteAssegnazione.objects
            .filter(legacy_anagrafica_id=self.legacy_id).order_by("data_inizio")
        )
        self.assertEqual(len(periodi), 2)
        self.assertEqual(periodi[0].data_fine, _fra(-1))
        self.assertIsNone(periodi[1].data_fine)

    def test_area_di_un_altro_reparto_viene_scartata(self):
        rep_altro = Reparto.objects.create(nome="MAG")
        area_altro = AreaAziendale.objects.create(nome="ZONA1", reparto=rep_altro)
        self._post(data_inizio=_oggi().isoformat(), area_aziendale=str(area_altro.pk))
        a = DipendenteAssegnazione.objects.get(legacy_anagrafica_id=self.legacy_id)
        self.assertIsNone(a.area_aziendale_id)

    # ── Annullamento ───────────────────────────────────────────────────────
    def test_annulla_spostamento_programmato(self):
        self._post(data_inizio=_fra(-30).isoformat())
        self._post(reparto="CNC", data_inizio=_fra(20).isoformat())
        programmata = DipendenteAssegnazione.objects.get(
            legacy_anagrafica_id=self.legacy_id, data_inizio=_fra(20)
        )
        resp = self.client.post(reverse(
            "anagrafica:dipendente_assegnazione_annulla",
            args=[self.legacy_id, programmata.pk],
        ))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(DipendenteAssegnazione.objects.filter(pk=programmata.pk).exists())
        # La precedente torna aperta: annullare non deve lasciare un buco.
        rimasta = DipendenteAssegnazione.objects.get(legacy_anagrafica_id=self.legacy_id)
        self.assertIsNone(rimasta.data_fine)

    def test_non_si_annulla_uno_spostamento_gia_attivo(self):
        self._post(data_inizio=_oggi().isoformat())
        attiva = DipendenteAssegnazione.objects.get(legacy_anagrafica_id=self.legacy_id)
        self.client.post(reverse(
            "anagrafica:dipendente_assegnazione_annulla", args=[self.legacy_id, attiva.pk],
        ))
        self.assertTrue(DipendenteAssegnazione.objects.filter(pk=attiva.pk).exists())

    # ── Permessi ───────────────────────────────────────────────────────────
    def test_non_admin_non_puo_spostare(self):
        self.client.force_login(User.objects.create_user(username="sposta_plain", password="x"))
        self._post(data_inizio=_oggi().isoformat())
        self.assertEqual(self._legacy("reparto"), "CNC")
        self.assertFalse(DipendenteAssegnazione.objects.exists())

    def test_verifica_idoneita_negata_ai_non_admin(self):
        self.client.force_login(User.objects.create_user(username="verif_plain", password="x"))
        resp = self.client.get(
            reverse("anagrafica:dipendente_assegnazione_verifica", args=[self.legacy_id]),
            {"mansione": "Tornitore"},
        )
        self.assertEqual(resp.status_code, 403)

    # ── Idoneità agganciata allo spostamento ───────────────────────────────
    def test_snapshot_idoneita_salvato_sull_assegnazione(self):
        from .models_formazione import TrainingCourse, TrainingPlan, TrainingRequirementRule
        mansione = Mansione.objects.create(nome="Tornitore")
        piano = TrainingPlan.objects.create(codice="PS", nome="Piano sicurezza")
        corso = TrainingCourse.objects.create(
            piano=piano, codice="C1", titolo="Uso tornio", durata_ore_teorica=8,
        )
        TrainingRequirementRule.objects.create(
            corso=corso, mansione=mansione, is_active=True, is_mandatory=True,
        )
        self._post(data_inizio=_oggi().isoformat())
        a = DipendenteAssegnazione.objects.get(legacy_anagrafica_id=self.legacy_id)
        self.assertEqual(a.idoneita_esito, DipendenteAssegnazione.IDONEITA_WARN)
        self.assertEqual(a.idoneita_label, "Abilitazione parziale")
        self.assertIn("Corso: Uso tornio", a.idoneita_gap)
        self.assertIsNotNone(a.idoneita_verificata_il)

    def test_endpoint_verifica_restituisce_json_con_gap(self):
        from .models_formazione import TrainingCourse, TrainingPlan, TrainingRequirementRule
        mansione = Mansione.objects.create(nome="Tornitore")
        piano = TrainingPlan.objects.create(codice="PS", nome="Piano sicurezza")
        corso = TrainingCourse.objects.create(
            piano=piano, codice="C1", titolo="Uso tornio", durata_ore_teorica=8,
        )
        TrainingRequirementRule.objects.create(
            corso=corso, mansione=mansione, is_active=True, is_mandatory=True,
        )
        resp = self.client.get(
            reverse("anagrafica:dipendente_assegnazione_verifica", args=[self.legacy_id]),
            {"mansione": "Tornitore"},
        )
        self.assertEqual(resp.status_code, 200)
        dati = resp.json()
        self.assertEqual(dati["label"], "Abilitazione parziale")
        self.assertIn("Uso tornio", dati["per_dominio"]["formazione"])


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class SchedaDipendenteSpostamentiUITests(TestCase):
    """La card degli spostamenti in scheda dipendente."""

    @classmethod
    def setUpTestData(cls):
        _ensure_anagrafica_table()
        cls.admin = User.objects.create_superuser(
            username="sposta_ui_admin", email="sposta_ui_admin@x.local", password="x"
        )

    def setUp(self):
        self.client.force_login(self.admin)
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM anagrafica_dipendenti")
            cursor.execute(
                "INSERT INTO anagrafica_dipendenti (aliasusername, nome, cognome, attivo) "
                "VALUES (%s, %s, %s, %s)",
                ["u.sposta", "Ugo", "Sposta", 1],
            )
            cursor.execute(
                "SELECT id FROM anagrafica_dipendenti WHERE aliasusername = %s", ["u.sposta"]
            )
            self.legacy_id = int(cursor.fetchone()[0])

    def test_pagina_espone_il_form_di_spostamento(self):
        resp = self.client.get(reverse("anagrafica:dipendente_detail", args=[self.legacy_id]))
        content = resp.content.decode()
        self.assertIn("Spostamenti organizzativi", content)
        self.assertIn('id="sp-mansione"', content)
        self.assertIn('name="data_inizio"', content)

    def test_i_vecchi_miniform_non_esistono_piu(self):
        """Un secondo scrittore su reparto/mansione desincronizzerebbe l'assegnazione."""
        resp = self.client.get(reverse("anagrafica:dipendente_detail", args=[self.legacy_id]))
        content = resp.content.decode()
        self.assertNotIn("toggleMansioneForm", content)
        self.assertNotIn("toggleRepartoForm", content)

    def test_card_programmata_si_distingue_da_quella_in_corso(self):
        DipendenteAssegnazione.objects.create(
            legacy_anagrafica_id=self.legacy_id, data_inizio=_fra(-20),
            data_fine=_fra(23), reparto="CNC",
        )
        DipendenteAssegnazione.objects.create(
            legacy_anagrafica_id=self.legacy_id, data_inizio=_fra(24), reparto="TORNI",
        )
        resp = self.client.get(reverse("anagrafica:dipendente_detail", args=[self.legacy_id]))
        content = resp.content.decode()
        self.assertIn("Programmata", content)
        self.assertIn("In corso", content)
        self.assertIn("sp-card-programmata", content)

    def test_gap_idoneita_mostrato_sulla_card(self):
        DipendenteAssegnazione.objects.create(
            legacy_anagrafica_id=self.legacy_id, data_inizio=_fra(-5), reparto="TORNI",
            mansione="Tornitore", idoneita_esito=DipendenteAssegnazione.IDONEITA_WARN,
            idoneita_mancanti=["Corso: Uso tornio"],
        )
        resp = self.client.get(reverse("anagrafica:dipendente_detail", args=[self.legacy_id]))
        content = resp.content.decode()
        self.assertIn("Abilitazione parziale", content)
        self.assertIn("Corso: Uso tornio", content)
