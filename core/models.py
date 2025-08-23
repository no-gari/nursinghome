from django.db import models
from django.conf import settings


class TimestampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Facility(TimestampedModel):
    code = models.CharField(max_length=32, unique=True, verbose_name='시설 코드', help_text='고유한 시설 식별 코드')
    name = models.CharField(max_length=255)
    kind = models.CharField(max_length=32, blank=True)
    grade = models.CharField(max_length=16, blank=True)
    availability = models.CharField(max_length=16, blank=True)
    capacity = models.PositiveIntegerField(null=True, blank=True, verbose_name='정원')
    occupancy = models.PositiveIntegerField(null=True, blank=True, verbose_name='현원')
    waiting = models.PositiveIntegerField(null=True, blank=True, verbose_name='대기')
    has_images = models.BooleanField(default=False, verbose_name='이미지 존재 여부', help_text='크롤링 가능하고 이미지가 있으면 True')
    sido = models.CharField(max_length=20, blank=True, db_index=True, verbose_name='시도')
    sigungu = models.CharField(max_length=30, blank=True, db_index=True, verbose_name='시군구')
    phone = models.CharField(max_length=20, blank=True, verbose_name='전화번호')
    homepage_url = models.URLField(blank=True, verbose_name='홈페이지 URL')
    location_info = models.TextField(blank=True, verbose_name='교통편 정보')
    evaluation_info = models.JSONField(default=dict, verbose_name='평가정보', help_text='{"제목": "내용"} 형태')
    staff_info = models.JSONField(default=dict, verbose_name='인력현황', help_text='{"제목": "내용"} 형태')
    program_info = models.JSONField(default=dict, verbose_name='프로그램운영', help_text='{"제목": "내용"} 형태')
    noncovered_info = models.JSONField(default=dict, verbose_name='비급여항목', help_text='{"제목": "금액"} 형태 (숫자만)')
    summary = models.TextField(blank=True, verbose_name='AI 요약', help_text='AI가 생성한 시설 요약 내용')

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


class ChatHistory(TimestampedModel):
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


class Blog(TimestampedModel):
    facility = models.ForeignKey(Facility, on_delete=models.CASCADE, related_name='blogs')
    title = models.CharField(max_length=255, verbose_name='블로그 제목')
    link = models.URLField(verbose_name='블로그 링크')
    description = models.TextField(blank=True, verbose_name='블로그 설명')
    bloggername = models.CharField(max_length=100, blank=True, verbose_name='블로거명')
    bloggerlink = models.URLField(blank=True, verbose_name='블로거 링크')
    postdate = models.CharField(max_length=20, blank=True, verbose_name='작성일')

    class Meta:
        ordering = ['-postdate', '-created_at']
        verbose_name = "블로그"
        verbose_name_plural = "블로그"
        unique_together = ['facility', 'link']  # 같은 시설의 동일한 링크 중복 방지

    def __str__(self):
        return f"{self.facility.name} - {self.title}"


class Hospital(TimestampedModel):
    code = models.CharField(max_length=32, unique=True, verbose_name='병원 코드', help_text='고유한 병원 식별 코드')
    name = models.CharField(max_length=255, verbose_name='병원명')
    grade = models.CharField(max_length=16, blank=True, verbose_name='등급')
    establishment_type = models.CharField(max_length=32, blank=True, verbose_name='설립구분')
    phone = models.CharField(max_length=20, blank=True, verbose_name='전화번호')
    establishment_date = models.DateField(null=True, blank=True, verbose_name='설립일자')
    bed_count = models.JSONField(default=dict, verbose_name='병상 수', help_text='{"병상유형": 병상수} 형태')
    operation_facility = models.JSONField(default=dict, verbose_name='운영/시설', help_text='{"항목": "내용"} 형태')
    doctor_count = models.JSONField(default=dict, verbose_name='의사수', help_text='{"과목": 의사수} 형태')
    specialist_by_department = models.JSONField(default=dict, verbose_name='전문과목별(전문의수)', help_text='{"과목명": 전문의수} 형태')
    department_specialists = models.JSONField(default=dict, verbose_name='진료과목별(전문의수)', help_text='{"진료과목": 전문의수} 형태')
    other_staff = models.JSONField(default=dict, verbose_name='기타인력', help_text='{"직종": 인원수} 형태')
    consultation_hours = models.JSONField(default=dict, verbose_name='진료시간', help_text='{"요일/시간": "내용"} 형태')
    medical_fee_info = models.JSONField(default=dict, verbose_name='진료비정보', help_text='{"항목": "금액"} 형태')
    location = models.CharField(max_length=512, blank=True, verbose_name='위치정보', help_text='병원 주소 및 위치 정보')
    has_images = models.BooleanField(default=False, verbose_name='이미지 존재 여부', help_text='크롤링 가능하고 이미지가 있으면 True')
    sido = models.CharField(max_length=20, blank=True, db_index=True, verbose_name='시도')
    sigungu = models.CharField(max_length=30, blank=True, db_index=True, verbose_name='시군구')
    homepage_url = models.URLField(blank=True, verbose_name='홈페이지 URL')
    summary = models.TextField(blank=True, verbose_name='AI 요약', help_text='AI가 생성한 병원 요약 내용')
    tags = models.ManyToManyField('Tag', related_name='hospitals', blank=True, verbose_name='태그')

    class Meta:
        ordering = ["name"]
        verbose_name = "요양병원"
        verbose_name_plural = "요양병원"

    def __str__(self):
        return f"{self.name} ({self.code})"


class HospitalImage(TimestampedModel):
    hospital = models.ForeignKey(Hospital, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='hospital_images/%Y/%m/%d')
    original_url = models.URLField(max_length=500, unique=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = "병원 이미지"
        verbose_name_plural = "병원 이미지"

    def __str__(self):
        return f"{self.hospital.code} - {self.original_url.split('/')[-1]}"
