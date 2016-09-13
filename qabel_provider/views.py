import functools
import hashlib
import hmac
import logging

from axes import decorators as axes_dec
from django.conf import settings
from django.contrib.auth.models import User
from django.db import transaction
from rest_auth.registration.views import RegisterView
from rest_auth.views import LoginView
from rest_framework.authtoken.models import Token
from rest_framework.decorators import api_view
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.reverse import reverse

from .serializers import UserSerializer, PlanSubscriptionSerializer, PlanIntervalSerializer
from .models import ProfilePlanLog
from .utils import get_request_origin

logger = logging.getLogger(__name__)


@api_view(('GET',))
def api_root(request, format=None):
    return Response({
        'register': reverse('rest_register', request=request, format=format),
        'verify-email': reverse('rest_verify_email', request=request, format=format),
        'auth': reverse('api-auth', request=request, format=format),
        'login': reverse('rest_login', request=request, format=format),
        'logout': reverse('rest_logout', request=request, format=format),
        'user': reverse('rest_user_details', request=request, format=format),
        'password_change': reverse('rest_password_change', request=request, format=format),
        'password_reset': reverse('rest_password_reset', request=request, format=format),
        'password_confirm': reverse('rest_password_reset_confirm', request=request, format=format),
    })


@functools.lru_cache()
def hashed_api_secret():
    return hashlib.sha512(settings.API_SECRET.encode()).digest()


def check_api_key(request):
    api_key = request.META.get('HTTP_APISECRET', '')
    # Avoid leaking length of the APISECRET via comparison timing.
    hashed_key = hashlib.sha512(api_key.encode()).digest()
    return hmac.compare_digest(hashed_key, hashed_api_secret())


def api_key_error():
    logger.warning('Called with invalid API key')
    return Response(status=403, data={'error': 'Invalid API key'})


@api_view(('POST',))
def auth_resource(request, format=None):
    """
    Handles auth for uploads, downloads and deletes on the storage backend.

    This returns user data by either passing an authentication token
    presented by the user (*auth*) or by passing an user ID (*user_id*).

    The first case authenticates the user to the client of this API, the second
    obviously doesn't.

    This resource is meant for the block server which can call it to check
    if the user is authenticated. The block server should set the same
    Authorization header that itself received by the user.

    :return: HttpResponseBadRequest|HttpResponse(status=204)|HttpResponse(status=403)|HttpResponse(status=404)
    """
    if not check_api_key(request):
        return api_key_error()

    if 'auth' in request.data and 'user_id' in request.data:
        return Response(status=400, data={'error': 'Pass *either* an auth token *or* an user ID'})
    elif 'auth' in request.data:
        user_auth = request.data['auth']
        try:
            auth_type, token = user_auth.split()
            if auth_type != 'Token':
                raise ValueError()
        except ValueError:
            return Response(status=400, data={'error': 'Invalid auth type'})
        try:
            user = Token.objects.get(key=token).user
        except Token.DoesNotExist:
            return Response(status=404, data={'error': 'Invalid token'})
    elif 'user_id' in request.data:
        try:
            user_id = int(request.data['user_id'])
        except (KeyError, ValueError):
            return Response(status=400, data={'error': 'Malformed user ID'})
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return Response(status=404, data={'error': 'Invalid user ID'})
    else:
        return Response(status=400, data={'error': 'No user identification supplied'})

    logger.debug('Auth resource called: user={}'.format(user))
    is_disabled = user.profile.check_confirmation_and_send_mail()
    profile = user.profile
    profile.use_plan()
    return Response({
        'user_id': user.id,
        'active': (not is_disabled),
        'block_quota': profile.plan.block_quota,
        'monthly_traffic_quota': profile.plan.monthly_traffic_quota,
    })


@api_view(('POST',))
def plan_subscription(request, format=None):
    """
    Set subscription for an user account.

    Payload layout::

        {
            'user_email': STR,
            'plan': STR (id-of-plan),
        }

    API authentication required.
    """
    if not check_api_key(request):
        return api_key_error()

    serializer = PlanSubscriptionSerializer(data=request.data)
    serializer.is_valid(True)
    profile, plan = serializer.save()

    audit_log = ProfilePlanLog(profile=profile,
                               action='set-plan', plan=plan,
                               origin=get_request_origin(request))

    with transaction.atomic():
        profile.subscribed_plan = plan
        profile.save()
        audit_log.save()

    return Response()


@api_view(('POST',))
def plan_add_interval(request, format=None):
    """
    Add plan interval to an user account.

    Payload layout::

        {
            'user_email': STR,
            'plan': STR (id-of-plan),
            'duration': STR ([DD] [HH:[MM:]]ss[.uuuuuu]),
        }

    For details on *duration*, see http://www.django-rest-framework.org/api-guide/fields/#durationfield
    """
    if not check_api_key(request):
        return api_key_error()

    serializer = PlanIntervalSerializer(data=request.data)
    serializer.is_valid(True)
    plan_interval = serializer.save()

    audit_log = ProfilePlanLog(profile=plan_interval.profile,
                               action='add-interval', interval=plan_interval, plan=plan_interval.plan,
                               origin=get_request_origin(request))

    with transaction.atomic():
        plan_interval.save()
        audit_log.save()

    return Response()


class ThrottledLoginView(LoginView):

    @staticmethod
    def lockout_response():
        return Response(status=429, data={'error': 'Too many login attempts'})

    # noinspection PyAttributeOutsideInit
    def post(self, request, *args, **kwargs):
        if axes_dec.is_already_locked(request):
            return self.lockout_response()

        self.serializer = self.get_serializer(data=self.request.data)
        try:
            self.serializer.is_valid(raise_exception=True)
        except ValidationError:
            if self.watch_login(request, False):
                raise
            else:
                return self.lockout_response()

        if self.watch_login(request, True):
            self.login()
            return self.get_response()
        else:
            return self.lockout_response()

    @staticmethod
    def watch_login(request, successful):
        axes_dec.AccessLog.objects.create(
            user_agent=request.META.get('HTTP_USER_AGENT', '<unknown>')[:255],
            ip_address=axes_dec.get_ip(request),
            username=request.data['username'],
            http_accept=request.META.get('HTTP_ACCEPT', '<unknown>'),
            path_info=request.META.get('PATH_INFO', '<unknown>'),
            trusted=successful
        )
        return axes_dec.check_request(request, not successful)


class PasswordPolicyRegisterView(RegisterView):
    serializer_class = UserSerializer
