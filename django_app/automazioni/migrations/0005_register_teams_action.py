from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ('automazioni', '0004_automation_composite_indexes'), 
    ]
    operations = [
        migrations.AlterField(
            model_name='automationaction',
            name='action_type',
            field=models.CharField(choices=[
                ('send_email', 'Send email'),
                ('insert_record', 'Insert record'),
                ('update_record', 'Update record'),
                ('update_dashboard_metric', 'Update dashboard metric'),
                ('write_log', 'Write log'),
                ('delay_schedule', 'Delay / Schedule (giorni)'),
                ('teams_webhook', 'Microsoft Teams Webhook')
            ], max_length=40),
        ),
    ]