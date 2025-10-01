import io
import qrcode
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.core.paginator import Paginator
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from tracker.decorators import role_required
from .forms import CaseCreateForm, LabSearchForm, LabActionForm,LabPinForm,GlobalPinForm,PraxisPinForm
from django.contrib.auth import logout
from .models import Case, Event, Lab
from .utils import public_token_url
from .models import AppSettings
from django.contrib import messages


def user_logout(request):
    print("Logging out user:", request.user)
    logout(request)
    return redirect('login')   # send to login page after logout


@login_required
def home(request):
    role = getattr(getattr(request.user, "profile", None), "role", None)
    return redirect("lab_home") if role == "LAB" else redirect("cases_list")


# Roles 
def user_role(u): return getattr(getattr(u, "profile", None), "role", None)
def user_lab(u):  return getattr(getattr(u, "profile", None), "lab", None)

@login_required
def lab_home(request):
    if user_role(request.user) != "LAB":
        from django.http import HttpResponseForbidden
        return HttpResponseForbidden("Nicht erlaubt.")
    lab = user_lab(request.user)
    from .forms import LabSearchForm
    form = LabSearchForm(request.GET or None)
    case = None
    if form.is_valid():
        code = form.cleaned_data["case_code"].strip()
        case = Case.objects.filter(case_code__iexact=code, lab=lab).first()
    return render(request, "lab_home.html", {"form": form, "case": case})



@role_required("CLINIC")
@login_required
def dashboard(request):
    counts = {
        "sent": Case.objects.filter(status=Case.Status.SENT_CLINIC).count(),
        "in_lab": Case.objects.filter(status=Case.Status.RECEIVED_BY_LAB).count(),
        "returned": Case.objects.filter(status=Case.Status.RETURNED_BY_LAB).count(),
        "completed": Case.objects.filter(status=Case.Status.RECEIVED_BY_CLINIC).count(),
    }
    recent = Case.objects.order_by("-created_at")[:10]
    return render(request, "dashboard.html", {"counts": counts, "recent": recent})


@login_required
def cases_list(request):
    qs = Case.objects.all().order_by("-created_at")
    status = request.GET.get("status")
    q = request.GET.get("q")

    if status:
        qs = qs.filter(status=status)

    if q:
        qs = qs.filter(Q(patient_name__icontains=q) | Q(case_code__icontains=q))

    ctx = {"cases": qs, "status": status, "q": q, "Case": Case}
    return render(request, "cases_list.html", ctx)


@login_required
@role_required("CLINIC")
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


@login_required
@role_required("CLINIC")
def case_detail(request, pk: int):
    case = get_object_or_404(Case, pk=pk)
    return render(request, "case_detail.html", {"case": case})


@login_required
@role_required("CLINIC")
def label_print(request, pk: int):
    case = get_object_or_404(Case, pk=pk)
    token_url = public_token_url(case.qr_token)
    return render(request, "label_print.html", {"case": case, "token_url": token_url})


@login_required
@role_required("CLINIC")
def case_qr_png(request, pk: int):
    """
    Returns a PNG of the QR code for this case's public token URL.
    Embedded by <img src="/cases/<id>/qr.png"> in templates.
    """
    case = get_object_or_404(Case, pk=pk)
    url = public_token_url(case.qr_token)
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return HttpResponse(buf.getvalue(), content_type="image/png")



    """
    Public page opened from the QR code (no login).
    Lab (or clinic on return) enters a 6-digit protection code and performs
    the next allowed action, with an optional note.
    """
def public_token_view(request, token):
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
            pin_ok = case.lab and case.lab.check_pin(code)
        elif need == "CLINIC":
            pin_ok = AppSettings.get().check_praxis_pin(code)

        if not pin_ok:
            messages.error(request, "Schutzcode ist falsch.")
            return render(request, "public_token.html", {"case": case})

        # Record and update
        actor = "LAB" if need == "LAB" else "CLINIC"
        Event.objects.create(
            case=case, status=target, actor=actor, note=note,
            ip=request.META.get("REMOTE_ADDR"), user_agent=request.META.get("HTTP_USER_AGENT",""),
        )
        case.status = target
        case.save(update_fields=["status"])
        messages.success(request, "Status aktualisiert.")
        return redirect("public_token", token=token)

    return render(request, "public_token.html", {"case": case})
    

@login_required
def settings_pin(request):
    if not require_role(request.user, "CLINIC"):
        return HttpResponseForbidden("Nur für Klinik-Konten.")
    settings_obj = AppSettings.get()

    if request.method == "POST":
        form = GlobalPinForm(request.POST)
        if form.is_valid():
            # Optional: if you want to enforce knowing current pin when one is set
            cur = form.cleaned_data.get("current_pin") or ""
            if settings_obj.pin_hash and not settings_obj.check_pin(cur):
                messages.error(request, "Aktueller PIN ist falsch.")
            else:
                settings_obj.set_pin(form.cleaned_data["new_pin"])
                settings_obj.save()
                messages.success(request, "Globaler PIN wurde aktualisiert.")
                return redirect("settings_pin")
    else:
        form = GlobalPinForm()

    return render(request, "settings_pin.html", {"form": form})


def require_role(user, role):
    return getattr(getattr(user, "profile", None), "role", None) == role


@login_required
def settings_praxis_pin(request):
    if not require_role(request.user, "CLINIC"):
        return HttpResponseForbidden("Nur für Klinik-Konten.")
    settings_obj = AppSettings.get()
    if request.method == "POST":
        form = PraxisPinForm(request.POST)
        if form.is_valid():
            settings_obj.set_praxis_pin(form.cleaned_data["new_pin"])
            settings_obj.save()
            messages.success(request, "Praxis-PIN wurde aktualisiert.")
            return redirect("settings_praxis_pin")
    else:
        form = PraxisPinForm()
    return render(request, "settings_praxis_pin.html", {"form": form})


@login_required
def clinic_mark_received(request, pk):
    if not require_role(request.user, "CLINIC"):
        return HttpResponseForbidden("Nur für Klinik-Konten.")
    case = get_object_or_404(Case, pk=pk)
    if case.status != Case.Status.RETURNED_BY_LAB:
        return HttpResponseForbidden("Dieser Schritt ist aktuell nicht erlaubt.")
    Event.objects.create(case=case, status=Case.Status.RECEIVED_BY_CLINIC,
                         actor="CLINIC", note="In Praxis erhalten")
    case.status = Case.Status.RECEIVED_BY_CLINIC
    case.save(update_fields=["status"])
    return redirect("case_detail", pk=case.pk)



@login_required
def clinic_set_lab_pin(request, lab_id):
    # only clinic users may set PINs
    if user_role(request.user) != "CLINIC":
        return HttpResponseForbidden("Nur für Klinik-Konten.")
    lab = get_object_or_404(Lab, pk=lab_id)

    if request.method == "POST":
        form = LabPinForm(request.POST)
        if form.is_valid():
            lab.set_pin(form.cleaned_data["new_pin"])
            lab.save()
            messages.success(request, f"PIN für {lab.name} aktualisiert.")
            return redirect("clinic_edit_lab", lab_id=lab.id)  # or wherever your lab edit page is
    else:
        form = LabPinForm()

    return render(request, "clinic_set_lab_pin.html", {"lab": lab, "form": form})


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
    return render(request, "lab_cases_list.html", {"page": page, "status": status, "q": q, "Case": Case})

@login_required
def lab_case_detail(request, pk):
    if user_role(request.user) != "LAB":
        return HttpResponseForbidden("Nicht erlaubt.")
    lab = user_lab(request.user)
    case = get_object_or_404(Case, pk=pk, lab=lab)  # <= only this lab’s case

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
            Event.objects.create(case=case, status=target, actor="LAB", note=note,
                                 ip=request.META.get("REMOTE_ADDR"),
                                 user_agent=request.META.get("HTTP_USER_AGENT",""))
            case.status = target
            case.save(update_fields=["status"])
            return redirect("lab_case_detail", pk=case.pk)

    # Build action list for template
    actions = []
    if Case.Status.RECEIVED_BY_LAB in allowed: actions.append(("receive_lab", "Im Labor eingegangen"))
    if Case.Status.RETURNED_BY_LAB in allowed: actions.append(("return_lab", "Zurück an Praxis"))

    return render(request, "lab_case_detail.html", {"case": case, "actions": actions})