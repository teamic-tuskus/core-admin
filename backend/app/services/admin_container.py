"""Admin service wiring."""

from __future__ import annotations

from functools import lru_cache

from app.core.settings import get_settings
from app.services.admin_service import AdminService
from app.services.firestore_repositories import (
    FirestorePortalAccessInvitationRepository,
    FirestoreSuperAdminRepository,
    FirestoreSubscriptionRepository,
    FirestoreTenantRepository,
)
from app.services.email_sender import SmtpEmailSender
from app.services.payment_gateway import RazorpayGateway
from app.services.repositories import (
    PortalAccessInvitationRepository,
    SubscriptionRepository,
    SuperAdminRepository,
    TenantRepository,
)


@lru_cache(maxsize=1)
def get_admin_service() -> AdminService:
    settings = get_settings()
    if settings.storage_backend == "firestore":
        tenant_repo = FirestoreTenantRepository()
        subscription_repo = FirestoreSubscriptionRepository()
        super_admin_repo = FirestoreSuperAdminRepository()
        portal_access_invitation_repo = FirestorePortalAccessInvitationRepository()
    else:
        tenant_repo = TenantRepository()
        subscription_repo = SubscriptionRepository()
        super_admin_repo = SuperAdminRepository()
        portal_access_invitation_repo = PortalAccessInvitationRepository()
    return AdminService(
        tenant_repo=tenant_repo,
        subscription_repo=subscription_repo,
        super_admin_repo=super_admin_repo,
        portal_access_invitation_repo=portal_access_invitation_repo,
        email_sender=SmtpEmailSender(),
        gateway=RazorpayGateway(),
    )
