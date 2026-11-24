"""Sessioni formative: dalla richiesta approvata alla chiusura firmata (specifica della Qualità v1.0)."""
from __future__ import annotations

from datetime import timedelta
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from django.utils import timezone

from .models import (
    AbilitazioneMacchina,
    AbilitazioneMacchinaVoce,
    CompetenzaCatalogo,
    ValutazioneCompetenzaStorico,
    VoceMacchinaCatalogo,
)
from .models_richieste import RichiestaCompetenze as R
from .models_sessioni import SessioneEvento, SessioneFormativa as S, SessioneRiga as Riga
from .services import richieste as rq
from .services import sessioni as svc
from .tests_richieste import _Scenario as _ScenarioRichieste


def _pdf(nome="mod040.pdf"):
    return SimpleUploadedFile(nome, b"%PDF-1.4 prova sintetica", content_type="application/pdf")


@override_settings(MEDIA_ROOT="C:/Dev/.pn-testdb/media_sessioni")
class _Scenario(_ScenarioRichieste):
    def setUp(self):
        super().setUp()
        self.disegno = CompetenzaCatalogo.objects.create(nome="Lettura disegno", chiave="lettura disegno")
        self.v_setup = VoceMacchinaCatalogo.objects.create(codice="T9-1", nome="Set-up T9", mansione=self.torno,
                                                           catalogo=self.catalogo, livello_minimo="U", ordine=1)
        self.v_disegno = VoceMacchinaCatalogo.objects.create(codice="T9-2", nome="Lettura disegno", mansione=self.torno,
                                                             catalogo=self.disegno, livello_minimo="L", ordine=2)
        self.v_misure = VoceMacchinaCatalogo.objects.create(codice="T9-3", nome="Misure", mansione=self.torno,
                                                            livello_minimo="U", ordine=3)
        # Rossi sa già fare il set-up a livello U sulla fresa: sul tornio entra «già presente».
        ab_fresa = AbilitazioneMacchina.objects.get(legacy_anagrafica_id=self.rossi, competenza=self.fresa)
        AbilitazioneMacchinaVoce.objects.create(abilitazione=ab_fresa, voce=self.voce, livello="U")
        self.persona = self._attore("rq_rossi", self.rossi)

    def _approvata(self, **extra):
        r = self._ram(**extra)
        return rq.decidi(self.rdd, r, approva=True)

    def _aperta(self, **extra):
        return svc.apri(self.hr, self._approvata(**extra))

    def _riga(self, s, voce):
        return s.righe.get(voce=voce)

    def _valuta_tutto(self, s, attore=None):
        attore = attore or self.capo
        oggi = timezone.localdate()
        svc.valuta(attore, self._riga(s, self.v_disegno), modalita="P", livello="L",
                   descrizione="Disegni letti in prova pratica", data_verifica=oggi)
        svc.valuta(attore, self._riga(s, self.v_misure), modalita="A", livello="U", tutor_nome="Tutor di prova",
                   dal=oggi - timedelta(days=10), al=oggi, ore="16", registro=_pdf())


class AprireTests(_Scenario):
    def test_apre_solo_qualita_o_hr_su_richiesta_approvata(self):
        richiesta = self._ram()
        self.assertIn("approvata", svc.motivo_non_apre(self.hr, richiesta))
        richiesta = rq.decidi(self.rdd, richiesta, approva=True)
        self.assertIn("Qualità o HR", svc.motivo_non_apre(self.capo, richiesta))
        s = svc.apri(self.hr, richiesta)
        self.assertRegex(s.codice, r"^SF-\d{4}-0001$")
        self.assertIn("già aperta", svc.motivo_non_apre(self.hr, richiesta))
        with self.assertRaises(svc.SessioneNonValida):
            svc.apri(self.hr, richiesta)

    def test_righe_dalle_competenze_della_mansione_e_gia_presenti(self):
        s = self._aperta()
        righe = {r.competenza_nome: r for r in s.righe.all()}
        self.assertEqual(list(righe), ["Set-up T9", "Lettura disegno", "Misure"])
        self.assertEqual((righe["Set-up T9"].stato, righe["Set-up T9"].livello_oggi), (Riga.STATO_GIA_PRESENTE, "U"))
        self.assertEqual(righe["Lettura disegno"].livello_richiesto, "L")
        self.assertEqual(righe["Misure"].stato, Riga.STATO_DA_ASSEGNARE)
        self.assertEqual(righe["Misure"].area, self.in1)
        self.assertEqual(svc.tocca_a(s), "Responsabile: valutare 2 competenze")

    def test_sospensione_non_ha_sessione(self):
        r = self._ram(tipo=R.TIPO_SOSPENSIONE, mansione_id=self.fresa.pk, livello="", motivazione="Fuori reparto")
        r = rq.decidi(self.rdd, r, approva=True)
        self.assertIn("non hanno sessione", svc.motivo_non_apre(self.hr, r))


class ValutareTests(_Scenario):
    def test_valuta_il_responsabile_e_servono_le_evidenze(self):
        s = self._aperta()
        riga = self._riga(s, self.v_misure)
        self.assertIn("responsabile", svc.motivo_non_valuta(self.estraneo, riga))
        with self.assertRaisesMessage(svc.SessioneNonValida, "registro MOD.040"):
            svc.valuta(self.capo, riga, modalita="A", livello="U", tutor_nome="Tutor", dal=timezone.localdate(), ore="8")
        with self.assertRaisesMessage(svc.SessioneNonValida, "verifica"):
            svc.valuta(self.capo, riga, modalita="C", livello="U", docente_ente="Ente di prova")
        riga = svc.valuta(self.capo, riga, modalita="C")
        self.assertEqual(riga.stato, Riga.STATO_IN_ACQUISIZIONE)
        s.refresh_from_db()
        self.assertEqual(s.stato, S.STATO_IN_CORSO)
        riga = svc.valuta(self.capo, riga, modalita="C", livello="L", docente_ente="Ente di prova", verifica="test")
        self.assertEqual(riga.stato, Riga.STATO_IN_ACQUISIZIONE)  # L non basta: serve U
        riga = svc.valuta(self.capo, riga, modalita="C", livello="U", docente_ente="Ente di prova", verifica="test")
        self.assertEqual((riga.stato, riga.livello_raggiunto), (Riga.STATO_POSITIVA, "U"))

    def test_la_modalita_cambia_solo_verso_corso_e_resta_scritto(self):
        s = self._aperta()
        riga = svc.valuta(self.capo, self._riga(s, self.v_misure), modalita="P")
        with self.assertRaisesMessage(svc.SessioneNonValida, "solo verso «Corso»"):
            svc.valuta(self.capo, riga, modalita="A")
        with self.assertRaisesMessage(svc.SessioneNonValida, "conferma il cambio"):
            svc.valuta(self.capo, riga, modalita="C")
        svc.valuta(self.capo, riga, modalita="C", conferma_cambio=True, nota="Serve il corso")
        ev = SessioneEvento.objects.get(sessione=s, azione="Modalità cambiata")
        self.assertEqual((ev.prima, ev.dopo, ev.nota), ("P", "C", "Serve il corso"))

    def test_gia_presente_non_si_rivaluta(self):
        s = self._aperta()
        self.assertIn("già presente", svc.motivo_non_valuta(self.capo, self._riga(s, self.v_setup)))


class FirmareEChiudereTests(_Scenario):
    def test_giro_completo_aggiorna_skill_matrix_e_richiesta(self):
        s = self._aperta()
        self.assertIn("Mancano 2", svc.motivo_non_firma_approvatore(self.rdd, s))
        self._valuta_tutto(s)
        self.assertIn("RDD", svc.motivo_non_firma_approvatore(self.mso, s))
        with self.assertRaisesMessage(svc.SessioneNonValida, "MOD.040"):
            svc.firma_approvatore(self.rdd, s)
        self.assertIn("Prima firma", svc.motivo_non_firma_persona(self.persona, s, su_carta=False))
        s = svc.firma_approvatore(self.rdd, s, visto_mod040=True)
        self.assertIn("solo la persona", svc.motivo_non_firma_persona(self.capo, s, su_carta=False))
        s = svc.firma_persona(self.persona, s)
        self.assertIn("Qualità o HR", svc.motivo_non_chiude(self.capo, s))
        svc.chiudi(self.hr, s)

        s.refresh_from_db()
        self.assertEqual(s.stato, S.STATO_POSITIVA)
        richiesta = s.richiesta
        richiesta.refresh_from_db()
        self.assertEqual(richiesta.stato, R.STATO_EVASA)
        ab = rq.abilitazione(self.torno, self.rossi)
        self.assertEqual(ab.livello, "U")  # da I (in formazione) al livello chiesto
        livelli = {v.voce_id: v.livello for v in ab.voci.all()}
        self.assertEqual((livelli[self.v_disegno.pk], livelli[self.v_misure.pk]), ("L", "U"))
        self.assertTrue(ValutazioneCompetenzaStorico.objects.filter(legacy_anagrafica_id=self.rossi, voce=self.v_misure,
                                                                    livello="U").exists())
        self.assertEqual(svc.tocca_a(s), "")

    def test_firma_su_carta_e_chiusura_negativa(self):
        s = self._aperta()
        self._valuta_tutto(s)
        s = svc.firma_approvatore(self.rdd, s, visto_mod040=True)
        self.assertIn("Qualità o HR", svc.motivo_non_firma_persona(self.capo, s, su_carta=True))
        with self.assertRaisesMessage(svc.SessioneNonValida, "futuro"):
            svc.firma_persona(self.hr, s, su_carta=True, data_firma=timezone.localdate() + timedelta(days=1))
        svc.firma_persona(self.hr, s, su_carta=True, data_firma=timezone.localdate(), file=_pdf("firma.pdf"))
        self.assertEqual(s.partecipanti.get().firma_modo, "carta")

        altra = self._aperta(mansione_id=self.fresa.pk, livello="O")
        with self.assertRaisesMessage(svc.SessioneNonValida, "motivo"):
            svc.chiudi_negativa(self.hr, altra, motivo="")
        svc.chiudi_negativa(self.hr, altra, motivo="Contratto non confermato")
        altra.refresh_from_db()
        self.assertEqual((altra.stato, altra.richiesta.stato), (S.STATO_NEGATIVA, R.STATO_EVASA))
        self.assertEqual(rq.abilitazione(self.fresa, self.rossi).livello, "U")  # la skill matrix non cambia

    def test_richiesta_di_competenza(self):
        r = self._ram(tipo=R.TIPO_COMPETENZA, mansione_id=None, competenza_id=self.disegno.pk, livello="U")
        r = rq.decidi(self.mso, r, approva=True)
        s = svc.apri(self.hr, r)
        riga = s.righe.get()
        self.assertEqual((riga.catalogo, riga.livello_richiesto), (self.disegno, "U"))
        svc.valuta(self.capo, riga, modalita="C", livello="U", docente_ente="Ente di prova", verifica="attestato")
        self.assertIn("MSO", svc.motivo_non_firma_approvatore(self.rdd, s))
        svc.firma_approvatore(self.mso, s)
        s = svc.firma_persona(self.persona, s)
        svc.chiudi(self.hr, s)
        self.assertTrue(ValutazioneCompetenzaStorico.objects.filter(legacy_anagrafica_id=self.rossi, catalogo=self.disegno,
                                                                    livello="U").exists())

    def test_registro_di_sola_aggiunta(self):
        s = self._aperta()
        ev = s.eventi.first()
        with self.assertRaises(ValueError):
            ev.save()
        with self.assertRaises(ValueError):
            ev.delete()


class DaFareTests(_Scenario):
    def test_ognuno_vede_il_suo_passo(self):
        richiesta = self._approvata()
        self.assertEqual([x["richiesta"] for x in svc.da_fare(self.hr)["da_aprire"]], [richiesta])
        s = svc.apri(self.hr, richiesta)
        self.assertEqual([x["sessione"] for x in svc.da_fare(self.capo)["da_valutare"]], [s])
        self._valuta_tutto(s)
        self.assertEqual([x["sessione"] for x in svc.da_fare(self.rdd)["da_firmare"]], [s])
        s = svc.firma_approvatore(self.rdd, s, visto_mod040=True)
        self.assertEqual([x["sessione"] for x in svc.da_fare(self.persona)["da_firmare_io"]], [s])
        s = svc.firma_persona(self.persona, s)
        self.assertEqual([x["sessione"] for x in svc.da_fare(self.hr)["da_chiudere"]], [s])


class PagineTests(_Scenario):
    def _come(self, attore):
        self.client.force_login(attore.user)
        return mock.patch("anagrafica.services.richieste.attore", return_value=attore)

    def test_giro_completo_dalle_pagine(self):
        richiesta = self._approvata()
        with self._come(self.hr):
            pagina = self.client.get(reverse("anagrafica:richiesta", args=[richiesta.pk]))
            self.assertContains(pagina, "Apri la sessione formativa")
            r = self.client.post(reverse("anagrafica:sessione_apri", args=[richiesta.pk]))
            s = S.objects.get(richiesta=richiesta)
            self.assertRedirects(r, reverse("anagrafica:sessione", args=[s.pk]))
            elenco = self.client.get(reverse("anagrafica:sessioni"))
            self.assertContains(elenco, s.codice)
            self.assertContains(elenco, "<template data-sc-modello>", count=1)
            self.assertNotContains(elenco, "{#")
        with self._come(self.capo):
            pagina = self.client.get(reverse("anagrafica:sessione", args=[s.pk]))
            self.assertContains(pagina, "Tocca a: Responsabile: valutare 2 competenze")
            self.assertContains(pagina, 'data-sf-valuta="', count=2)
            self.assertNotContains(pagina, "{#")
            riga = self._riga(s, self.v_misure)
            r = self.client.post(reverse("anagrafica:sessione_valuta", args=[riga.pk]), {
                "modalita": "A", "livello": "U", "tutor_nome": "Tutor di prova", "dal": "2026-11-01",
                "al": "2026-11-20", "ore": "16", "registro_mod040": _pdf()})
            self.assertRedirects(r, reverse("anagrafica:sessione", args=[s.pk]))
            riga.refresh_from_db()
            self.assertEqual((riga.stato, riga.ore), (Riga.STATO_POSITIVA, 16))
            self.assertEqual(self.client.get(reverse("anagrafica:sessione_file_riga", args=[s.pk, "mod040", riga.pk])).status_code, 200)
            svc.valuta(self.capo, self._riga(s, self.v_disegno), modalita="C", livello="L", docente_ente="Ente",
                       verifica="conferma")
        with self._come(self.rdd):
            r = self.client.post(reverse("anagrafica:sessione_firma", args=[s.pk]), {"visto_mod040": "1"})
            self.assertRedirects(r, reverse("anagrafica:sessione", args=[s.pk]))
        with self._come(self.persona):
            self.client.post(reverse("anagrafica:sessione_firma_persona", args=[s.pk]), {"modo": "portale"})
        with self._come(self.hr):
            self.client.post(reverse("anagrafica:sessione_chiudi", args=[s.pk]))
        s.refresh_from_db()
        self.assertEqual(s.stato, S.STATO_POSITIVA)
        self.assertEqual(rq.abilitazione(self.torno, self.rossi).livello, "U")

    def test_chi_non_c_entra_non_vede_e_i_file_sono_protetti(self):
        s = self._aperta()
        with self._come(self.estraneo):
            self.assertEqual(self.client.get(reverse("anagrafica:sessione", args=[s.pk])).status_code, 404)
            self.assertEqual(self.client.post(reverse("anagrafica:sessione_chiudi", args=[s.pk])).status_code, 404)
            self.assertEqual(self.client.get(reverse("anagrafica:sessione_file", args=[s.pk, "firma"])).status_code, 404)
            self.assertNotContains(self.client.get(reverse("anagrafica:sessioni")), s.codice)
        with self._come(self.capo):
            r = self.client.post(reverse("anagrafica:sessione_valuta", args=[self._riga(s, self.v_misure).pk]),
                                 {"modalita": "A", "registro_mod040": SimpleUploadedFile("x.exe", b"MZ")}, follow=True)
            self.assertContains(r, "PDF o un&#x27;immagine")

    def test_voci_di_menu_in_organizzazione_e_formazione(self):
        from .models import SubnavLinkAnagrafica

        voci = SubnavLinkAnagrafica.objects.filter(url_value="anagrafica:sessioni", is_active=True)
        # Accanto a «Richieste» in Organizzazione e accanto alle edizioni dei corsi in Formazione.
        posti = {(v.categoria_id, v.gruppo) for v in voci}
        for vicina in ("anagrafica:richieste", "anagrafica:formazione_sessioni_list"):
            accanto = SubnavLinkAnagrafica.objects.filter(url_value=vicina).first()
            if accanto is not None:
                self.assertIn((accanto.categoria_id, accanto.gruppo), posti)
        self.assertTrue(voci.exists())
        # In Organizzazione «Sessioni formative»; in Formazione «Formazione su mansioni», accanto a «Sessioni» dei corsi.
        etichette = {(v.categoria_id, v.gruppo): v.etichetta for v in voci}
        richieste = SubnavLinkAnagrafica.objects.filter(url_value="anagrafica:richieste").first()
        corsi = SubnavLinkAnagrafica.objects.filter(url_value="anagrafica:formazione_sessioni_list").first()
        if richieste is not None:
            self.assertEqual(etichette[(richieste.categoria_id, richieste.gruppo)], "Sessioni formative")
        if corsi is not None:
            self.assertEqual(etichette[(corsi.categoria_id, corsi.gruppo)], "Formazione su mansioni")


    def test_da_fare_e_dashboard_mostrano_le_sessioni(self):
        richiesta = self._approvata()
        with self._come(self.hr):
            pagina = self.client.get(reverse("anagrafica:richieste_da_fare"))
            self.assertContains(pagina, "Sessioni da aprire · 1")
            righe = self.client.get(reverse("anagrafica:index")).context["cose_da_gestire"]
            self.assertIn("Sessioni formative da aprire", [x["titolo"] for x in righe])
        s = svc.apri(self.hr, richiesta)
        with self._come(self.capo):
            self.assertContains(self.client.get(reverse("anagrafica:richieste_da_fare")), "Competenze da valutare · 1")
            self.assertContains(self.client.get(reverse("anagrafica:richiesta", args=[richiesta.pk])), s.codice)



class GruppoEStampeTests(_Scenario):
    def _gruppo(self):
        r = rq.crea(self.hr, tipo=R.TIPO_COMPETENZA, persona_id=self.rossi, competenza_id=self.disegno.pk, livello="U",
                    altre_persone=[self.bianchi, self.rossi])
        return rq.decidi(self.mso, r, approva=True)

    def test_richiesta_di_competenza_su_piu_persone(self):
        r = self._gruppo()
        self.assertEqual(r.persone_ids, [self.rossi, self.bianchi])
        self.assertIn("e un'altra persona", rq.righe([r])[0]["persona"])
        with self.assertRaisesMessage(rq.RichiestaNonValida, "già una richiesta aperta uguale"):
            rq.crea(self.hr, tipo=R.TIPO_COMPETENZA, persona_id=self.verdi, competenza_id=self.disegno.pk, livello="U",
                    altre_persone=[self.bianchi])
        with self.assertRaisesMessage(rq.RichiestaNonValida, "solo per una richiesta di competenza"):
            rq.crea(self.hr, tipo=R.TIPO_AGGIUNTA, persona_id=self.rossi, mansione_id=self.fresa.pk, livello="O",
                    altre_persone=[self.bianchi])
        # Il responsabile di Rossi vede la richiesta anche se nel gruppo c'è chi non è del suo team.
        self.assertTrue(rq.puo_vedere(self.capo, r))
        s = svc.apri(self.hr, r)
        self.assertEqual(sorted(s.righe.values_list("legacy_anagrafica_id", flat=True)), sorted([self.rossi, self.bianchi]))
        for riga in s.righe.all():
            svc.valuta(self.hr, riga, modalita="C", livello="U", docente_ente="Ente di prova", verifica="test")
        s = svc.firma_approvatore(self.mso, s)
        s = svc.firma_persona(self.persona, s)
        self.assertEqual(svc.tocca_a(s), "Le persone: firmare (1 di 2)")
        self.assertIn("Manca la firma", svc.motivo_non_chiude(self.hr, s))
        svc.firma_persona(self.hr, s, su_carta=True, data_firma=timezone.localdate(), persona_id=self.bianchi)
        svc.chiudi(self.hr, s)
        for pid in (self.rossi, self.bianchi):
            self.assertTrue(ValutazioneCompetenzaStorico.objects.filter(legacy_anagrafica_id=pid, catalogo=self.disegno,
                                                                        livello="U").exists())

    def test_pdf_della_sessione_e_storico_della_persona(self):
        s = self._aperta()
        self._valuta_tutto(s)
        with mock.patch("anagrafica.services.richieste.attore", return_value=self.capo):
            self.client.force_login(self.capo.user)
            r = self.client.get(reverse("anagrafica:sessione_pdf", args=[s.pk]))
            self.assertEqual((r.status_code, r["Content-Type"]), (200, "application/pdf"))
            self.assertTrue(r.content.startswith(b"%PDF"))
            r = self.client.get(reverse("anagrafica:storico_competenze_pdf", args=[self.rossi]))
            self.assertEqual(r.status_code, 200)
            self.assertTrue(r.content.startswith(b"%PDF"))
            # Fuori dal team del capo: niente storico.
            self.assertEqual(self.client.get(reverse("anagrafica:storico_competenze_pdf", args=[self.gialli])).status_code, 404)
        with mock.patch("anagrafica.services.richieste.attore", return_value=self.estraneo):
            self.client.force_login(self.estraneo.user)
            self.assertEqual(self.client.get(reverse("anagrafica:sessione_pdf", args=[s.pk])).status_code, 404)

    def test_corso_da_una_edizione_a_cui_la_persona_e_iscritta(self):
        from datetime import date

        from .models import TrainingCourse, TrainingEnrollment, TrainingPlan, TrainingSession

        piano = TrainingPlan.objects.create(codice="PSF1", nome="Piano di prova")
        corso = TrainingCourse.objects.create(piano=piano, codice="CRS-PROVA", titolo="Lettura disegno di prova",
                                              durata_ore_teorica=4)
        edizione = TrainingSession.objects.create(corso=corso, codice_sessione="ED-PROVA-1", data_inizio=date(2026, 10, 1),
                                                  data_fine=date(2026, 10, 2))
        TrainingEnrollment.objects.create(sessione=edizione, legacy_anagrafica_id=self.rossi, stato="COMPLETATO", idoneo=True)
        self.assertEqual([e["id"] for e in svc.edizioni_persona(self.rossi)], [edizione.pk])
        s = self._aperta()
        riga = svc.valuta(self.capo, self._riga(s, self.v_disegno), modalita="C", livello="L", edizione_id=edizione.pk)
        self.assertEqual((riga.corso, riga.edizione, riga.verifica, riga.stato),
                         (corso, edizione, Riga.VERIFICA_ATTESTATO, Riga.STATO_POSITIVA))
        altra = TrainingSession.objects.create(corso=corso, codice_sessione="ED-PROVA-2", data_inizio=date(2026, 11, 1),
                                               data_fine=date(2026, 11, 1))
        with self.assertRaisesMessage(svc.SessioneNonValida, "non è iscritta"):
            svc.valuta(self.capo, self._riga(s, self.v_misure), modalita="C", livello="U", edizione_id=altra.pk)

    def test_avviso_a_chi_firma_quando_tutto_e_valutato(self):
        s = self._aperta()
        oggi = timezone.localdate()
        svc.valuta(self.capo, self._riga(s, self.v_disegno), modalita="P", livello="L", descrizione="Prova", data_verifica=oggi)
        with mock.patch("anagrafica.services.richieste.attore", return_value=self.capo),                 mock.patch("anagrafica.views_sessioni._notifica") as avviso:
            self.client.force_login(self.capo.user)
            self.client.post(reverse("anagrafica:sessione_valuta", args=[self._riga(s, self.v_misure).pk]), {
                "modalita": "C", "livello": "U", "docente_ente": "Ente", "verifica": "conferma"})
        destinatari = [c.args[0] for c in avviso.call_args_list]
        self.assertIn({self.neri}, destinatari)  # Neri è RDD: tocca a lui firmare



class RefreshEIngressoTests(_Scenario):
    def test_il_refresh_non_mostra_le_mansioni_sospese_e_porta_alle_richieste(self):
        from .services import skillmatrix_refresh as refresh

        r = self._ram(tipo=R.TIPO_SOSPENSIONE, mansione_id=self.fresa.pk, livello="", motivazione="Fuori reparto")
        rq.decidi(self.rdd, r, approva=True)
        persone = {a.legacy_anagrafica_id for a in refresh.abilitazioni_reparto("Fresatura")
                   if a.competenza_id == self.fresa.pk}
        self.assertNotIn(self.rossi, persone)

    def test_formazione_in_ingresso_assegna_la_matricola_solo_col_contatore_acceso(self):
        from django.db import connection

        from .models_sessioni import ContatoreMatricola

        with self.assertRaisesMessage(rq.RichiestaNonValida, "inquadramento"):
            rq.crea(self.hr, tipo=R.TIPO_AGGIUNTA, persona_id=self.rossi, mansione_id=self.torno.pk, livello="U", onboarding=True)
        with self.assertRaisesMessage(rq.RichiestaNonValida, "la chiede HR"):
            rq.crea(self.capo, tipo=R.TIPO_AGGIUNTA, persona_id=self.rossi, mansione_id=self.torno.pk, livello="U",
                    onboarding=True, inquadramento="operatore")

        def chiudi_ingresso(mansione):
            r = rq.crea(self.hr, tipo=R.TIPO_AGGIUNTA, persona_id=self.rossi, mansione_id=mansione.pk, livello="U",
                        onboarding=True, inquadramento="operatore")
            s = svc.apri(self.hr, rq.decidi(self.rdd, r, approva=True))
            for riga in s.righe.exclude(stato=Riga.STATO_GIA_PRESENTE):
                svc.valuta(self.hr, riga, modalita="C", livello="U", docente_ente="Ente", verifica="test")
            s = svc.firma_approvatore(self.rdd, s)
            s = svc.firma_persona(self.persona, s)
            return svc.chiudi(self.hr, s)

        with connection.cursor() as c:
            c.execute("UPDATE anagrafica_dipendenti SET matricola = '' WHERE id = %s", [self.rossi])
        cnt, _ = ContatoreMatricola.objects.get_or_create(prefisso="CNO", defaults={"inquadramento": "operatore"})
        cnt.attivo, cnt.ultimo = False, 0
        cnt.save()
        s = chiudi_ingresso(self.torno)
        self.assertEqual(svc.matricola_di(self.rossi), "")
        self.assertIn("contatore CNO non è attivo", s.eventi.get(azione="Sessione chiusa positiva").nota)

        cnt.attivo, cnt.ultimo = True, 41
        cnt.save()
        s = chiudi_ingresso(self._crea_mansione("Montaggio M7", self.in1, self.op))
        self.assertEqual(svc.matricola_di(self.rossi), "CNO0042")
        cnt.refresh_from_db()
        self.assertEqual(cnt.ultimo, 42)
        # Una matricola presente non si cambia più.
        chiudi_ingresso(self._crea_mansione("Montaggio M8", self.in1, self.op))
        self.assertEqual(svc.matricola_di(self.rossi), "CNO0042")
