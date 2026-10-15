import importlib

from django.apps import apps
from django.test import TestCase

from .models import ColonnaProfiloSNMP, DispositivoSNMP, ProfiloSNMP, SondaSNMP

m0037 = importlib.import_module("contatori.migrations.0037_kyocera_contatori_stampa_copia")


class Migrazione0037SondaDuplicataTests(TestCase):
    """Il dispositivo ha gia' una sonda manuale con l'OID nuovo: niente IntegrityError."""

    def setUp(self):
        self.profilo, _ = ProfiloSNMP.objects.get_or_create(
            slug="kyocera", defaults={"nome": "Kyocera", "produttore": "Kyocera"})
        self.colonna = ColonnaProfiloSNMP.objects.filter(profilo=self.profilo, contatore_mfc="a4_bn").first()
        if self.colonna is None:
            self.colonna = ColonnaProfiloSNMP.objects.create(
                profilo=self.profilo, nome="A4 BN Kyocera", oid=m0037.VECCHI["a4_bn"], contatore_mfc="a4_bn")
        ColonnaProfiloSNMP.objects.filter(pk=self.colonna.pk).update(oid=m0037.VECCHI["a4_bn"])
        self.disp = DispositivoSNMP.objects.create(nome="MFC demo", host="192.0.2.237")
        self.vecchia = SondaSNMP.objects.create(
            dispositivo=self.disp, profilo_colonna=self.colonna, nome="A4 BN Kyocera", oid=m0037.VECCHI["a4_bn"])
        self.nuovo_oid = m0037.NUOVI["a4_bn"][1]
        self.manuale = SondaSNMP.objects.create(dispositivo=self.disp, nome="Manuale", oid=self.nuovo_oid)

    def test_forwards_tiene_la_sonda_esistente_e_spegne_la_vecchia(self):
        m0037._applica(apps, m0037.NUOVI, 1, m0037.FONTE)
        self.vecchia.refresh_from_db()
        self.manuale.refresh_from_db()
        self.assertFalse(self.vecchia.attiva)
        self.assertIsNone(self.vecchia.profilo_colonna_id)
        self.assertEqual(self.vecchia.oid, m0037.VECCHI["a4_bn"])
        self.assertEqual(self.manuale.profilo_colonna_id, self.colonna.pk)
        self.assertEqual(self.manuale.nome, m0037.NUOVI["a4_bn"][0])
        self.assertEqual(SondaSNMP.objects.filter(dispositivo=self.disp, oid=self.nuovo_oid).count(), 1)

    def test_forwards_senza_duplicato_aggiorna_l_oid(self):
        self.manuale.delete()
        m0037._applica(apps, m0037.NUOVI, 1, m0037.FONTE)
        self.vecchia.refresh_from_db()
        self.assertEqual(self.vecchia.oid, self.nuovo_oid)
        self.assertTrue(self.vecchia.attiva)
