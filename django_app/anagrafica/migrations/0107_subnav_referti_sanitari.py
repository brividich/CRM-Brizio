from django.db import migrations

# Voce di navigazione per la coda di revisione dei referti sanitari.
#
# Sta sotto il pilastro «Compliance», accanto a «Visite mediche», perché è lo
# stesso dato e lo stesso permesso: non è una sezione a sé, è il modo in cui le
# visite entrano nel portale senza che qualcuno le digiti.
#
# La voce nasce **non di sistema**: resta riordinabile o eliminabile da
# Impostazioni → Navigazione, come tutte le altre. La navigazione non è un
# confine di sicurezza — chi non ha il permesso viene comunque respinto dalla
# view, che è l'unica autorità.

VOCE = (
    "anagrafica:referti_coda",   # url_value (chiave stabile)
    "Compliance",                # categoria
    "",                          # gruppo
    "Referti da rivedere",       # etichetta
    315,                         # ordine: subito dopo «Visite mediche» (310)
)


def aggiungi_voce(apps, schema_editor):
    Cat = apps.get_model("anagrafica", "SubnavCategoriaAnagrafica")
    Link = apps.get_model("anagrafica", "SubnavLinkAnagrafica")

    url_value, cat_name, gruppo, etichetta, ordine = VOCE
    cat = Cat.objects.filter(nome=cat_name).order_by("id").first()

    link = Link.objects.filter(url_value=url_value).order_by("id").first()
    if link is None:
        Link.objects.create(
            url_value=url_value, url_type="named", etichetta=etichetta,
            icona="", gruppo=gruppo, categoria=cat, ordine=ordine,
            # La voce resta evidenziata anche sulle pagine sorelle del modulo.
            active_view_names=(
                "anagrafica:referti_coda,anagrafica:referti_registro,"
                "anagrafica:referti_impostazioni"
            ),
            is_active=True, is_sistema=False,
        )
        return

    # Già presente (rilancio della migrazione): non si sovrascrivono le scelte
    # fatte a mano su categoria e ordine, si riattiva soltanto.
    if not link.is_active:
        link.is_active = True
        link.save(update_fields=["is_active"])


def rimuovi_voce(apps, schema_editor):
    Link = apps.get_model("anagrafica", "SubnavLinkAnagrafica")
    Link.objects.filter(url_value=VOCE[0]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0105_aliasesitoidoneita_refertointakeconfig_and_more"),
    ]

    operations = [
        migrations.RunPython(aggiungi_voce, rimuovi_voce),
    ]
