from django.contrib import admin
from .models import BlogCategory, BlogTag, BlogPost


@admin.register(BlogCategory)
class BlogCategoryAdmin(admin.ModelAdmin):
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ["name"]
    list_display = ["name", "slug"]


@admin.register(BlogTag)
class BlogTagAdmin(admin.ModelAdmin):
    prepopulated_fields = {"slug": ("name",)}
    search_fields = ["name"]
    list_display = ["name", "slug"]


@admin.register(BlogPost)
class BlogPostAdmin(admin.ModelAdmin):
    list_display = ["title", "category", "published", "is_featured", "published_at", "updated_at"]
    list_filter = ["published", "is_featured", "category", "published_at"]
    search_fields = ["title", "excerpt", "content"]
    autocomplete_fields = ["category", "tags"]
    prepopulated_fields = {"slug": ("title",)}
    list_editable = ["published", "is_featured"]
    ordering = ["-published_at"]

