from django.conf import settings


def product(request):
    return {
        'billing_enabled': settings.BILLING_ENABLED,
        'kwacart_source_url': settings.KWACART_SOURCE_URL,
    }
