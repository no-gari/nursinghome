from django.urls import path
from .views import (
    LoginPageView,
    kakao_login,
    kakao_callback,
    logout_view,
)

urlpatterns = [
    path("auth/login/", LoginPageView.as_view(), name="login-page"),
    path("auth/kakao/login/", kakao_login, name="kakao-login"),
    path("auth/kakao/callback/", kakao_callback, name="kakao-callback"),
    path("auth/logout/", logout_view, name="auth-logout"),
]
