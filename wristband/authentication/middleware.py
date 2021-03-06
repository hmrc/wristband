# https://github.com/MongoEngine/mongoengine/issues/966

from django.utils.functional import SimpleLazyObject
from mongoengine.django.auth import get_user

from .utils import get_user_session_key



class AuthenticationMiddleware(object):
    def process_request(self, request):
        assert hasattr(request, 'session'), (
            "The Django authentication middleware requires session middleware "
            "to be installed. Edit your MIDDLEWARE_CLASSES setting to insert "
            "'django.contrib.sessions.middleware.SessionMiddleware' before "
            "'django.contrib.auth.middleware.AuthenticationMiddleware'."
        )
        request.user = SimpleLazyObject(lambda: get_user(get_user_session_key(request)))
