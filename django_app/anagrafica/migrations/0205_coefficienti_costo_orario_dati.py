"""Dati di partenza per classificazione, coefficienti e costo orario (ottobre 2026).

- Coefficienti: a chi ha mansioni in lista e attive si danno parti uguali (somma
  1); chi ne ha più d'una resta «da rivedere», perché la ripartizione vera la
  decide HR.
- Costo orario: si calcola per tutti i mesi che hanno la voce RML (RML ÷ 26 ÷
  6,66, la correzione manuale vince, per ogni mese vale l'import più recente).
- Binding ACL delle pagine nuove, copiati dalle sorelle (schema della 0185).
"""
from decimal import ROUND_HALF_UP, Decimal

from django.db import migrations

PASSO = Decimal("0.0001")
ROTTE = {
    "anagrafica:mansioni_coefficienti": "anagrafica:mansionario_persona",
    "anagrafica:costo_orario": "anagrafica:retribuzioni_globale",
    "anagrafica:costo_orario_export": "anagrafica:retribuzioni_globale",
}
NOTA = "[COEFF_0205] copiato da {}"


def _parti_uguali(n):
    valori = [(Decimal(1) / n).quantize(PASSO, rounding=ROUND_HALF_UP)] * n
    valori[0] += Decimal(1) - sum(valori)
    return valori


def coefficienti(apps, schema_editor):
    Abilitazione = apps.get_model("anagrafica", "AbilitazioneMacchina")
    Profilo = apps.get_model("anagrafica", "ProfiloMansioniPersona")
    per_persona = {}
    for pk, lid in (Abilitazione.objects.filter(in_lista=True, stato="attiva", competenza__isnull=False)
                    .order_by("legacy_anagrafica_id", "pk").values_list("pk", "legacy_anagrafica_id")):
        per_persona.setdefault(lid, []).append(pk)
    for lid, pks in per_persona.items():
        for pk, v in zip(pks, _parti_uguali(len(pks))):
            Abilitazione.objects.filter(pk=pk).update(coefficiente=v)
        if len(pks) > 1:
            Profilo.objects.update_or_create(
                legacy_anagrafica_id=lid,
                defaults={"coefficienti_da_rivedere": True, "motivo": "ripartizione iniziale in parti uguali"})


def costo_orario(apps, schema_editor):
    Voce = apps.get_model("anagrafica", "VoceRetributiva")
    Costo = apps.get_model("anagrafica", "CostoOrarioMensile")
    Civile = apps.get_model("anagrafica", "DipendenteAnagraficaCivile")
    gruppi = {}
    for v in Voce.objects.filter(pay_item_key="rml").values(
            "pk", "tax_code", "data_competenza", "importo", "manuale", "legacy_anagrafica_id", "importazione_id",
            "importazione__data_importazione"):
        cf = (v["tax_code"] or "").strip().upper()
        if cf:
            gruppi.setdefault((cf, v["data_competenza"].replace(day=1)), []).append(v)
    if not gruppi:
        return
    civile = {(cf or "").strip().upper(): lid for cf, lid in
              Civile.objects.exclude(codice_fiscale="").values_list("codice_fiscale", "legacy_anagrafica_id")}
    giorni, ore = Decimal("26"), Decimal("6.66")
    for (cf, mese), gruppo in gruppi.items():
        manuali = [v for v in gruppo if v["manuale"]]
        if manuali:
            scelta = max(manuali, key=lambda v: v["pk"])
        else:
            ultima = max(gruppo, key=lambda v: (v["importazione__data_importazione"], v["importazione_id"]))
            scelta = max((v for v in gruppo if v["importazione_id"] == ultima["importazione_id"]),
                         key=lambda v: v["pk"])
        rml = scelta["importo"]
        if rml is None or rml <= 0:
            continue
        lid = next((v["legacy_anagrafica_id"] for v in gruppo if v["legacy_anagrafica_id"]), None) or civile.get(cf)
        Costo.objects.update_or_create(
            tax_code=cf, mese=mese,
            defaults={"legacy_anagrafica_id": lid, "rml": rml, "rml_manuale": bool(scelta["manuale"]),
                      "divisore_giorni": giorni, "divisore_ore": ore,
                      "costo_orario": (rml / giorni / ore).quantize(PASSO, rounding=ROUND_HALF_UP)})


def binding(apps, schema_editor):
    Binding = apps.get_model("core", "RoutePermissionBinding")
    for rotta, sorella in ROTTE.items():
        if Binding.objects.filter(route_name=rotta).exists():
            continue
        modello = None
        for candidata in (sorella, "anagrafica:dipendenti_list"):
            modello = Binding.objects.filter(route_name=candidata, is_active=True).order_by("-priority", "pk").first()
            if modello is not None:
                break
        if modello is None:
            continue
        Binding.objects.create(
            route_name=rotta, path_pattern="", match_strategy=modello.match_strategy,
            permission_id=modello.permission_id, source_app="anagrafica", priority=modello.priority,
            is_active=True, note=NOTA.format(sorella),
        )


def avanti(apps, schema_editor):
    coefficienti(apps, schema_editor)
    costo_orario(apps, schema_editor)
    binding(apps, schema_editor)


def indietro(apps, schema_editor):
    Binding = apps.get_model("core", "RoutePermissionBinding")
    for rotta, sorella in ROTTE.items():
        Binding.objects.filter(route_name=rotta, note=NOTA.format(sorella)).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0204_classificazione_coefficiente_costo_orario"),
        ("core", "0001_initial"),
    ]

    operations = [migrations.RunPython(avanti, indietro)]
