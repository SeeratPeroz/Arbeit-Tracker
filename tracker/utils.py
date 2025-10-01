from django.conf import settings


def public_token_url(token: str) -> str:
    base = getattr(settings, 'PUBLIC_BASE_URL', '')
    return f"{base}/t/{token}/".replace('//t','/t')