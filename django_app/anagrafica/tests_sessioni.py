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
        s.refresh_from_db()
        self.assertEqual(s.firma_persona_modo, S.FIRMA_CARTA)

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
