"""
Migration 0036 — Subnav admin: rimozione voci legacy ACL, riordino voci canonico v2.

Rimuove: Permessi, Matrice, Pulsanti (gestione legacy ora sostituita da ACL Canonico v2).
Riordina: ACL Canonico → 50, Route Coverage → 60, Mappa Permessi → 80, Diagnostica ACL → 85.
"""
from django.db import migrations


def apply(apps, schema_editor):
    NavigationItem = apps.get_model("core", "NavigationItem")

    # Rimuovi voci legacy ACL che non servono più
    NavigationItem.objects.filter(
        code__in=["admin-permessi", "admin-matrice", "admin-pulsanti"],
        section="admin_subnav",
    ).delete()

    # ACL Canonico: sposta in posizione 50
    NavigationItem.objects.filter(code="admin-acl-canonico", section="admin_subnav").update(
        order=50,
        label="ACL Canonico",
    )

    # Route Coverage: sposta in posizione 60
    NavigationItem.objects.filter(code="admin-acl-route-coverage", section="admin_subnav").update(
        order=60,
        label="Route Coverage",
    )

    # Mappa Permessi: sposta in posizione 80 (era 205)
    NavigationItem.objects.filter(code="admin-mappa-permessi-nav", section="admin_subnav").update(
        order=80,
    )

    # Vecchia "ACL" diagnostica: rinomina e sposta in posizione 85
    NavigationItem.objects.filter(code="admin-acl", section="admin_subnav").update(
        order=85,
        label="Diagnostica ACL",
    )


def rollback(apps, schema_editor):
    NavigationItem = apps.get_model("core", "NavigationItem")

    # Ripristina ordini originali
    NavigationItem.objects.filter(code="admin-acl-canonico", section="admin_subnav").update(order=395, label="ACL Canonico")
    NavigationItem.objects.filter(code="admin-acl-route-coverage", section="admin_subnav").update(order=396, label="ACL Route Coverage")
    NavigationItem.objects.filter(code="admin-mappa-permessi-nav", section="admin_subnav").update(order=205)
    NavigationItem.objects.filter(code="admin-acl", section="admin_subnav").update(order=200, label="ACL")

    # Ricrea le voci legacy rimosse
    items_to_restore = [
        dict(
            code="admin-permessi",
            section="admin_subnav",
            label="Permessi",
            route_name="admin_portale:permessi",
            order=50,
            is_active=True,
            icon="",
            url_path="",
            parent_code="",
            open_in_new_tab=False,
        ),
        dict(
            code="admin-matrice",
            section="admin_subnav",
            label="Matrice",
            route_name="admin_portale:matrice_permessi",
            order=60,
            is_active=True,
            icon="",
            url_path="",
            parent_code="",
            open_in_new_tab=False,
        ),
        dict(
            code="admin-pulsanti",
            section="admin_subnav",
            label="Pulsanti",
            route_name="admin_portale:pulsanti",
            order=80,
            is_active=True,
            icon="",
            url_path="",
            parent_code="",
            open_in_new_tab=False,
        ),
    ]
    for item in items_to_restore:
        NavigationItem.objects.get_or_create(code=item["code"], section=item["section"], defaults=item)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0035_admin_acl_route_coverage_subnav"),
    ]

    operations = [
        migrations.RunPython(apply, rollback),
    ]
