
import hashlib
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from redis import Redis
from redis.exceptions import RedisError
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.auth_service import (
    create_access_token,
    hash_password,
    verify_password,
)
from app.config import settings
from app.database import get_db
from app.models import User
from app.schemas_auth import (
    TokenResponse,
    UserLogin,
    UserRegister,
    UserResponse,
)


logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/auth",
    tags=["Authentication"],
)


# ---------------------------------------------------------
# REDIS RATE LIMITER
# ---------------------------------------------------------

redis_client = Redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=2,
    socket_timeout=2,
)


def get_client_ip(request: Request) -> str:
    """
    Get the connecting client's IP address.

    Behind a reverse proxy, configure trusted proxy handling
    separately. Do not blindly trust X-Forwarded-For.
    """

    if request.client:
        return request.client.host

    return "unknown"


def make_rate_limit_key(category: str, value: str) -> str:
    """
    Hash identifying information before storing it in Redis.
    """

    hashed_value = hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()

    return f"auth:ratelimit:{category}:{hashed_value}"


def get_rate_limit_count(key: str) -> int:
    try:
        count = redis_client.get(key)
        return int(count or 0)

    except RedisError as exc:
        logger.exception("Redis rate-limit check failed")

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service temporarily unavailable",
        ) from exc


def increment_rate_limit(key: str, window_seconds: int) -> int:
    """
    Atomically increment a Redis counter and set its expiry
    on the first request.
    """

    script = """
    local count = redis.call('INCR', KEYS[1])

    if count == 1 then
        redis.call('EXPIRE', KEYS[1], ARGV[1])
    end

    return count
    """

    try:
        return int(
            redis_client.eval(
                script,
                1,
                key,
                window_seconds,
            )
        )

    except RedisError as exc:
        logger.exception("Redis rate-limit update failed")

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service temporarily unavailable",
        ) from exc


def check_login_rate_limit(
    ip_key: str,
    email_key: str,
):
    """
    Block login requests when either the IP address or
    email address has reached its failed-attempt limit.
    """

    ip_attempts = get_rate_limit_count(ip_key)
    email_attempts = get_rate_limit_count(email_key)

    if (
        ip_attempts >= settings.login_max_attempts
        or email_attempts >= settings.login_max_attempts
    ):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts. Please try again later.",
        )


# ---------------------------------------------------------
# USER REGISTRATION
# ---------------------------------------------------------

@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_user(
    payload: UserRegister,
    request: Request,
    db: Session = Depends(get_db),
):
    ip_address = get_client_ip(request)

    registration_key = make_rate_limit_key(
        "register_ip",
        ip_address,
    )

    registration_attempts = increment_rate_limit(
        registration_key,
        settings.registration_window_seconds,
    )

    if registration_attempts > settings.registration_max_attempts:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many registration attempts. Please try again later.",
        )

    username = payload.username.strip().lower()
    email = str(payload.email).strip().lower()

    existing_user = db.scalar(
        select(User).where(
            or_(
                User.username == username,
                User.email == email,
            )
        )
    )

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username or email is already registered",
        )

    user = User(
        username=username,
        email=email,
        hashed_password=hash_password(payload.password),
        role=payload.role,
    )

    try:
        db.add(user)
        db.commit()
        db.refresh(user)

    except IntegrityError:
        db.rollback()

        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username or email is already registered",
        )

    return user


# ---------------------------------------------------------
# USER LOGIN
# ---------------------------------------------------------

@router.post(
    "/login",
    response_model=TokenResponse,
)
def login_user(
    payload: UserLogin,
    request: Request,
    db: Session = Depends(get_db),
):
    email = str(payload.email).strip().lower()
    ip_address = get_client_ip(request)

    ip_key = make_rate_limit_key(
        "login_ip",
        ip_address,
    )

    email_key = make_rate_limit_key(
        "login_email",
        email,
    )

    # Check previous failed attempts before authentication.
    check_login_rate_limit(
        ip_key,
        email_key,
    )

    user = db.scalar(
        select(User).where(User.email == email)
    )

    if user is None or not verify_password(
        payload.password,
        user.hashed_password,
    ):
        # Count only failed login attempts.
        increment_rate_limit(
            ip_key,
            settings.login_window_seconds,
        )

        increment_rate_limit(
            email_key,
            settings.login_window_seconds,
        )

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account is inactive",
        )

    access_token = create_access_token(
        {
            "sub": str(user.id),
            "role": user.role,
        }
    )

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=settings.access_token_expire_minutes * 60,
        user=user,
    )


# ---------------------------------------------------------
# CURRENT USER PROFILE
# ---------------------------------------------------------

@router.get(
    "/me",
    response_model=UserResponse,
)
def get_my_profile(
    current_user: User = Depends(get_current_user),
):
    return current_user
