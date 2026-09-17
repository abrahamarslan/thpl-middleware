from pydantic import BaseModel


class OAuthInitiateOut(BaseModel):
    authorization_url: str


class OAuthCallbackOut(BaseModel):
    connected: bool = True


class OAuthRevokeOut(BaseModel):
    disconnected: bool = True


class OAuthStatusOut(BaseModel):
    is_connected: bool
