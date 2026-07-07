from django.db import migrations

# Voce subnav per il MOD.128 MPQ (processi qualificati), agganciata al gruppo
# ESISTENTE "Qualifiche" del pilastro "Competenze" (stesso idioma di 0072 skill
# matrix): idempotente per ``url_value``, voce NON di sistema (riordinabile o
# nascondibile da Impostazioni → Navigazione). Nessuna nuova sezione: il MOD.128
# vive accanto a Cruscotto / Catalogo qualifiche / Sessioni di rinnovo.

CATEGORIA = "Competenze"
GRUPPO = "Qualifiche"

# (url_value, etichetta, ordine) — 258 = tra "Catalogo qualifiche" (255) e
# "Sessioni di rinnovo" (260).
LINKS = [
    ("anagrafica:mpq_cruscotto", "Processi qualificati (MOD.128)", 258),
]


def apply_subnav(apps, schema_editor):
    Cat = apps.get_model("anagrafica", "SubnavCategoriaAnagrafica")
    Link = apps.get_model("anagrafica", "SubnavLinkAnagrafica")

    cat = Cat.objects.filter(nome=CATEGORIA).order_by("id").first()
    if cat is None:
        # Fallback robusto se "Competenze" non esiste ancora (ordini come in 0070).
        cat = Cat.objects.create(
            nome=CATEGORIA, icona="🎓", ordine=200, is_active=True,
            landing_url_type="named",
            landing_url_value="anagrafica:formazione_dashboard",
        )

    for url_value, etichetta, ordine in LINKS:
        link = Link.objects.filter(url_value=url_value).order_by("id").first()
        if link is None:
            Link.objects.create(
                url_value=url_value, url_type="named", etichetta=etichetta,
                icona="", gruppo=GRUPPO, categoria=cat, ordine=ordine,
                active_view_names=url_value, is_active=True, is_sistema=False,
            )
            continue
        link.categoria = cat
        link.gruppo = GRUPPO
        link.etichetta = etichetta
        link.ordine = ordine
        link.is_active = True
        if not link.active_view_names:
            link.active_view_names = url_value
        link.save()


def reverse_subnav(apps, schema_editor):
    Link = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    Link.objects.filter(url_value__in=[u for u, _, _ in LINKS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0076_abilitazioneprocesso_clientequalificante_and_more"),
    ]

    operations = [
        migrations.RunPython(apply_subnav, reverse_subnav),
    ]
