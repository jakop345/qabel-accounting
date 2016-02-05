"""qabel_id URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/1.8/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  url(r'^$', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  url(r'^$', Home.as_view(), name='home')
Including another URLconf
    1. Add an import:  from blog import urls as blog_urls
    2. Add a URL to urlpatterns:  url(r'^blog/', include(blog_urls))
"""
from django.conf.urls import include, url
from django.contrib import admin
from qabel_provider import views

# noinspection PyCallByClass
profile = views.ProfileViewSet.as_view({
    'get': 'retrieve',
})

rest_urls = [
    url(r'^$', views.api_root, name='api-root'),
    url(r'^profile/', profile, name='api-profile'),
    url(r'^prefix/', views.PrefixList.as_view(), name='api-prefix'),
    url(r'^auth/', include('rest_auth.urls')),
    url(r'^auth/registration/', include('rest_auth.registration.urls')),
    url(r'^auth/(?P<prefix>[\d\w-]+)/(?P<file_path>[\d\w-]+)',
        views.auth_resource, name='api-auth'),
    url(r'^quota/', views.quota, name="api-quota"),
]

urlpatterns = [
    url(r'^admin/', include(admin.site.urls)),
    url('^accounts/', include('django.contrib.auth.urls')),
    url('^accounts/profile', views.profile),
    url(r'^api/v0/', include(rest_urls))
]
