"""Area HR delle assenze: calendario aziendale, saldi, contatori, copertura, storico, solleciti."""
from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import mail
from django.http import HttpResponse
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from anagrafica.models import DipendenteAnagraficaCivile, SaldoCedolino
from automazioni.models import AutomationAction, AutomationRule

from . import hr
from .models import (
    AssenzaModifica,
    AssenzaSerie,
    AssenzaSollecito,
    AssenzeImpostazioniHR,
    ChiusuraAziendale,
    ContatoreAssenza,
    SogliaCopertura,
)


def _cal(**kw):
    base = {"ore_giornata": Decimal("8"), "sabato_lavorativo": False}
    base.update(kw)
    return hr.Calendario(**base)


class CalendarioAziendaleTests(SimpleTestCase):
    def test_pasqua_e_festivita_mobili(self):
        self.assertEqual(hr.pasqua(2026), date(2026, 4, 5))
        self.assertEqual(hr.pasqua(2027), date(2027, 3, 28))
        fest = hr.festivita(2026)
        self.assertEqual(fest[date(2026, 4, 6)], "Lunedì dell'Angelo")
        self.assertIn(date(2026, 10, 4), fest)
        self.assertNotIn(date(2025, 10, 4), hr.festivita(2025))

    def test_patrono_dalle_impostazioni(self):
        imp = AssenzeImpostazioniHR(patrono_giorno=24, patrono_mese=6, patrono_nome="San Giovanni")
        self.assertEqual(hr.festivita(2026, imp)[date(2026, 6, 24)], "Patrono: San Giovanni")

    def test_giorni_lavorativi_tolgono_weekend_festivi_e_chiusure(self):
        cal = _cal(festivi={date(2026, 6, 2): "Festa"}, chiusure={date(2026, 6, 3): "Ponte"})
        # lun 1 - dom 7 giugno 2026: restano lun 1, gio 4, ven 5
        self.assertEqual(
            cal.giorni_lavorativi(date(2026, 6, 1), date(2026, 6, 7)),
            [date(2026, 6, 1), date(2026, 6, 4), date(2026, 6, 5)],
        )

    def test_sabato_lavorativo(self):
        cal = _cal(sabato_lavorativo=True)
        self.assertEqual(len(cal.giorni_lavorativi(date(2026, 6, 1), date(2026, 6, 7))), 6)


class ValoreRichiestaTests(SimpleTestCase):
    def test_ferie_su_piu_giorni_valgono_giorni_lavorativi(self):
        cal = _cal(festivi={date(2026, 6, 2): "Festa"})
        ore, giorni, _ = hr.valore_richiesta(datetime(2026, 6, 1), datetime(2026, 6, 5, 23, 59), cal)
        self.assertEqual((ore, giorni), (Decimal("32"), Decimal("4")))

    def test_permesso_vale_le_sue_ore(self):
        ore, giorni, _ = hr.valore_richiesta(datetime(2026, 6, 1, 8), datetime(2026, 6, 1, 10, 30), _cal())
        self.assertEqual(ore, Decimal("2.50"))
        self.assertEqual(giorni, Decimal("0.31"))

    def test_permesso_in_festivo_non_vale_niente(self):
        cal = _cal(festivi={date(2026, 6, 2): "Festa"})
        ore, _g, _ = hr.valore_richiesta(datetime(2026, 6, 2, 8), datetime(2026, 6, 2, 10), cal)
        self.assertEqual(ore, Decimal("0"))

    def test_differenze_tra_versioni(self):
        diff = hr.differenze(
            {"data_inizio": datetime(2026, 6, 1, 8), "consenso": "Approvato", "motivazione_richiesta": "x"},
            {"data_inizio": "2026-06-01 09:00:00", "consenso": "Approvato", "motivazione_richiesta": "x"},
        )
        self.assertEqual(diff, [{"campo": "Inizio", "prima": "01/06/2026 08:00", "dopo": "01/06/2026 09:00"}])


def _righe(*righe):
    """Righe come le restituisce ``carica_richieste`` (stato già calcolato)."""
    out = []
    for i, (nome, tipo, inizio, fine, stato, motivo) in enumerate(righe, start=1):
        out.append({
            "id": i, "copia_nome": nome, "email_esterna": "", "tipo_assenza": tipo,
            "data_inizio": inizio, "data_fine": fine, "motivazione_richiesta": motivo,
            "consenso": "Approvato" if stato == "confermata" else "In attesa", "moderation_status": None,
            "stato": stato,
        })
    return out


IDENTITA = {
    1: {"nome": "MARIO", "cognome": "ROSSI", "names": {"ROSSI MARIO", "MARIO ROSSI"}, "sql_names": set(), "emails": set()},
    2: {"nome": "LUCA", "cognome": "BIANCHI", "names": {"BIANCHI LUCA", "LUCA BIANCHI"}, "sql_names": set(), "emails": set()},
    3: {"nome": "ANNA", "cognome": "VERDI", "names": {"VERDI ANNA", "ANNA VERDI"}, "sql_names": set(), "emails": set()},
}


@patch("assenze.availability._resolve_identities", side_effect=lambda ids: {i: IDENTITA[i] for i in ids if i in IDENTITA})
class SaldiTests(TestCase):
    def setUp(self):
        # Mese precedente: deve vincere il cedolino più recente.
        SaldoCedolino.objects.create(
            tax_code="RSSMRA80A01H501U", legacy_anagrafica_id=1, data_competenza=date(2026, 4, 30),
            ferie_residui=Decimal("99"),
        )
        SaldoCedolino.objects.create(
            tax_code="RSSMRA80A01H501U", legacy_anagrafica_id=1, data_competenza=date(2026, 5, 31),
            ferie_residui=Decimal("40"), rol_residui=Decimal("6"), ex_fest_residui=Decimal("4"),
        )
        self.saldo = hr.saldo_anagrafica(1)

    def test_saldo_dall_ultimo_cedolino_in_anagrafica(self, _ident):
        self.assertEqual(self.saldo.situazione_al, date(2026, 5, 31))
        self.assertEqual((self.saldo.ferie_ore, self.saldo.permessi_ore), (Decimal("40"), Decimal("10")))

    def test_cedolino_senza_id_si_aggancia_col_codice_fiscale(self, _ident):
        DipendenteAnagraficaCivile.objects.create(legacy_anagrafica_id=2, codice_fiscale="bnclcu80a01h501x")
        SaldoCedolino.objects.create(
            tax_code="BNCLCU80A01H501X", data_competenza=date(2026, 5, 31), ferie_residui=Decimal("12"),
        )
        self.assertEqual(hr.saldo_anagrafica(2).ferie_ore, Decimal("12"))
        self.assertEqual(set(hr.saldi_anagrafica([1, 2, 3])), {1, 2})

    def test_residuo_toglie_richieste_dopo_il_cedolino_e_chiusure(self, _ident):
        ChiusuraAziendale.objects.create(data_inizio=date(2026, 8, 10), data_fine=date(2026, 8, 14), descrizione="Estate")
        righe = _righe(
            ("ROSSI MARIO", "Ferie", datetime(2026, 6, 8), datetime(2026, 6, 9, 23, 59), "confermata", ""),
            ("ROSSI MARIO", "Permesso", datetime(2026, 6, 10, 8), datetime(2026, 6, 10, 12), "pendente", ""),
            ("ROSSI MARIO", "Ferie", datetime(2026, 5, 4), datetime(2026, 5, 5, 23, 59), "confermata", ""),
        )
        with patch("assenze.hr.carica_richieste", return_value=righe):
            res = hr.residui([self.saldo], oggi=date(2026, 6, 15))[1]
        self.assertEqual(res.ferie_usate, Decimal("16"))
        self.assertEqual(res.chiusure_ore, Decimal("40"))  # 5 giorni lavorativi di chiusura
        self.assertEqual(res.ferie_residue, Decimal("-16"))
        self.assertEqual(res.permessi_residui, Decimal("6.00"))
        self.assertEqual(res.in_attesa_ore, Decimal("4.00"))

    def test_avviso_saldo_non_blocca_ma_avvisa(self, _ident):
        with patch("assenze.hr.carica_richieste", return_value=[]):
            self.assertEqual(hr.avviso_saldo(1, "Ferie", datetime(2026, 6, 8), datetime(2026, 6, 12, 23, 59)), "")
            testo = hr.avviso_saldo(1, "Ferie", datetime(2026, 6, 8), datetime(2026, 6, 19, 23, 59))
        self.assertIn("Saldo ferie insufficiente", testo)
        self.assertIn("80 ore", testo)

    def test_senza_saldo_nessun_avviso(self, _ident):
        self.assertEqual(hr.avviso_saldo(2, "Ferie", datetime(2026, 6, 8), datetime(2026, 6, 30)), "")


@patch("assenze.availability._resolve_identities", side_effect=lambda ids: {i: IDENTITA[i] for i in ids if i in IDENTITA})
class ContatoriECoperturaTests(TestCase):
    def test_contatore_assemblea_oltre_il_limite(self, _ident):
        ContatoreAssenza.objects.create(nome="Assemblea", motivazione="Assemblea sindacale", unita="ore",
                                        limite=Decimal("10"), periodo="anno")
        righe = _righe(
            ("ROSSI MARIO", "Permesso", datetime(2026, 3, 2, 8), datetime(2026, 3, 2, 16), "confermata", "assemblea SINDACALE"),
        )
        with patch("assenze.hr.carica_richieste", return_value=righe):
            self.assertEqual(hr.avviso_contatore(1, "Assemblea sindacale", datetime(2026, 4, 1, 8), datetime(2026, 4, 1, 10)), "")
            testo = hr.avviso_contatore(1, "Assemblea sindacale", datetime(2026, 4, 1, 8), datetime(2026, 4, 1, 12))
        self.assertIn("il limite è 10", testo)

    def test_copertura_reparto_oltre_soglia(self, _ident):
        SogliaCopertura.objects.create(reparto="Saldatura", max_assenti=1)
        attivi = {1: {"nominativo": "ROSSI MARIO", "reparto": "SALDATURA"},
                  2: {"nominativo": "BIANCHI LUCA", "reparto": "Saldatura"},
                  3: {"nominativo": "VERDI ANNA", "reparto": "Montaggio"}}
        confermate = _righe(
            ("BIANCHI LUCA", "Ferie", datetime(2026, 6, 8), datetime(2026, 6, 9, 23, 59), "confermata", ""),
        )
        coda = [{"id": 99, "copia_nome": "ROSSI MARIO", "data_inizio": datetime(2026, 6, 9),
                 "data_fine": datetime(2026, 6, 10, 23, 59)},
                {"id": 98, "copia_nome": "VERDI ANNA", "data_inizio": datetime(2026, 6, 9),
                 "data_fine": datetime(2026, 6, 9, 23, 59)}]
        with patch("assenze.hr.dipendenti_attivi", return_value=attivi), \
                patch("assenze.hr.carica_richieste", return_value=confermate):
            avvisi = hr.avvisi_copertura(coda)
        self.assertEqual(list(avvisi), [99])
        self.assertIn("il 09/06 sarebbero assenti 2 persone (soglia 1)", avvisi[99])


class StoricoTests(TestCase):
    def test_registra_scrive_le_differenze(self):
        hr.registra(7, "modificata", utente="hr", prima={"consenso": "In attesa"}, dopo={"consenso": "Approvato"},
                    motivo="corretto")
        m = AssenzaModifica.objects.get(assenza_id=7)
        self.assertEqual(m.modifiche, [{"campo": "Stato", "prima": "In attesa", "dopo": "Approvato"}])
        self.assertEqual(m.motivo, "corretto")


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class AreaHrViewTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser("hr-admin", "hr@example.com", "pass12345")
        self.client.force_login(self.admin)

    def test_pagine_hr_si_aprono(self):
        for nome in ("assenze_hr", "assenze_hr_saldi", "assenze_hr_calendario", "assenze_hr_contatori",
                     "assenze_hr_copertura"):
            resp = self.client.get(reverse(nome))
            self.assertEqual(resp.status_code, 200, nome)
            self.assertNotContains(resp, "{#", msg_prefix=nome)
            self.assertContains(resp, "Area HR", msg_prefix=nome)

    @patch("assenze.views.hr_gestione._puo_gestire", return_value=False)
    def test_senza_permesso_403(self, _m):
        self.assertEqual(self.client.get(reverse("assenze_hr_saldi")).status_code, 403)
        self.assertEqual(self.client.post(reverse("assenze_hr_calendario"), {"form": "impostazioni"}).status_code, 403)

    def test_chiusura_e_impostazioni(self):
        resp = self.client.post(reverse("assenze_hr_calendario"), {
            "form": "chiusura", "descrizione": "Estate", "data_inizio": "2026-08-10", "data_fine": "2026-08-21",
            "scala_ferie": "1",
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(ChiusuraAziendale.objects.filter(descrizione="Estate", scala_ferie=True).exists())
        self.client.post(reverse("assenze_hr_calendario"), {
            "form": "impostazioni", "ore_giornata": "7,5", "patrono_giorno": "24", "patrono_mese": "6",
            "sollecito_attivo": "1", "sollecito_dopo_giorni": "3", "sollecito_ripeti_giorni": "2",
        })
        imp = AssenzeImpostazioniHR.get_solo()
        self.assertEqual(imp.ore_giornata, Decimal("7.50"))
        self.assertEqual((imp.patrono_giorno, imp.patrono_mese, imp.sollecito_dopo_giorni), (24, 6, 3))

    @patch("assenze.hr.carica_richieste", return_value=[])
    @patch("assenze.hr.dipendenti_attivi", return_value={
        5: {"nominativo": "MARIO ROSSI", "reparto": "A"}, 6: {"nominativo": "LUCA BIANCHI", "reparto": "A"},
    })
    def test_pagina_saldi_legge_i_cedolini_e_non_accetta_post(self, _att, _rich):
        SaldoCedolino.objects.create(
            tax_code="RSSMRA80A01H501U", legacy_anagrafica_id=5, data_competenza=date(2026, 9, 30),
            ferie_residui=Decimal("120.5"), rol_residui=Decimal("16"),
        )
        resp = self.client.get(reverse("assenze_hr_saldi"))
        self.assertEqual(resp.status_code, 200)
        righe = {r["anagrafica_id"]: r for r in resp.context["righe_saldi"]}
        self.assertEqual(righe[5]["saldo"].ferie_ore, Decimal("120.5"))
        self.assertIsNone(righe[6]["saldo"])
        self.assertContains(resp, "nessun cedolino in Anagrafica")
        self.assertEqual(self.client.post(reverse("assenze_hr_saldi"), {"form": "salva"}).status_code, 405)

    def test_contatori_consigliati(self):
        self.client.post(reverse("assenze_hr_contatori"), {"form": "consigliati"})
        self.assertEqual(ContatoreAssenza.objects.count(), 2)
        self.client.post(reverse("assenze_hr_contatori"), {"form": "consigliati"})
        self.assertEqual(ContatoreAssenza.objects.count(), 2)



@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class ModificaApprovataTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser("hr-mod", "hr-mod@example.com", "pass12345")
        self.client.force_login(self.user)
        self.current = {
            "id": 42, "copia_nome": "ROSSI MARIO", "email_esterna": "", "tipo_assenza": "Ferie",
            "data_inizio": datetime(2026, 6, 8), "data_fine": datetime(2026, 6, 9, 23, 59),
            "motivazione_richiesta": "", "certificato_medico": "", "consenso": "Approvato", "moderation_status": 0,
        }

    def _post(self, **extra):
        payload = {"item_id": 42, "tipo": "Ferie", "consenso": "Approvato", "inizio": "2026-06-08T00:00",
                   "fine": "2026-06-10T23:59", "motivazione": ""}
        payload.update(extra)
        with patch("assenze.views._helpers._get_assenza", return_value=dict(self.current)), \
                patch("assenze.views._helpers._update_assenza", return_value=True) as upd, \
                patch("assenze.views._helpers._validate_business_rules", return_value=("", "")), \
                patch("assenze.views._helpers._sharepoint_managed_error", return_value=None), \
                patch("assenze.views._helpers._graph_configured", return_value=False), \
                patch("assenze.views._helpers._assenze_permissions",
                      return_value={"can_edit_events": True, "can_update_any": True}):
            resp = self.client.post(reverse("assenze_api_evento_update_static"), data=payload,
                                    content_type="application/json")
        return resp, upd

    def test_approvata_senza_motivo_rifiutata(self):
        resp, upd = self._post()
        self.assertEqual(resp.status_code, 400)
        self.assertIn("motivo", resp.json()["error"])
        upd.assert_not_called()

    def test_approvata_con_motivo_va_nello_storico(self):
        resp, upd = self._post(motivo_modifica="Prolungate su richiesta")
        self.assertEqual(resp.status_code, 200)
        voce = AssenzaModifica.objects.get(assenza_id=42)
        self.assertEqual(voce.motivo, "Prolungate su richiesta")
        self.assertEqual(voce.modifiche[0]["campo"], "Fine")
        storico = self.client.get(reverse("assenze_api_storico", args=[42]))
        self.assertEqual(storico.json()["voci"][0]["motivo"], "Prolungate su richiesta")

    def test_salvataggio_senza_cambi_non_chiede_motivo(self):
        resp, _ = self._post(fine="2026-06-09T23:59")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(AssenzaModifica.objects.filter(assenza_id=42).exists())


class SollecitiTests(TestCase):
    @override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
                       DEFAULT_FROM_EMAIL="noreply@example.com")
    def test_una_mail_per_capo_e_niente_ripetizioni_ravvicinate(self):
        from . import solleciti

        righe = [
            {"id": 1, "copia_nome": "ROSSI MARIO", "tipo_assenza": "Ferie", "data_inizio": datetime(2026, 6, 8),
             "data_fine": datetime(2026, 6, 9), "created_datetime": datetime(2026, 6, 1), "capo_email": "capo@example.com"},
            {"id": 2, "copia_nome": "VERDI ANNA", "tipo_assenza": "Permesso", "data_inizio": datetime(2026, 6, 8, 8),
             "data_fine": datetime(2026, 6, 8, 10), "created_datetime": datetime(2026, 6, 1), "capo_email": "capo@example.com"},
        ]
        with patch("assenze.solleciti.richieste_da_sollecitare", return_value=righe):
            esito = solleciti.invia_solleciti()
        self.assertEqual(esito["email_sent"], 1)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("2 richieste", mail.outbox[0].subject)
        self.assertIn("Aggiungi a Outlook", mail.outbox[0].alternatives[0][0])
        self.assertEqual(AssenzaSollecito.objects.get(assenza_id=1).invii, 1)

    def test_solleciti_spenti(self):
        from . import solleciti

        imp = AssenzeImpostazioniHR.get_solo()
        imp.sollecito_attivo = False
        imp.save()
        self.assertIn("skipped", solleciti.invia_solleciti())

    def test_richiesta_sollecitata_di_recente_esclusa(self):
        from . import solleciti

        AssenzaSollecito.objects.create(assenza_id=1, ultimo_invio=timezone.now() - timedelta(hours=5), invii=1)
        rows = [{"id": 1, "copia_nome": "X"}, {"id": 2, "copia_nome": "Y"}]
        with patch("assenze.views._helpers._table_exists", return_value=True), \
                patch("assenze.views._helpers._has_assenze_column", return_value=True), \
                patch("assenze.views._helpers._fetch_all_dict", return_value=rows), \
                patch("assenze.views._helpers._capo_email_for_row", return_value="capo@example.com"):
            out = solleciti.richieste_da_sollecitare()
        self.assertEqual([r["id"] for r in out], [2])


class AssenzeSpecialiSaltaApprovazioneTests(TestCase):
    def _regola(self, code, to, cc):
        rule = AutomationRule.objects.create(code=code, name=code, source_code="assenze", operation_type="update")
        AutomationAction.objects.create(rule=rule, order=1, action_type="send_email", is_enabled=True,
                                        config_json={"to": to, "cc": cc, "subject_template": "x"})
        return rule

    def test_divide_le_mail_ad_assenza(self):
        from automazioni.assenze_avviso_speciali import applica

        assemblea = self._regola("assenze-pa-assemblea-sindacale-avviso",
                                 "hr@example.com, car@example.com, assenza@example.com", "")
        fless = self._regola("assenze-pa-flessibilita-avviso", "assenza@example.com", "{dipendente_email}")
        esito = applica()
        self.assertTrue(esito["assenze-pa-assemblea-sindacale-avviso"].startswith("divisa"))
        azioni = list(assemblea.actions.order_by("order"))
        self.assertEqual(azioni[0].config_json["run_if"]["negate"], True)
        self.assertEqual(azioni[1].config_json["to"], "hr@example.com, car@example.com")
        self.assertEqual(azioni[1].config_json["run_if"]["operator"], "is_true")
        variante = fless.actions.order_by("order")[1].config_json
        self.assertEqual((variante["to"], variante["cc"]), ("{dipendente_email}", ""))
        # Idempotente
        self.assertEqual(applica()["assenze-pa-flessibilita-avviso"], "già divisa")

    def test_regole_assenti(self):
        from automazioni.assenze_avviso_speciali import applica

        self.assertEqual(set(applica().values()), {"assente"})


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
@patch("assenze.views.richieste._render_richiesta", side_effect=lambda request, **kw: HttpResponse(kw.get("error") or kw.get("success") or ""))
@patch("assenze.views.richieste._registra_inserita_da")
@patch("assenze.views.richieste._resolve_capo_local_id", return_value=None)
@patch("assenze.views.richieste._resolve_capo_lookup_id", return_value=None)
@patch("assenze.views.richieste._resolve_nome_lookup_id", return_value=77)
@patch("assenze.views.richieste._resolve_request_display_name", return_value="Mario Rossi")
@patch("assenze.views._helpers._sp_enqueue_upsert", return_value={"queued": False})
@patch("assenze.views._helpers._load_capi_options", return_value=[])
@patch("assenze.views._helpers._validate_business_rules", return_value=(None, ""))
@patch("assenze.views._helpers._table_exists", return_value=True)
@patch("assenze.views._helpers._legacy_identity", return_value=("Mario Rossi", "mario@example.com", 77))
@patch("assenze.views._helpers._assenze_permissions", return_value={"can_insert": True, "can_skip_approval": False})
class PermessoRipetutoTests(TestCase):
    def setUp(self):
        from core.models import UserOnboarding

        self.user = get_user_model().objects.create_user(username="ripeti-user", password="pass12345")
        UserOnboarding.objects.create(user=self.user, completed=True, completed_at=timezone.now())
        self.client.force_login(self.user)

    def _invia(self, **extra):
        from .views.richieste import _build_submit_token

        session = self.client.session
        request = type("Req", (), {"user": self.user, "session": session})()
        dati = {
            "submit_token": _build_submit_token(request, "assenze_invio"),
            "tipoassenza": "Permesso", "motivazione": "Motivo",
            "date_start": "2026-10-29", "date_end": "2026-10-29", "time_start": "08:00", "time_end": "10:00",
        }
        dati.update(extra)
        session.save()
        return self.client.post(reverse("assenze_invio"), dati)

    def test_un_permesso_per_ogni_giorno_lavorativo_stesso_orario(self, *_mocks):
        # 29/10 gio, 30/10 ven, 31/10 sab, 1/11 dom (festa), 2/11 lun.
        with patch("assenze.views.richieste._insert_assenza", side_effect=[101, 102, 103]) as ins, \
                patch("assenze.hr.avvisi_richiesta", return_value=[]):
            resp = self._invia(ripeti_fino_al="2026-11-02")
        self.assertContains(resp, "3 permessi registrati")
        giorni = [(c.args[0]["data_inizio"], c.args[0]["data_fine"]) for c in ins.call_args_list]
        self.assertEqual(giorni, [
            (datetime(2026, 10, 29, 8), datetime(2026, 10, 29, 10)),
            (datetime(2026, 10, 30, 8), datetime(2026, 10, 30, 10)),
            (datetime(2026, 11, 2, 8), datetime(2026, 11, 2, 10)),
        ])
        self.assertEqual(AssenzaModifica.objects.filter(azione="creata").count(), 3)
        # Una sola serie, capofila il primo giorno.
        self.assertEqual(
            list(AssenzaSerie.objects.values_list("assenza_id", "capofila_id")), [(101, 101), (102, 101), (103, 101)]
        )

    def test_solo_il_primo_giorno_fa_partire_le_automazioni(self, *_mocks):
        with patch("assenze.views.richieste._insert_assenza", side_effect=[101, 102]),                 patch("assenze.hr.avvisi_richiesta", return_value=[]),                 patch("assenze.views._helpers._set_automation_queue_skip") as skip:
            self._invia(ripeti_fino_al="2026-10-30")
        # Il flag che spegne i trigger si accende e spegne attorno al solo secondo insert.
        self.assertEqual([c.args[0] for c in skip.call_args_list], [True, False])

    def test_senza_ripeti_una_sola_richiesta(self, *_mocks):
        with patch("assenze.views.richieste._insert_assenza", return_value=101) as ins, \
                patch("assenze.hr.avvisi_richiesta", return_value=[]):
            self._invia()
        self.assertEqual(ins.call_count, 1)

    def test_ripeti_prima_dell_inizio_o_troppo_lungo_rifiutato(self, *_mocks):
        with patch("assenze.views.richieste._insert_assenza") as ins:
            self.assertContains(self._invia(ripeti_fino_al="2026-10-28"), "uguale o successiva")
            self.assertContains(self._invia(ripeti_fino_al="2026-12-31"), "al massimo per 31 giorni")
        ins.assert_not_called()


class SerieMailTests(TestCase):
    def setUp(self):
        from . import serie

        serie.registra([201, 202, 203])
        self.righe = [
            {"id": 202, "data_inizio": datetime(2026, 10, 30, 8), "data_fine": datetime(2026, 10, 30, 10)},
            {"id": 201, "data_inizio": datetime(2026, 10, 29, 8), "data_fine": datetime(2026, 10, 29, 10)},
            {"id": 203, "data_inizio": datetime(2026, 11, 2, 8), "data_fine": datetime(2026, 11, 2, 10)},
        ]

    def test_mail_della_capofila_dice_dal_al(self):
        from . import serie

        with patch("assenze.views._helpers._fetch_all_dict", return_value=self.righe):
            testo, html_blocco, info = serie.blocco_mail("assenze", {"id": "201"}, approvazione=True)
            self.assertEqual(serie.blocco_mail("assenze", {"id": 202}), ("", "", None))
        self.assertIn("Permesso ripetuto dal 29/10/2026 al 02/11/2026: 3 giorni lavorativi (29/10, 30/10, 02/11), "
                      "dalle 08:00 alle 10:00.", testo)
        self.assertIn("tutti i giorni", testo)
        self.assertIn("Permesso ripetuto dal 29/10/2026", html_blocco)
        self.assertEqual(serie.suffisso_oggetto(info), " · permesso ripetuto dal 29/10/2026 al 02/11/2026")
        self.assertEqual(serie.blocco_mail("altro", {"id": 201}), ("", "", None))

    def test_decisione_della_capofila_passa_ai_giorni_in_attesa(self):
        from . import serie

        stato = {201: {"id": 201, "moderation_status": 0, "consenso": "Approvato"},
                 202: {"id": 202, "moderation_status": 2, "consenso": "In attesa"},
                 203: {"id": 203, "moderation_status": 1, "consenso": "Rifiutato"}}
        with patch("assenze.views._helpers._get_assenza", side_effect=lambda i: stato[int(i)]),                 patch("assenze.views._helpers._approval_timestamp_update", return_value={}),                 patch("assenze.views._helpers._update_assenza", return_value=True) as upd,                 patch("assenze.views._helpers._sp_enqueue_upsert") as sp,                 patch("assenze.views._helpers._set_automation_queue_skip") as skip:
            self.assertEqual(serie.propaga(201), 1)
            self.assertEqual(serie.propaga(202), 0)  # non è la capofila
        self.assertEqual(upd.call_args.args[0], 202)
        self.assertEqual((upd.call_args.args[1]["moderation_status"], upd.call_args.args[1]["consenso"]), (0, "Approvato"))
        sp.assert_called_once_with(202)
        self.assertEqual([c.args[0] for c in skip.call_args_list], [True, False])

    def test_capofila_in_attesa_non_propaga(self):
        from . import serie

        with patch("assenze.views._helpers._get_assenza", return_value={"moderation_status": 2}),                 patch("assenze.views._helpers._update_assenza") as upd:
            self.assertEqual(serie.propaga(201), 0)
        upd.assert_not_called()
