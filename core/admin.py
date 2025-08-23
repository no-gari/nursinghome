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

class HospitalImageInline(admin.TabularInline):
    model = models.HospitalImage
    extra = 0
    can_delete = False
    fields = ('image_preview', 'original_url', 'created_at')
    readonly_fields = ('image_preview', 'original_url', 'created_at')

    def image_preview(self, obj):
        if obj.image:
            return format_html('<a href="{}" target="_blank"><img src="{}" width="100" height="75" style="object-fit: cover; border-radius: 5px;" /></a>',
                              obj.image.url, obj.image.url)
        return '-'
    image_preview.short_description = '이미지'

    def has_add_permission(self, request, obj=None):
        return False


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


@admin.register(models.FacilityBasic)
class FacilityBasicAdmin(admin.ModelAdmin):
    list_display = ('facility', 'title', 'created_at')
    list_filter = ('created_at', 'facility__sido', 'facility__sigungu')
    search_fields = ('facility__name', 'title', 'content')
    readonly_fields = ('facility', 'title', 'content', 'created_at', 'updated_at')

    def has_add_permission(self, request):
        return False


@admin.register(models.FacilityEvaluation)
class FacilityEvaluationAdmin(admin.ModelAdmin):
    list_display = ('facility', 'title', 'created_at')
    list_filter = ('created_at', 'facility__sido', 'facility__sigungu')
    search_fields = ('facility__name', 'title', 'content')
    readonly_fields = ('facility', 'title', 'content', 'created_at', 'updated_at')

    def has_add_permission(self, request):
        return False


@admin.register(models.FacilityStaff)
class FacilityStaffAdmin(admin.ModelAdmin):
    list_display = ('facility', 'title', 'created_at')
    list_filter = ('created_at', 'facility__sido', 'facility__sigungu')
    search_fields = ('facility__name', 'title', 'content')
    readonly_fields = ('facility', 'title', 'content', 'created_at', 'updated_at')

    def has_add_permission(self, request):
        return False


@admin.register(models.FacilityProgram)
class FacilityProgramAdmin(admin.ModelAdmin):
    list_display = ('facility', 'title', 'created_at')
    list_filter = ('created_at', 'facility__sido', 'facility__sigungu')
    search_fields = ('facility__name', 'title', 'content')
    readonly_fields = ('facility', 'title', 'content', 'created_at', 'updated_at')

    def has_add_permission(self, request):
        return False


@admin.register(models.FacilityLocation)
class FacilityLocationAdmin(admin.ModelAdmin):
    list_display = ('facility', 'title', 'created_at')
    list_filter = ('created_at', 'facility__sido', 'facility__sigungu')
    search_fields = ('facility__name', 'title', 'content')
    readonly_fields = ('facility', 'title', 'content', 'created_at', 'updated_at')

    def has_add_permission(self, request):
        return False


@admin.register(models.FacilityHomepage)
class FacilityHomepageAdmin(admin.ModelAdmin):
    list_display = ('facility', 'title', 'created_at')
    list_filter = ('created_at', 'facility__sido', 'facility__sigungu')
    search_fields = ('facility__name', 'title', 'content')
    readonly_fields = ('facility', 'title', 'content', 'created_at', 'updated_at')

    def has_add_permission(self, request):
        return False


@admin.register(models.FacilityNonCovered)
class FacilityNonCoveredAdmin(admin.ModelAdmin):
    list_display = ('facility', 'title', 'created_at')
    list_filter = ('created_at', 'facility__sido', 'facility__sigungu')
    search_fields = ('facility__name', 'title', 'content')
    readonly_fields = ('facility', 'title', 'content', 'created_at', 'updated_at')

    def has_add_permission(self, request):
        return False


@admin.register(models.Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ('name', 'facility_count', 'created_at')
    list_filter = ('created_at',)
    search_fields = ('name',)
    filter_horizontal = ('facilities',)

    def facility_count(self, obj):
        return obj.facilities.count()
    facility_count.short_description = '시설 수'


@admin.register(models.FacilityImage)
class FacilityImageAdmin(admin.ModelAdmin):
    list_display = ('facility', 'image_preview', 'original_url', 'created_at')
    list_filter = ('created_at', 'facility__sido', 'facility__sigungu')
    search_fields = ('facility__name', 'original_url')
    readonly_fields = ('facility', 'image', 'original_url', 'created_at', 'updated_at')

    def image_preview(self, obj):
        if obj.image:
            return format_html('<img src="{}" width="50" height="50" />', obj.image.url)
        return '-'
    image_preview.short_description = '이미지'

    def has_add_permission(self, request):
        return False


@admin.register(models.ChatHistory)
class ChatHistoryAdmin(admin.ModelAdmin):
    list_display = ('user', 'query_preview', 'created_at')
    list_filter = ('created_at', 'user')
    search_fields = ('user__username', 'query', 'answer')
    readonly_fields = ('user', 'query', 'answer', 'created_at', 'updated_at')

    def query_preview(self, obj):
        return obj.query[:50] + '...' if len(obj.query) > 50 else obj.query
    query_preview.short_description = '질문'

    def has_add_permission(self, request):
        return False


@admin.register(models.Hospital)
class HospitalAdmin(admin.ModelAdmin):
    list_display = ('name', 'grade', 'establishment_type', 'image_status', 'sido', 'sigungu')
    list_filter = ('grade', 'establishment_type', 'has_images', 'sido', 'sigungu', 'establishment_date')
    search_fields = ('code', 'name', 'phone', 'location')
    filter_horizontal = ('tags',)
    readonly_fields = ('code', 'name', 'grade', 'establishment_type', 'phone', 'establishment_date',
                      'bed_count', 'operation_facility', 'doctor_count', 'specialist_by_department',
                      'department_specialists', 'other_staff', 'consultation_hours', 'medical_fee_info',
                      'location', 'has_images', 'sido', 'sigungu', 'homepage_url', 'summary', 'created_at', 'updated_at')

    inlines = [HospitalImageInline]

    fieldsets = (
        ('기본 정보', {
            'fields': ('code', 'name', 'grade', 'establishment_type', 'phone', 'establishment_date')
        }),
        ('시설 정보', {
            'fields': ('bed_count', 'operation_facility', 'has_images')
        }),
        ('인력 정보', {
            'fields': ('doctor_count', 'specialist_by_department', 'department_specialists', 'other_staff')
        }),
        ('진료 정보', {
            'fields': ('consultation_hours', 'medical_fee_info')
        }),
        ('위치 정보', {
            'fields': ('location', 'sido', 'sigungu')
        }),
        ('기타 정보', {
            'fields': ('homepage_url', 'summary', 'tags')
        }),
        ('시스템 정보', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        })
    )

    def image_status(self, obj):
        if obj.has_images:
            image_count = obj.images.count()
            return format_html('<span style="color: green;">⚫ 있음 ({}장)</span>', image_count)
        else:
            return format_html('<span style="color: red;">⚪ 없음</span>')
    image_status.short_description = '이미지'
    image_status.admin_order_field = 'has_images'

    def has_add_permission(self, request):
        return False  # 크롤링으로만 데이터 생성


@admin.register(models.HospitalImage)
class HospitalImageAdmin(admin.ModelAdmin):
    list_display = ('hospital', 'image_preview', 'original_url', 'created_at')
    list_filter = ('created_at', 'hospital__sido', 'hospital__sigungu')
    search_fields = ('hospital__name', 'hospital__code', 'original_url')
    readonly_fields = ('hospital', 'image', 'original_url', 'created_at', 'updated_at', 'large_image_preview')

    def image_preview(self, obj):
        if obj.image:
            return format_html('<a href="{}" target="_blank"><img src="{}" width="100" height="75" style="object-fit: cover; border-radius: 5px;" /></a>',
                              obj.image.url, obj.image.url)
        return '-'
    image_preview.short_description = '이미지'

    def large_image_preview(self, obj):
        if obj.image:
            return format_html('<img src="{}" style="max-width: 800px; max-height: 600px;" />', obj.image.url)
        return '-'
    large_image_preview.short_description = '이미지 미리보기'

    def has_add_permission(self, request):
        return False
