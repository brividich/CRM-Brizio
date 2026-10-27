"""Capo dell'area dalla «Responsabilità dell'area» (27/10/2026).

Il file MEGA SKILL MATRIX v8 dà una «Responsabilità» a ognuna delle sue 31
unità, che nel portale sono le aree: la mansione del capo scelta a mano
(0199, mai andata in produzione) lascia il posto a una mansione generata dal
ruolo responsabile dell'area, come per i reparti.
"""
import re

import django.db.models.deletion
from django.db import migrations, models

NOME = "Responsabilità dell'area"


def _chiave(CompetenzaSkm, nome):
    base = "MANS-" + re.sub(r"[^0-9A-Z]+", "-", nome.upper()).strip("-")[:100]
    chiave, n = base, 2
    while CompetenzaSkm.objects.filter(competenza_key=chiave).exists():
        chiave, n = f"{base}-{n}", n + 1
    return chiave


def genera(apps, schema_editor):
    AreaAziendale = apps.get_model("anagrafica", "AreaAziendale")
    CompetenzaSkm = apps.get_model("anagrafica", "CompetenzaSkm")
    aree = AreaAziendale.objects.filter(is_active=True, ruolo_responsabile__isnull=False,
                                        reparto__isnull=False).select_related("reparto")
    for area in aree:
        if (area.nome or "").strip().casefold() == (area.reparto.nome or "").strip().casefold():
            continue
        if CompetenzaSkm.objects.filter(responsabilita_area=area).exists():
            continue
        nome = f"{NOME} {area.nome}"
        m = CompetenzaSkm.objects.create(
            competenza_key=_chiave(CompetenzaSkm, nome), display=nome, tipo="processo",
            area_id=area.pk, reparto_id=area.reparto_id, attiva=True, responsabilita_area=area,
        )
        m.ruoli.set([area.ruolo_responsabile_id])


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0199_mansione_capo"),
    ]

    operations = [
        migrations.RemoveField(model_name="areaaziendale", name="mansione_capo"),
        migrations.RemoveField(model_name="reparto", name="mansione_capo"),
        migrations.AddField(
            model_name="competenzaskm",
            name="responsabilita_area",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                                    related_name="mansioni_responsabilita", to="anagrafica.areaaziendale"),
        ),
        migrations.AddConstraint(
            model_name="competenzaskm",
            constraint=models.UniqueConstraint(condition=models.Q(("responsabilita_area__isnull", False)),
                                               fields=("responsabilita_area",), name="skm_responsabilita_area_unica"),
        ),
        migrations.RunPython(genera, migrations.RunPython.noop),
    ]
