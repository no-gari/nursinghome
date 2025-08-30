from django.db import models
from django.utils.text import slugify
from django.urls import reverse
from ckeditor.fields import RichTextField


class BlogCategory(models.Model):
    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(max_length=90, unique=True, blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "카테고리"
        verbose_name_plural = "카테고리"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('blog:list') + f'?category={self.slug}'


class BlogTag(models.Model):
    name = models.CharField(max_length=60, unique=True)
    slug = models.SlugField(max_length=70, unique=True, blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "태그"
        verbose_name_plural = "태그"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse('blog:list') + f'?tag={self.slug}'


class BlogPost(models.Model):
    category = models.ForeignKey(BlogCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name='posts')
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=210, unique=True, blank=True)
    excerpt = models.TextField(blank=True, help_text='리스트/OG 설명 (자동 생성 가능)')
    content = RichTextField()
    cover_image = models.ImageField(upload_to='blog/cover/%Y/%m/%d', blank=True, null=True)
    tags = models.ManyToManyField(BlogTag, blank=True, related_name='posts')
    is_featured = models.BooleanField(default=False, help_text='리스트 상단 Featured 영역에 노출')
    published = models.BooleanField(default=True)
    published_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-published_at']
        verbose_name = '포스트'
        verbose_name_plural = '포스트'

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.title)[:180]
            if not base:  # 한글 등 slugify 결과 비어있는 경우 대비
                base = 'post'
            slug_candidate = base
            i = 1
            while BlogPost.objects.filter(slug=slug_candidate).exclude(pk=self.pk).exists():
                slug_candidate = f"{base}-{i}"[:200]
                i += 1
            self.slug = slug_candidate
        if not self.excerpt:
            plain = self._plain_text()[:150]
            self.excerpt = plain + ('…' if len(plain) == 150 else '')
        super().save(*args, **kwargs)

    def _plain_text(self):
        import re
        text = re.sub('<[^<]+?>', ' ', self.content or '')
        return ' '.join(text.split())

    @property
    def reading_minutes(self):
        words = len(self._plain_text().split())
        return max(1, (words + 199)//200)

    def get_absolute_url(self):
        return reverse('blog:detail', args=[self.slug])
