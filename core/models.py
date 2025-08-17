from django.db import models

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
