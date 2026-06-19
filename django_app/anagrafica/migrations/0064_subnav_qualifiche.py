from django.db import migrations

# Token di highlight oggi agganciati al link "Formazione" che spostiamo
# sui nuovi link dedicati del dropdown "Qualifiche" (evita il doppio-highlight,
# stesso criterio delle migrazioni 0044/0045).
CATALOGO_VIEWS = [
    "anagrafica:qualifiche_list",
    "anagrafica:tipo_qualifica_detail",
    "anagrafica:tipo_qualifica_edit",
]
SESSIONI_VIEWS = [
    "anagrafica:qualifica_sessioni_list",
    "anagrafica:qualifica_sessione_create",
    "anagrafica:qualifica_sessione_detail",
]


def _tokens(value):
    return [t.strip() for t in (value or "").split(",") if t.strip()]


def _formazione_tokens(Link, *, remove=(), add=()):
    """Rimuove/aggiunge token di highlight sul link Formazione (se esiste)."""
    link = Link.objects.filter(url_value="anagrafica:formazione_dashboard").first()
    if not link:
        return
    tokens = _tokens(link.active_view_names)
    tokens = [t for t in tokens if t not in remove]
    for t in add:
        if t not in tokens:
            tokens.append(t)
    link.active_view_names = ",".join(tokens)
    link.save(update_fields=["active_view_names"])


def seed_qualifiche_subnav(apps, schema_editor):
    Cat = apps.get_model("anagrafica", "SubnavCategoriaAnagrafica")
    Link = apps.get_model("anagrafica", "SubnavLinkAnagrafica")

    cat, _ = Cat.objects.get_or_create(
        nome="Qualifiche",
        defaults=dict(icona="🎓", ordine=63, is_active=True),
    )

    nuovi = [
        dict(url_value="anagrafica:qualifiche_dashboard", etichetta="Cruscotto",
             ordine=63, active_view_names="anagrafica:qualifiche_dashboard"),
        dict(url_value="anagrafica:qualifiche_list", etichetta="Catalogo qualifiche",
             ordine=64, active_view_names=",".join(CATALOGO_VIEWS)),
        dict(url_value="anagrafica:qualifiche_scadenzario", etichetta="Scadenzario qualifiche",
             ordine=65, active_view_names="anagrafica:qualifiche_scadenzario"),
        dict(url_value="anagrafica:qualifica_sessioni_list", etichetta="Sessioni di rinnovo",
             ordine=66, active_view_names=",".join(SESSIONI_VIEWS)),
    ]
    for data in nuovi:
        Link.objects.get_or_create(
            url_value=data["url_value"],
            defaults=dict(
                categoria=cat,
                etichetta=data["etichetta"],
                icona="",
                url_type="named",
                active_view_names=data["active_view_names"],
                ordine=data["ordine"],
                is_sistema=True,
                is_active=True,
            ),
        )

    # Sposta i token di highlight via dalla "Formazione".
    _formazione_tokens(Link, remove=set(CATALOGO_VIEWS) | set(SESSIONI_VIEWS))


def remove_qualifiche_subnav(apps, schema_editor):
    Cat = apps.get_model("anagrafica", "SubnavCategoriaAnagrafica")
    Link = apps.get_model("anagrafica", "SubnavLinkAnagrafica")

    Link.objects.filter(url_value__in=[
        "anagrafica:qualifiche_dashboard",
        "anagrafica:qualifiche_list",
        "anagrafica:qualifiche_scadenzario",
        "anagrafica:qualifica_sessioni_list",
    ]).delete()

    # Ripristina i token di highlight sul link Formazione.
    _formazione_tokens(Link, add=["anagrafica:qualifiche_list", "anagrafica:qualifica_sessioni_list"])

    Cat.objects.filter(nome="Qualifiche").delete()


class Migration(migrations.Migration):

    dependencies = [
        ("anagrafica", "0063_cartella_sottocartelle"),
    ]

    operations = [
        migrations.RunPython(seed_qualifiche_subnav, remove_qualifiche_subnav),
    ]
