from django.db import migrations

# Aggiunge la voce subnav "Refresh semestrale" al gruppo Skill Matrix (pilastro
# Competenze). Stesso idioma di 0072: idempotente per url_value, voce non di sistema.

CATEGORIA = "Competenze"
GRUPPO = "Skill Matrix"
LINK = ("anagrafica:skm_refresh", "Refresh semestrale", 290)


def apply_subnav(apps, schema_editor):
    Cat = apps.get_model("anagrafica", "SubnavCategoriaAnagrafica")
    Link = apps.get_model("anagrafica", "SubnavLinkAnagrafica")

    cat = Cat.objects.filter(nome=CATEGORIA).order_by("id").first()
    if cat is None:
        cat = Cat.objects.create(nome=CATEGORIA, icona="🎓", ordine=200, is_active=True,
                                 landing_url_type="named",
                                 landing_url_value="anagrafica:formazione_dashboard")
    url_value, etichetta, ordine = LINK
    link = Link.objects.filter(url_value=url_value).order_by("id").first()
    if link is None:
        Link.objects.create(
            url_value=url_value, url_type="named", etichetta=etichetta,
            icona="", gruppo=GRUPPO, categoria=cat, ordine=ordine,
            active_view_names=url_value, is_active=True, is_sistema=False,
        )
    else:
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
    Link.objects.filter(url_value=LINK[0]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0073_seed_continuita_cndpt"),
    ]

    operations = [
        migrations.RunPython(apply_subnav, reverse_subnav),
    ]
