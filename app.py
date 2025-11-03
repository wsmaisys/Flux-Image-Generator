"""
FLUX Image Generator API
=======================

This FastAPI application provides an interface to generate images using the FLUX.1-schnell model.

Usage Instructions:
-----------------

1. Web Interface:
   - Access the web UI by opening http://localhost:8000 in your browser
   - Fill in the prompt and adjust image dimensions
   - Click Generate to create an image

2. Using curl:
   a) Get API Information:
      ```
      curl http://localhost:8000
      ```

   b) Generate Image (save as PNG):
      ```
      curl -X POST "http://localhost:8000/generate-image" \
        -H "Content-Type: application/json" \
        -d "{\"prompt\": \"a beautiful sunset\", \"width\": 1024, \"height\": 768, \"return_format\": \"raw\"}" \
        --output image.png
      ```

   c) Generate Image (get base64):
      ```
      curl -X POST "http://localhost:8000/generate-image" \
        -H "Content-Type: application/json" \
        -d "{\"prompt\": \"a beautiful sunset\", \"width\": 1024, \"height\": 768, \"return_format\": \"base64\"}"
      ```

   d) Check API Health:
      ```
      curl http://localhost:8000/health
      ```

Docker Usage:
-----------
1. Build the image:
   ```
   docker build -t flux-image-generator .
   ```

2. Run the container:
   ```
   docker run -p 8000:8000 --env-file .env flux-image-generator
   ```

Environment Variables:
-------------------
- HF_TOKEN: Your Hugging Face API token (required)
"""

from fastapi import FastAPI, Body, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, Response
from huggingface_hub import InferenceClient
from pydantic import BaseModel
from dotenv import load_dotenv
import os, base64
from typing import Optional

# Load environment variables from .env file
load_dotenv()

app = FastAPI()

# Mount the static directory
app.mount("/static", StaticFiles(directory="static"), name="static")

client = InferenceClient(
    token=os.environ.get("HF_TOKEN")
)

class ImageRequest(BaseModel):
    prompt: str
    width: int = 1024
    height: int = 768
    return_format: Optional[str] = "base64"  # Can be "base64" or "raw"
    hf_token: Optional[str] = None

@app.get("/")
async def read_root(request: Request):
    if "curl" in request.headers.get("user-agent", "").lower():
        return {
            "message": "Welcome to FLUX Image Generator API",
            "endpoints": {
                "generate": "POST /generate-image",
                "health": "GET /health"
            },
            "example": 'curl -X POST "http://localhost:8000/generate-image" -H "Content-Type: application/json" -d "{\\"prompt\\": \\"a beautiful sunset\\", \\"width\\": 1024, \\"height\\": 768, \\"return_format\\": \\"raw\\"}" --output image.png'
        }
    return FileResponse("static/index.html")

@app.get("/health")
async def health_check():
    return {"status": "healthy", "version": "1.0.0"}

@app.post("/generate-image")
async def generate_image(request: ImageRequest, http_request: Request):
    try:
        # Create a new client instance if user provided a token
        current_client = InferenceClient(token=request.hf_token) if request.hf_token else client
        
        image = current_client.text_to_image(
            request.prompt,
            model="black-forest-labs/FLUX.1-schnell",
            width=request.width,
            height=request.height
        )
        # Convert PIL Image to bytes
        import io
        img_byte_array = io.BytesIO()
        image.save(img_byte_array, format='PNG')
        img_byte_array = img_byte_array.getvalue()

        # Handle different return formats
        is_curl = "curl" in http_request.headers.get("user-agent", "").lower()
        if request.return_format == "raw" or (is_curl and request.return_format != "base64"):
            return Response(
                content=img_byte_array,
                media_type="image/png",
                headers={"Content-Disposition": "attachment; filename=generated-image.png"}
            )
        return {"image_base64": base64.b64encode(img_byte_array).decode("utf-8")}
    except Exception as e:
        import traceback
        error_details = {
            "error": str(e),
            "traceback": traceback.format_exc(),
            "prompt": request.prompt,
            "dimensions": f"{request.width}x{request.height}"
        }
        print(f"Image generation error: {error_details}")  # This will show in the Azure logs
        raise HTTPException(status_code=500, detail=error_details)