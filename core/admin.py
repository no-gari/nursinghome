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

class FacilityNonCoveredInline(admin.StackedInline):
    model = models.FacilityNonCovered
    extra = 0
    readonly_fields = ('title', 'content')
    can_delete = False

@admin.register(models.Facility)
class FacilityAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'kind', 'grade', 'capacity', 'occupancy', 'waiting', 'availability', 'view_detail_link')
    list_filter = ('kind', 'grade', 'availability')
    search_fields = ('code', 'name')
    readonly_fields = ('code', 'name', 'kind', 'grade', 'capacity', 'occupancy', 'waiting', 'availability')

    inlines = [
        FacilityBasicInline,
        FacilityEvaluationInline,
        FacilityStaffInline,
        FacilityProgramInline,
        FacilityLocationInline,
        FacilityHomepageInline,
        FacilityNonCoveredInline,
    ]

    def view_detail_link(self, obj):
        if obj.code:
            url = reverse('core:facility_detail', args=[obj.code])
            return format_html('<a href="{}" target="_blank">상세보기</a>', url)
        return '-'
    view_detail_link.short_description = '상세페이지'

    def has_add_permission(self, request):
        return False  # 크롤링으로만 데이터 생성

# 개별 모델들도 등록 (필요시 직접 접근)
@admin.register(models.FacilityBasic)
class FacilityBasicAdmin(admin.ModelAdmin):
    list_display = ('facility', 'title', 'content_preview')
    list_filter = ('title',)
    search_fields = ('facility__name', 'title', 'content')

    def content_preview(self, obj):
        return obj.content[:50] + '...' if len(obj.content) > 50 else obj.content
    content_preview.short_description = '내용 미리보기'

@admin.register(models.FacilityEvaluation)
class FacilityEvaluationAdmin(admin.ModelAdmin):
    list_display = ('facility', 'title', 'content_preview')
    list_filter = ('title',)
    search_fields = ('facility__name', 'title', 'content')

    def content_preview(self, obj):
        return obj.content[:50] + '...' if len(obj.content) > 50 else obj.content
    content_preview.short_description = '내용 미리보기'

@admin.register(models.FacilityStaff)
class FacilityStaffAdmin(admin.ModelAdmin):
    list_display = ('facility', 'title', 'content_preview')
    list_filter = ('title',)
    search_fields = ('facility__name', 'title', 'content')

    def content_preview(self, obj):
        return obj.content[:50] + '...' if len(obj.content) > 50 else obj.content
    content_preview.short_description = '내용 미리보기'

@admin.register(models.FacilityProgram)
class FacilityProgramAdmin(admin.ModelAdmin):
    list_display = ('facility', 'title', 'content_preview')
    list_filter = ('title',)
    search_fields = ('facility__name', 'title', 'content')

    def content_preview(self, obj):
        return obj.content[:50] + '...' if len(obj.content) > 50 else obj.content
    content_preview.short_description = '내용 미리보기'