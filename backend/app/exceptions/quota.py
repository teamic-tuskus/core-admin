"""Quota enforcement exceptions for subscription limits."""


class QuotaExceededError(Exception):
    """Raised when a user exceeds their subscription quota."""

    def __init__(self, message: str, quota_type: str = "unknown"):
        self.message = message
        self.quota_type = quota_type
        super().__init__(message)


class UserSeatsExceededError(QuotaExceededError):
    """Raised when max active operators limit exceeded."""

    def __init__(self, message: str):
        super().__init__(message, quota_type="seats")
