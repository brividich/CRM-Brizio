"""«Chi può aprire questa pagina» e tipologia dell'assegnazione nella provenienza degli accessi.

Dati sintetici.
"""
from __future__ import annotations

from django.test import TestCase

from core.models import AuditLog, GroupPermissionGrant
from core.permessi.chi_accede import chi_puo_aprire
from core.permessi.organigramma import provenienze_per_utenti
from core.tests_permessi_organigramma import OrganigrammaMixin


class ChiAccedeTests(OrganigrammaMixin, TestCase):
    def _codice_hr(self):
        return GroupPermissionGrant.objects.filter(group=self.hr, enabled=True).values_list(
            "permission_id", flat=True).first()

    def test_ad_interim_si_vede_nella_provenienza_e_nel_registro(self):
        self.r_personale.profili_permessi.add(self.hr)
        _user, legacy = self.persona("Interim")
        a = self.assegna(legacy, self.r_personale)
        a.tipologia = "AD_INTERIM"
        a.save()
        self.assertEqual(provenienze_per_utenti([legacy.id])[legacy.id][self.hr.id],
                         ["Addetto ufficio personale TEST (ad interim)"])
        a.delete()
        causa = AuditLog.objects.filter(azione="accessi_da_organigramma").order_by("-id").first().dettaglio["causa"]
        self.assertEqual(causa, "Ruolo «Addetto ufficio personale TEST» (ad interim) tolto")

    def test_chi_puo_aprire_dice_perche_e_da_dove(self):
        codice = self._codice_hr()
        self.assertTrue(codice)
        self.r_personale.profili_permessi.add(self.hr)
        _user, legacy = self.persona("Accede")
        self.assegna(legacy, self.r_personale)
        esito = chi_puo_aprire(codice)
        riga = next(r for r in esito["persone"] if r["utente"].id == legacy.id)
        self.assertIn(self.hr.label, riga["motivo"])
        self.assertEqual(riga["provenienza"], "organigramma: Addetto ufficio personale TEST")
        self.assertEqual(chi_puo_aprire("codice.inesistente")["permesso"], None)
