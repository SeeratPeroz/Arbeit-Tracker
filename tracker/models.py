import uuid
from django.conf import settings
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from django.contrib.auth.hashers import make_password, check_password
from django.db.models.signals import post_save
from django.dispatch import receiver


class Lab(models.Model):
    name = models.CharField(max_length=120, unique=True)
    contact = models.CharField(max_length=200, blank=True)
    pin_hash = models.CharField(max_length=256, blank=True)  # per-Lab PIN (hashed)

    def set_pin(self, raw_pin: str):
        self.pin_hash = make_password(raw_pin)

    def check_pin(self, raw_pin: str) -> bool:
        return bool(self.pin_hash) and check_password(raw_pin, self.pin_hash)

    def __str__(self):
        return self.name


class Case(models.Model):
    class Status(models.TextChoices):
        SENT_CLINIC = ("SENT_CLINIC", "Von Praxis gesendet")
        RECEIVED_BY_LAB = ("RECEIVED_BY_LAB", "Im Labor eingegangen")
        RETURNED_BY_LAB = ("RETURNED_BY_LAB", "An Praxis zurückgesendet")
        RECEIVED_BY_CLINIC = ("RECEIVED_BY_CLINIC", "In Praxis erhalten")

    # Optional Lab-Substages (for Fortschritt im Labor)
    SUBSTAGE_CHOICES = [
        ("DESIGN", "Design"),
        ("MILL", "Fräsen"),
        ("SINTER", "Sintern"),
        ("GLAZE", "Glasur"),
        ("QA", "Qualitätsprüfung"),
    ]

    case_code = models.CharField(max_length=32, unique=True, editable=False)
    patient_name = models.CharField(max_length=120)
    patient_dob = models.DateField()
    lab = models.ForeignKey(Lab, on_delete=models.PROTECT)

    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.SENT_CLINIC
    )

    # Lab-progress helpers
    substage = models.CharField(max_length=20, choices=SUBSTAGE_CHOICES, blank=True)
    eta = models.DateField(null=True, blank=True)  # voraussichtliches Fertigstellungsdatum

    # Rücksendung an Praxis (Tracking etc.)
    returned_tracking_no = models.CharField(max_length=100, blank=True)
    returned_at = models.DateTimeField(null=True, blank=True)

    # QR / Schutzcode
    qr_token = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    protection_code = models.CharField(max_length=6, editable=False, blank=True, null=True)

    # Audit
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)  # useful for listings/orders

    def save(self, *args, **kwargs):
        # Generate case code (C-YYYY-#####)
        if not self.case_code:
            year = timezone.now().year
            last = (
                Case.objects.filter(case_code__startswith=f"C-{year}-")
                .order_by("-id")
                .first()
            )
            seq = 1
            if last:
                try:
                    seq = int(last.case_code.split("-")[-1]) + 1
                except Exception:
                    seq = last.id + 1
            self.case_code = f"C-{year}-{seq:05d}"

        # No per-case PIN anymore (global Praxis-PIN via AppSettings)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.case_code} — {self.patient_name}"


class Event(models.Model):
    """
    Ereignisprotokoll für einen Fall.
    - status: Status, der gesetzt/erreicht wurde
    - action/payload: optional für detaillierte Lab-Aktionen (Upload, Check-in, etc.)
    """
    case = models.ForeignKey(Case, on_delete=models.CASCADE, related_name="events")
    status = models.CharField(max_length=20, choices=Case.Status.choices)

    # optional detailierte Aktion
    action = models.CharField(max_length=50, blank=True)
    payload = models.JSONField(default=dict, blank=True)

    note = models.TextField(blank=True)
    actor = models.CharField(
        max_length=12,
        choices=[("CLINIC", "Clinic"), ("LAB", "Lab"), ("PUBLIC", "Public")],
        default="PUBLIC",
    )
    ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        when = self.created_at.strftime("%Y-%m-%d %H:%M")
        return f"{self.case.case_code}: {self.get_status_display()} @ {when}"


class Attachment(models.Model):
    """Dateianhänge (Berichte, Fotos, STL, etc.) pro Fall."""
    case = models.ForeignKey(Case, on_delete=models.CASCADE, related_name="attachments")
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    file = models.FileField(upload_to="case_attachments/%Y/%m/")
    label = models.CharField(max_length=120, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        base = self.label or (self.file.name if self.file else "Attachment")
        return f"{self.case.case_code} — {base}"


class UserProfile(models.Model):
    class Role(models.TextChoices):
        CLINIC = ("CLINIC", "Clinic")
        LAB = ("LAB", "Lab")

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.CLINIC)
    lab = models.ForeignKey(Lab, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return f"{self.user.username} ({self.role})"


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)


class AppSettings(models.Model):
    """Globale App-Einstellungen, inkl. Praxis-PIN (gehasht)."""
    name = models.CharField(max_length=32, unique=True, default="default")
    praxis_pin_hash = models.CharField(max_length=256, blank=True)

    def set_praxis_pin(self, raw_pin: str):
        self.praxis_pin_hash = make_password(raw_pin)

    def check_praxis_pin(self, raw_pin: str) -> bool:
        return bool(self.praxis_pin_hash) and check_password(raw_pin, self.praxis_pin_hash)

    @classmethod
    def get(cls):
        obj, created = cls.objects.get_or_create(name="default")
        if created or not obj.praxis_pin_hash:
            obj.set_praxis_pin("000000")   # default
            obj.save()
        return obj
