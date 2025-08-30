from django.test import TestCase
from django.urls import reverse
from .models import BlogPost, BlogCategory, BlogTag

class BlogViewsTest(TestCase):
    def setUp(self):
        cat = BlogCategory.objects.create(name='소식')
        tag1 = BlogTag.objects.create(name='요양')
        tag2 = BlogTag.objects.create(name='케어')
        post = BlogPost.objects.create(title='첫 번째 글', content='<p>본문 내용 테스트</p>', category=cat, is_featured=True)
        post.tags.add(tag1, tag2)
        self.post = post

    def test_list_view_ok(self):
        url = reverse('blog:list')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '첫 번째 글')

    def test_detail_view_ok(self):
        url = self.post.get_absolute_url()
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '본문 내용 테스트')
        self.assertContains(resp, '첫 번째 글')

    def test_search(self):
        url = reverse('blog:list') + '?q=첫'
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '첫 번째 글')

    def test_tag_filter(self):
        tag = self.post.tags.first()
        url = reverse('blog:list') + f'?tag={tag.slug}'
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '첫 번째 글')

    def test_category_filter(self):
        cat = self.post.category
        url = reverse('blog:list') + f'?category={cat.slug}'
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '첫 번째 글')

