from django.urls import include, path
from . import views
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    # Home
    path("", views.home, name="home"),

    # Auth (login, logout, password reset, etc.)
    path("", include("django.contrib.auth.urls")),

    path("dashboard/", views.dashboard, name="dashboard"),
    path("help/", views.help_guide, name="help_guide"),




    # Clinic
    path("cases/", views.cases_list, name="cases_list"),
    path("cases/new/", views.case_new, name="case_new"),
    path("cases/<int:pk>/", views.case_detail, name="case_detail"),
    path("cases/<int:pk>/label/", views.label_print, name="label_print"),
    path("cases/<int:pk>/qr.png", views.case_qr_png, name="case_qr_png"),
    path("cases/<int:pk>/receive/", views.clinic_mark_received, name="clinic_mark_received"),
    path("cases/<int:pk>/edit/", views.case_edit, name="case_edit"),
    path("cases/<int:pk>/delete/", views.case_delete, name="case_delete"),
    path("settings/pin/", views.settings_pin, name="settings_pin"),
    path("settings/praxis-pin/", views.settings_praxis_pin, name="settings_praxis_pin"),
    path("labs/<int:lab_id>/set-pin/", views.clinic_set_lab_pin, name="clinic_set_lab_pin"),

    # Lab
    path("lab/", views.lab_home, name="lab_home"),
    # Alias so old links like {% url 'lab_dashboard' %} keep working:
    path("lab/dashboard/", views.lab_home, name="lab_dashboard"),
    path("lab/cases/", views.lab_cases_list, name="lab_cases"),
    path("lab/cases/<int:pk>/", views.lab_case_detail, name="lab_case_detail"),
    path("lab/cases/<int:pk>/qr.png", views.lab_case_qr_png, name="lab_case_qr_png"),
    path("labs/new/", views.clinic_create_lab, name="clinic_create_lab"),
    path("labs/<int:lab_id>/edit/", views.clinic_edit_lab, name="clinic_edit_lab"),
    path("labs/<int:lab_id>/set-pin/", views.clinic_set_lab_pin, name="clinic_set_lab_pin"),
    path("labs/users/", views.clinic_lab_users, name="clinic_lab_users"),
    path("labs/users/new/", views.clinic_create_lab_user, name="clinic_create_lab_user"),
    # tracker/urls.py (add these)
    path("labs/users/", views.clinic_lab_users, name="clinic_lab_users"),
    path("labs/users/<int:user_id>/edit/", views.clinic_edit_lab_user, name="clinic_edit_lab_user"),
    path("labs/users/<int:user_id>/toggle/", views.clinic_toggle_lab_user, name="clinic_toggle_lab_user"),

    # Dashboard TV
    path("display/board/", views.display_board, name="display_board"),
    path("api/dashboard/recent/", views.dashboard_recent_api, name="dashboard_recent_api"),
    path("api/dashboard/counts/", views.dashboard_counts_api, name="dashboard_counts_api"),

    path("cases/<int:pk>/comment/", views.case_add_comment, name="case_add_comment"),


    # Public QR
    path("t/<uuid:token>/", views.public_token_view, name="public_token"),
]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)