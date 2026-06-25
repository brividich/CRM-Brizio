from django.db import migrations

# Voci subnav per la Skill Matrix MOD.187 (abilitazioni macchina), sotto il
# pilastro "Competenze" (gruppo "Skill Matrix" del mega-menu). Stesso idioma di
# 0070: idempotente per ``url_value``, voci NON di sistema (riordinabili o
# nascondibili da Impostazioni → Navigazione). La pagina di validazione match è
# il gate F2a; la matrice è la pagina principale del modulo.

CATEGORIA = "Competenze"
GRUPPO = "Skill Matrix"

# (url_value, etichetta, ordine)
LINKS = [
    ("anagrafica:skill_matrix_macchina", "Abilitazioni macchina (MOD.187)", 280),
    ("anagrafica:skm_match_validazione", "Validazione abbinamento macchine", 285),
]


def apply_subnav(apps, schema_editor):
    Cat = apps.get_model("anagrafica", "SubnavCategoriaAnagrafica")
    Link = apps.get_model("anagrafica", "SubnavLinkAnagrafica")

    cat = Cat.objects.filter(nome=CATEGORIA).order_by("id").first()
    if cat is None:
        # Fallback robusto se "Competenze" non esiste ancora (ordini come in 0070).
        cat = Cat.objects.create(nome=CATEGORIA, icona="🎓", ordine=200, is_active=True,
                                 landing_url_type="named",
                                 landing_url_value="anagrafica:formazione_dashboard")

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
        ("anagrafica", "0071_campagnarefresh_skillmatrixconfig_skmcorsiattivati_and_more"),
    ]

    operations = [
        migrations.RunPython(apply_subnav, reverse_subnav),
    ]
