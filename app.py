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
import os
import base64
import io
import sys
import logging
from typing import Optional
from PIL import Image, ImageFile
ImageFile.LOAD_TRUNCATED_IMAGES = True

# Load environment variables from .env file
load_dotenv()

app = FastAPI()

# Mount the static directory
app.mount("/static", StaticFiles(directory="static"), name="static")

# Set the API endpoint environment variable for the new Inference Providers API
os.environ["HF_ENDPOINT"] = "https://router.huggingface.co"

# Initialize the client with the new endpoint
client = InferenceClient(
    token=os.environ.get("HF_TOKEN"),
    base_url="https://router.huggingface.co/hf-inference"
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
        logging.basicConfig(level=logging.INFO)
        logger = logging.getLogger(__name__)
        
        # Log the token being used (first 8 chars only for security)
        token_preview = (request.hf_token or os.environ.get("HF_TOKEN") or "")[:8] + "..."
        logger.info(f"Using HF token starting with: {token_preview}")
        
        # Create a new client instance if user provided a token
        current_client = InferenceClient(
            token=request.hf_token,
            base_url="https://router.huggingface.co/hf-inference"
        ) if request.hf_token else client
        
        logger.info(f"Starting image generation with prompt: {request.prompt}")
        logger.info(f"Image dimensions: {request.width}x{request.height}")
        
        try:
            logger.info("Calling Hugging Face API...")
            # Try with original dimensions first, with a shorter timeout
            try:
                # Use text_to_image method
                image = current_client.text_to_image(
                    prompt=request.prompt,
                    model="black-forest-labs/FLUX.1-schnell",
                    width=request.width,
                    height=request.height,
                )
                logger.info("Image generation successful at original dimensions")
            except Exception as dim_error:
                if "memory" in str(dim_error).lower():
                    # Try with reduced dimensions
                    logger.info("Retrying with reduced dimensions due to memory constraints")
                    scale_factor = 0.5  # Reduce dimensions by 50%
                    reduced_width = int(request.width * scale_factor)
                    reduced_height = int(request.height * scale_factor)
                    
                    image = current_client.text_to_image(
                        prompt=request.prompt,
                        model="black-forest-labs/FLUX.1-schnell",
                        width=reduced_width,
                        height=reduced_height,
                    )
                    
                    # Upscale the image back to requested dimensions
                    image = image.resize((request.width, request.height), Image.Resampling.LANCZOS)
                    logger.info("Image generation successful with reduced dimensions and upscaling")
                else:
                    raise
        except Exception as gen_error:
            print(f"Image generation error: {str(gen_error)}")
            error_message = str(gen_error)
            if "token" in error_message.lower():
                raise HTTPException(
                    status_code=401,
                    detail="Authentication failed with Hugging Face API. Please check your token."
                )
            elif "timeout" in error_message.lower():
                raise HTTPException(
                    status_code=504,
                    detail="The request timed out. Please try again with a simpler prompt or smaller image dimensions."
                )
            elif "memory" in error_message.lower():
                raise HTTPException(
                    status_code=503,
                    detail="The server ran out of memory. Please try with smaller image dimensions."
                )
            else:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to generate image: {error_message}"
                )
        # Convert PIL Image to bytes
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