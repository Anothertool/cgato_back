from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('surgeries', '0008_remove_surgery_surgery_amount_paid_nonnegative_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='surgery',
            name='iol_model',
            field=models.CharField(
                blank=True,
                choices=[
                    ('PURE_DEN00V', 'PURE DEN00V'),
                    ('PURE_TORICA_DET', 'PURE + TORICA DET'),
                    ('MULTI_DRN00V', 'MULTI DRN00V'),
                    ('MULTI_TORICA_DRT', 'MULTI + TORICA DRT'),
                    ('HOYA_XY1', 'HOYA XY1'),
                    ('EYEHANCE_TORICA', 'Eyhance tórica J&J'),
                    ('EDOF_BVI_SERENITY', 'EDOF BVI Serenity'),
                    ('EDOF_TORICA', 'EDOF tórica'),
                    ('OTHER', 'Otros'),
                ],
                max_length=255,
            ),
        ),
    ]
