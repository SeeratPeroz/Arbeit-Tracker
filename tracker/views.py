import io
import qrcode
from django.conf import settings
from django.urls import reverse
from django.http import JsonResponse
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.contrib.auth.models import User
from .forms import LabUserEditForm, LabUserCreateForm
from django.db.models import Q
from django.http import HttpResponse, HttpResponseForbidden, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from tracker.decorators import role_required
from .forms import (
    CaseCreateForm,
    LabSearchForm,
    LabActionForm,  # (keep if you use it in templates)
    LabPinForm,
    GlobalPinForm,
    PraxisPinForm,
    CaseForm,
    LabForm,
    CaseCommentForm,  # NEW
)
from .models import Case, Event, Lab, AppSettings, CaseComment, Attachment
from .utils import public_token_url


# -------------------------------
# Helpers
# -------------------------------
def user_role(u):
    return getattr(getattr(u, "profile", None), "role", None)

def user_lab(u):
    return getattr(getattr(u, "profile", None), "lab", None)

def require_role(user, role):
    return user_role(user) == role


# -------------------------------
# Auth / Home
# -------------------------------
def user_logout(request):
    print("Logging out user:", request.user)
    logout(request)
    return redirect("login")

@login_required
def home(request):
    # return redirect("lab_home") if user_role(request.user) == "LAB" else redirect("cases_list")
    return redirect("lab_home") if user_role(request.user) == "LAB" else redirect("dashboard")



# -------------------------------
# LAB: quick home (scan/search by code)
# -------------------------------
@login_required
def lab_home(request):
    if user_role(request.user) != "LAB":
        return HttpResponseForbidden("Nicht erlaubt.")
    lab = user_lab(request.user)
    form = LabSearchForm(request.GET or None)
    case = None
    if form.is_valid():
        code = form.cleaned_data["case_code"].strip()
        case = Case.objects.filter(case_code__iexact=code, lab=lab).first()
    return render(request, "lab_home.html", {"form": form, "case": case})


# -------------------------------
# CLINIC: dashboard & list
# -------------------------------
@role_required("CLINIC")
@login_required
def dashboard(request):
    counts = {
        "sent": Case.objects.filter(status=Case.Status.SENT_CLINIC).count(),
        "in_lab": Case.objects.filter(status=Case.Status.RECEIVED_BY_LAB).count(),
        "returned": Case.objects.filter(status=Case.Status.RETURNED_BY_LAB).count(),
        "completed": Case.objects.filter(status=Case.Status.RECEIVED_BY_CLINIC).count(),
    }
    recent = (Case.objects
                  .select_related('lab')           # ensure lab is joined
                  .order_by("-created_at")[:10])
    labs = (Case.objects
                .select_related('lab')
                .values_list('lab__name', flat=True)
                .distinct().order_by('lab__name'))
    return render(request, "dashboard.html", {"counts": counts, "recent": recent, "labs": labs})

@login_required
def cases_list(request):
    # LAB users should not see the clinic-wide list
    if user_role(request.user) == "LAB":
        return redirect("lab_cases")

    qs = Case.objects.select_related('lab').order_by('-created_at')

    status = (request.GET.get("status") or "").strip()
    q = (request.GET.get("q") or "").strip()

    if status:
        qs = qs.filter(status=status)

    if q:
        qs = qs.filter(
            Q(patient_name__icontains=q) |
            Q(case_code__icontains=q) |
            Q(lab__name__icontains=q)
        )

    # ALWAYS define labs so the template has it
    labs = list(
        Case.objects.select_related('lab')
        .values_list('lab__name', flat=True)
        .distinct()
        .order_by('lab__name')
    )

    return render(request, "cases_list.html", {
        "cases": qs,
        "status": status,
        "q": q,
        "Case": Case,
        "labs": labs,
    })

# -------------------------------
# CLINIC: create / detail / label
# -------------------------------
@role_required("CLINIC")
@login_required
def case_new(request):
    if request.method == "POST":
        form = CaseCreateForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                case = form.save(commit=False)
                case.created_by = request.user
                case.save()
                Event.objects.create(
                    case=case,
                    status=Case.Status.SENT_CLINIC,
                    actor="CLINIC",
                    note="Created in clinic",
                )
            if "print" in request.POST:
                return redirect("label_print", pk=case.pk)
            return redirect("case_detail", pk=case.pk)
    else:
        form = CaseCreateForm()
    return render(request, "case_form.html", {"form": form})

@role_required("CLINIC")
@login_required
def case_detail(request, pk: int):
    case = get_object_or_404(Case, pk=pk)
    # comments will be accessed via case.comments.all in template
    return render(request, "case_detail.html", {"case": case})

@role_required("CLINIC")
@login_required
def label_print(request, pk: int):
    case = get_object_or_404(Case, pk=pk)
    token_url = public_token_url(case.qr_token)
    return render(request, "label_print.html", {"case": case, "token_url": token_url})

@role_required("CLINIC")
@login_required
def case_qr_png(request, pk: int):
    """
    PNG des QR-Codes für die öffentliche Token-URL.
    """
    case = get_object_or_404(Case, pk=pk)
    url = public_token_url(case.qr_token)
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return HttpResponse(buf.getvalue(), content_type="image/png")


# -------------------------------
# PUBLIC: QR token page (no login)
# -------------------------------
def public_token_view(request, token):
    """
    Öffentliche Seite aus dem QR-Code.
    Das Labor (oder die Praxis bei Rückgabe) gibt den Schutzcode ein und führt die
    jeweils erlaubte nächste Aktion aus.
    """
    case = get_object_or_404(Case, qr_token=token)

    # Allowed transitions
    next_map = {
        Case.Status.SENT_CLINIC: [Case.Status.RECEIVED_BY_LAB, Case.Status.RETURNED_BY_LAB],
        Case.Status.RECEIVED_BY_LAB: [Case.Status.RETURNED_BY_LAB],
        Case.Status.RETURNED_BY_LAB: [Case.Status.RECEIVED_BY_CLINIC],
        Case.Status.RECEIVED_BY_CLINIC: [],
    }

    if request.method == "POST":
        code = (request.POST.get("code") or "").strip()
        note = (request.POST.get("note") or "").strip()
        action = request.POST.get("action") or ""

        # Map action -> target + which PIN is required
        target, need = None, None
        if action == "receive_lab":
            target, need = Case.Status.RECEIVED_BY_LAB, "LAB"
        elif action == "return_lab":
            target, need = Case.Status.RETURNED_BY_LAB, "LAB"
        elif action == "receive_clinic":
            target, need = Case.Status.RECEIVED_BY_CLINIC, "CLINIC"

        if not (target and target in next_map.get(case.status, [])):
            messages.error(request, "Diese Aktion ist derzeit nicht erlaubt.")
            return render(request, "public_token.html", {"case": case})

        # PIN checks
        pin_ok = False
        if need == "LAB":
            pin_ok = bool(case.lab and case.lab.check_pin(code))
        elif need == "CLINIC":
            pin_ok = AppSettings.get().check_praxis_pin(code)

        if not pin_ok:
            messages.error(request, "Schutzcode ist falsch.")
            return render(request, "public_token.html", {"case": case})

        # Record and update
        actor = "LAB" if need == "LAB" else "CLINIC"
        Event.objects.create(
            case=case,
            status=target,
            actor=actor,
            note=note,
            ip=request.META.get("REMOTE_ADDR"),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
        )
        case.status = target
        case.save(update_fields=["status"])
        messages.success(request, "Status aktualisiert.")
        return redirect("public_token", token=token)

    return render(request, "public_token.html", {"case": case})


# -------------------------------
# SETTINGS (Clinic only)
# -------------------------------
@login_required
def settings_pin(request):
    """
    Nutzt GlobalPinForm, arbeitet intern aber mit AppSettings.praxis_pin_hash
    (check_praxis_pin / set_praxis_pin), damit es mit deinem aktuellen AppSettings-Modell
    ohne Änderungen funktioniert.
    """
    if not require_role(request.user, "CLINIC"):
        return HttpResponseForbidden("Nur für Klinik-Konten.")
    settings_obj = AppSettings.get()

    if request.method == "POST":
        form = GlobalPinForm(request.POST)
        if form.is_valid():
            cur = (form.cleaned_data.get("current_pin") or "").strip()
            new = form.cleaned_data["new_pin"].strip()
            # falls schon ein PIN gesetzt ist, optional current prüfen
            if settings_obj.praxis_pin_hash and not settings_obj.check_praxis_pin(cur):
                messages.error(request, "Aktueller PIN ist falsch.")
            else:
                settings_obj.set_praxis_pin(new)
                settings_obj.save()
                messages.success(request, "PIN wurde aktualisiert.")
                return redirect("settings_pin")
    else:
        form = GlobalPinForm()

    return render(request, "settings_pin.html", {"form": form})

@login_required
def settings_praxis_pin(request):
    """
    Clinic-only page: lists all labs and allows adding/editing labs and changing lab PINs via modals.
    """
    if not require_role(request.user, "CLINIC"):
        return HttpResponseForbidden("Nur für Klinik-Konten.")
    labs = Lab.objects.all().order_by("name")
    # empty forms for the modals
    return render(request, "settings_praxis_pin.html", {
        "labs": labs,
        "lab_form": LabForm(),
        "lab_pin_form": LabPinForm(),
    })


@require_POST
@login_required
def clinic_create_lab(request):
    if not require_role(request.user, "CLINIC"):
        return HttpResponseForbidden("Nur für Klinik-Konten.")
    form = LabForm(request.POST)
    if form.is_valid():
        form.save()
        messages.success(request, "Labor wurde erstellt.")
    else:
        messages.error(request, "Labor konnte nicht erstellt werden. Bitte Eingaben prüfen.")
    return redirect("settings_praxis_pin")


@require_POST
@login_required
def clinic_edit_lab(request, lab_id):
    if not require_role(request.user, "CLINIC"):
        return HttpResponseForbidden("Nur für Klinik-Konten.")
    lab = get_object_or_404(Lab, pk=lab_id)
    form = LabForm(request.POST, instance=lab)
    if form.is_valid():
        form.save()
        messages.success(request, "Labor wurde aktualisiert.")
    else:
        messages.error(request, "Aktualisierung fehlgeschlagen. Bitte Eingaben prüfen.")
    return redirect("settings_praxis_pin")

@require_POST
@login_required
def clinic_set_lab_pin(request, lab_id):
    if user_role(request.user) != "CLINIC":
        return HttpResponseForbidden("Nur für Klinik-Konten.")
    lab = get_object_or_404(Lab, pk=lab_id)
    form = LabPinForm(request.POST)
    if form.is_valid():
        lab.set_pin(form.cleaned_data["new_pin"])
        lab.save(update_fields=["pin_hash"])
        messages.success(request, f"PIN für {lab.name} aktualisiert.")
    else:
        for field, errs in form.errors.get_json_data().items():
            for err in errs:
                messages.error(request, f"{field}: {err['message']}")
    return redirect("settings_praxis_pin")


# -------------------------------
# CLINIC actions
# -------------------------------
@login_required
def clinic_mark_received(request, pk):
    if not require_role(request.user, "CLINIC"):
        return HttpResponseForbidden("Nur für Klinik-Konten.")
    case = get_object_or_404(Case, pk=pk)
    if case.status != Case.Status.RETURNED_BY_LAB:
        return HttpResponseForbidden("Dieser Schritt ist aktuell nicht erlaubt.")
    Event.objects.create(
        case=case,
        status=Case.Status.RECEIVED_BY_CLINIC,
        actor="CLINIC",
        note="In Praxis erhalten",
    )
    case.status = Case.Status.RECEIVED_BY_CLINIC
    case.save(update_fields=["status"])
    return redirect("case_detail", pk=case.pk)


# -------------------------------
# LAB: list & detail (with simple transitions)
# -------------------------------
@login_required
def lab_cases_list(request):
    if user_role(request.user) != "LAB":
        return HttpResponseForbidden("Nicht erlaubt.")
    lab = user_lab(request.user)
    qs = Case.objects.filter(lab=lab).order_by("-created_at")

    status = request.GET.get("status") or ""
    q = request.GET.get("q") or ""
    if status:
        qs = qs.filter(status=status)
    if q:
        qs = qs.filter(Q(case_code__icontains=q) | Q(patient_name__icontains=q))

    page = Paginator(qs, 25).get_page(request.GET.get("page"))

    labs = (Case.objects.select_related('lab')
        .values_list('lab__name', flat=True)
        .distinct().order_by('lab__name'))
    
    return render(request, "lab_cases_list.html", {"page": page, "status": status, "q": q, "Case": Case, "labs": labs})

@login_required
def lab_case_detail(request, pk):
    if user_role(request.user) != "LAB":
        return HttpResponseForbidden("Nicht erlaubt.")
    lab = user_lab(request.user)
    case = get_object_or_404(Case, pk=pk, lab=lab)  # restrict to this lab

    next_map = {
        Case.Status.SENT_CLINIC: [Case.Status.RECEIVED_BY_LAB, Case.Status.RETURNED_BY_LAB],
        Case.Status.RECEIVED_BY_LAB: [Case.Status.RETURNED_BY_LAB],
        Case.Status.RETURNED_BY_LAB: [Case.Status.RECEIVED_BY_CLINIC],
        Case.Status.RECEIVED_BY_CLINIC: [],
    }
    allowed = next_map.get(case.status, [])

    if request.method == "POST":
        action = request.POST.get("action")
        note = (request.POST.get("note") or "").strip()
        target = None
        if action == "receive_lab":
            target = Case.Status.RECEIVED_BY_LAB
        elif action == "return_lab":
            target = Case.Status.RETURNED_BY_LAB

        if target and target in allowed:
            Event.objects.create(
                case=case,
                status=target,
                actor="LAB",
                note=note,
                ip=request.META.get("REMOTE_ADDR"),
                user_agent=request.META.get("HTTP_USER_AGENT", ""),
            )
            case.status = target
            case.save(update_fields=["status"])
            return redirect("lab_case_detail", pk=case.pk)

    # Build action list for template
    actions = []
    if Case.Status.RECEIVED_BY_LAB in allowed:
        actions.append(("receive_lab", "Im Labor eingegangen"))
    if Case.Status.RETURNED_BY_LAB in allowed:
        actions.append(("return_lab", "Zurück an Praxis"))

    return render(request, "lab_case_detail.html", {"case": case, "actions": actions})


# -------------------------------
# CLINIC: edit & delete
# -------------------------------
def _is_clinic(user):
    return getattr(getattr(user, 'profile', None), 'role', '') == 'CLINIC'

@login_required
def case_edit(request, pk):
    case = get_object_or_404(Case, pk=pk)
    if not _is_clinic(request.user):
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden("Nur Praxis-Benutzer dürfen Fälle bearbeiten.")

    if request.method == 'POST':
        form = CaseForm(request.POST, instance=case)
        if form.is_valid():
            form.save()
            messages.success(request, "Fall gespeichert.")
            return redirect('case_detail', pk=case.pk)
    else:
        form = CaseForm(instance=case)

    return render(request, 'case_edit.html', {'form': form, 'case': case})

@require_POST
@login_required
def case_delete(request, pk):
    case = get_object_or_404(Case, pk=pk)
    if not _is_clinic(request.user):
        return HttpResponseForbidden("Nur Praxis-Benutzer dürfen Fälle löschen.")
    case.delete()
    messages.success(request, "Fall gelöscht.")
    return redirect('cases_list')


# -------------------------------
# LAB: QR code as PNG
@login_required
def lab_case_qr_png(request, pk):
    # only LAB users, only for their own case
    if user_role(request.user) != "LAB":
        return HttpResponseForbidden("Nicht erlaubt.")
    case = get_object_or_404(Case, pk=pk, lab=user_lab(request.user))
    url = public_token_url(case.qr_token)
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return HttpResponse(buf.getvalue(), content_type="image/png")



# -------------------------------
# CLINIC: manage lab users
@login_required
def clinic_lab_users(request):
    if getattr(getattr(request.user, "profile", None), "role", None) != "CLINIC":
        return HttpResponseForbidden("Nur für Klinik-Konten.")
    users = (User.objects
                 .filter(profile__role='LAB')
                 .select_related('profile__lab')
                 .order_by('profile__lab__name', 'username'))
    labs = Lab.objects.all().order_by('name')
    return render(request, "clinic_lab_users.html", {
        "users": users,
        "labs": labs,
        "form": LabUserCreateForm(),  # your existing create form
    })

@require_POST
@login_required
def clinic_create_lab_user(request):
    if getattr(getattr(request.user, "profile", None), "role", None) != "CLINIC":
        return HttpResponseForbidden("Nur für Klinik-Konten.")
    form = LabUserCreateForm(request.POST)
    if form.is_valid():
        user = User.objects.create_user(
            username=form.cleaned_data['username'],
            email=form.cleaned_data.get('email') or "",
            password=form.cleaned_data['password1'],
        )
        # profile created by your post_save signal; now set role + lab
        user.refresh_from_db()
        user.profile.role = "LAB"
        user.profile.lab = form.cleaned_data['lab']
        user.is_active = form.cleaned_data.get('is_active', True)
        user.profile.save()
        user.save(update_fields=['is_active', 'email'])
        messages.success(request, "Labor-Login wurde angelegt.")
    else:
        # surface exact form errors
        for field, errs in form.errors.get_json_data().items():
            for err in errs:
                messages.error(request, f"{field}: {err['message']}")
    return redirect("clinic_lab_users")

@require_POST
@login_required
def clinic_edit_lab_user(request, user_id):
    user = get_object_or_404(User, pk=user_id, profile__role='LAB')
    form = LabUserEditForm(request.POST, user_instance=user)
    if form.is_valid():
        user.username = form.cleaned_data['username']
        user.email = form.cleaned_data.get('email') or ""
        user.is_active = form.cleaned_data.get('is_active', False)
        user.profile.lab = form.cleaned_data['lab']
        user.profile.save()

        pwd = form.cleaned_data.get('password1')
        if pwd:
            user.set_password(pwd)
            user.save()  # <-- save everything incl. password
        else:
            user.save(update_fields=['username','email','is_active'])

        messages.success(request, "Labor-Login aktualisiert.")
    else:
        for field, errs in form.errors.get_json_data().items():
            for err in errs:
                messages.error(request, f"{field}: {err['message']}")
    return redirect("clinic_lab_users")

@require_POST
@login_required
def clinic_toggle_lab_user(request, user_id):
    if getattr(getattr(request.user, "profile", None), "role", None) != "CLINIC":
        return HttpResponseForbidden("Nur für Klinik-Konten.")
    user = get_object_or_404(User, pk=user_id, profile__role='LAB')
    action = (request.POST.get('action') or '').lower()
    if action == 'disable':
        user.is_active = False
        user.save(update_fields=['is_active'])
        messages.success(request, f"{user.username} wurde deaktiviert.")
    elif action == 'enable':
        user.is_active = True
        user.save(update_fields=['is_active'])
        messages.success(request, f"{user.username} wurde aktiviert.")
    else:
        messages.error(request, "Unbekannte Aktion.")
    return redirect("clinic_lab_users")


# -------------------------------
# CLINIC: display board (TV view)
# -------------------------------
@login_required
@role_required("CLINIC")
def display_board(request):
    # Read-only TV page — data comes via AJAX
    return render(request, "display_board.html")

@login_required
@role_required("CLINIC")
def dashboard_recent_api(request):
    # ?limit=ALL to return everything; otherwise cap to a sane number
    limit_param = (request.GET.get("limit") or "").strip().lower()
    if limit_param in ("all", "0", "-1"):
        qs = Case.objects.select_related("lab").order_by("-created_at")
    else:
        try:
            limit = max(1, min(int(limit_param or 500), 2000))  # default 500, hard cap 2000
        except ValueError:
            limit = 500
        qs = Case.objects.select_related("lab").order_by("-created_at")[:limit]

    data = [{
        "id": c.id,
        "case_code": c.case_code,
        "patient_name": c.patient_name,
        "patient_dob": c.patient_dob.strftime("%d.%m.%Y") if c.patient_dob else "",
        "patient_dob_order": c.patient_dob.strftime("%Y-%m-%d") if c.patient_dob else "",
        "lab": c.lab.name if c.lab else "",
        "status": c.status,
        "status_label": c.get_status_display(),
        "detail_url": reverse("case_detail", args=[c.id]),
        "delete_url": reverse("case_delete", args=[c.id]),
    } for c in qs]

    return JsonResponse(data, safe=False)

@login_required
@role_required("CLINIC")
def dashboard_counts_api(request):
    return JsonResponse({
        "sent": Case.objects.filter(status=Case.Status.SENT_CLINIC).count(),
        "in_lab": Case.objects.filter(status=Case.Status.RECEIVED_BY_LAB).count(),
        "returned": Case.objects.filter(status=Case.Status.RETURNED_BY_LAB).count(),
        "completed": Case.objects.filter(status=Case.Status.RECEIVED_BY_CLINIC).count(),
    })


# -------------------------------
# CHAT / COMMENTS: clinic + lab
# -------------------------------
@require_POST
@login_required
def case_add_comment(request, pk):
    """
    Add a message + optional attachments to a case.
    Clinic can comment on all cases, Lab only on its own lab's cases.
    """
    case = get_object_or_404(Case, pk=pk)
    role = user_role(request.user)

    if role == "CLINIC":
        allowed = True
    elif role == "LAB":
        allowed = (case.lab_id == getattr(user_lab(request.user), "id", None))
    else:
        allowed = False

    if not allowed:
        return HttpResponseForbidden("Nicht erlaubt für diesen Fall.")

    form = CaseCommentForm(request.POST, request.FILES)
    if form.is_valid():
        comment = CaseComment.objects.create(
            case=case,
            author=request.user,
            text=form.cleaned_data["text"].strip(),
        )
        # multiple files
        for f in request.FILES.getlist("files"):
            Attachment.objects.create(
                case=case,
                uploaded_by=request.user,
                comment=comment,
                file=f,
                label=f.name,
            )
        messages.success(request, "Nachricht gesendet.")
    else:
        messages.error(request, "Bitte Nachricht oder Anhänge prüfen.")

    if role == "LAB":
        return redirect("lab_case_detail", pk=case.pk)
    return redirect("case_detail", pk=case.pk)


@login_required
def help_guide(request):
    contact_email = getattr(settings, "SUPPORT_EMAIL", "s.peroz@dens-health-management.de")
    return render(request, "help.html", {"contact_email": contact_email})
