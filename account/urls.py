# accounts/urls.py
from django.urls import path
from .views import (
    LoginPageView,
    KakaoLoginStartView,
    KakaoCallbackView,
    MeAPIView,
    logout_view,
)

urlpatterns = [
    path("auth/login/", LoginPageView.as_view(), name="login-page"),
    path("auth/kakao/login/", KakaoLoginStartView.as_view(), name="kakao-login"),
    path("auth/kakao/callback/", KakaoCallbackView.as_view(), name="kakao-callback"),
    path("auth/me/", MeAPIView.as_view(), name="auth-me"),
    path("auth/logout/", logout_view, name="auth-logout"),
]
