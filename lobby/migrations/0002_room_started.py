from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ("lobby", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="room",
            name="started",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="room",
            name="started_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
