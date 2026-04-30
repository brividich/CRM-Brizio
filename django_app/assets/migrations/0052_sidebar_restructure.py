from django.db import migrations


def seed(apps, schema_editor):
    AssetSidebarButton = apps.get_model("assets", "AssetSidebarButton")

    # Pulisce tutto e ricrea la struttura completa
    AssetSidebarButton.objects.all().delete()

    # ── MAIN ─────────────────────────────────────────────────────────────────

    cruscotto = AssetSidebarButton.objects.create(
        code="cruscotto",
        section="MAIN",
        label="Cruscotto",
        target_url="/assets/",
        active_match="",
        is_subitem=False,
        parent=None,
        sort_order=10,
        is_visible=True,
    )

    # ── Dispositivi IT ───────────────────────────────────────────────────────

    dispositivi_it = AssetSidebarButton.objects.create(
        code="dispositivi_it",
        section="MAIN",
        label="Dispositivi IT",
        target_url="django:assets:device_list",
        active_match="/assets/dispositivi/",
        is_subitem=False,
        parent=None,
        sort_order=20,
        is_visible=True,
    )

    AssetSidebarButton.objects.create(
        code="dev_server",
        section="MAIN",
        label="Server",
        target_url="/assets/dispositivi/?asset_type=SERVER",
        active_match="asset_type=SERVER",
        is_subitem=True,
        parent=dispositivi_it,
        sort_order=21,
        is_visible=True,
    )

    AssetSidebarButton.objects.create(
        code="dev_pc",
        section="MAIN",
        label="PC",
        target_url="/assets/dispositivi/?asset_type=PC",
        active_match="asset_type=PC",
        is_subitem=True,
        parent=dispositivi_it,
        sort_order=22,
        is_visible=True,
    )

    AssetSidebarButton.objects.create(
        code="dev_rete",
        section="MAIN",
        label="Rete",
        target_url="/assets/dispositivi/?asset_type=FIREWALL",
        active_match="asset_type=FIREWALL",
        is_subitem=True,
        parent=dispositivi_it,
        sort_order=23,
        is_visible=True,
    )

    AssetSidebarButton.objects.create(
        code="dev_tvcc",
        section="MAIN",
        label="TVCC",
        target_url="/assets/dispositivi/?asset_type=CCTV",
        active_match="asset_type=CCTV",
        is_subitem=True,
        parent=dispositivi_it,
        sort_order=24,
        is_visible=True,
    )

    AssetSidebarButton.objects.create(
        code="dev_fonia",
        section="MAIN",
        label="Fonia",
        target_url="/assets/dispositivi/?asset_type=FONIA",
        active_match="asset_type=FONIA",
        is_subitem=True,
        parent=dispositivi_it,
        sort_order=25,
        is_visible=True,
    )

    AssetSidebarButton.objects.create(
        code="dev_calendario",
        section="MAIN",
        label="Calendario asset",
        target_url="django:assets:calendario_asset",
        active_match="",
        is_subitem=True,
        parent=dispositivi_it,
        sort_order=26,
        is_visible=True,
    )

    AssetSidebarButton.objects.create(
        code="dev_manut_per",
        section="MAIN",
        label="Manutenzione periodica IT",
        target_url="django:assets:periodic_verifications?scope=it",
        active_match="",
        is_subitem=True,
        parent=dispositivi_it,
        sort_order=27,
        is_visible=True,
    )

    AssetSidebarButton.objects.create(
        code="dev_reports",
        section="MAIN",
        label="Report dispositivi IT",
        target_url="django:assets:reports?scope=it",
        active_match="",
        is_subitem=True,
        parent=dispositivi_it,
        sort_order=28,
        is_visible=True,
    )

    # ── Asset produzione ─────────────────────────────────────────────────────

    asset_produzione = AssetSidebarButton.objects.create(
        code="asset_produzione",
        section="MAIN",
        label="Asset produzione",
        target_url="django:assets:work_machine_dashboard",
        active_match="/assets/work-machines/",
        is_subitem=False,
        parent=None,
        sort_order=40,
        is_visible=True,
    )

    AssetSidebarButton.objects.create(
        code="prod_cnc",
        section="MAIN",
        label="CNC",
        target_url="/assets/work-machines/?asset_type=CNC",
        active_match="asset_type=CNC",
        is_subitem=True,
        parent=asset_produzione,
        sort_order=41,
        is_visible=True,
    )

    AssetSidebarButton.objects.create(
        code="prod_carroponti",
        section="MAIN",
        label="Carroponti",
        target_url="/assets/work-machines/?asset_type=CARROPONTE",
        active_match="asset_type=CARROPONTE",
        is_subitem=True,
        parent=asset_produzione,
        sort_order=42,
        is_visible=True,
    )

    AssetSidebarButton.objects.create(
        code="prod_macch_utensili",
        section="MAIN",
        label="Macchine Utensili",
        target_url="/assets/work-machines/?asset_type=WORK_MACHINE",
        active_match="asset_type=WORK_MACHINE",
        is_subitem=True,
        parent=asset_produzione,
        sort_order=43,
        is_visible=True,
    )

    AssetSidebarButton.objects.create(
        code="prod_reports",
        section="MAIN",
        label="Report asset produzione",
        target_url="django:assets:reports?scope=production",
        active_match="",
        is_subitem=True,
        parent=asset_produzione,
        sort_order=44,
        is_visible=True,
    )

    # ── Top-level tools ──────────────────────────────────────────────────────

    AssetSidebarButton.objects.create(
        code="mappa_officina",
        section="MAIN",
        label="Mappa officina",
        target_url="django:assets:plant_layout_map",
        active_match="/assets/work-machines/map/",
        is_subitem=False,
        parent=None,
        sort_order=50,
        is_visible=True,
    )

    AssetSidebarButton.objects.create(
        code="calendario_main",
        section="MAIN",
        label="Calendario asset",
        target_url="django:assets:calendario_asset",
        active_match="/assets/calendario/",
        is_subitem=False,
        parent=None,
        sort_order=51,
        is_visible=True,
    )

    AssetSidebarButton.objects.create(
        code="manut_per_main",
        section="MAIN",
        label="Manutenzione periodica produzione",
        target_url="django:assets:periodic_verifications?scope=production",
        active_match="",
        is_subitem=False,
        parent=None,
        sort_order=52,
        is_visible=True,
    )

    AssetSidebarButton.objects.create(
        code="licenze",
        section="MAIN",
        label="Licenze software",
        target_url="django:assets:software_license_list",
        active_match="/assets/licenze/",
        is_subitem=False,
        parent=None,
        sort_order=60,
        is_visible=True,
    )

    AssetSidebarButton.objects.create(
        code="scadenze",
        section="MAIN",
        label="Scadenze amministrative",
        target_url="django:assets:asset_administrative_deadline_list",
        active_match="/assets/scadenze/",
        is_subitem=False,
        parent=None,
        sort_order=70,
        is_visible=True,
    )

    AssetSidebarButton.objects.create(
        code="componenti",
        section="MAIN",
        label="Componenti",
        target_url="django:assets:asset_component_list",
        active_match="/assets/componenti/",
        is_subitem=False,
        parent=None,
        sort_order=80,
        is_visible=True,
    )

    # ── Impostazioni ─────────────────────────────────────────────────────────

    impostazioni = AssetSidebarButton.objects.create(
        code="impostazioni",
        section="MAIN",
        label="Impostazioni",
        target_url="django:assets:maintenance_template_list",
        active_match="",
        is_subitem=False,
        parent=None,
        sort_order=90,
        is_visible=True,
    )

    AssetSidebarButton.objects.create(
        code="impost_template",
        section="MAIN",
        label="Template manutenzione",
        target_url="django:assets:maintenance_template_list",
        active_match="/assets/manutenzione/templates/",
        is_subitem=True,
        parent=impostazioni,
        sort_order=91,
        is_visible=True,
    )

    AssetSidebarButton.objects.create(
        code="impost_regole",
        section="MAIN",
        label="Regole manutenzione",
        target_url="django:assets:maintenance_rule_list",
        active_match="/assets/manutenzione/regole/",
        is_subitem=True,
        parent=impostazioni,
        sort_order=92,
        is_visible=True,
    )

    # ── OPERATIONS ───────────────────────────────────────────────────────────

    AssetSidebarButton.objects.create(
        code="manut_schedule",
        section="OPERATIONS",
        label="Prossime manutenzioni",
        target_url="django:assets:maintenance_schedule",
        active_match="/assets/manutenzione/prossime/",
        is_subitem=False,
        parent=None,
        sort_order=10,
        is_visible=True,
    )

    AssetSidebarButton.objects.create(
        code="contratti",
        section="OPERATIONS",
        label="Contratti assistenza",
        target_url="django:assets:assistance_contract_list",
        active_match="/assets/manutenzione/contratti/",
        is_subitem=False,
        parent=None,
        sort_order=20,
        is_visible=True,
    )


def unseed(apps, schema_editor):
    # Non è possibile ripristinare lo stato precedente in modo affidabile
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("assets", "0051_asset_type_fonia_carroponte"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
