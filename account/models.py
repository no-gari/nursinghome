# accounts/models.py
from django.conf import settings
from django.db import models

class SocialAccount(models.Model):
    PROVIDER_CHOICES = (("kakao", "Kakao"),)

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="social_accounts",
    )
    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES, default="kakao")
    kakao_id = models.CharField(max_length=64, unique=True, db_index=True)

    email = models.EmailField(blank=True, null=True)
    nickname = models.CharField(max_length=100, blank=True)
    profile_image = models.URLField(blank=True)

    access_token = models.CharField(max_length=512, blank=True)
    refresh_token = models.CharField(max_length=512, blank=True)
    token_expires_at = models.DateTimeField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = (("provider", "kakao_id"),)

    def __str__(self):
        return f"{self.provider}:{self.kakao_id} -> {self.user}"
