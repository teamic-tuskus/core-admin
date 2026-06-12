"""Provision or update a CoreAdmin super admin user in Firebase Auth + Firestore.

Usage example:
  COREADMIN_GCP_PROJECT_ID=core-admin-tuskus \
  python3 scripts/create_super_admin_user.py \
    --email sagar@teamic.in \
    --password 123456 \
    --name "sagar singh" \
    --designation "Director"
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone

from app.core.firebase import get_firebase_auth, get_firestore_client
from app.core.secret_manager import init_secret_manager
from app.core.settings import get_settings


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create or update a CoreAdmin super admin user")
    parser.add_argument("--email", required=True, help="Super admin email")
    parser.add_argument("--password", required=True, help="Super admin password")
    parser.add_argument("--name", required=True, help="Full name")
    parser.add_argument("--designation", required=True, help="Designation label")
    parser.add_argument(
        "--email-verified",
        action="store_true",
        default=True,
        help="Mark email as verified (default: true)",
    )
    return parser.parse_args()


def ensure_super_admin(*, email: str, password: str, name: str, designation: str, email_verified: bool) -> dict:
    auth_client = get_firebase_auth()
    db = get_firestore_client()

    normalized_email = email.strip().lower()
    display_name = name.strip()
    now = _now()

    created = False
    try:
        existing = auth_client.get_user_by_email(normalized_email)
        user = auth_client.update_user(
            existing.uid,
            email=normalized_email,
            password=password,
            display_name=display_name,
            disabled=False,
            email_verified=email_verified,
        )
    except Exception:
        user = auth_client.create_user(
            email=normalized_email,
            password=password,
            display_name=display_name,
            disabled=False,
            email_verified=email_verified,
        )
        created = True

    claims = {
        "role": "super_admin",
        "roles": ["admin", "super_admin"],
    }
    auth_client.set_custom_user_claims(user.uid, claims)

    db.collection("admin_profiles").document(user.uid).set(
        {
            "uid": user.uid,
            "email": normalized_email,
            "full_name": display_name,
            "designation": designation.strip(),
            "role": "super_admin",
            "updated_at": now,
            "created_at": now,
        },
        merge=True,
    )

    db.collection("super_admin").document("current").set(
        {
            "uid": user.uid,
            "email": normalized_email,
            "display_name": display_name,
            "assigned_at": now,
            "assigned_by_uid": user.uid,
            "assigned_by_email": normalized_email,
            "updated_at": now,
        }
    )

    return {
        "uid": user.uid,
        "email": normalized_email,
        "display_name": display_name,
        "designation": designation.strip(),
        "created": created,
    }


def main() -> None:
    args = parse_args()
    settings = get_settings()
    init_secret_manager(settings.gcp_project_id, settings.gcp_secret_version)

    result = ensure_super_admin(
        email=args.email,
        password=args.password,
        name=args.name,
        designation=args.designation,
        email_verified=bool(args.email_verified),
    )

    status = "created" if result["created"] else "updated"
    print(f"Super admin {status}: {result['email']} ({result['uid']})")
    print(f"Name: {result['display_name']}")
    print(f"Designation: {result['designation']}")


if __name__ == "__main__":
    main()
