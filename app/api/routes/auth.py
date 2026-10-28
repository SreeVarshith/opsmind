from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.security import User, UserStore, create_token, get_current_user, get_user_store

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int
    username: str
    role: str


class MeResponse(BaseModel):
    username: str
    role: str
    access: list[str]


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest, store: UserStore = Depends(get_user_store)) -> TokenResponse:
    s = get_settings()
    user = store.authenticate(req.username, req.password)
    if user is None:  # same message for unknown user and wrong password
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong username or password")
    if not s.jwt_secret:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "JWT_SECRET is not configured")
    return TokenResponse(access_token=create_token(user, s.jwt_secret, s.token_ttl_minutes),
                         expires_in_minutes=s.token_ttl_minutes, username=user.username, role=user.role)


@router.get("/me", response_model=MeResponse)
def me(user: User = Depends(get_current_user)) -> MeResponse:
    return MeResponse(username=user.username, role=user.role, access=user.access)
