import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("contatori", "0050_acl_fabbisogno_letture_mensili"),
    ]

    operations = [
        migrations.AddField(
            model_name="dispositivosnmp",
            name="porte_totali",
            field=models.PositiveSmallIntegerField(default=0, help_text="Porte disegnate nel pannello frontale (firewall, switch). 0 = non disegnare."),
        ),
        migrations.CreateModel(
            name="PortaApparato",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("numero", models.PositiveSmallIntegerField()),
                ("nome", models.CharField(blank=True, help_text="Es. «WAN1», «Uplink core», «Ufficio tecnico».", max_length=60)),
                ("tipo", models.CharField(choices=[("LAN", "LAN"), ("WAN", "WAN / Internet"), ("SFP", "Fibra / SFP"), ("POE", "LAN con PoE"), ("MGMT", "Gestione")], default="LAN", max_length=6)),
                ("vlan", models.CharField(blank=True, max_length=40)),
                ("collegato_testo", models.CharField(blank=True, help_text="Cosa c'è collegato se non è un apparato del modulo.", max_length=120)),
                ("nota", models.CharField(blank=True, max_length=200)),
                ("collegato_dispositivo", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="collegato_da_porte", to="contatori.dispositivosnmp")),
                ("collegato_macchina", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="collegato_da_porte", to="contatori.macchina")),
                ("dispositivo", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="porte_disegnate", to="contatori.dispositivosnmp")),
            ],
            options={"ordering": ["dispositivo", "numero"]},
        ),
        migrations.AddConstraint(
            model_name="portaapparato",
            constraint=models.UniqueConstraint(fields=("dispositivo", "numero"), name="cont_porta_disp_numero"),
        ),
    ]
