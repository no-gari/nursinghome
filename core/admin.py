from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from . import models

class FacilityBasicInline(admin.TabularInline):
    model = models.FacilityBasic
    extra = 0
    readonly_fields = ('title', 'content')
    can_delete = False

class FacilityEvaluationInline(admin.TabularInline):
    model = models.FacilityEvaluation
    extra = 0
    readonly_fields = ('title', 'content')
    can_delete = False

class FacilityStaffInline(admin.TabularInline):
    model = models.FacilityStaff
    extra = 0
    readonly_fields = ('title', 'content')
    can_delete = False

class FacilityProgramInline(admin.TabularInline):
    model = models.FacilityProgram
    extra = 0
    readonly_fields = ('title', 'content')
    can_delete = False

class FacilityLocationInline(admin.StackedInline):
    model = models.FacilityLocation
    extra = 0
    readonly_fields = ('title', 'content')
    can_delete = False

class FacilityHomepageInline(admin.StackedInline):
    model = models.FacilityHomepage
    extra = 0
    readonly_fields = ('title', 'content')
    can_delete = False

class BlogInline(admin.TabularInline):
    model = models.Blog
    extra = 0
    readonly_fields = ('title', 'link', 'description', 'bloggername', 'bloggerlink', 'postdate', 'created_at')
    can_delete = False
    fields = ('title', 'link', 'bloggername', 'postdate', 'created_at')

class FacilityNonCoveredInline(admin.StackedInline):
    model = models.FacilityNonCovered
    extra = 0
    readonly_fields = ('title', 'content')
    can_delete = False

@admin.register(models.Facility)
class FacilityAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'kind', 'grade', 'capacity', 'occupancy', 'waiting', 'availability', 'has_images', 'blog_count', 'view_detail_link')
    list_filter = ('kind', 'grade', 'availability', 'has_images')
    search_fields = ('code', 'name')
    readonly_fields = ('code', 'name', 'kind', 'grade', 'capacity', 'occupancy', 'waiting', 'availability', 'has_images')

    inlines = [
        FacilityBasicInline,
        FacilityEvaluationInline,
        FacilityStaffInline,
        FacilityProgramInline,
        FacilityLocationInline,
        FacilityHomepageInline,
        FacilityNonCoveredInline,
        BlogInline,
    ]

    def blog_count(self, obj):
        return obj.blogs.count()
    blog_count.short_description = '블로그 수'

    def view_detail_link(self, obj):
        if obj.code:
            url = reverse('core:facility_detail', args=[obj.code])
            return format_html('<a href="{}" target="_blank">상세보기</a>', url)
        return '-'
    view_detail_link.short_description = '상세페이지'

    def has_add_permission(self, request):
        return False  # 크롤링으로만 데이터 생성

@admin.register(models.Blog)
class BlogAdmin(admin.ModelAdmin):
    list_display = ('facility', 'title_preview', 'bloggername', 'postdate', 'created_at', 'view_blog_link')
    list_filter = ('postdate', 'created_at', 'facility__sido', 'facility__sigungu')
    search_fields = ('facility__name', 'title', 'description', 'bloggername')
    readonly_fields = ('facility', 'title', 'link', 'description', 'bloggername', 'bloggerlink', 'postdate', 'created_at', 'updated_at')

    def title_preview(self, obj):
        return obj.title[:30] + '...' if len(obj.title) > 30 else obj.title
    title_preview.short_description = '제목'

    def view_blog_link(self, obj):
        if obj.link:
            return format_html('<a href="{}" target="_blank">보기</a>', obj.link)
        return '-'
    view_blog_link.short_description = '블로그 링크'

    def has_add_permission(self, request):
        return False  # API를 통해서만 데이터 생성

    def has_change_permission(self, request, obj=None):
        return False  # 수정 불가
