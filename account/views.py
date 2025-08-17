# accounts/views.py
import os
import time
import requests
from datetime import datetime, timedelta, timezone

from django.conf import settings
from django.contrib.auth import get_user_model, login, logout
from django.http import HttpResponseBadRequest, HttpResponseRedirect, JsonResponse
from django.shortcuts import redirect, render
from django.utils.crypto import get_random_string
from django.views import View
from django.views.generic import TemplateView
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import ensure_csrf_cookie

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import SocialAccount
from .serializers import MeSerializer

User = get_user_model()

KAUTH_AUTHORIZE = "https://kauth.kakao.com/oauth/authorize"
KAUTH_TOKEN = "https://kauth.kakao.com/oauth/token"
KAPI_ME = "https://kapi.kakao.com/v2/user/me"

def _get_env(name, default=""):
    return getattr(settings, name, os.getenv(name, default))

def build_redirect(next_url):
    return f"{_get_env('KAKAO_REDIRECT_URI')}?next={next_url or ''}"

class LoginPageView(TemplateView):
    template_name = "auth/login.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        next_url = self.request.GET.get("next", "/")
        ctx["kakao_login_url"] = (
            f"/account/auth/kakao/login/?next={next_url}"
        )
        return ctx

class KakaoLoginStartView(View):
    def get(self, request):
        client_id = _get_env("KAKAO_REST_API_KEY")
        redirect_uri = _get_env("KAKAO_REDIRECT_URI")
        state = get_random_string(16)
        request.session["kakao_oauth_state"] = state

        next_url = request.GET.get("next", "/")
        request.session["login_next"] = next_url

        scope = "account_email profile_nickname"  # profile_image 제거
        authorize_url = (
            f"{KAUTH_AUTHORIZE}"
            f"?client_id={client_id}"
            f"&redirect_uri={redirect_uri}"
            f"&response_type=code"
            f"&state={state}"
            f"&scope={scope}"
        )
        return redirect(authorize_url)

class KakaoCallbackView(View):
    def get(self, request):
        code = request.GET.get("code")
        state = request.GET.get("state")
        saved_state = request.session.get("kakao_oauth_state")

        # 디버깅용 로그 추가
        print(f"받은 state: {state}")
        print(f"저장된 state: {saved_state}")
        print(f"세션 키들: {list(request.session.keys())}")

        if not code:
            return HttpResponseBadRequest("Authorization code가 없습니다")

        if not saved_state:
            return HttpResponseBadRequest("세션에 저장된 state가 없습니다. 다시 로그인을 시도해주세요")

        if state != saved_state:
            return HttpResponseBadRequest("OAuth state가 일치하지 않습니다. 다시 로그인을 시도해주세요")

        # state 사�� 후 삭제
        del request.session["kakao_oauth_state"]

        # 1) 토큰 교환
        data = {
            "grant_type": "authorization_code",
            "client_id": _get_env("KAKAO_REST_API_KEY"),
            "redirect_uri": _get_env("KAKAO_REDIRECT_URI"),
            "code": code,
        }
        client_secret = _get_env("KAKAO_CLIENT_SECRET")
        if client_secret:
            data["client_secret"] = client_secret

        token_res = requests.post(KAUTH_TOKEN, data=data, timeout=10)
        token_res.raise_for_status()
        token_json = token_res.json()

        access_token = token_json.get("access_token")
        refresh_token = token_json.get("refresh_token")
        expires_in = token_json.get("expires_in", 0)

        # 2) 사용자 정보
        headers = {"Authorization": f"Bearer {access_token}"}
        me_res = requests.get(KAPI_ME, headers=headers, timeout=10)
        me_res.raise_for_status()
        me = me_res.json()

        kakao_id = str(me.get("id"))
        kakao_account = me.get("kakao_account", {}) or {}
        profile = kakao_account.get("profile", {}) or {}

        email = kakao_account.get("email")
        nickname = profile.get("nickname") or f"user_{kakao_id}"
        profile_image = profile.get("profile_image_url")

        # 3) 유저 조회/생성
        user = None
        if email:
            user, _ = User.objects.get_or_create(
                email=email, defaults={"username": email.split("@")[0]}
            )
        else:
            # 이메일 미동의 시 username 임의 생성
            user, _ = User.objects.get_or_create(
                username=f"kakao_{kakao_id}",
                defaults={"email": ""},
            )

        # 4) 소셜 계정 연결/갱신
        sa, _ = SocialAccount.objects.get_or_create(
            provider="kakao", kakao_id=kakao_id, defaults={"user": user}
        )
        if sa.user_id != user.id:
            sa.user = user
        sa.email = email or sa.email
        sa.nickname = nickname or sa.nickname
        sa.profile_image = profile_image or sa.profile_image
        sa.access_token = access_token or ""
        sa.refresh_token = refresh_token or ""
        if expires_in:
            sa.token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
        sa.save()

        # 5) 세션 로그인
        login(request, user)
        request.session.modified = True  # 프론트 즉시 반영하도록 세션 플래그
        next_url = request.session.pop("login_next", "/") or "/"
        if "application/json" in (request.headers.get("Accept") or ""):
            return JsonResponse({
                "ok": True,
                "next": next_url,
                "user": MeSerializer(user).data,
                "authenticated": True,
            })
        return HttpResponseRedirect(next_url)

@method_decorator(ensure_csrf_cookie, name='dispatch')
class MeAPIView(APIView):
    """프론트가 주기적으로 호출하여 로그인 상태 동기화.
    - 항상 JSON
    - 캐시 방지 헤더
    """
    authentication_classes = []  # 기본 세션 인증 사용
    permission_classes = []

    def get(self, request):
        resp_data = {"authenticated": request.user.is_authenticated}
        if request.user.is_authenticated:
            resp_data["user"] = MeSerializer(request.user).data
        else:
            resp_data["user"] = None
        resp = Response(resp_data)
        # 캐시 방지 (Safari 등에서 세션 쿠키 재사용 시 구버전 캐시 회피)
        resp["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp["Pragma"] = "no-cache"
        resp["Expires"] = "0"
        return resp

def logout_view(request):
    """로그아웃 후 JSON/Redirect 모두 지원.
    - GET/POST 모두 허용 (프론트 fetch POST 사용 시 편의)
    """
    logout(request)
    next_url = request.GET.get("next") or "/"
    if "application/json" in (request.headers.get("Accept") or ""):
        resp = JsonResponse({"ok": True, "authenticated": False})
        resp["Cache-Control"] = "no-store"
        return resp
    return redirect(next_url)
