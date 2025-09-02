from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings

class Migration(migrations.Migration):
    dependencies = [
        ('core', '0023_alter_facilityevaluation_options_facility_location'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ChatSession',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('title', models.CharField(blank=True, help_text='첫 질문 요약 등을 제목으로 사용', max_length=255)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='chat_sessions', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': '채팅 세션',
                'verbose_name_plural': '채팅 세션',
                'ordering': ['-updated_at'],
            },
        ),
        migrations.AddField(
            model_name='chathistory',
            name='session',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='messages', to='core.chatsession'),
        ),
    ]

