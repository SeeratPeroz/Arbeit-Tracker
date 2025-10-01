from functools import wraps
from django.http import HttpResponseForbidden

def role_required(role):
    def deco(view):
        @wraps(view)
        def _wrap(request, *a, **kw):
            r = getattr(getattr(request.user, "profile", None), "role", None)
            return view(request, *a, **kw) if r == role else HttpResponseForbidden("Nicht erlaubt.")
        return _wrap
    return deco
