from django.shortcuts import render, get_object_or_404
from django.core.paginator import Paginator
from django.db.models import Q
from .models import BlogPost, BlogTag, BlogCategory


def blog_list(request):
    qs = BlogPost.objects.filter(published=True).select_related('category').prefetch_related('tags')
    search = request.GET.get('q', '').strip()
    tag_slug = request.GET.get('tag')
    category_slug = request.GET.get('category')

    if search:
        qs = qs.filter(Q(title__icontains=search) | Q(excerpt__icontains=search) | Q(content__icontains=search))
    if tag_slug:
        qs = qs.filter(tags__slug=tag_slug)
    if category_slug:
        qs = qs.filter(category__slug=category_slug)

    featured = qs.filter(is_featured=True).first()
    if featured:
        qs = qs.exclude(pk=featured.pk)

    paginator = Paginator(qs, 9)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    ctx = {
        'featured': featured,
        'posts': page_obj.object_list,
        'page_obj': page_obj,
        'paginator': paginator,
        'search': search,
        'current_tag': tag_slug,
        'current_category': category_slug,
        'tags': BlogTag.objects.order_by('name')[:30],
        'categories': BlogCategory.objects.order_by('name')[:30],
    }
    return render(request, 'blog/list.html', ctx)


def blog_detail(request, slug):
    post = get_object_or_404(BlogPost.objects.select_related('category').prefetch_related('tags'), slug=slug, published=True)
    # 이전/다음
    prev_post = BlogPost.objects.filter(published=True, published_at__gt=post.published_at).order_by('published_at').first()
    next_post = BlogPost.objects.filter(published=True, published_at__lt=post.published_at).order_by('-published_at').first()
    ctx = {
        'post': post,
        'prev_post': prev_post,
        'next_post': next_post,
    }
    return render(request, 'blog/detail.html', ctx)

