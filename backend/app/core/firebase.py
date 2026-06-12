"""Firebase Admin SDK initialization using GCP Secret Manager only."""

from __future__ import annotations

import json
from functools import lru_cache

import firebase_admin
from firebase_admin import auth, credentials, firestore, storage

from app.core.secret_manager import get_secret
from app.core.settings import get_settings


@lru_cache(maxsize=1)
def get_firebase_app() -> firebase_admin.App:
    """Initialize Firebase Admin from the service account JSON secret."""
    settings = get_settings()
    if firebase_admin._apps:
        return firebase_admin.get_app()

    service_account_json = get_secret("firebase-service-account-json")
    service_account_info = json.loads(service_account_json)
    cred = credentials.Certificate(service_account_info)
    app_options: dict[str, str] = {"projectId": settings.gcp_project_id}
    if settings.firebase_storage_bucket:
        app_options["storageBucket"] = settings.firebase_storage_bucket
    return firebase_admin.initialize_app(cred, app_options)


def get_firestore_client():
    """Return a Firestore client bound to the initialized Firebase app."""
    get_firebase_app()
    return firestore.client()


def get_firebase_auth():
    """Return Firebase auth module after initialization."""
    get_firebase_app()
    return auth


def get_storage_bucket():
    """Return Firebase Storage bucket bound to the initialized Firebase app."""
    get_firebase_app()
    return storage.bucket()
