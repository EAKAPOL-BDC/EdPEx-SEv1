import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies=[('governance','0003_accessrequest_privacy_contact_snapshot_and_more'),('rounds','0004_collection_data_kind'),migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations=[migrations.CreateModel(name='WorkspaceRefresh',fields=[
        ('id',models.UUIDField(primary_key=True,default=uuid.uuid4,editable=False,serialize=False)),
        ('plan_hash',models.CharField(max_length=64)),('manifest',models.JSONField(default=dict)),
        ('summary',models.JSONField(default=dict)),('revision',models.CharField(max_length=80)),('reason',models.TextField()),
        ('database_transaction',models.BigIntegerField(null=True)),('status',models.CharField(max_length=12,default='running')),
        ('created_at',models.DateTimeField(auto_now_add=True)),('completed_at',models.DateTimeField(null=True)),
        ('scope',models.ForeignKey(to='accounts.accessscope',on_delete=django.db.models.deletion.PROTECT)),
        ('actor',models.ForeignKey(to=settings.AUTH_USER_MODEL,on_delete=django.db.models.deletion.PROTECT)),
    ])]
