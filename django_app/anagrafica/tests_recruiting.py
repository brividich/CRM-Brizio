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


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class CriteriAzioniTests(TestCase):
    """Le azioni per riga: modificare un criterio non deve richiedere di ridigitarlo."""

    def setUp(self):
        _ensure_anagrafica_table()
        _ensure_utenti_table()
        self.criteri = _crea_criteri()
        self.admin = User.objects.create_superuser(
            username="hr-crit", email="hr-crit@example.com", password="pass12345",
        )
        self.client.force_login(self.admin)

    def test_tabella_espone_le_azioni_per_riga(self):
        resp = self.client.get(reverse("anagrafica:recruiting_criteri"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "rcr-edit")
        self.assertContains(resp, reverse(
            "anagrafica:recruiting_criterio_toggle", args=[self.criteri["sintonia"].id],
        ))
        self.assertContains(resp, reverse(
            "anagrafica:recruiting_criterio_move", args=[self.criteri["sintonia"].id],
        ))

    def test_peso_effettivo_e_normalizzato_sui_soli_attivi(self):
        """Sintonia è al 20% nominale, ma con tutti i criteri attivi (100) resta 20%."""
        resp = self.client.get(reverse("anagrafica:recruiting_criteri"))
        righe = {r["criterio"].codice: r for r in resp.context["criteri"]}
        self.assertEqual(righe["sintonia"]["peso_effettivo"], Decimal("20.0"))

        # Disattivando «Competenze tecniche» (20) il totale attivo scende a 80:
        # Sintonia pesa ora 20/80 = 25%.
        self.client.post(reverse(
            "anagrafica:recruiting_criterio_toggle", args=[self.criteri["competenze_tecniche"].id],
        ))
        resp = self.client.get(reverse("anagrafica:recruiting_criteri"))
        righe = {r["criterio"].codice: r for r in resp.context["criteri"]}
        self.assertEqual(righe["sintonia"]["peso_effettivo"], Decimal("25.0"))
        self.assertIsNone(righe["competenze_tecniche"]["peso_effettivo"])

    def test_toggle_ricalcola_i_punteggi(self):
        candidato = Candidato.objects.create(cognome="Toggle", nome="T")
        recruiting_service.salva_punteggi(candidato, {
            self.criteri["sintonia"].id: 5,
            self.criteri["vicinanza"].id: 1,
        })
        candidato.refresh_from_db()
        self.assertNotEqual(candidato.punteggio_ponderato, Decimal("5.00"))

        self.client.post(reverse(
            "anagrafica:recruiting_criterio_toggle", args=[self.criteri["vicinanza"].id],
        ))
        candidato.refresh_from_db()
        self.assertEqual(candidato.punteggio_ponderato, Decimal("5.00"))

    def test_eliminazione_criterio_mai_usato(self):
        criterio = RecruitingCriterio.objects.create(
            codice="sperimentale", label="Sperimentale", peso_percentuale=Decimal("10"),
        )
        resp = self.client.post(reverse("anagrafica:recruiting_criterio_delete", args=[criterio.id]))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(RecruitingCriterio.objects.filter(pk=criterio.pk).exists())

    def test_criterio_gia_votato_non_si_elimina(self):
        """Cancellare un criterio già usato falsificherebbe lo storico delle decisioni."""
        candidato = Candidato.objects.create(cognome="Usato", nome="T")
        recruiting_service.salva_punteggi(candidato, {self.criteri["sintonia"].id: 4})

        self.client.post(reverse(
            "anagrafica:recruiting_criterio_delete", args=[self.criteri["sintonia"].id],
        ))
        self.assertTrue(RecruitingCriterio.objects.filter(pk=self.criteri["sintonia"].pk).exists())

    def test_riordino_scambia_la_posizione(self):
        primo = self.criteri["sintonia"]        # ordine 10
        secondo = self.criteri["vicinanza"]     # ordine 20
        self.client.post(
            reverse("anagrafica:recruiting_criterio_move", args=[secondo.id]), {"direzione": "su"},
        )
        primo.refresh_from_db()
        secondo.refresh_from_db()
        self.assertLess(secondo.ordine, primo.ordine)

    def test_riordino_non_esce_dai_bordi(self):
        primo = self.criteri["sintonia"]
        ordine_prima = primo.ordine
        self.client.post(
            reverse("anagrafica:recruiting_criterio_move", args=[primo.id]), {"direzione": "su"},
        )
        primo.refresh_from_db()
        self.assertEqual(primo.ordine, ordine_prima)

    def test_azioni_negate_a_chi_non_gestisce(self):
        utente = User.objects.create_user(username="hr-nogest", password="pass12345")
        self.client.force_login(utente)
        resp = self.client.post(reverse(
            "anagrafica:recruiting_criterio_toggle", args=[self.criteri["sintonia"].id],
        ))
        self.assertEqual(resp.status_code, 302)
        self.criteri["sintonia"].refresh_from_db()
        self.assertTrue(self.criteri["sintonia"].is_active)


class ImportXlsxTests(TestCase):
    """Riconoscimento delle intestazioni e conversioni del comando di import."""

    def test_intestazioni_riconosciute_con_sinonimi_e_accenti(self):
        from anagrafica.management.commands.import_recruiting_xlsx import _match_colonna

        self.assertEqual(_match_colonna("Data 1° colloquio"), "data_primo_colloquio")
        self.assertEqual(_match_colonna("MANSIONE PRIMARIA CERCATA"), "mansione_cercata")
        self.assertEqual(_match_colonna("Località"), "localita")
        self.assertEqual(_match_colonna("Rischio di abbandono"), "rischio_abbandono")
        self.assertEqual(_match_colonna("C.V."), "cv_esito")
        self.assertIsNone(_match_colonna("Colonna inventata"))

    def test_canale_non_riconosciuto_finisce_in_altro_senza_perdere_il_testo(self):
        from anagrafica.management.commands.import_recruiting_xlsx import _canale

        self.assertEqual(_canale("Autocandidatura")[0], Candidato.CANALE_AUTOCANDIDATURA)
        self.assertEqual(_canale("Agenzia interinale")[0], Candidato.CANALE_AGENZIA)
        codice, dettaglio = _canale("Fiera del lavoro 2026")
        self.assertEqual(codice, Candidato.CANALE_ALTRO)
        self.assertEqual(dettaglio, "Fiera del lavoro 2026")

    def test_conversioni_di_valore(self):
        from anagrafica.management.commands.import_recruiting_xlsx import (
            _booleano, _cv_esito, _data, _giudizio, _intero,
        )

        self.assertEqual(_data("15/03/2026"), date(2026, 3, 15))
        self.assertIsNone(_data("non una data"))
        self.assertTrue(_booleano("SI"))
        self.assertFalse(_booleano("no"))
        self.assertIsNone(_booleano(""))
        self.assertEqual(_cv_esito("OK"), Candidato.CV_OK)
        self.assertEqual(_cv_esito("0"), Candidato.CV_KO)
        self.assertEqual(_giudizio("POSITIVO"), Candidato.GIUDIZIO_POSITIVO)
        self.assertEqual(_giudizio(""), "")
        self.assertIsNone(_intero("9", 1, 5))   # voto fuori scala
        self.assertEqual(_intero("4", 1, 5), 4)

    def test_stato_dedotto_dai_dati(self):
        from anagrafica.management.commands.import_recruiting_xlsx import _stato_iniziale

        self.assertEqual(_stato_iniziale({"data_assunzione": date.today()}), Candidato.STATO_ASSUNTO)
        self.assertEqual(
            _stato_iniziale({"giudizio_finale": Candidato.GIUDIZIO_NEGATIVO}),
            Candidato.STATO_SCARTATO,
        )
        self.assertEqual(
            _stato_iniziale({"data_secondo_colloquio": date.today()}),
            Candidato.STATO_COLLOQUIO_2,
        )
        self.assertEqual(_stato_iniziale({}), Candidato.STATO_NUOVO)

    def test_le_colonne_di_punteggio_seguono_i_criteri_a_db(self):
        """Un criterio rinominato da HR resta riconoscibile senza toccare il codice."""
        from anagrafica.management.commands.import_recruiting_xlsx import Command

        criteri = _crea_criteri()
        criteri["sintonia"].label = "Sintonia con il team"
        criteri["sintonia"].save(update_fields=["label"])

        mappa, mappa_criteri, ignorate, sconosciute = Command()._analizza([
            "Cognome", "Nome", "Sintonia con il team", "Vicinanza",
            "Punteggio medio totale ponderato", "Colonna misteriosa",
        ])
        self.assertEqual(mappa["cognome"], 0)
        etichette = {c.codice for c, _ in mappa_criteri}
        self.assertEqual(etichette, {"sintonia", "vicinanza"})
        self.assertIn("Punteggio medio totale ponderato", ignorate)
        self.assertIn("Colonna misteriosa", sconosciute)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class CicloVitaTests(TestCase):
    """Annullamento, riapertura, sola-lettura degli iter chiusi."""

    def setUp(self):
        _ensure_anagrafica_table()
        _ensure_utenti_table()
        self.admin = User.objects.create_superuser(
            username="hr-vita", email="hr-vita@example.com", password="pass12345",
        )
        self.client.force_login(self.admin)
        self.candidato = Candidato.objects.create(
            cognome="Rossi", nome="Test", data_primo_colloquio=date(2026, 3, 1),
            cv_esito=Candidato.CV_OK,
        )

    def test_annulla_toglie_dalle_liste_ma_conserva_log(self):
        resp = self.client.post(reverse("anagrafica:recruiting_annulla", args=[self.candidato.id]), {
            "motivo": "Inserita per errore",
        })
        self.assertEqual(resp.status_code, 302)
        self.candidato.refresh_from_db()
        self.assertEqual(self.candidato.stato, Candidato.STATO_ANNULLATO)
        # Log preservato, con il motivo.
        riga = CandidatoLog.objects.filter(
            candidato=self.candidato, tipo=CandidatoLog.TIPO_STATO,
        ).latest("id")
        self.assertIn("Inserita per errore", riga.note)
        # Fuori dalle liste operative di default...
        resp = self.client.get(reverse("anagrafica:recruiting_list"))
        self.assertNotIn(self.candidato, resp.context["page_obj"].object_list)
        # ...ma visibile filtrando per stato.
        resp = self.client.get(reverse("anagrafica:recruiting_list"), {"stato": "ANNULLATO"})
        self.assertIn(self.candidato, resp.context["page_obj"].object_list)

    def test_ricerca_trova_anche_gli_annullati(self):
        recruiting_service.annulla_scheda(self.candidato, user=self.admin)
        resp = self.client.get(reverse("anagrafica:recruiting_list"), {"q": "Rossi"})
        self.assertIn(self.candidato, resp.context["page_obj"].object_list)

    def test_modifica_bloccata_su_iter_chiuso(self):
        self.candidato.stato = Candidato.STATO_SCARTATO
        self.candidato.save(update_fields=["stato"])
        resp = self.client.get(reverse("anagrafica:recruiting_edit", args=[self.candidato.id]))
        self.assertEqual(resp.status_code, 302)  # redirect a detail
        # E la scheda è marcata sola-lettura nel context del dettaglio.
        resp = self.client.get(reverse("anagrafica:recruiting_detail", args=[self.candidato.id]))
        self.assertTrue(resp.context["sola_lettura"])

    def test_riapertura_deduce_lo_stato_e_traccia(self):
        self.candidato.stato = Candidato.STATO_SCARTATO
        self.candidato.save(update_fields=["stato"])
        resp = self.client.post(reverse("anagrafica:recruiting_riapri", args=[self.candidato.id]))
        self.assertEqual(resp.status_code, 302)
        self.candidato.refresh_from_db()
        # Ha una data di primo colloquio ma non il secondo → COLLOQUIO_1.
        self.assertEqual(self.candidato.stato, Candidato.STATO_COLLOQUIO_1)
        self.assertFalse(self.candidato.iter_chiuso)
        self.assertTrue(CandidatoLog.objects.filter(
            candidato=self.candidato, tipo=CandidatoLog.TIPO_STATO, note="Iter riaperto.",
        ).exists())

    def test_riapertura_non_scollega_onboarding(self):
        pratica = recruiting_service.assumi_e_avvia_onboarding(self.candidato, user=self.admin)
        recruiting_service.riapri_iter(self.candidato, user=self.admin)
        self.candidato.refresh_from_db()
        self.assertEqual(self.candidato.onboarding_pratica_id, pratica.id)
        self.assertTrue(self.candidato.legacy_anagrafica_id)

    def test_annulla_negato_a_chi_non_gestisce(self):
        utente = User.objects.create_user(username="hr-novita", password="pass12345")
        self.client.force_login(utente)
        self.client.post(reverse("anagrafica:recruiting_annulla", args=[self.candidato.id]))
        self.candidato.refresh_from_db()
        self.assertNotEqual(self.candidato.stato, Candidato.STATO_ANNULLATO)


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class SchedaAnonimaTests(TestCase):
    """Import senza nominativi e completamento dal portale."""

    def setUp(self):
        _ensure_anagrafica_table()
        _ensure_utenti_table()
        self.admin = User.objects.create_superuser(
            username="hr-anon", email="hr-anon@example.com", password="pass12345",
        )
        self.client.force_login(self.admin)

    def test_scheda_anonima_e_da_completare(self):
        c = Candidato.objects.create(cognome="", nome="", codice_riferimento="12")
        self.assertTrue(c.anagrafica_da_completare)
        self.assertEqual(c.etichetta, "Da completare · rif. 12")

    def test_contatore_e_filtro_da_completare(self):
        Candidato.objects.create(cognome="", nome="", codice_riferimento="1")
        Candidato.objects.create(cognome="Bianchi", nome="Ann", codice_riferimento="2")
        resp = self.client.get(reverse("anagrafica:recruiting_list"))
        self.assertEqual(resp.context["n_da_completare"], 1)
        resp = self.client.get(reverse("anagrafica:recruiting_list"), {"da_completare": "1"})
        etichette = [c.etichetta for c in resp.context["page_obj"].object_list]
        self.assertEqual(etichette, ["Da completare · rif. 1"])

    def test_una_anonima_non_si_puo_assumere(self):
        c = Candidato.objects.create(cognome="", nome="", codice_riferimento="9")
        with self.assertRaises(recruiting_service.TransizioneError):
            recruiting_service.assumi_e_avvia_onboarding(c, user=self.admin)

    def test_completamento_nominativo_via_form(self):
        c = Candidato.objects.create(cognome="", nome="", codice_riferimento="7")
        resp = self.client.post(reverse("anagrafica:recruiting_edit", args=[c.id]), {
            "cognome": "Neri", "nome": "Luca",
            "codice_riferimento": "7",
            "canale_provenienza": Candidato.CANALE_AUTOCANDIDATURA,
            "stato": Candidato.STATO_NUOVO,
        })
        self.assertEqual(resp.status_code, 302)
        c.refresh_from_db()
        self.assertFalse(c.anagrafica_da_completare)
        self.assertEqual(c.nominativo, "Neri Luca")

    def test_import_anonimo_riconosce_riferimento_e_significativita(self):
        from anagrafica.management.commands.import_recruiting_xlsx import Command

        cmd = Command()
        mappa = {"codice_riferimento": 0, "mansione_cercata": 1, "data_primo_colloquio": 2}
        # Riga con dati ma senza nome → significativa; codice dal file.
        valori = cmd._leggi(["7", "Operatore", "15/03/2026"], mappa, numero_riga=5)
        self.assertEqual(valori["codice_riferimento"], "7")
        self.assertEqual(valori["cognome"], "")
        self.assertTrue(cmd._riga_significativa(valori, ["7", "Operatore", "15/03/2026"], []))
        # Riga del tutto vuota → non significativa; riferimento = numero riga.
        vuota = cmd._leggi([None, None, None], mappa, numero_riga=9)
        self.assertEqual(vuota["codice_riferimento"], "riga 9")
        self.assertFalse(cmd._riga_significativa(vuota, [None, None, None], []))

    def test_dedup_anonima_su_riferimento(self):
        from anagrafica.management.commands.import_recruiting_xlsx import Command

        cmd = Command()
        Candidato.objects.create(cognome="", nome="", codice_riferimento="42")
        self.assertTrue(cmd._esiste({"cognome": "", "nome": "", "codice_riferimento": "42"}))
        self.assertFalse(cmd._esiste({"cognome": "", "nome": "", "codice_riferimento": "99"}))
        # Il fallback "riga N" non deduplica (non è stabile).
        self.assertFalse(cmd._esiste({"cognome": "", "nome": "", "codice_riferimento": "riga 3"}))


class SubnavTests(TestCase):
    """Il modulo deve stare nel menu di Anagrafica, non solo nella pill «Vai a»."""

    def test_voce_recruiting_nel_pilastro_persone(self):
        from .models import SubnavLinkAnagrafica

        link = SubnavLinkAnagrafica.objects.filter(
            url_value="anagrafica:recruiting_list",
        ).first()
        self.assertIsNotNone(link, "voce di subnav Recruiting mancante")
        self.assertTrue(link.is_active)
        self.assertEqual(link.etichetta, "Recruiting")
        self.assertEqual(getattr(link.categoria, "nome", ""), "Persone")

    def test_precede_onboarding_nel_menu(self):
        """La selezione viene prima dell'inserimento: l'ordine segue il processo."""
        from .models import SubnavLinkAnagrafica

        recruiting = SubnavLinkAnagrafica.objects.get(url_value="anagrafica:recruiting_list")
        onboarding = SubnavLinkAnagrafica.objects.filter(
            url_value="anagrafica:onboarding_list",
        ).first()
        if onboarding is None:
            self.skipTest("voce Onboarding non presente in questo ambiente")
        self.assertLess(recruiting.ordine, onboarding.ordine)

    def test_tutte_le_pagine_evidenziano_la_voce(self):
        from .models import SubnavLinkAnagrafica
        from .urls import urlpatterns

        link = SubnavLinkAnagrafica.objects.get(url_value="anagrafica:recruiting_list")
        attivi = {t.strip() for t in (link.active_view_names or "").split(",") if t.strip()}
        dichiarate = {
            f"anagrafica:{p.name}"
            for p in urlpatterns
            if getattr(p, "name", "") and p.name.startswith("recruiting_")
        }
        # Le route POST-only (azioni) non hanno una pagina da evidenziare.
        azioni = {
            "anagrafica:recruiting_step2",
            "anagrafica:recruiting_assumi",
            "anagrafica:recruiting_archivia",
            "anagrafica:recruiting_annulla",
            "anagrafica:recruiting_riapri",
            "anagrafica:recruiting_criterio_toggle",
            "anagrafica:recruiting_criterio_delete",
            "anagrafica:recruiting_criterio_move",
        }
        self.assertEqual(dichiarate - azioni - attivi, set())


@override_settings(LEGACY_AUTH_ENABLED=False, SECURE_SSL_REDIRECT=False)
class ImpostazioniPermessiTests(TestCase):
    """La sezione Recruiting deve essere configurabile da Impostazioni → Permessi."""

    def setUp(self):
        _ensure_anagrafica_table()
        _ensure_utenti_table()
        self.admin = User.objects.create_superuser(
            username="hr-imp", email="hr-imp@example.com", password="pass12345",
        )
        self.client.force_login(self.admin)

    def test_card_recruiting_presente_tra_i_permessi(self):
        resp = self.client.get(reverse("anagrafica:impostazioni"))
        self.assertEqual(resp.status_code, 200)
        prefissi = {card["prefix"] for card in resp.context["permessi_cards"]}
        self.assertEqual(prefissi, {"stat", "hr", "visite", "recruiting"})
        self.assertContains(resp, 'name="recruiting_accesso"')

    def test_salvataggio_permesso_recruiting(self):
        resp = self.client.post(reverse("anagrafica:impostazioni_permessi_save"), {
            "stat_accesso": RecruitingPermission.ACCESSO_ADMIN,
            "hr_accesso": RecruitingPermission.ACCESSO_ADMIN,
            "visite_accesso": RecruitingPermission.ACCESSO_ADMIN,
            "recruiting_accesso": RecruitingPermission.ACCESSO_RUOLI,
            "recruiting_ruolo_ids": ["3", "7"],
        })
        self.assertEqual(resp.status_code, 302)
        perm = RecruitingPermission.get_instance()
        self.assertEqual(perm.accesso, RecruitingPermission.ACCESSO_RUOLI)
        self.assertEqual(perm.ruolo_ids, [3, 7])

    def test_le_altre_card_non_vengono_azzerate(self):
        """Il salvataggio scrive tutti i prefissi: nessuno resta indietro."""
        self.client.post(reverse("anagrafica:impostazioni_permessi_save"), {
            "stat_accesso": RecruitingPermission.ACCESSO_TUTTI,
            "hr_accesso": RecruitingPermission.ACCESSO_ADMIN,
            "visite_accesso": RecruitingPermission.ACCESSO_ADMIN,
            "recruiting_accesso": RecruitingPermission.ACCESSO_ADMIN,
        })
        from .models import AnagraficaStatPermission

        self.assertEqual(
            AnagraficaStatPermission.get_instance().accesso,
            AnagraficaStatPermission.ACCESSO_TUTTI,
        )


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

    def test_form_nuovo_candidato_si_rende_col_form_kit(self):
        """Le pagine usano il form-kit canonico `hub-`, non un namespace ad-hoc."""
        resp = self.client.get(reverse("anagrafica:recruiting_create"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "hub-form-grid")
        self.assertContains(resp, "hub-field")
        self.assertContains(resp, "rcr-scale")          # scala 1-5, componente proprio
        self.assertNotContains(resp, "rcr-form")        # namespace duplicato rimosso

    def test_form_modifica_preseleziona_i_voti(self):
        candidato = Candidato.objects.create(cognome="Preself", nome="T")
        recruiting_service.salva_punteggi(candidato, {self.criteri["sintonia"].id: 4})
        resp = self.client.get(reverse("anagrafica:recruiting_edit", args=[candidato.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(
            resp, f'id="crit{self.criteri["sintonia"].id}-4"', msg_prefix="radio del voto assente",
        )
        self.assertContains(resp, "checked")

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
