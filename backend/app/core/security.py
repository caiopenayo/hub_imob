from typing import Optional

from fastapi import Header, HTTPException

from .config import SECRET_KEY


def require_api_key(x_api_key: Optional[str] = Header(None)) -> None:
    if not SECRET_KEY:
        raise HTTPException(status_code=500, detail="Server secret not configured")
    if not x_api_key or x_api_key != SECRET_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")
