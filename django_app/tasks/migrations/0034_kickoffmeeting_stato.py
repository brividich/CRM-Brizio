from django.db import migrations, models


def backfill_stato(apps, schema_editor):
    """Gli incontri gia' esistenti che hanno un verbale (o che sono nel passato) sono «svolti».

    Prima di questa migrazione non esisteva la distinzione fra incontro pianificato e
    incontro tenuto: il form chiedeva tutto insieme. Un record con `note`, `next_steps`
    o `problemi_aperti` valorizzati e' inequivocabilmente un incontro gia' fatto; per gli
    altri si usa la data come euristica (passata = svolto, futura = pianificato).
    """
    from django.db.models import Q
    from django.utils import timezone

    KickoffMeeting = apps.get_model("tasks", "KickoffMeeting")
    today = timezone.localdate()
    (
        KickoffMeeting.objects.filter(
            Q(note__gt="")
            | Q(next_steps__gt="")
            | Q(problemi_aperti__gt="")
            | Q(data__lt=today)
        ).update(stato="SVOLTO")
    )


def noop_reverse(apps, schema_editor):
    """Il rollback rimuove la colonna: non c'e' nulla da ripristinare."""


class Migration(migrations.Migration):

    dependencies = [
        ("tasks", "0033_merge_20260713_1512"),
    ]

    operations = [
        migrations.AddField(
            model_name="kickoffmeeting",
            name="stato",
            field=models.CharField(
                choices=[
                    ("PIANIFICATO", "Pianificato"),
                    ("SVOLTO", "Svolto"),
                    ("ANNULLATO", "Annullato"),
                ],
                db_index=True,
                default="PIANIFICATO",
                help_text=(
                    "Pianificato: convocazione inviata, incontro non ancora tenuto. "
                    "Svolto: verbale registrato. Annullato: incontro non tenuto."
                ),
                max_length=16,
                verbose_name="Stato",
            ),
        ),
        migrations.AddField(
            model_name="kickoffmeeting",
            name="svolto_at",
            field=models.DateTimeField(
                blank=True, null=True, verbose_name="Esito registrato il"
            ),
        ),
        migrations.RunPython(backfill_stato, noop_reverse),
    ]
