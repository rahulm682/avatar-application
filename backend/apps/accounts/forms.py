from django.contrib.auth.forms import BaseUserCreationForm
from django.contrib.auth.forms import UserChangeForm as BaseUserChangeForm

from .models import User


class UserCreationForm(BaseUserCreationForm):
    """Admin 'add user' form: email and password."""

    class Meta:
        model = User
        fields = ("email",)


class UserChangeForm(BaseUserChangeForm):
    """Admin 'change user' form."""

    class Meta:
        model = User
        fields = "__all__"
