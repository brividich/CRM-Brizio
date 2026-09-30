from django.db import migrations, models

_VPN_WORDS = ("vpn", "ssl", "ipsec", "pptp", "l2tp", "ikev2")


def backfill_kind(apps, schema_editor):
    """Righe gia' salvate: il tipo si ricava dal metodo. Metodo vuoto = si assume VPN, come
    faceva il parser prima di distinguere i tipi (i rifiuti VPN non avevano la colonna)."""
    Access = apps.get_model("security", "SecurityVpnAccess")
    for row in Access.objects.filter(kind="").only("id", "method").iterator():
        method = (row.method or "").lower()
        if not method or any(word in method for word in _VPN_WORDS):
            kind = "vpn"
        elif "firewall" in method:
            kind = "firewall"
        elif "guest" in method or "portal" in method:
            kind = "guest"
        else:
            kind = "other"
        Access.objects.filter(pk=row.pk).update(kind=kind)


class Migration(migrations.Migration):

    dependencies = [
        ("security", "0012_securityvpnaccess"),
    ]

    operations = [
        migrations.AddField(
            model_name="securityvpnaccess",
            name="kind",
            field=models.CharField(blank=True, db_index=True, default="", max_length=16),
        ),
        migrations.AddField(
            model_name="securityvpnaccess",
            name="reason",
            field=models.CharField(blank=True, max_length=300),
        ),
        migrations.RunPython(backfill_kind, migrations.RunPython.noop),
    ]
