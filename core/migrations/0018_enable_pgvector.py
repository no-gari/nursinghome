# core/migrations/0018_enable_pgvector.py
from django.db import migrations
from pgvector.django import VectorExtension

class Migration(migrations.Migration):
    dependencies = [
        ("core", "0017_alter_hospital_code"),
    ]
    operations = [
        VectorExtension(),  # CREATE EXTENSION IF NOT EXISTS vector;
    ]
