from django.core.exceptions import ValidationError
from django.test import TestCase

from dpi.models import CategoriaDPI

from .models import (
    AreaAziendale,
    DipendenteAnagraficaAziendale,
    Mansione,
    TipoVisitaMedica,
)
from .models_rischi import EsposizioneRischio, FattoreRischio
from .services.mansionario import requisiti_dipendente


class EsposizioneRischioTargetTests(TestCase):
    def setUp(self):
        self.fattore = FattoreRischio.objects.create(codice="RUM", nome="Rumore")

    def test_target_solo_dipendente_valido(self):
        esp = EsposizioneRischio(fattore=self.fattore, legacy_anagrafica_id=42)
        esp.full_clean()  # non deve sollevare
        esp.save()
        self.assertEqual(esp.legacy_anagrafica_id, 42)

    def test_nessun_target_non_valido(self):
        esp = EsposizioneRischio(fattore=self.fattore)
        with self.assertRaises(ValidationError):
            esp.full_clean()

    def test_target_mansione_resta_valido(self):
        m = Mansione.objects.create(nome="Tornitore-A1")
        EsposizioneRischio(fattore=self.fattore, mansione=m).full_clean()


class RequisitiDipendenteTests(TestCase):
    def setUp(self):
        self.dpi_guanti = CategoriaDPI.objects.create(nome="Guanti")
        self.dpi_cuffie = CategoriaDPI.objects.create(nome="Cuffie")
        self.visita_audio = TipoVisitaMedica.objects.create(nome="Audiometria", durata_mesi=24)

        self.f_rumore = FattoreRischio.objects.create(codice="RUM", nome="Rumore")
        self.f_rumore.categorie_dpi.add(self.dpi_cuffie)
        self.f_rumore.tipi_visita.add(self.visita_audio)

        self.f_chimico = FattoreRischio.objects.create(codice="CHI", nome="Chimico")
        self.f_chimico.categorie_dpi.add(self.dpi_guanti)

        # Mansione lavorativa "Verniciatore" esposta al chimico.
        self.mansione = Mansione.objects.create(nome="Verniciatore-A1")
        EsposizioneRischio.objects.create(fattore=self.f_chimico, mansione=self.mansione)

    def test_eredita_dalla_mansione(self):
        req = requisiti_dipendente(700, mansione_nome="Verniciatore-A1")
        self.assertIn(self.dpi_guanti, req["dpi"])

    def test_esposizione_diretta_aggiunge_fattore(self):
        EsposizioneRischio.objects.create(fattore=self.f_rumore, legacy_anagrafica_id=700)
        req = requisiti_dipendente(700, mansione_nome="Verniciatore-A1")
        self.assertIn(self.dpi_cuffie, req["dpi"])
        self.assertIn(self.visita_audio, req["visite"])

    def test_esposizione_di_area_aggiunge_fattore(self):
        area = AreaAziendale.objects.create(nome="IN1-A1")
        EsposizioneRischio.objects.create(fattore=self.f_rumore, area=area)
        req = requisiti_dipendente(701, mansione_nome="Verniciatore-A1", area_id=area.id)
        self.assertIn(self.dpi_cuffie, req["dpi"])

    def test_dedup_tra_fonti(self):
        # Stesso DPI dal chimico via mansione E via esposizione diretta.
        EsposizioneRischio.objects.create(fattore=self.f_chimico, legacy_anagrafica_id=700)
        req = requisiti_dipendente(700, mansione_nome="Verniciatore-A1")
        self.assertEqual([d for d in req["dpi"] if d == self.dpi_guanti], [self.dpi_guanti])

    def test_dipendente_nudo_requisiti_vuoti(self):
        req = requisiti_dipendente(999, mansione_nome="Inesistente", area_id=None)
        self.assertEqual(req, {"dpi": [], "visite": [], "corsi": [], "piani": [], "fattori": []})

    def test_area_risolta_da_db_se_non_passata(self):
        area = AreaAziendale.objects.create(nome="IN2-A1")
        DipendenteAnagraficaAziendale.objects.create(legacy_anagrafica_id=702, area_aziendale=area)
        EsposizioneRischio.objects.create(fattore=self.f_rumore, area=area)
        req = requisiti_dipendente(702, mansione_nome="")
        self.assertIn(self.dpi_cuffie, req["dpi"])
