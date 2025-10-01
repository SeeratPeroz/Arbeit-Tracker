from django.urls import include, path
from . import views


urlpatterns = [
    path("", views.home, name="home"),
    path('', include('django.contrib.auth.urls')),    
    path('', views.dashboard, name='dashboard'),
    path('cases/', views.cases_list, name='cases_list'),
    path('cases/new/', views.case_new, name='case_new'),
    path('cases/<int:pk>/', views.case_detail, name='case_detail'),
    path('cases/<int:pk>/label/', views.label_print, name='label_print'),
    path('cases/<int:pk>/qr.png', views.case_qr_png, name='case_qr_png'),
    path("cases/<int:pk>/receive/", views.clinic_mark_received, name="clinic_mark_received"),
    path("settings/pin/", views.settings_pin, name="settings_pin"),
    path("labs/<int:lab_id>/set-pin/", views.clinic_set_lab_pin, name="clinic_set_lab_pin"),
    path("settings/praxis-pin/", views.settings_praxis_pin, name="settings_praxis_pin"),


    path("lab/cases/", views.lab_cases_list, name="lab_cases_list"),
    path("lab/case/<int:pk>/", views.lab_case_detail, name="lab_case_detail"),

    # Public QR
    path("t/<uuid:token>/", views.public_token_view, name="public_token"),

    # Lab
    path("lab/", views.lab_home, name="lab_home"),
    path("lab/case/<int:pk>/", views.lab_case_detail, name="lab_case_detail"),


    # Authentication 
    path('logout/', views.user_logout, name='logout'),

]