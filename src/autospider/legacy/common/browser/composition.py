"""Browser handler composition."""

from __future__ import annotations

from .handlers.base import BaseAnomalyHandler
from .handlers.captcha_handler import CaptchaHandler
from .handlers.challenge_handler import ChallengeHandler
from .handlers.login_handler import LoginHandler
from .handlers.rate_limit_handler import RateLimitHandler


def build_default_handlers() -> list[BaseAnomalyHandler]:
    return [
        LoginHandler(),
        CaptchaHandler(),
        ChallengeHandler(),
        RateLimitHandler(),
    ]
