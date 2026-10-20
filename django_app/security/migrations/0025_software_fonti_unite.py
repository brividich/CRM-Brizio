"""Migration 0025 — Inventario software: una installazione = una riga, anche con più fonti.

Prima la chiave di un'installazione includeva la fonte: lo stesso software sullo stesso PC
arrivato da WatchGuard e da Defender diventava due righe. Ora la chiave è (host, vendor,
prodotto, versione) e ``fonti`` elenca chi lo vede.

Dati esistenti: le righe che oggi condividono la nuova chiave vengono fuse in una sola
(le fonti si sommano, gli impatti CVE passano alla riga tenuta). Le righe dei firmware SNMP
non si toccano: un dispositivo non è un PC e ha la sua chiave per fonte.
"""
import hashlib

from django.db import migrations, models

FIRMWARE = "snmp_firmware"


def _chiave(host, vendor, product, version):
    seed = "|".join(["sw", host, vendor, product, str(version).strip().lower()])
    return hashlib.sha256(seed.encode()).hexdigest()


def fondi(apps, schema_editor):
    Install = apps.get_model("security", "SoftwareInstallation")
    Impact = apps.get_model("security", "SecurityCveImpact")

    gruppi = {}
    for pk, source, host, vendor, product, version, detected, seen in Install.objects.exclude(
        source_kind=FIRMWARE
    ).values_list("pk", "source_kind", "host", "vendor", "product", "version_raw", "still_detected", "last_seen_at").iterator():
        gruppi.setdefault(_chiave(host, vendor, product, version), []).append((pk, source, detected, seen))

    for chiave, righe in gruppi.items():
        # Tiene la riga rilevata più di recente (a parità, la più vecchia per id: la prima nata).
        righe.sort(key=lambda r: (not r[2], -(r[3].timestamp() if r[3] else 0), r[0]))
        tenuta = righe[0][0]
        altre = [r[0] for r in righe[1:]]
        fonti = sorted({source for _pk, source, detected, _seen in righe if detected})
        if altre:
            Impact.objects.filter(installation_id__in=altre).update(installation_id=tenuta)
            Install.objects.filter(pk__in=altre).delete()
        Install.objects.filter(pk=tenuta).update(dedup_key=chiave, fonti=fonti)

    Install.objects.filter(source_kind=FIRMWARE, still_detected=True).update(fonti=[FIRMWARE])


def annulla(apps, schema_editor):
    # Le righe fuse non si possono ricostruire: la chiave senza fonte resta valida per l'import.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("security", "0024_fonte_defender_endpoint"),
    ]

    operations = [
        migrations.AddField(
            model_name="softwareinstallation",
            name="fonti",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.RunPython(fondi, annulla),
    ]
