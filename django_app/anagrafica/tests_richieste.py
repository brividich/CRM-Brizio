"""Richieste su mansioni e competenze: chi chiede, chi approva, che cosa cambia in skill matrix.

Scenario di ``tests_esplora_struttura``: rossi in IN1 con la mansione «Fresa F1» a livello U,
bianchi in IN2. Qui bianchi è il responsabile di rossi, neri ha il ruolo RDD, verdi il ruolo MSO.
"""
from __future__ import annotations

from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.urls import reverse

from .models import AbilitazioneMacchina, DipendenteRuoloOperativo, RuoloOperativo, SubnavLinkAnagrafica
from .models_richieste import RichiestaCompetenze as R
from .models_richieste import RichiestaEvento
from .services import richieste as svc
from .tests_esplora_struttura import _Base

User = get_user_model()


class _Scenario(_Base):
    def setUp(self):
        super().setUp()
        cache.clear()
        for sigla, nome, chi in (("RDD", "Management Representative", self.neri),
                                 ("MSO", "Management System Officer", self.verdi)):
            ruolo = RuoloOperativo.objects.create(nome=nome, sigla=sigla)
            DipendenteRuoloOperativo.objects.create(legacy_anagrafica_id=chi, ruolo=ruolo)
        self.capo = self._attore("rq_capo", self.bianchi, team={self.rossi})
        self.rdd = self._attore("rq_rdd", self.neri, sigle={"RDD"})
        self.mso = self._attore("rq_mso", self.verdi, sigle={"MSO"})
        self.hr = self._attore("rq_hr", None, gestione=True)
        self.estraneo = self._attore("rq_altro", self.gialli)
        self.torno = self._crea_mansione("Tornio T9", self.in1, self.op)

    def _attore(self, username, legacy_id, **extra):
        from django.utils import timezone

        from core.models import UserOnboarding

        user = User.objects.create_user(username, password="x")
        # Primo accesso già fatto: altrimenti il middleware rimanda alla pagina di benvenuto.
        UserOnboarding.objects.update_or_create(user=user, defaults={"completed": True, "completed_at": timezone.now()})
        return svc.Attore(user=user, legacy_id=legacy_id, nome=username, **extra)

    def _ram(self, attore=None, **extra):
        dati = dict(tipo=R.TIPO_AGGIUNTA, persona_id=self.rossi, mansione_id=self.torno.pk, livello="U")
        dati.update(extra)
        return svc.crea(attore or self.capo, **dati)


class CreareTests(_Scenario):
    def test_il_responsabile_chiede_una_mansione_per_il_suo_team(self):
        r = self._ram(motivazione="Secondo turno")
        self.assertRegex(r.codice, r"^RAM-\d{4}-0001$")
        self.assertEqual((r.stato, r.livello, r.richiedente_nome), (R.STATO_IN_APPROVAZIONE, "U", "rq_capo"))
        self.assertEqual(self._ram(mansione_id=self.fresa.pk, livello="O").codice[-4:], "0002")
        self.assertEqual([e.azione for e in r.eventi.all()], ["Richiesta creata"])

    def test_la_competenza_ha_la_sua_numerazione(self):
        r = svc.crea(self.capo, tipo=R.TIPO_COMPETENZA, persona_id=self.rossi, competenza_id=self.catalogo.pk, livello="U")
        self.assertRegex(r.codice, r"^RAC-\d{4}-0001$")
        self.assertEqual(svc.sigla_approva(r), "MSO")

    def test_chi_puo_chiedere_che_cosa(self):
        self.assertEqual(svc.tipi_ammessi(self.capo, self.rossi), [R.TIPO_AGGIUNTA, R.TIPO_SOSPENSIONE, R.TIPO_RIMOZIONE,
                                                                 R.TIPO_COMPETENZA])
        self.assertEqual(svc.tipi_ammessi(self.capo, self.verdi), [])            # non è del suo team
        self.assertEqual(svc.tipi_ammessi(self.hr, self.rossi), [R.TIPO_AGGIUNTA, R.TIPO_COMPETENZA])
        self.assertEqual(svc.tipi_ammessi(self.mso, self.rossi), [R.TIPO_SOSPENSIONE, R.TIPO_RIMOZIONE, R.TIPO_COMPETENZA])
        self.assertEqual(svc.tipi_ammessi(self.estraneo, self.rossi), [])
        with self.assertRaisesMessage(svc.RichiestaNonValida, "Non puoi aprire"):
            self._ram(self.estraneo)
        with self.assertRaisesMessage(svc.RichiestaNonValida, "Non puoi aprire"):
            self._ram(self.hr, tipo=R.TIPO_SOSPENSIONE, mansione_id=self.fresa.pk, motivazione="x")

    def test_controlli_sui_dati(self):
        with self.assertRaisesMessage(svc.RichiestaNonValida, "ha già la mansione a livello U"):
            self._ram(mansione_id=self.fresa.pk, livello="U")
        with self.assertRaisesMessage(svc.RichiestaNonValida, "livello da raggiungere"):
            self._ram(livello="")
        with self.assertRaisesMessage(svc.RichiestaNonValida, "non ha questa mansione"):
            self._ram(tipo=R.TIPO_SOSPENSIONE, motivazione="fuori reparto")
        with self.assertRaisesMessage(svc.RichiestaNonValida, "serve la motivazione"):
            self._ram(tipo=R.TIPO_RIMOZIONE, mansione_id=self.fresa.pk)
        with self.assertRaisesMessage(svc.RichiestaNonValida, "Scegli la persona"):
            self._ram(persona_id=987654)
        self._ram()
        with self.assertRaisesMessage(svc.RichiestaNonValida, "già una richiesta aperta uguale"):
            self._ram()


class DecidereTests(_Scenario):
    def test_approva_solo_chi_ha_il_ruolo_e_mai_la_propria(self):
        r = self._ram()
        self.assertIn("ruolo RDD", svc.motivo_non_decide(self.mso, r))
        self.assertIn("ruolo RDD", svc.motivo_non_decide(self.hr, r))
        self.assertEqual(svc.motivo_non_decide(self.rdd, r), "")
        sua = svc.crea(self.mso, tipo=R.TIPO_COMPETENZA, persona_id=self.rossi, competenza_id=self.catalogo.pk, livello="U")
        self.assertIn("propria richiesta", svc.motivo_non_decide(self.mso, sua))
        with self.assertRaises(svc.RichiestaNonValida):
            svc.decidi(self.mso, sua, approva=True)

    def test_assegnazione_approvata_mette_la_persona_in_formazione(self):
        r = svc.decidi(self.rdd, self._ram(), approva=True, nota="ok")
        self.assertEqual((r.stato, r.deciso_da_nome), (R.STATO_APPROVATA, "rq_rdd"))
        ab = svc.abilitazione(self.torno, self.rossi)
        self.assertEqual((ab.livello, ab.in_lista), ("I", True))
        self.assertIn("Skill matrix: mansione in formazione", [e.azione for e in r.eventi.all()])
        self.assertEqual(svc.tocca_a(r), "Qualità o HR: aprire la sessione formativa")
        with self.assertRaisesMessage(svc.RichiestaNonValida, "non è più in approvazione"):
            svc.decidi(self.rdd, r, approva=True)

    def test_chi_ha_gia_la_mansione_non_viene_abbassato(self):
        r = svc.decidi(self.rdd, self._ram(mansione_id=self.fresa.pk, livello="O"), approva=True)
        self.assertEqual(r.stato, R.STATO_APPROVATA)
        self.assertEqual(svc.abilitazione(self.fresa, self.rossi).livello, "U")

    def test_sospensione_e_rimozione_aggiornano_subito_la_skill_matrix(self):
        r = svc.decidi(self.rdd, self._ram(tipo=R.TIPO_SOSPENSIONE, mansione_id=self.fresa.pk, motivazione="fuori reparto"),
                       approva=True)
        self.assertEqual(r.stato, R.STATO_EVASA)
        self.assertEqual(svc.abilitazione(self.fresa, self.rossi).stato, AbilitazioneMacchina.STATO_SOSPESA)
        r = svc.decidi(self.rdd, self._ram(tipo=R.TIPO_RIMOZIONE, mansione_id=self.fresa.pk, motivazione="non conformità"),
                       approva=True)
        self.assertEqual(r.stato, R.STATO_EVASA)
        self.assertIsNone(svc.abilitazione(self.fresa, self.rossi))
        self.assertEqual(svc.passi(r)[-1], {"nome": "Skill matrix aggiornata", "sotto": "Senza sessione formativa",
                                            "stato": "fatto"})

    def test_respingere_richiede_il_motivo_e_non_tocca_la_skill_matrix(self):
        r = self._ram()
        with self.assertRaisesMessage(svc.RichiestaNonValida, "scrivi il motivo"):
            svc.decidi(self.rdd, r, approva=False)
        r = svc.decidi(self.rdd, r, approva=False, nota="organico al completo")
        self.assertEqual((r.stato, r.nota_decisione), (R.STATO_RESPINTA, "organico al completo"))
        self.assertIsNone(svc.abilitazione(self.torno, self.rossi))
        self.assertEqual(svc.passi(r)[1]["stato"], "respinta")

    def test_il_registro_e_di_sola_aggiunta(self):
        evento = self._ram().eventi.first()
        evento.nota = "ritoccata"
        with self.assertRaises(ValueError):
            evento.save()
        with self.assertRaises(ValueError):
            evento.delete()
        self.assertEqual(RichiestaEvento.objects.count(), 1)


class VedereTests(_Scenario):
    def test_ognuno_vede_il_suo(self):
        r = self._ram()
        altra = svc.crea(self.mso, tipo=R.TIPO_COMPETENZA, persona_id=self.bianchi, competenza_id=self.catalogo.pk, livello="U")
        self.assertEqual(set(svc.visibili(self.hr)), {r, altra})
        self.assertEqual(set(svc.visibili(self.capo)), {r, altra})      # la sua richiesta e quella che lo riguarda
        self.assertEqual(set(svc.visibili(self.rdd)), {r})
        self.assertEqual(set(svc.visibili(self.estraneo)), set())
        self.assertFalse(svc.puo_vedere(self.estraneo, r))
        self.assertTrue(svc.puo_vedere(self._attore("rq_lui", self.rossi), r))

    def test_da_fare_dice_a_chi_tocca(self):
        r = self._ram()
        self.assertEqual([x["richiesta"] for x in svc.da_fare(self.rdd)["da_approvare"]], [r])
        self.assertEqual(svc.da_fare(self.mso)["da_approvare"], [])
        in_attesa = svc.da_fare(self.capo)["in_attesa"]
        self.assertEqual([(x["richiesta"], x["tocca_a"]) for x in in_attesa], [(r, "RDD: approvare")])
        svc.decidi(self.rdd, r, approva=False, nota="no")
        self.assertEqual(svc.da_fare(self.capo)["in_attesa"], [])

    def test_fabbisogno_confronta_richiesto_e_oggi(self):
        r = self._ram(mansione_id=self.fresa.pk, livello="O")
        riga = svc.fabbisogno(r)[0]
        self.assertEqual((riga["nome"], riga["richiesto"]["codice"], riga["oggi"], riga["presente"]),
                         ("Set-up F1", "U", None, False))


class PagineTests(_Scenario):
    def _come(self, attore):
        self.client.force_login(attore.user)
        return mock.patch("anagrafica.views_richieste.svc.attore", return_value=attore)

    def test_il_giro_completo_dalle_pagine(self):
        with self._come(self.capo):
            r = self.client.get(reverse("anagrafica:richiesta_nuova"), {"persona": self.rossi})
            self.assertContains(r, "Invia la richiesta")
            self.assertNotContains(r, "{#")
            r = self.client.post(reverse("anagrafica:richiesta_nuova"), {
                "tipo": R.TIPO_AGGIUNTA, "persona": self.rossi, "mansione": self.torno.pk, "livello": "U",
                "motivazione": "Secondo turno"})
            richiesta = R.objects.get()
            self.assertRedirects(r, reverse("anagrafica:richiesta", args=[richiesta.pk]))
            pagina = self.client.get(reverse("anagrafica:richiesta", args=[richiesta.pk]))
            self.assertContains(pagina, "<dt>Tipo di richiesta:</dt>")
            self.assertContains(pagina, "Tocca a RDD")
            self.assertNotContains(pagina, 'value="approva"')
            self.assertContains(self.client.get(reverse("anagrafica:richieste_da_fare")), richiesta.codice)
        with self._come(self.rdd):
            self.assertContains(self.client.get(reverse("anagrafica:richieste_da_fare")), "Da approvare · 1")
            pagina = self.client.get(reverse("anagrafica:richiesta", args=[richiesta.pk]))
            self.assertContains(pagina, 'value="approva"')
            r = self.client.post(reverse("anagrafica:richiesta_decidi", args=[richiesta.pk]), {"azione": "approva"})
            self.assertRedirects(r, reverse("anagrafica:richiesta", args=[richiesta.pk]))
        richiesta.refresh_from_db()
        self.assertEqual(richiesta.stato, R.STATO_APPROVATA)
        with self._come(self.hr):
            self.assertContains(self.client.get(reverse("anagrafica:richieste"), {"stato": "approvata"}), richiesta.codice)

    def test_errore_di_compilazione_torna_sul_modulo(self):
        with self._come(self.capo):
            r = self.client.post(reverse("anagrafica:richiesta_nuova"), {
                "tipo": R.TIPO_SOSPENSIONE, "persona": self.rossi, "mansione": self.fresa.pk})
        self.assertContains(r, "serve la motivazione")
        self.assertFalse(R.objects.exists())

    def test_chi_non_c_entra_non_vede_e_non_decide(self):
        richiesta = self._ram()
        with self._come(self.estraneo):
            self.assertEqual(self.client.get(reverse("anagrafica:richiesta", args=[richiesta.pk])).status_code, 404)
            self.assertEqual(self.client.post(reverse("anagrafica:richiesta_decidi", args=[richiesta.pk]),
                                              {"azione": "approva"}).status_code, 404)
            self.assertRedirects(self.client.get(reverse("anagrafica:richiesta_nuova")),
                                 reverse("anagrafica:richieste_da_fare"))
        with self._come(self.capo):
            self.client.post(reverse("anagrafica:richiesta_decidi", args=[richiesta.pk]), {"azione": "approva"})
        richiesta.refresh_from_db()
        self.assertEqual(richiesta.stato, R.STATO_IN_APPROVAZIONE)

    def test_voci_di_menu(self):
        voci = dict(SubnavLinkAnagrafica.objects.filter(gruppo="Richieste").values_list("url_value", "etichetta"))
        self.assertEqual(voci, {"anagrafica:richieste_da_fare": "Da fare", "anagrafica:richieste": "Richieste"})
