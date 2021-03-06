import csv

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as OriginalUserAdmin
from django.contrib.auth.models import User
from django.http import HttpResponse
from django.utils import timezone
from django.utils.translation import ugettext_lazy as _

from allauth.account.models import EmailAddress

import nested_admin

from .models import Profile, Plan, PlanInterval, ProfilePlanLog

admin.site.site_title = _('Accounting')
admin.site.site_header = _('Qabel Account Management')
admin.site.index_title = _('Qabel Account Management')


class PlanIntervalInline(nested_admin.NestedTabularInline):
    model = PlanInterval
    can_delete = False
    extra = 1

    fields = (
        'plan', 'duration', 'state', 'started_at',
    )


class ProfilePlanLogInline(nested_admin.NestedTabularInline):
    model = ProfilePlanLog
    extra = 0
    can_delete = False

    def has_add_permission(self, request):
        return False

    fields = (
        'timestamp', 'action', 'plan', 'interval',
    )
    readonly_fields = fields
    # This is basically just a table now; no adding, deleting or modifying of records in the admin.


class UserProfileInline(nested_admin.NestedStackedInline):
    inlines = [PlanIntervalInline, ProfilePlanLogInline]
    model = Profile
    can_delete = False

    fields = (
        'plus_notification_mail', 'pro_notification_mail',
        'subscribed_plan', 'created_on_behalf',
        'next_confirmation_mail', 'needs_confirmation_after'
    )


class UserAdmin(OriginalUserAdmin, nested_admin.NestedModelAdmin):
    inlines = [UserProfileInline]
    list_filter = OriginalUserAdmin.list_filter + \
        ('profile__plus_notification_mail', 'profile__pro_notification_mail',
         'profile__subscribed_plan',
         'profile__next_confirmation_mail', 'profile__needs_confirmation_after',)

    actions = ('export_user_data',)

    def export_user_data(self, request, queryset):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename=Qabel-User-Data-%s.csv' % timezone.now().replace(microsecond=0).isoformat()

        csv_writer = csv.writer(response)
        csv_writer.writerow(['username', 'email'])

        emails = EmailAddress.objects.filter(user__in=queryset, primary=True, verified=True).select_related('user')
        written_rows = emails.count()
        failed_no_address = queryset.count() - written_rows
        csv_writer.writerows((email.user.username, email.email) for email in emails)
        self.message_user(request, _('admin user data export {written_rows} {failed_no_address}').format(
            written_rows=written_rows,
            failed_no_address=failed_no_address,
        ))
        return response
    export_user_data.short_description = _('admin user action export data label')


class PlanAdmin(admin.ModelAdmin):
    model = Plan

    fields = (
        'id', 'name', 'block_quota', 'monthly_traffic_quota',
    )

try:
    admin.site.unregister(User)
finally:
    admin.site.register(User, UserAdmin)
admin.site.register(Plan, PlanAdmin)
