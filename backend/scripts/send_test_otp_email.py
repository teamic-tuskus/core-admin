"""Send a branded OTP test email using CoreAdmin SMTP settings and GCP secrets."""

from __future__ import annotations

import argparse
import random

from app.core.secret_manager import init_secret_manager
from app.core.settings import get_settings
from app.services.email_sender import SmtpEmailSender


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send OTP test email")
    parser.add_argument("--to", required=True, help="Recipient email address")
    parser.add_argument(
        "--otp",
        default=f"{random.randint(0, 999999):06d}",
        help="OTP code to send (default: random 6-digit)",
    )
    parser.add_argument(
        "--validity-minutes",
        type=int,
        default=10,
        help="OTP validity in minutes (default: 10)",
    )
    parser.add_argument(
        "--product-name",
        default="Core",
        help="Product name shown in email subject/body",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = get_settings()

    init_secret_manager(
        project_id=settings.gcp_project_id,
        default_version=settings.gcp_secret_version,
    )

    sender = SmtpEmailSender()
    sender.send_otp_email(
        to_email=args.to,
        otp_code=args.otp,
        validity_minutes=args.validity_minutes,
        product_name=args.product_name,
    )

    print(
        "OTP test email sent successfully "
        f"to {args.to} with code {args.otp} and validity {args.validity_minutes} minutes"
    )


if __name__ == "__main__":
    main()
