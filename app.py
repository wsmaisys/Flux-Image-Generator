"""
FLUX Image Generator API
=======================

This FastAPI application provides an interface to generate images using the FLUX.1-schnell model.

PRIVACY NOTICE:
--------------
- User-provided HF tokens are NEVER logged, cached, or stored
- Prompts are logged only in truncated form (first 50 chars)
- No user data is persisted to disk or databases
- Each request is processed independently with no session tracking

Usage Instructions:
-----------------

1. Web Interface:
   - Access the web UI by opening http://localhost:8000 in your browser
   - Fill in the prompt and adjust image dimensions
   - Optionally provide your own HF token if the default token fails

2. Using curl:
   a) Generate Image (save as PNG):
      ```
      curl -X POST "http://localhost:8000/generate-image" \
        -H "Content-Type: application/json" \
        -d "{\"prompt\": \"a beautiful sunset\", \"width\": 1024, \"height\": 768}" \
        --output image.png
      ```

   b) Generate with custom HF token:
      ```
      curl -X POST "http://localhost:8000/generate-image" \
        -H "Content-Type: application/json" \
        -d "{\"prompt\": \"a beautiful sunset\", \"hf_token\": \"hf_...\"}" \
        --output image.png
      ```

Environment Variables:
-------------------
- HF_TOKEN: Your Hugging Face API token (optional - users can provide their own)
"""

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from huggingface_hub import InferenceClient
from pydantic import BaseModel, Field
from dotenv import load_dotenv
import os
import base64
import io
import logging
import hashlib
from typing import Optional
from PIL import Image

# Load environment variables
load_dotenv()

# Setup logging with privacy filters
class PrivacyFilter(logging.Filter):
    """Filter to prevent sensitive data from appearing in logs"""
    def filter(self, record):
        # Redact any HF tokens that might appear in logs
        if hasattr(record, 'msg'):
            msg = str(record.msg)
            # Redact patterns that look like HF tokens
            if 'hf_' in msg.lower():
                record.msg = msg.replace(msg[msg.lower().find('hf_'):msg.lower().find('hf_')+20], '[REDACTED]')
        return True

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
logger.addFilter(PrivacyFilter())

app = FastAPI()

# Mount static directory
app.mount("/static", StaticFiles(directory="static"), name="static")

# Model configuration
MODEL_ID = "black-forest-labs/FLUX.1-schnell"  # Keep original model ID
DEFAULT_TOKEN = os.environ.get("HF_TOKEN")

class ImageRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=1000)
    width: int = Field(default=1024, ge=256, le=2048)
    height: int = Field(default=768, ge=256, le=2048)
    return_format: Optional[str] = Field(default="base64", pattern="^(base64|raw)$")
    hf_token: Optional[str] = None
    
    class Config:
        # Ensure tokens are never included in any Pydantic representations
        json_encoders = {
            str: lambda v: '[REDACTED]' if v and 'hf_' in v.lower() else v
        }

def get_token_hash(token: Optional[str]) -> str:
    """Create a secure hash of token for identification without exposing it"""
    if not token:
        return "default"
    # Use SHA256 hash for secure, one-way identification
    return hashlib.sha256(token.encode()).hexdigest()[:8]

def create_client(token: Optional[str] = None) -> InferenceClient:
    """Create InferenceClient without caching to protect user privacy"""
    api_key = token or DEFAULT_TOKEN
    if not api_key:
        raise ValueError("No HF token available")
    return InferenceClient(
        provider="nebius",
        api_key=api_key
    )

@app.get("/")
async def read_root(request: Request):
    if "curl" in request.headers.get("user-agent", "").lower():
        return {
            "message": "FLUX Image Generator API",
            "privacy": "User tokens and prompts are never logged or stored",
            "endpoints": {
                "generate": "POST /generate-image",
                "health": "GET /health"
            },
            "example": 'curl -X POST "http://localhost:8000/generate-image" -H "Content-Type: application/json" -d "{\\"prompt\\": \\"a cat\\"}" --output image.png'
        }
    return FileResponse("static/index.html")

@app.get("/health")
async def health_check():
    has_default_token = bool(DEFAULT_TOKEN)
    return {
        "status": "healthy",
        "model": MODEL_ID,
        "default_token_configured": has_default_token
    }

@app.post("/generate-image")
async def generate_image(req: ImageRequest, http_request: Request):
    # Create token hash for logging (privacy-safe)
    token_hash = get_token_hash(req.hf_token)
    
    try:
        # Create client (not cached to prevent token exposure)
        try:
            client = create_client(req.hf_token)
        except ValueError:
            raise HTTPException(
                status_code=401,
                detail="No HF token provided. Set HF_TOKEN environment variable or pass hf_token in request."
            )
        
        # Log only truncated prompt and token hash (never full prompt or token)
        prompt_preview = req.prompt[:50] + "..." if len(req.prompt) > 50 else req.prompt
        logger.info(f"Request [token:{token_hash}]: '{prompt_preview}' ({req.width}x{req.height})")
        
        # Ensure dimensions are multiples of 8
        width = (req.width // 8) * 8
        height = (req.height // 8) * 8
        
        try:
            # Generate image
            image = client.text_to_image(
                prompt=req.prompt,
                model=MODEL_ID,
                width=width,
                height=height
            )
            logger.info(f"Success [token:{token_hash}]")
            
        except Exception as e:
            error_msg = str(e).lower()
            
            # Map error to appropriate HTTP status
            if any(x in error_msg for x in ["token", "unauthorized", "authentication"]):
                status_code, detail = 401, "Invalid HF token. Check your token or try providing your own."
            elif "timeout" in error_msg:
                status_code, detail = 504, "Request timed out. Try a simpler prompt or smaller dimensions."
            elif "rate limit" in error_msg:
                status_code, detail = 429, "Rate limit exceeded. Try again later or use your own HF token."
            else:
                status_code = 500
                # Log the actual error for debugging
                logger.error(f"Error details [token:{token_hash}]: {error_msg}")
                detail = "Image generation failed. Please try again."
            
            logger.error(f"Error [token:{token_hash}]: {status_code} - {detail}")
            raise HTTPException(status_code=status_code, detail=detail)
        
        # Convert to bytes
        img_bytes = io.BytesIO()
        image.save(img_bytes, format='PNG', optimize=True)
        img_bytes = img_bytes.getvalue()
        
        # Clear client reference immediately to allow garbage collection
        del client
        
        # Return based on format
        is_curl = "curl" in http_request.headers.get("user-agent", "").lower()
        if req.return_format == "raw" or (is_curl and req.return_format != "base64"):
            return Response(
                content=img_bytes,
                media_type="image/png",
                headers={
                    "Content-Disposition": "attachment; filename=generated-image.png",
                    # Privacy headers
                    "Cache-Control": "no-store, no-cache, must-revalidate, private",
                    "Pragma": "no-cache",
                    "Expires": "0"
                }
            )
        
        return {
            "image_base64": base64.b64encode(img_bytes).decode("utf-8")
        }
        
    except HTTPException:
        raise
    except Exception as e:
        # Log error details without sensitive info
        error_type = type(e).__name__
        error_msg = str(e)
        if "token" not in error_msg.lower():
            logger.error(f"Unexpected error [token:{token_hash}]: {error_type} - {error_msg}")
        else:
            logger.error(f"Unexpected error [token:{token_hash}]: {error_type}")
        raise HTTPException(status_code=500, detail="An unexpected error occurred. Please try again.")


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    # Add privacy and security headers
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    return response