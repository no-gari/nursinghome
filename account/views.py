# accounts/views.py (개선된 버전)
import os
import requests
import logging
from django.conf import settings
from django.contrib.auth import get_user_model, login, logout
from django.shortcuts import redirect
from django.views.generic import TemplateView

User = get_user_model()
logger = logging.getLogger(__name__)

def _get_env(name, default=""):
    return getattr(settings, name, os.getenv(name, default))


class LoginPageView(TemplateView):
    template_name = "auth/login.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        next_url = self.request.GET.get("next", "/")
        reason = self.request.GET.get("reason", "")

        # 채팅 접근 시 특별한 메시지 표시
        if reason == "chat":
            ctx["login_message"] = "채팅을 이용하려면 로그인이 필요합니다."

        ctx["kakao_login_url"] = f"/account/auth/kakao/login/?next={next_url}"
        ctx["next_url"] = next_url
        return ctx


def kakao_login(request):
    # 카카오 로그인 URL 생성
    kakao_auth_url = f"https://kauth.kakao.com/oauth/authorize?client_id={settings.KAKAO_REST_API_KEY}&redirect_uri={settings.KAKAO_REDIRECT_URI}&response_type=code"
    return redirect(kakao_auth_url)


def kakao_callback(request):
    code = request.GET.get('code')

    if not code:
        return redirect('login-page')

    # 1. 액세스 토큰 받기
    token_url = "https://kauth.kakao.com/oauth/token"
    token_data = {
        'grant_type': 'authorization_code',
        'client_id': settings.KAKAO_REST_API_KEY,
        'redirect_uri': settings.KAKAO_REDIRECT_URI,
        'code': code,
    }

    token_response = requests.post(token_url, data=token_data)
    token_json = token_response.json()
    access_token = token_json.get('access_token')

    if not access_token:
        return redirect('login-page')

    # 2. 사용자 정보 받기
    user_info_url = "https://kapi.kakao.com/v2/user/me"
    headers = {'Authorization': f'Bearer {access_token}'}
    user_response = requests.get(user_info_url, headers=headers)
    user_json = user_response.json()

    # 3. 사용자 생성 또는 로그인
    kakao_id = user_json.get('id')
    kakao_account = user_json.get('kakao_account', {})
    email = kakao_account.get('email')
    nickname = kakao_account.get('profile', {}).get('nickname', f'kakao_user_{kakao_id}')

    # 사용자 찾기 또는 생성
    username = f'kakao_{kakao_id}'
    user, created = User.objects.get_or_create(
        username=username,
        defaults={
            'email': email or '',
            'first_name': nickname,
        }
    )

    # 로그인 처리
    login(request, user)
    return redirect('core:main')


def logout_view(request):
    logout(request)
    return redirect('core:main')
