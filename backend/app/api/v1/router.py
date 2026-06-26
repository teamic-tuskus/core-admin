"""Router composition for API v1."""

from fastapi import APIRouter

from app.api.v1.routes.admin import router as admin_router
from app.api.v1.routes.checkout import router as checkout_router
from app.api.v1.routes.coupons import router as coupons_router
from app.api.v1.routes.health import router as health_router
from app.api.v1.routes.integrations import router as integrations_router
from app.api.v1.routes.onboarding import router as onboarding_router
from app.api.v1.routes.otp import router as otp_router
from app.api.v1.routes.products import router as products_router
from app.api.v1.routes.sales import router as sales_router

router = APIRouter()
router.include_router(health_router)
router.include_router(integrations_router)
router.include_router(otp_router)
router.include_router(onboarding_router)
router.include_router(sales_router)
router.include_router(products_router)
router.include_router(coupons_router)
router.include_router(checkout_router)
router.include_router(admin_router)
