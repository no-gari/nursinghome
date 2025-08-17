from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

# DRF 라우터 설정
router = DefaultRouter()
router.register(r'facilities', views.FacilityViewSet)
router.register(r'chat/sessions', views.ChatSessionViewSet, basename='chat-session')

app_name = 'core'

urlpatterns = [
    # Django 템플릿 뷰
    path('', views.main_view, name='main'),
    path('chat/', views.chat_view, name='chat'),
    path('facility/<str:code>/', views.facility_detail, name='facility_detail'),

    # DRF API
    path('api/', include(router.urls)),
    path('api/chat/', views.ChatbotAPI.as_view(), name='chatbot_api'),
    path('api/initialize-rag/', views.initialize_rag, name='initialize_rag'),
]
