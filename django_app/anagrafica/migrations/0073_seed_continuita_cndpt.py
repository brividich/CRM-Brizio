from django.db import migrations

# Seed del catalogo processi critici (continuità operativa). Solo l'unico processo
# CERTO al momento — CND-PT (controllo non distruttivo, liquidi penetranti) — secondo
# MT CN 65 §3.7 / EN 4179-NAS 410. Saldatura ISO 9606 e cromatura restano APERTI:
# da confermare in sessione di avvio prima di aggiungerli. Idempotente per nome.

PROCESSI = [
    {
        "nome": "CND-PT",
        "riferimento_normativo": "EN 4179 / NAS 410 — MT CN 65 §3.7 (Annual Proficiency)",
        "note": "Controllo non distruttivo con liquidi penetranti. Continuità = "
                "esecuzione entro finestra; oltre la finestra → abilitazione sospesa.",
    },
]


def seed(apps, schema_editor):
    Proc = apps.get_model("anagrafica", "ProcessoCriticoContinuita")
    for p in PROCESSI:
        Proc.objects.get_or_create(
            nome=p["nome"],
            defaults={
                "riferimento_normativo": p["riferimento_normativo"],
                "note": p["note"],
                "attivo": True,
            },
        )


def unseed(apps, schema_editor):
    Proc = apps.get_model("anagrafica", "ProcessoCriticoContinuita")
    Proc.objects.filter(nome__in=[p["nome"] for p in PROCESSI]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0072_subnav_skill_matrix"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
