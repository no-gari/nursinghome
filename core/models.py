from django.db import models
from django.conf import settings

# Create your models here.

class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        abstract = True

class Facility(TimestampedModel):
    code = models.CharField(max_length=32, unique=True, help_text="URL 내 고유 코드")
    name = models.CharField(max_length=255)
    kind = models.CharField(max_length=32, blank=True)
    grade = models.CharField(max_length=16, blank=True)
    availability = models.CharField(max_length=16, blank=True)
    capacity = models.PositiveIntegerField(null=True, blank=True, verbose_name='정원')
    occupancy = models.PositiveIntegerField(null=True, blank=True, verbose_name='현원')
    waiting = models.PositiveIntegerField(null=True, blank=True, verbose_name='대기')
    has_images = models.BooleanField(default=False, verbose_name='이미지 존재 여부', help_text='크롤링 가능하고 이미지가 있으면 True')
    class Meta:
        ordering = ["name"]
        verbose_name = "시설"
        verbose_name_plural = "시설"
    def __str__(self):
        return f"{self.name} ({self.code})"

class FacilityBasic(TimestampedModel):
    facility = models.ForeignKey(Facility, on_delete=models.CASCADE, related_name='basic_items')
    title = models.CharField(max_length=100, default='기본정보')
    content = models.TextField(blank=True)
    class Meta:
        verbose_name = "기본정보"
        verbose_name_plural = "기본정보"
    def __str__(self):
        return f"{self.facility.code}-{self.title}"

class FacilityEvaluation(TimestampedModel):
    facility = models.ForeignKey(Facility, on_delete=models.CASCADE, related_name='evaluation_items')
    title = models.CharField(max_length=100, default='평가정보')
    content = models.TextField(blank=True)
    class Meta:
        verbose_name = "평가정보"
        verbose_name_plural = "평가정보"
    def __str__(self):
        return f"{self.facility.code}-{self.title}"

class FacilityStaff(TimestampedModel):
    facility = models.ForeignKey(Facility, on_delete=models.CASCADE, related_name='staff_items')
    title = models.CharField(max_length=100, default='인력현황')
    content = models.TextField(blank=True)
    class Meta:
        verbose_name = "인력현황"
        verbose_name_plural = "인력현황"
    def __str__(self):
        return f"{self.facility.code}-{self.title}"

class FacilityProgram(TimestampedModel):
    facility = models.ForeignKey(Facility, on_delete=models.CASCADE, related_name='program_items')
    title = models.CharField(max_length=100, default='프로그램운영')
    content = models.TextField(blank=True)
    class Meta:
        verbose_name = "프로그램운영"
        verbose_name_plural = "프로그램운영"
    def __str__(self):
        return f"{self.facility.code}-{self.title}"

class FacilityLocation(TimestampedModel):
    facility = models.ForeignKey(Facility, on_delete=models.CASCADE, related_name='location_items')
    title = models.CharField(max_length=100, default='위치')
    content = models.TextField(blank=True)
    class Meta:
        verbose_name = "위치"
        verbose_name_plural = "위치"
    def __str__(self):
        return f"{self.facility.code}-{self.title}"

class FacilityHomepage(TimestampedModel):
    facility = models.OneToOneField(Facility, on_delete=models.CASCADE, related_name='homepage_info')
    title = models.CharField(max_length=100, default='홈페이지')
    content = models.TextField(blank=True)
    class Meta:
        verbose_name = "홈페이지"
        verbose_name_plural = "홈페이지"
    def __str__(self):
        return self.title

class FacilityNonCovered(TimestampedModel):
    facility = models.ForeignKey(Facility, on_delete=models.CASCADE, related_name='noncovered_items')
    title = models.CharField(max_length=100, default='비급여 항목')
    content = models.TextField(blank=True)
    class Meta:
        verbose_name = "비급여 항목"
        verbose_name_plural = "비급여 항목"
    def __str__(self):
        return f"{self.facility.code}-{self.title}"

# ---- 추가: 시설 태그 및 이미지 ----
class Tag(TimestampedModel):
    name = models.CharField(max_length=100, unique=True)
    facilities = models.ManyToManyField(Facility, related_name='tags', blank=True)
    class Meta:
        ordering = ["name"]
        verbose_name = "태그"
        verbose_name_plural = "태그"
    def __str__(self):
        return self.name

class FacilityImage(TimestampedModel):
    facility = models.ForeignKey(Facility, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='facility_images/%Y/%m/%d')
    original_url = models.URLField(max_length=500, unique=True)
    class Meta:
        ordering = ['-created_at']
        verbose_name = "시설 이미지"
        verbose_name_plural = "시설 이미지"
    def __str__(self):
        return f"{self.facility.code} - {self.original_url.split('/')[-1]}"

class FacilitySummary(TimestampedModel):
    facility = models.OneToOneField(Facility, on_delete=models.CASCADE, related_name='summary')
    content = models.TextField(verbose_name='AI 요약 내용')
    model_name = models.CharField(max_length=100, default='llama3.2', verbose_name='사용된 모델')
    is_generated = models.BooleanField(default=False, verbose_name='요약 생성 완료')
    class Meta:
        verbose_name = "시설 요약"
        verbose_name_plural = "시설 요약"
    def __str__(self):
        return f"{self.facility.code} 요약"

class ChatHistory(TimestampedModel):
    """Stores chat queries and answers for authenticated users."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="chat_histories"
    )
    query = models.TextField()
    answer = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "채팅 기록"
        verbose_name_plural = "채팅 기록"

    def __str__(self):
        return f"{self.user} - {self.created_at:%Y-%m-%d %H:%M:%S}"
