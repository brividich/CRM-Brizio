"""Simulatore dei permessi (core.permessi.simulatore) e pagine «Confronta due ruoli» / «Prova un ruolo»."""
from __future__ import annotations

from django.test import TestCase
from django.urls import reverse

from core.models import AccessGroup, RuoloPermessoModulo
from core.permessi.cache import invalida_permessi
from core.permessi.motore import decisione
from core.permessi.simulatore import confronta_ruoli, effetto_modifica
from core.tests_permessi import PersoneMixin


class SimulatoreTests(PersoneMixin, TestCase):
    def setUp(self):
        self.lettore = AccessGroup.objects.create(code="sim_lettore", label="Lettore assenze", priority=300)
        self.gestore = AccessGroup.objects.create(code="sim_gestore", label="Gestore assenze", priority=400)
        RuoloPermessoModulo.objects.create(ruolo=self.lettore, modulo="assenze", azione="vedere", ambito="team")
        RuoloPermessoModulo.objects.create(ruolo=self.gestore, modulo="assenze", azione="vedere", ambito="tutti")
        RuoloPermessoModulo.objects.create(ruolo=self.gestore, modulo="assenze", azione="approvare", ambito="tutti")
        invalida_permessi()

    def test_confronto_evidenzia_le_differenze(self):
        c = confronta_ruoli(self.lettore, self.gestore)
        assenze = next(m for m in c.moduli if m["modulo"].chiave == "assenze")
        per_label = {r["label"]: r for r in assenze["righe"]}
        self.assertTrue(all(r["diverso"] for r in per_label.values()))  # team vs tutti, no vs sì
        self.assertGreaterEqual(c.differenze, 2)
        # Un ruolo confrontato con sé stesso non ha differenze.
        self.assertEqual(confronta_ruoli(self.gestore, self.gestore).differenze, 0)

    def test_prova_un_ruolo_non_salva_e_mostra_solo_i_cambi(self):
        user, legacy = self.persona("Persona sintetica", ruoli=("sim_lettore",))
        cambi = effetto_modifica(user, aggiungi=[self.gestore.id])
        etichette = {(c["modulo"].chiave, c["label"]) for c in cambi}
        self.assertTrue(any(k == "assenze" for k, _ in etichette))
        self.assertTrue(all(c["prima"].consentito != c["dopo"].consentito or c["prima"].ambito != c["dopo"].ambito
                            for c in cambi))
        # Niente è stato scritto: la persona decide come prima.
        self.assertFalse(decisione(user, "assenze", "approvare").consentito)
        # Togliere il ruolo che concede: perde la visibilità.
        tolto = effetto_modifica(user, togli=[self.lettore.id])
        self.assertTrue(any(c["perde"] or c["dopo"].ambito != c["prima"].ambito for c in tolto))

    def test_pagine(self):
        admin, _ = self.persona("Amministratore sintetico", superuser=True)
        self.client.force_login(admin)
        url = reverse("admin_portale:ruoli_portale")
        resp = self.client.get(url, {"tab": "confronta", "a": self.lettore.id, "b": self.gestore.id})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "differenze")
        user, legacy = self.persona("Persona da provare", ruoli=("sim_lettore",))
        resp = self.client.get(url, {"tab": "anteprima", "persona": legacy.id, "prova_aggiungi": self.gestore.id})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Mostra cosa cambia")
        self.assertContains(resp, "aggiungi «Gestore assenze»")
