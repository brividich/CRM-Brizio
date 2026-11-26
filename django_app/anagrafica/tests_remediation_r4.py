"""Remediation formazione R4 (26/11/2026): viste per persona, copertura, conformità, sicurezza.

Dati sintetici.
"""
from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.contrib.sessions.backends.db import SessionStore
from django.test import RequestFactory, TestCase
from django.utils import timezone

from .models import DipendenteAnagraficaAziendale, DipendenteQualifica, TipoQualifica
from .models_formazione import TrainingCourse, TrainingDeadline, TrainingEmployeeRecord, TrainingPlan

User = get_user_model()
OGGI = timezone.localdate()


def _corso(codice="C-R4", **kw):
    piano, _ = TrainingPlan.objects.get_or_create(codice="P-R4", defaults={"nome": "Piano R4"})
    kw.setdefault("durata_ore_teorica", 4)
    return TrainingCourse.objects.create(piano=piano, codice=codice, titolo=f"Corso {codice}", **kw)


def _request(path="/anagrafica/"):
    request = RequestFactory().get(path)
    request.user = User.objects.create_user(username=f"r4_{User.objects.count()}", password="x")
    request.session = SessionStore()
    request._messages = mock.MagicMock()
    return request


# ── A) pagine per persona: ambito del ruolo ───────────────────────────────────

class AmbitoPaginePersonaTests(TestCase):
    """Utente con ambito limitato (vede solo la scheda 1): la scheda 2 è negata."""

    def _con_ambito(self):
        from .views import dipendenti

        return (mock.patch.object(dipendenti._helpers, "_ruoli_attivi", return_value=True),
                mock.patch.object(dipendenti, "_schede_visibili", return_value={1}),
                mock.patch.object(dipendenti._helpers, "_can_view_formazione", return_value=True))

    def _chiama(self, vista, *args, path="/x/"):
        a, b, c = self._con_ambito()
        with a, b, c:
            return vista(_request(path), *args)

    def test_libretto_formativo_pagina_e_pdf_negati(self):
        from .views import dipendenti

        self.assertEqual(self._chiama(dipendenti.dipendente_libretto_formativo, 2).status_code, 403)
        self.assertEqual(self._chiama(dipendenti.dipendente_libretto_formativo, 2, path="/x/?formato=pdf").status_code, 403)

    def test_stampa_scheda_negata(self):
        from .views import dipendenti

        self.assertEqual(self._chiama(dipendenti.dipendente_print, 2).status_code, 403)

    def test_ccnl_espansione_e_plan_persona_negati(self):
        from .views import formazione

        self.assertEqual(self._chiama(formazione.formazione_ccnl_dipendente_espansione, 2).status_code, 403)
        self.assertEqual(self._chiama(formazione.formazione_plan, 2).status_code, 403)


# ── B) una sola regola «ex dipendente» ────────────────────────────────────────

class InForzaTests(TestCase):
    def setUp(self):
        DipendenteAnagraficaAziendale.objects.create(legacy_anagrafica_id=401, data_cessazione=OGGI - timedelta(days=5))
        # Cessazione futura già registrata: oggi è ancora in forza.
        DipendenteAnagraficaAziendale.objects.create(legacy_anagrafica_id=402, data_cessazione=OGGI + timedelta(days=10))
        # Riassunto dopo la cessazione: la vecchia data appartiene al rapporto precedente.
        DipendenteAnagraficaAziendale.objects.create(
            legacy_anagrafica_id=403, data_cessazione=OGGI - timedelta(days=400),
            data_assunzione_ultima=OGGI - timedelta(days=100))
        # Ultimo giorno di lavoro = oggi: ancora in forza.
        DipendenteAnagraficaAziendale.objects.create(legacy_anagrafica_id=404, data_cessazione=OGGI)

    def test_regola_unica(self):
        from .services.in_forza import cessati_ids

        self.assertEqual(cessati_ids(), {401})
        self.assertEqual(cessati_ids(OGGI + timedelta(days=11)), {401, 402, 404})

    def test_funzioni_storiche_delegano(self):
        from .services.organigramma_albero import cessati_legacy_ids
        from .services.training_eligibility import _cessati_ids
        from .views._helpers import _cessati_legacy_ids

        self.assertEqual(_cessati_legacy_ids(), {401})
        self.assertEqual(_cessati_ids(), {401})
        self.assertEqual(cessati_legacy_ids(), {401})


# ── C) Le mie attività: qualifiche dallo scadenzario unificato ────────────────

class MieAttivitaQualificheTests(TestCase):
    def test_scadute_recenti_prima_poi_prossime(self):
        from dashboard import views_mie_attivita as v

        voci = [
            {"giorni": -200, "scaduta": True, "legacy_id": 1, "tipo_id": 1, "tipo_nome": "Vecchia",
             "data_scadenza": OGGI - timedelta(days=200), "cognome": "ROSSI", "nome": "ANNA"},
            {"giorni": 40, "scaduta": False, "legacy_id": 2, "tipo_id": 1, "tipo_nome": "Lontana",
             "data_scadenza": OGGI + timedelta(days=40), "cognome": "BIANCHI", "nome": "LUCA"},
            {"giorni": -3, "scaduta": True, "legacy_id": 3, "tipo_id": 2, "tipo_nome": "Recente",
             "data_scadenza": OGGI - timedelta(days=3), "cognome": "VERDI", "nome": "SARA"},
            {"giorni": 5, "scaduta": False, "legacy_id": 4, "tipo_id": 2, "tipo_nome": "Vicina",
             "data_scadenza": OGGI + timedelta(days=5), "cognome": "NERI", "nome": "UGO"},
        ]
        with mock.patch("anagrafica.views._can_view_formazione", return_value=True), \
                mock.patch("anagrafica.views._helpers._build_scadenzario_voci", return_value=voci) as build:
            out = v._safety_scadenze(_request())
        build.assert_called_once()
        self.assertEqual(build.call_args.kwargs.get("filtro_tipo"), "qualifica")
        self.assertEqual([r["title"] for r in out], ["Recente", "Vecchia", "Vicina", "Lontana"])
        self.assertEqual(out[0]["status"], "Scaduta")

    def test_senza_permesso_none(self):
        from dashboard import views_mie_attivita as v

        with mock.patch("anagrafica.views._can_view_formazione", return_value=False):
            self.assertIsNone(v._safety_scadenze(_request()))


# ── D) Conformità ─────────────────────────────────────────────────────────────

class ConformitaTests(TestCase):
    def test_mai_frequentato_e_avviso_mancante(self):
        from .services import conformita

        voce = SimpleNamespace(stato="MAI_FREQUENTATO", corso=SimpleNamespace(titolo="Antincendio"))
        out = conformita._formazione_batch([7], voci={7: [voce]})
        self.assertEqual(out[7]["esito"], conformita.ESITO_WARN)
        self.assertIn("Antincendio: mancante", out[7]["dettagli"])

    def test_qualifiche_solo_richieste_e_soglia_90(self):
        from .services import conformita

        richiesta = TipoQualifica.objects.create(nome="Patentino R4")
        mancante = TipoQualifica.objects.create(nome="Saldatore R4")
        non_richiesta = TipoQualifica.objects.create(nome="Extra R4")
        DipendenteQualifica.objects.create(legacy_anagrafica_id=501, tipo=richiesta,
                                           data_conseguimento=OGGI - timedelta(days=300),
                                           data_scadenza=OGGI + timedelta(days=80))
        DipendenteQualifica.objects.create(legacy_anagrafica_id=501, tipo=non_richiesta,
                                           data_conseguimento=OGGI - timedelta(days=900),
                                           data_scadenza=OGGI - timedelta(days=10))
        richieste = {501: {richiesta.pk: ["Ruolo «X»"], mancante.pk: ["Ruolo «X»"]}}
        with mock.patch("anagrafica.services.requisiti.qualifiche_richieste", return_value=richieste):
            out = conformita._qualifiche_batch([501])
        # La qualifica scaduta non richiesta non dà «non conforme»; a 80 giorni è «in scadenza» (soglia 90).
        self.assertEqual(out[501]["esito"], conformita.ESITO_WARN)
        self.assertIn("Saldatore R4: mancante", out[501]["dettagli"])
        self.assertIn("Patentino R4: in scadenza", out[501]["dettagli"])
        self.assertFalse(any("Extra R4" in d for d in out[501]["dettagli"]))

    def test_libretto_qualifiche_mancanti_e_soglia(self):
        from .services import libretto_sanitario as ls

        q = SimpleNamespace(tipo_id=1, tipo=SimpleNamespace(nome="Patentino"), data_scadenza=OGGI + timedelta(days=80),
                            data_conseguimento=OGGI - timedelta(days=200), livello="")
        righe = ls._righe_qualifiche([q], OGGI, {1: ["Ruolo"], 2: ["Mansione"]}, {2: "Saldatore"})
        per_nome = {r.nome: r for r in righe}
        self.assertEqual(per_nome["Saldatore"].stato, ls.STATO_MANCANTE)
        self.assertEqual(per_nome["Patentino"].stato, ls.STATO_WARN)


# ── E) colonna Formazione dell'elenco: solo obbligatori ───────────────────────

class ColonnaFormazioneTests(TestCase):
    def test_solo_obbligatori(self):
        from .services.colonne_elenco import _carica_formazione

        c1, c2 = _corso("C-R4E1"), _corso("C-R4E2")
        TrainingDeadline.objects.create(legacy_anagrafica_id=601, corso=c1, is_required=True,
                                        stato_scadenza="SCADUTO", data_scadenza=OGGI - timedelta(days=1))
        TrainingDeadline.objects.create(legacy_anagrafica_id=601, corso=c2, is_required=False,
                                        stato_scadenza="SCADUTO", data_scadenza=OGGI - timedelta(days=1))
        self.assertEqual(_carica_formazione([601], None)[601]["scaduti"], 1)


# ── F) copertura processi: qualificati operativi ─────────────────────────────

class CoperturaProcessoTests(TestCase):
    def test_usa_qualificati(self):
        from .services import skillmatrix_copertura

        with mock.patch("anagrafica.services.mpq_persone.qualificati", return_value={(1, 9), (2, 9)}) as q:
            self.assertEqual(skillmatrix_copertura._conta_processo(9), 2)
        self.assertEqual(q.call_args.args[1], [9])


# ── G) ambito nelle pagine globali ────────────────────────────────────────────

class AmbitoGlobaliTests(TestCase):
    def test_filtra_ambito(self):
        from .views._helpers import _filtra_ambito

        c = _corso("C-R4G")
        for lid in (701, 702):
            TrainingDeadline.objects.create(legacy_anagrafica_id=lid, corso=c, is_required=True,
                                            stato_scadenza="SCADUTO", data_scadenza=OGGI - timedelta(days=1))
        qs = TrainingDeadline.objects.all()
        self.assertEqual(_filtra_ambito(qs, None).count(), 2)
        self.assertEqual(list(_filtra_ambito(qs, {701}).values_list("legacy_anagrafica_id", flat=True)), [701])
        self.assertEqual(_filtra_ambito(qs, set()).count(), 0)

    def test_gap_formativo_con_ambito_vuoto(self):
        from .services.training_eligibility import righe_gap_formativo

        _, _, righe = righe_gap_formativo(visibili=set())
        self.assertEqual(righe, [])


# ── H) completamenti validi a lotti ───────────────────────────────────────────

class CompletamentiMultiTests(TestCase):
    def test_regola(self):
        from .services.formazione_completamento import ids_con_completamento_valido_multi

        c1, c2 = _corso("C-R4H1"), _corso("C-R4H2")
        TrainingEmployeeRecord.objects.create(corso=c1, legacy_anagrafica_id=801, idoneo=True,
                                              data_completamento=OGGI - timedelta(days=10))
        TrainingEmployeeRecord.objects.create(corso=c2, legacy_anagrafica_id=801, idoneo=True,
                                              data_completamento=OGGI - timedelta(days=400),
                                              data_scadenza=OGGI - timedelta(days=35))  # scaduto
        TrainingEmployeeRecord.objects.create(corso=c1, legacy_anagrafica_id=802, idoneo=False,
                                              data_completamento=OGGI - timedelta(days=10))  # non idoneo
        TrainingEmployeeRecord.objects.create(corso=c2, legacy_anagrafica_id=802, idoneo=True,
                                              data_completamento=OGGI + timedelta(days=10))  # futuro
        TrainingEmployeeRecord.objects.create(corso=c2, legacy_anagrafica_id=803, idoneo=True,
                                              data_completamento=OGGI - timedelta(days=10),
                                              data_scadenza=OGGI + timedelta(days=300))
        self.assertEqual(ids_con_completamento_valido_multi([c1.pk, c2.pk], [801, 802, 803]),
                         {(801, c1.pk), (803, c2.pk)})

    def test_corso_valido_gate_skill_matrix(self):
        from .services.skillmatrix_qualifica import corso_valido

        c = _corso("C-R4H3")
        # Cache dice VALIDO ma nessun completamento reale: non vale più.
        TrainingDeadline.objects.create(legacy_anagrafica_id=804, corso=c, stato_scadenza="VALIDO")
        self.assertFalse(corso_valido(804, c))
        TrainingEmployeeRecord.objects.create(corso=c, legacy_anagrafica_id=804, idoneo=True,
                                              data_completamento=OGGI - timedelta(days=1))
        self.assertTrue(corso_valido(804, c))


# ── I) soglie dalle costanti ──────────────────────────────────────────────────

class SoglieTests(TestCase):
    def test_reportistica(self):
        from .reportistica import sezioni
        from .scadenze_soglie import GIORNI_PREAVVISO, GIORNI_PREAVVISO_VISITE
        from .views._helpers import GIORNI_PREAVVISO_VISITE as visite_helpers

        self.assertEqual(GIORNI_PREAVVISO_VISITE, visite_helpers)
        prev = {o.nome: o.predefinito for o in sezioni._opz_qualifiche()}
        self.assertEqual(prev["preavviso"], GIORNI_PREAVVISO)
        self.assertEqual(sezioni._SIGLE_FORMAZIONE["IN_SCADENZA_90"][1], "!")
