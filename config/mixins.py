from django.contrib import messages
from django.db.models.deletion import ProtectedError
from django.http import HttpResponseRedirect
from django.urls import reverse_lazy


class ProtectedDeleteMixin:
    """
    Reusable mixin for safe delete handling.

    Purpose:
    - Prevent raw error pages when an object cannot be deleted due to related data.
    - Show a friendly Django message instead.
    - Redirect the user back to a safe page.
    - Keep delete success/error messaging centralized in one place.
    """

    protected_message = (
        "This item cannot be deleted because there is related data connected to it."
    )
    delete_success_message = "{object} was deleted successfully."
    protected_redirect_url = None

    def get_protected_message(self):
        return self.protected_message

    def get_delete_success_message(self, object_display):
        return self.delete_success_message.format(object=object_display)

    def get_protected_redirect_url(self):
        if self.protected_redirect_url:
            return str(self.protected_redirect_url)

        if hasattr(self, "success_url") and self.success_url:
            return str(self.success_url)

        return str(reverse_lazy("home"))

    def form_valid(self, form):
        self.object = self.get_object()
        object_display = str(self.object)

        try:
            success_url = self.get_success_url()
            self.object.delete()
        except ProtectedError:
            messages.error(self.request, self.get_protected_message())
            return HttpResponseRedirect(self.get_protected_redirect_url())

        messages.success(self.request, self.get_delete_success_message(object_display))
        return HttpResponseRedirect(success_url)