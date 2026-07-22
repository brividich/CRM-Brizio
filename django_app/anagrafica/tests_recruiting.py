"""Recruiting MOD. 05-01 — test.

Copre il calcolo del punteggio ponderato, la garanzia strutturale che i dati
informativi (età, cittadinanza) non possano influenzarlo, il gating della
sezione, la transizione a onboarding e la tracciabilità delle modifiche.

Nessun dato reale: tutti gli esempi sono fittizi.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from .models_recruiting import (
    Candidato,
    CandidatoLog,
    CandidatoPunteggio,
    RecruitingCriterio,
    RecruitingPermission,
)
from .services import recruiting as recruiting_service
from .tests import _ensure_anagrafica_table, _ensure_utenti_table

User = get_user_model()


def _crea_criteri() -> dict[str, RecruitingCriterio]:
    """I 5 criteri dell'Excel con i pesi originali (come li semina la migrazione)."""
    from .models_recruiting import CRITERI_SEED

    criteri = {}
    for payload in CRITERI_SEED:
        criteri[payload["codice"]], _ = RecruitingCriterio.objects.get_or_create(
            codice=payload["codice"],
            defaults={
                "label": payload["label"],
                "descrizione": payload["descrizione"],
                "peso_percentuale": payload["peso_percentuale"],
                "ordine": payload["ordine"],
            },
        )
    return criteri


class CalcoloPonderatoTests(TestCase):
    """La formula: media pesata normalizzata sui pesi effettivamente presenti."""

    def test_media_pesata_dei_cinque_criteri(self):
        # 5×20 + 3×15 + 4×25 + 4×20 + 5×20 = 100+45+100+80+100 = 425 su peso 100
        risultato = recruiting_service.calcola_ponderato([
            (5, Decimal("20")), (3, Decimal("15")), (4, Decimal("25")),
            (4, Decimal("20")), (5, Decimal("20")),
        ])
        self.assertEqual(risultato, Decimal("4.25"))

    def test_valutazione_parziale_resta_sulla_scala_1_5(self):
        """Con due soli criteri valutati il risultato non collassa verso zero."""
        risultato = recruiting_service.calcola_ponderato([
            (5, Decimal("20")), (5, Decimal("15")),
        ])
        self.assertEqual(risultato, Decimal("5.00"))

    def test_peso_zero_non_sposta_il_risultato(self):
        risultato = recruiting_service.calcola_ponderato([
            (4, Decimal("50")), (1, Decimal("0")),
        ])
        self.assertEqual(risultato, Decimal("4.00"))

    def test_nessun_criterio_valutabile_da_none(self):
        self.assertIsNone(recruiting_service.calcola_ponderato([]))
        self.assertIsNone(recruiting_service.calcola_ponderato([(5, Decimal("0"))]))


class RicalcoloSuCandidatoTests(TestCase):
    def setUp(self):
        self.criteri = _crea_criteri()
        self.candidato = Candidato.objects.create(cognome="Rossi", nome="Test")

    def test_ricalcolo_persiste_il_punteggio(self):
        recruiting_service.salva_punteggi(self.candidato, {
            self.criteri["sintonia"].id: 5,
            self.criteri["vicinanza"].id: 3,
            self.criteri["esperienze_pregresse"].id: 4,
            self.criteri["capacita_relazionali"].id: 4,
            self.criteri["competenze_tecniche"].id: 5,
        })
        self.candidato.refresh_from_db()
        self.assertEqual(self.candidato.punteggio_ponderato, Decimal("4.25"))
        self.assertIsNotNone(self.candidato.punteggio_aggiornato_il)

    def test_criterio_disattivato_esce_dal_calcolo(self):
        """Disattivare «Vicinanza» è la leva HR per toglierla dal punteggio."""
        recruiting_service.salva_punteggi(self.candidato, {
            self.criteri["sintonia"].id: 5,
            self.criteri["vicinanza"].id: 1,
        })
        self.candidato.refresh_from_db()
        con_vicinanza = self.candidato.punteggio_ponderato

        self.criteri["vicinanza"].is_active = False
        self.criteri["vicinanza"].save(update_fields=["is_active"])
        recruiting_service.ricalcola_punteggio(self.candidato)

        self.candidato.refresh_from_db()
        self.assertEqual(self.candidato.punteggio_ponderato, Decimal("5.00"))
        self.assertNotEqual(con_vicinanza, self.candidato.punteggio_ponderato)

    def test_voto_fuori_scala_viene_ignorato(self):
        recruiting_service.salva_punteggi(self.candidato, {
            self.criteri["sintonia"].id: 9,
            self.criteri["competenze_tecniche"].id: 4,
        })
        self.candidato.refresh_from_db()
        self.assertEqual(self.candidato.punteggio_ponderato, Decimal("4.00"))
        self.assertFalse(
            CandidatoPunteggio.objects
            .filter(candidato=self.candidato, criterio=self.criteri["sintonia"])
            .exists()
        )

    def test_voto_azzerato_cancella_la_riga(self):
        recruiting_service.salva_punteggi(self.candidato, {self.criteri["sintonia"].id: 4})
        recruiting_service.salva_punteggi(self.candidato, {self.criteri["sintonia"].id: None})
        self.candidato.refresh_from_db()
        self.assertIsNone(self.candidato.punteggio_ponderato)


class DatiInformativiFuoriDalPunteggioTests(TestCase):
    """Età e cittadinanza non possono pesare sull'esito, nemmeno indirettamente.

    Non è una convenzione ma una proprietà della struttura dati: il calcolo legge
    solo ``CandidatoPunteggio``, che esiste solo in relazione a un criterio.
    """

    def setUp(self):
        self.criteri = _crea_criteri()

    def test_eta_e_cittadinanza_non_cambiano_il_punteggio(self):
        voti = {self.criteri["competenze_tecniche"].id: 4}

        giovane = Candidato.objects.create(
            cognome="A", nome="Uno", eta=22, cittadinanza="Italiana",
        )
        anziano = Candidato.objects.create(
            cognome="B", nome="Due", eta=58, cittadinanza="Marocchina",
        )
        recruiting_service.salva_punteggi(giovane, voti)
        recruiting_service.salva_punteggi(anziano, voti)

        giovane.refresh_from_db()
        anziano.refresh_from_db()
        self.assertEqual(giovane.punteggio_ponderato, anziano.punteggio_ponderato)

    def test_nessun_criterio_corrisponde_a_un_campo_protetto(self):
        codici = set(RecruitingCriterio.objects.values_list("codice", flat=True))
        for vietato in ("eta", "cittadinanza", "sesso", "genere", "titolo_studio"):
            self.assertNotIn(vietato, codici)

    def test_il_punteggio_dipende_solo_dalle_righe_di_punteggio(self):
        candidato = Candidato.objects.create(cognome="C", nome="Tre", eta=40)
        recruiting_service.salva_punteggi(candidato, {self.criteri["sintonia"].id: 3})
        candidato.refresh_from_db()
        atteso = candidato.punteggio_ponderato

        candidato.eta = 60
        candidato.cittadinanza = "Albanese"
        candidato.titolo_studio = "Licenza media"
        candidato.save()
        recruiting_service.ricalcola_punteggio(candidato)

        candidato.refresh_from_db()
        self.assertEqual(candidato.punteggio_ponderato, atteso)


class TracciabilitaTests(TestCase):
    def setUp(self):
        self.criteri = _crea_criteri()
        self.user = User.objects.create_user(username="hr-log", password="pass12345")
        self.candidato = Candidato.objects.create(cognome="Bianchi", nome="Test")

    def test_cambio_punteggio_registra_valore_precedente(self):
        recruiting_service.salva_punteggi(
            self.candidato, {self.criteri["sintonia"].id: 3}, user=self.user,
        )
        recruiting_service.salva_punteggi(
            self.candidato, {self.criteri["sintonia"].id: 5}, user=self.user,
        )
        log = CandidatoLog.objects.filter(
            candidato=self.candidato, tipo=CandidatoLog.TIPO_PUNTEGGIO,
        ).order_by("id")
        self.assertEqual(log.count(), 2)
        self.assertEqual(log[1].valore_prima, "3")
        self.assertEqual(log[1].valore_dopo, "5")
        self.assertEqual(log[1].user_id, self.user.id)

    def test_valore_invariato_non_genera_riga(self):
        recruiting_service.salva_punteggi(
            self.candidato, {self.criteri["sintonia"].id: 4}, user=self.user,
        )
        prima = CandidatoLog.objects.filter(candidato=self.candidato).count()
        recruiting_service.salva_punteggi(
            self.candidato, {self.criteri["sintonia"].id: 4}, user=self.user,
        )
        self.assertEqual(CandidatoLog.objects.filter(candidato=self.candidato).count(), prima)

    def test_cambio_giudizio_tracciato(self):
        recruiting_service.registra_cambio_giudizio(
            self.candidato, "", Candidato.GIUDIZIO_POSITIVO, user=self.user,
        )
        riga = CandidatoLog.objects.get(candidato=self.candidato, tipo=CandidatoLog.TIPO_GIUDIZIO)
        self.assertEqual(riga.valore_dopo, "POSITIVO")


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class TransizioneOnboardingTests(TestCase):
    def setUp(self):
        _ensure_anagrafica_table()
        _ensure_utenti_table()
        self.user = User.objects.create_superuser(
            username="hr-transizione", email="hr-tr@example.com", password="pass12345",
        )
        self.candidato = Candidato.objects.create(
            cognome="Verdi", nome="Test", mansione_cercata="Operatore CNC",
            data_assunzione=date.today(),
        )

    def test_assunzione_crea_dipendente_e_pratica(self):
        pratica = recruiting_service.assumi_e_avvia_onboarding(
            self.candidato, user=self.user, reparto="Produzione",
        )
        self.candidato.refresh_from_db()
        self.assertEqual(self.candidato.stato, Candidato.STATO_ASSUNTO)
        self.assertTrue(self.candidato.legacy_anagrafica_id)
        self.assertEqual(self.candidato.onboarding_pratica_id, pratica.id)
        self.assertEqual(pratica.mansione, "Operatore CNC")
        self.assertTrue(pratica.tasks.exists())

    def test_assunzione_e_idempotente(self):
        prima = recruiting_service.assumi_e_avvia_onboarding(self.candidato, user=self.user)
        self.candidato.refresh_from_db()
        dopo = recruiting_service.assumi_e_avvia_onboarding(self.candidato, user=self.user)
        self.assertEqual(prima.id, dopo.id)

    def test_candidato_senza_nome_non_diventa_dipendente(self):
        vuoto = Candidato.objects.create(cognome="", nome="")
        with self.assertRaises(recruiting_service.TransizioneError):
            recruiting_service.assumi_e_avvia_onboarding(vuoto, user=self.user)

    def test_archiviazione_mantiene_il_profilo(self):
        recruiting_service.archivia_in_database(self.candidato, user=self.user)
        self.candidato.refresh_from_db()
        self.assertEqual(self.candidato.stato, Candidato.STATO_IN_DATABASE)
        self.assertTrue(Candidato.objects.filter(pk=self.candidato.pk).exists())
        self.assertTrue(
            CandidatoLog.objects
            .filter(candidato=self.candidato, tipo=CandidatoLog.TIPO_STATO)
            .exists()
        )


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class GatingTests(TestCase):
    """La sezione contiene dati sensibili: default ristretto, come le visite mediche."""

    def setUp(self):
        _ensure_anagrafica_table()
        _ensure_utenti_table()
        _crea_criteri()
        self.candidato = Candidato.objects.create(cognome="Neri", nome="Test")
        self.admin = User.objects.create_superuser(
            username="hr-admin", email="hr-admin@example.com", password="pass12345",
        )
        self.utente = User.objects.create_user(username="hr-base", password="pass12345")

    def test_anonimo_non_entra(self):
        resp = self.client.get(reverse("anagrafica:recruiting_list"))
        self.assertNotEqual(resp.status_code, 200)

    def test_utente_comune_respinto_col_default_admin(self):
        self.assertEqual(
            RecruitingPermission.get_instance().accesso,
            RecruitingPermission.ACCESSO_ADMIN,
        )
        self.client.force_login(self.utente)
        resp = self.client.get(reverse("anagrafica:recruiting_list"))
        self.assertEqual(resp.status_code, 302)

    def test_superuser_vede_lista_e_scheda(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("anagrafica:recruiting_list")).status_code, 200)
        self.assertEqual(
            self.client.get(reverse("anagrafica:recruiting_detail", args=[self.candidato.id])).status_code,
            200,
        )

    def test_utente_comune_non_modifica(self):
        self.client.force_login(self.utente)
        resp = self.client.post(
            reverse("anagrafica:recruiting_archivia", args=[self.candidato.id]),
        )
        self.assertEqual(resp.status_code, 302)
        self.candidato.refresh_from_db()
        self.assertNotEqual(self.candidato.stato, Candidato.STATO_IN_DATABASE)

    def test_singleton_non_puo_allargare_oltre_l_acl(self):
        """Il singleton restringe, non concede: l'ACL canonico resta autoritativo.

        Portarlo a «Tutti gli utenti autenticati» toglie il restringimento di
        sezione, ma chi non ha il grant canonico continua a non entrare. È il
        comportamento fail-closed voluto: una manopola di sezione non deve poter
        aggirare la governance ACL.
        """
        perm = RecruitingPermission.get_instance()
        perm.accesso = RecruitingPermission.ACCESSO_TUTTI
        perm.save(update_fields=["accesso"])
        self.client.force_login(self.utente)
        self.assertEqual(self.client.get(reverse("anagrafica:recruiting_list")).status_code, 302)


class AclBootstrapTests(TestCase):
    """Con ACL_STRICT_CANONICAL una route non mappata viene negata a tutti.

    Ogni rotta del modulo deve quindi avere il suo RoutePermissionBinding: è la
    verifica che in produzione la sezione sia raggiungibile da chi ha il grant.
    """

    def test_ogni_route_recruiting_ha_un_binding(self):
        from core.models import PermissionDefinition, RoutePermissionBinding

        from .acl_bootstrap import (
            _RECR_ROUTE_BINDINGS,
            _bootstrap_recruiting_canonical,
            PERM_RECR_MANAGE,
            PERM_RECR_VIEW,
        )

        _bootstrap_recruiting_canonical()

        for code in (PERM_RECR_VIEW, PERM_RECR_MANAGE):
            self.assertTrue(PermissionDefinition.objects.filter(code=code).exists(), code)

        for route_name, code in _RECR_ROUTE_BINDINGS.items():
            binding = RoutePermissionBinding.objects.filter(
                route_name=route_name, is_active=True,
            ).first()
            self.assertIsNotNone(binding, f"binding mancante per {route_name}")
            self.assertEqual(binding.permission_id, code, route_name)

    def test_i_binding_coprono_tutte_le_rotte_dichiarate_in_urls(self):
        from .acl_bootstrap import _RECR_ROUTE_BINDINGS
        from .urls import urlpatterns

        dichiarate = {
            f"anagrafica:{pattern.name}"
            for pattern in urlpatterns
            if getattr(pattern, "name", "") and pattern.name.startswith("recruiting_")
        }
        self.assertTrue(dichiarate)
        self.assertEqual(dichiarate - set(_RECR_ROUTE_BINDINGS), set())


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class ViewsTests(TestCase):
    def setUp(self):
        _ensure_anagrafica_table()
        _ensure_utenti_table()
        self.criteri = _crea_criteri()
        self.admin = User.objects.create_superuser(
            username="hr-view", email="hr-view@example.com", password="pass12345",
        )
        self.client.force_login(self.admin)

    def test_creazione_calcola_il_punteggio_lato_server(self):
        resp = self.client.post(reverse("anagrafica:recruiting_create"), {
            "cognome": "Gialli", "nome": "Test",
            "canale_provenienza": Candidato.CANALE_AUTOCANDIDATURA,
            "stato": Candidato.STATO_COLLOQUIO_1,
            "cv_esito": Candidato.CV_OK,
            "eta": 30,
            f"criterio_{self.criteri['sintonia'].id}": "5",
            f"criterio_{self.criteri['competenze_tecniche'].id}": "3",
            # Valore ostile: il ponderato non è un campo del form.
            "punteggio_ponderato": "5.00",
        })
        self.assertEqual(resp.status_code, 302)
        candidato = Candidato.objects.get(cognome="Gialli")
        # (5×20 + 3×20) / 40 = 4.00, non il 5.00 arrivato dal client.
        self.assertEqual(candidato.punteggio_ponderato, Decimal("4.00"))

    def test_step2_sulla_stessa_scheda(self):
        candidato = Candidato.objects.create(
            cognome="Blu", nome="Test", data_primo_colloquio=date.today() - timedelta(days=10),
        )
        resp = self.client.post(
            reverse("anagrafica:recruiting_step2", args=[candidato.id]),
            {
                "data_secondo_colloquio": date.today().isoformat(),
                "note_secondo_colloquio": "Colloquio tecnico con il responsabile.",
                "comunicazione_esito": Candidato.COMUNICAZIONE_SI,
            },
        )
        self.assertEqual(resp.status_code, 302)
        candidato.refresh_from_db()
        self.assertEqual(candidato.data_secondo_colloquio, date.today())
        self.assertEqual(candidato.stato, Candidato.STATO_COLLOQUIO_2)
        self.assertEqual(candidato.giorni_tra_colloqui, 10)

    def test_step2_rifiuta_data_precedente_al_primo(self):
        candidato = Candidato.objects.create(
            cognome="Grigi", nome="Test", data_primo_colloquio=date.today(),
        )
        self.client.post(
            reverse("anagrafica:recruiting_step2", args=[candidato.id]),
            {"data_secondo_colloquio": (date.today() - timedelta(days=5)).isoformat()},
        )
        candidato.refresh_from_db()
        self.assertIsNone(candidato.data_secondo_colloquio)

    def test_filtro_per_punteggio_minimo(self):
        alto = Candidato.objects.create(cognome="Alto", nome="T", punteggio_ponderato=Decimal("4.50"))
        Candidato.objects.create(cognome="Basso", nome="T", punteggio_ponderato=Decimal("2.00"))
        resp = self.client.get(reverse("anagrafica:recruiting_list"), {"punteggio_min": "4"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual([c.id for c in resp.context["page_obj"].object_list], [alto.id])

    def test_cruscotto_kpi(self):
        Candidato.objects.create(
            cognome="K1", nome="T", giudizio_finale=Candidato.GIUDIZIO_POSITIVO,
            stato=Candidato.STATO_ASSUNTO, punteggio_ponderato=Decimal("4.00"),
            data_primo_colloquio=date.today() - timedelta(days=14),
            data_secondo_colloquio=date.today() - timedelta(days=4),
        )
        Candidato.objects.create(
            cognome="K2", nome="T", giudizio_finale=Candidato.GIUDIZIO_NEGATIVO,
            punteggio_ponderato=Decimal("2.00"),
        )
        resp = self.client.get(reverse("anagrafica:recruiting_dashboard"))
        self.assertEqual(resp.status_code, 200)
        kpi = resp.context["kpi"]
        self.assertEqual(kpi["totale"], 2)
        self.assertEqual(kpi["positivi"], 1)
        self.assertEqual(kpi["negativi"], 1)
        self.assertEqual(kpi["pct_positivi"], 50.0)
        self.assertEqual(kpi["tasso_assunzione"], 50.0)
        self.assertEqual(kpi["giorni_medi_tra_colloqui"], 10.0)

    def test_pagina_criteri_espone_le_note_di_conformita(self):
        resp = self.client.get(reverse("anagrafica:recruiting_criteri"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "UNI/PdR 125")
        self.assertContains(resp, "Vicinanza")

    def test_cambio_peso_ricalcola_le_schede_aperte(self):
        candidato = Candidato.objects.create(cognome="Peso", nome="T")
        recruiting_service.salva_punteggi(candidato, {
            self.criteri["sintonia"].id: 5,
            self.criteri["competenze_tecniche"].id: 1,
        })
        candidato.refresh_from_db()
        self.assertEqual(candidato.punteggio_ponderato, Decimal("3.00"))

        criterio = self.criteri["sintonia"]
        resp = self.client.post(reverse("anagrafica:recruiting_criteri"), {
            "criterio_id": criterio.id,
            "codice": criterio.codice,
            "label": criterio.label,
            "descrizione": criterio.descrizione,
            "rubrica": "1 = nessuna sintonia\n3 = adeguata\n5 = piena",
            "peso_percentuale": "60",
            "ordine": criterio.ordine,
            "is_active": "on",
        })
        self.assertEqual(resp.status_code, 302)
        candidato.refresh_from_db()
        # (5×60 + 1×20) / 80 = 4.00
        self.assertEqual(candidato.punteggio_ponderato, Decimal("4.00"))
