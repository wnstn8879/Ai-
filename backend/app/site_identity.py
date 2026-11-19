"""Optional trusted Sites bridge. Never trust visitor headers without the secret."""

import hmac
import os
import secrets
from uuid import uuid5, NAMESPACE_URL
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from app.database import Session


def valid_service_key(request):
    expected = os.getenv("IMAGINE_SITE_SERVICE_KEY", "")
    supplied = request.headers.get("x-imagine-service-key", "")
    return len(expected) >= 32 and hmac.compare_digest(expected, supplied)


def service_user(request):
    if not os.getenv("IMAGINE_SITE_SERVICE_KEY"):
        return None
    visitor = request.headers.get("x-imagine-visitor")
    if visitor is None:
        return None
    site = os.getenv("IMAGINE_SITE_ID", "")
    if not site or not 1 <= len(visitor) <= 200 or not valid_service_key(request):
        raise HTTPException(401, "Trusted site identity required")
    from app.security import User, password_hash

    uid = str(uuid5(NAMESPACE_URL, "imagine-sites:" + site + ":" + visitor))
    with Session() as db:
        if db.get(User, uid) is not None:
            return uid
    try:
        with Session.begin() as db:
            db.add(
                User(
                    id=uid,
                    email="sites-" + uid + "@imagine.invalid",
                    display_name="IMAGINE 독자",
                    password_hash=password_hash(secrets.token_urlsafe(48)),
                )
            )
    except IntegrityError:
        with Session() as db:
            if db.get(User, uid) is None:
                raise
    return uid
