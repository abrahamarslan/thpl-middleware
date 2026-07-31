from pydantic import BaseModel

class OAuthInitiateRequest(BaseModel):
    return_url: str | None = None

class OAuthTokenResponse(BaseModel):
    access_token: str
    expires_in: int
