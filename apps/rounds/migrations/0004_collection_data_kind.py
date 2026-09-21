from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies=[('rounds','0003_population_locking_and_retired_bindings')]
    operations=[
        migrations.AddField('collectionround','data_kind',models.CharField(max_length=12,default='real',choices=[('real','ข้อมูลจริง'),('synthetic','ข้อมูลสมมุติ')])),
        migrations.AddField('collectionround','schedule_confirmed',models.BooleanField(default=True)),
    ]
