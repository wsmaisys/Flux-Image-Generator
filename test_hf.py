from huggingface_hub import InferenceClient
from dotenv import load_dotenv
import os
import logging

# Enable debug logging
logging.basicConfig(level=logging.DEBUG)

# Load environment variables
load_dotenv()

# Get token
token = os.getenv("HF_TOKEN")
if not token:
    print("Error: HF_TOKEN not found in environment variables")
    exit(1)

print(f"Token exists and starts with: {token[:6]}...")

# Create client
try:
    client = InferenceClient(token=token)
    print("Successfully created InferenceClient")
except Exception as e:
    print(f"Error creating client: {str(e)}")
    exit(1)

# Test model access
MODEL_ID = "black-forest-labs/FLUX.1-schnell"
try:
    # Try a small test generation
    print(f"\nTesting model access to {MODEL_ID}...")
    image = client.text_to_image(
        prompt="test image",
        model=MODEL_ID,
        width=256,
        height=256
    )
    print("Successfully generated test image!")
    
    # Save the test image
    image.save("test_output.png")
    print("Saved test image to test_output.png")
    
except Exception as e:
    print(f"Error accessing model: {str(e)}")
    exit(1)