"""Assenze: le Impostazioni hanno un'azione loro, separata da «Chiudere / gestire».

«impostazioni» apre solo la pagina Impostazioni (``assenze.impostazioni.manage``).
La gestione interna (``assenze.assenze.manage``, ``legacy.assenze.admin_assenze``:
certificazione presenza, area HR, gestione admin) resta a «gestire».
Dati sintetici: i permessi si creano nel test.
"""
from __future__ import annotations

from django.core.cache import cache
from django.test import TestCase

from core.models import AccessGroup, PermissionDefinition, RuoloPermessoModulo
from core.permessi.registro import ModuloPermessi, registra_modulo
from core.permessi.sync import codici_desiderati, dati_anteprima_ruolo, stato_pagine_ruolo

IMPOSTAZIONI = ("assenze.impostazioni.manage",)
GESTIONE_INTERNA = ("assenze.assenze.manage", "legacy.assenze.admin_assenze")
ALTRA_GESTIONE = "assenze.sintetica_moderazione.manage"


class AzioneImpostazioniAssenzeTests(TestCase):
    def setUp(self):
        cache.clear()
        for code in (*IMPOSTAZIONI, *GESTIONE_INTERNA, ALTRA_GESTIONE):
            PermissionDefinition.objects.get_or_create(code=code, defaults={"label": code, "module": "assenze"})
        self.ruolo = AccessGroup.objects.create(code="t-gestore-assenze", label="Gestore assenze (test)", priority=300)

    def _cella(self, azione, ambito="tutti", consentito=True):
        RuoloPermessoModulo.objects.create(
            ruolo=self.ruolo, modulo="assenze", azione=azione, ambito=ambito, consentito=consentito
        )

    def test_gestire_non_apre_le_impostazioni(self):
        self._cella("gestire", ambito="team")
        desiderati, governati = codici_desiderati(self.ruolo)
        self.assertIn(ALTRA_GESTIONE, desiderati)
        # Certificazione presenza, area HR e gestione admin restano a chi gestisce.
        for code in GESTIONE_INTERNA:
            self.assertIn(code, desiderati, code)
        for code in IMPOSTAZIONI:
            self.assertNotIn(code, desiderati, code)
            self.assertIn(code, governati, code)  # la sincronizzazione le spegne

    def test_azione_impostazioni_apre_solo_le_impostazioni(self):
        self._cella("impostazioni")
        desiderati, _ = codici_desiderati(self.ruolo)
        for code in IMPOSTAZIONI:
            self.assertIn(code, desiderati, code)
        for code in (*GESTIONE_INTERNA, ALTRA_GESTIONE):
            self.assertNotIn(code, desiderati, code)

    def test_impostazioni_no_resta_chiusa(self):
        self._cella("gestire")
        self._cella("impostazioni", consentito=False)
        desiderati, _ = codici_desiderati(self.ruolo)
        for code in IMPOSTAZIONI:
            self.assertNotIn(code, desiderati, code)

    def test_vede_tutto_non_apre_le_impostazioni(self):
        self.ruolo.vede_tutto = True
        self.ruolo.save()
        desiderati, _ = codici_desiderati(self.ruolo)
        for code in IMPOSTAZIONI:
            self.assertNotIn(code, desiderati, code)

    def test_badge_pagine_sotto_la_cella_impostazioni(self):
        self._cella("impostazioni")
        stato = stato_pagine_ruolo(self.ruolo)
        self.assertEqual(stato[("assenze", "impostazioni")].totale, len(IMPOSTAZIONI))
        gestire = stato.get(("assenze", "gestire"))
        if gestire is not None:
            self.assertFalse(set(IMPOSTAZIONI) & set(gestire.concesse + gestire.chiuse))
        anteprima = dati_anteprima_ruolo(self.ruolo)
        self.assertEqual(anteprima["azioni"]["impostazioni"], ["azione:impostazioni"])
        caps = {riga[0]: riga[1] for riga in anteprima["moduli"]["assenze"]["pagine"]}
        for code in IMPOSTAZIONI:
            self.assertEqual(caps[code], "azione:impostazioni")

    def test_registro_rifiuta_pagine_di_azione_non_dichiarata(self):
        with self.assertRaises(ValueError):
            registra_modulo(ModuloPermessi(
                chiave="t_modulo_sbagliato", nome="Sbagliato",
                pagine_azioni=(("inesistente", ("x.y.view",)),),
            ))
