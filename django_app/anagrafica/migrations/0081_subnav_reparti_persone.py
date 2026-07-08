from django.db import migrations

# Voce subnav dedicata per il catalogo Reparti/Aree aziendali (`aree_list`,
# `/anagrafica/aree/`), agganciata al pillar "Persone" (dropdown), subito dopo
# "Report dipendenti". Prima di questa migration la pagina era raggiungibile
# solo da dentro il Pannello Impostazioni (tab "Reparti"); resta comunque
# visibile lì. Toglie il token dagli ``active_view_names`` di Impostazioni per
# evitare il doppio-highlight (stesso criterio di 0044/0045/0077). Link NON di
# sistema: riordinabile/nascondibile da Impostazioni → Navigazione.

URL_VALUE = "anagrafica:aree_list"
CATEGORIA = "Persone"
ETICHETTA = "Reparti"
ORDINE = 145


def _set_tokens(active_view_names, *, remove):
    tokens = [t.strip() for t in (active_view_names or "").split(",") if t.strip()]
    tokens = [t for t in tokens if t != remove]
    return ",".join(tokens)


def _add_token(active_view_names, *, add, after):
    tokens = [t.strip() for t in (active_view_names or "").split(",") if t.strip()]
    if add in tokens:
        return ",".join(tokens)
    if after in tokens:
        idx = tokens.index(after)
        tokens.insert(idx + 1, add)
    else:
        tokens.append(add)
    return ",".join(tokens)


def apply_subnav(apps, schema_editor):
    Cat = apps.get_model("anagrafica", "SubnavCategoriaAnagrafica")
    Link = apps.get_model("anagrafica", "SubnavLinkAnagrafica")

    cat = Cat.objects.filter(nome=CATEGORIA).order_by("id").first()

    link = Link.objects.filter(url_value=URL_VALUE).order_by("id").first()
    if link is None:
        Link.objects.create(
            url_value=URL_VALUE, url_type="named", etichetta=ETICHETTA,
            icona="", gruppo="", categoria=cat, ordine=ORDINE,
            active_view_names=URL_VALUE, is_active=True, is_sistema=False,
        )
    else:
        link.categoria = cat
        link.gruppo = ""
        link.etichetta = ETICHETTA
        link.ordine = ORDINE
        link.is_active = True
        if not link.active_view_names:
            link.active_view_names = URL_VALUE
        link.save()

    impostazioni = Link.objects.filter(url_value="anagrafica:impostazioni").first()
    if impostazioni:
        impostazioni.active_view_names = _set_tokens(impostazioni.active_view_names, remove=URL_VALUE)
        impostazioni.save(update_fields=["active_view_names"])


def reverse_subnav(apps, schema_editor):
    Link = apps.get_model("anagrafica", "SubnavLinkAnagrafica")

    Link.objects.filter(url_value=URL_VALUE).delete()

    impostazioni = Link.objects.filter(url_value="anagrafica:impostazioni").first()
    if impostazioni:
        impostazioni.active_view_names = _add_token(
            impostazioni.active_view_names, add=URL_VALUE, after="anagrafica:impostazioni"
        )
        impostazioni.save(update_fields=["active_view_names"])


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0080_reparto_area_aziendale_inversione"),
    ]

    operations = [
        migrations.RunPython(apply_subnav, reverse_subnav),
    ]
