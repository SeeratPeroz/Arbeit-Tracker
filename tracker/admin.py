from django.contrib import admin
from .models import Lab, Case, Event, UserProfile
from django.contrib.auth.models import User
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin


# ------------------------
# Case + Event
# ------------------------

class EventInline(admin.TabularInline):
    model = Event
    extra = 0
    readonly_fields = ('created_at', 'ip', 'user_agent')


@admin.register(Case)
class CaseAdmin(admin.ModelAdmin):
    list_display = ('case_code', 'patient_name', 'patient_dob', 'lab', 'status', 'created_at')
    list_filter = ('status', 'lab', 'created_at')
    search_fields = ('case_code', 'patient_name')
    inlines = [EventInline]


admin.site.register(Lab)
admin.site.register(Event)


# ------------------------
# User + Profile
# ------------------------

class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "lab")
    list_filter = ("role", "lab")
    search_fields = ("user__username", "user__email")


class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    fk_name = "user"
    extra = 0


class UserAdmin(BaseUserAdmin):
    inlines = (UserProfileInline,)

    # Hide inline on "Add User" form (to avoid duplicate profile creation).
    def get_inline_instances(self, request, obj=None):
        if obj is None:
            return []
        return super().get_inline_instances(request, obj)


# Unregister default User admin and register the custom one
admin.site.unregister(User)
admin.site.register(User, UserAdmin)
