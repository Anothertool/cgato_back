from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('cash', '0002_cashentry_surgery_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='cashentry',
            name='import_reference',
            field=models.CharField(
                max_length=255, unique=True, null=True, blank=True, editable=False,
            ),
        ),
    ]
