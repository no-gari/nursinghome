from django.shortcuts import render, get_object_or_404
from django.core.paginator import Paginator
from .models import BlogPost, BlogCategory


def blog_list(request):
    qs = BlogPost.objects.filter(published=True).select_related('category').prefetch_related('tags')
    category_slug = request.GET.get('category')

    if category_slug:
        qs = qs.filter(category__slug=category_slug)

    # Featured 먼저 정렬
    qs = qs.order_by('-is_featured', '-published_at')
    featured = qs.first()

    paginator = Paginator(qs, 9)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    ctx = {
        'featured': featured,  # OG 이미지 등에 사용
        'posts': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'current_category': category_slug,
        'categories': BlogCategory.objects.order_by('name')[:30],
    }
    return render(request, 'blog/list.html', ctx)


def blog_detail(request, slug):
    post = get_object_or_404(BlogPost.objects.select_related('category').prefetch_related('tags'), slug=slug, published=True)
    prev_post = BlogPost.objects.filter(published=True, published_at__gt=post.published_at).order_by('published_at').first()
    next_post = BlogPost.objects.filter(published=True, published_at__lt=post.published_at).order_by('-published_at').first()
    ctx = {
        'post': post,
        'prev_post': prev_post,
        'next_post': next_post,
    }
    return render(request, 'blog/detail.html', ctx)
