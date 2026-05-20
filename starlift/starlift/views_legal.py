from django.conf import settings
from django.views.generic import TemplateView


class LegalView(TemplateView):
    template_name: str = ""

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["legal_doc_version"] = settings.LEGAL_DOC_VERSION
        return ctx


class PrivacyView(LegalView):
    template_name = "legal/privacy.html"


class ConsentView(LegalView):
    template_name = "legal/consent.html"


class TermsView(LegalView):
    template_name = "legal/terms.html"
