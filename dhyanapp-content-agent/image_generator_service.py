"""
Image Generator Service for Auto Quote Poster.

This service handles:
- Generating beautiful background images using DALL-E 3
- Overlaying quote text on the image using Pillow
- Uploading images to Firebase Storage
- Returning public URLs for the images
"""

import os
import io
import uuid
import textwrap
import requests
from datetime import datetime
from typing import Optional

from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
import firebase_admin
from firebase_admin import credentials, storage
from dotenv import load_dotenv

from llm_usage_tracker import record_openai_image

load_dotenv()

# Configuration
FIREBASE_CREDENTIALS_PATH = os.getenv(
    "FIREBASE_CREDENTIALS_PATH",
    os.path.join(os.path.dirname(__file__), "firebase_credentials.json")
)
FIREBASE_STORAGE_BUCKET = "dhyanapp-90de4.appspot.com"
DHYANI_USER_ID = "7es9AYnaW7afNtMeOBtXl8Z2ILF3"

# Font paths - try multiple common locations
FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "C:/Windows/Fonts/arial.ttf",
]

FONT_BOLD_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "C:/Windows/Fonts/arialbd.ttf",
]


def get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Get a font, trying multiple paths."""
    paths = FONT_BOLD_PATHS if bold else FONT_PATHS

    for path in paths:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue

    # Fallback to default
    return ImageFont.load_default()


class ImageGeneratorService:
    """Service for generating and uploading quote images."""

    def __init__(self):
        """Initialize the image generator service."""
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self._initialize_firebase_storage()

    def _initialize_firebase_storage(self):
        """Initialize Firebase Storage."""
        try:
            # Check if Firebase is already initialized
            if not firebase_admin._apps:
                if os.path.exists(FIREBASE_CREDENTIALS_PATH):
                    cred = credentials.Certificate(FIREBASE_CREDENTIALS_PATH)
                    firebase_admin.initialize_app(cred, {
                        'storageBucket': FIREBASE_STORAGE_BUCKET
                    })
                else:
                    print(f"[WARNING] Firebase credentials not found")
                    return

            self.bucket = storage.bucket(FIREBASE_STORAGE_BUCKET)
            print("[SUCCESS] Firebase Storage initialized")

        except Exception as e:
            print(f"[ERROR] Failed to initialize Firebase Storage: {e}")
            self.bucket = None

    def generate_background_image(self, theme: str) -> Optional[bytes]:
        """
        Generate a beautiful background image using DALL-E 3.

        Args:
            theme: The theme/saying for context

        Returns:
            Image bytes or None if failed
        """
        # Create a prompt for DALL-E that generates a beautiful background WITHOUT text
        prompt = f"""Create a beautiful, serene square meditation/spiritual background image.

Style requirements:
- Soft, calming colors (gentle purples, blues, warm golds, peaceful greens, or soft pinks)
- Minimalist, zen-like aesthetic
- NO TEXT whatsoever - just a pure visual background
- Peaceful background options: soft gradients, gentle nature elements (lotus, water, mountains, sky), abstract peaceful patterns, subtle mandala elements, bokeh lights, soft clouds
- No human faces or figures
- Slightly darker or muted tones to allow white text overlay
- High quality, professional design suitable for a meditation app
- The overall mood should evoke peace, mindfulness, and inner calm

Theme inspiration: {theme}

IMPORTANT: Do NOT include any text, letters, words, or typography in the image. This is purely a background image."""

        try:
            print(f"[INFO] Generating background image with DALL-E 3...")

            response = self.client.images.generate(
                model="dall-e-3",
                prompt=prompt,
                size="1024x1024",  # Square format
                quality="standard",
                n=1,
            )
            record_openai_image(model="dall-e-3", service="image_generator.background", n=1)

            image_url = response.data[0].url
            print(f"[SUCCESS] Background image generated")

            # Download the image
            img_response = requests.get(image_url, timeout=30)
            img_response.raise_for_status()

            return img_response.content

        except Exception as e:
            print(f"[ERROR] Failed to generate background image: {e}")
            return None

    def add_text_to_image(self, image_bytes: bytes, quote: str, saying: str) -> bytes:
        """
        Add quote text overlay to the background image.

        Args:
            image_bytes: The background image bytes
            quote: The quote text to add
            saying: The theme/saying to add at bottom

        Returns:
            Final image bytes with text overlay
        """
        # Open the image
        img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
        width, height = img.size

        # Create a slightly darker overlay for better text readability
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)

        # Add a subtle dark gradient overlay
        for i in range(height):
            alpha = int(80 + (i / height) * 40)  # Gradual darkening
            overlay_draw.line([(0, i), (width, i)], fill=(0, 0, 0, alpha))

        img = Image.alpha_composite(img, overlay)

        # Create drawing context
        draw = ImageDraw.Draw(img)

        # Calculate text area (with padding)
        padding = 80
        text_area_width = width - (padding * 2)

        # Wrap the quote text
        quote_font_size = 42
        quote_font = get_font(quote_font_size, bold=True)

        # Calculate characters per line based on font size
        avg_char_width = quote_font_size * 0.6
        chars_per_line = int(text_area_width / avg_char_width)

        wrapped_quote = textwrap.fill(quote, width=chars_per_line)

        # If text is too long, reduce font size
        lines = wrapped_quote.split('\n')
        while len(lines) > 8 and quote_font_size > 28:
            quote_font_size -= 2
            quote_font = get_font(quote_font_size, bold=True)
            avg_char_width = quote_font_size * 0.6
            chars_per_line = int(text_area_width / avg_char_width)
            wrapped_quote = textwrap.fill(quote, width=chars_per_line)
            lines = wrapped_quote.split('\n')

        # Calculate text position (centered)
        # Get text bounding box
        bbox = draw.textbbox((0, 0), wrapped_quote, font=quote_font)
        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]

        # Position quote in center
        x = (width - text_width) // 2
        y = (height - text_height) // 2 - 40  # Slightly above center

        # Draw text shadow for depth
        shadow_offset = 3
        draw.text((x + shadow_offset, y + shadow_offset), wrapped_quote,
                  font=quote_font, fill=(0, 0, 0, 150))

        # Draw main quote text (white)
        draw.text((x, y), wrapped_quote, font=quote_font, fill=(255, 255, 255, 255))

        # Add quotation marks
        quote_mark_font = get_font(72, bold=True)
        draw.text((padding - 20, y - 60), '"', font=quote_mark_font, fill=(255, 255, 255, 180))

        # Add the saying/theme at bottom
        saying_font = get_font(28, bold=False)
        saying_text = f"~ {saying} ~"
        saying_bbox = draw.textbbox((0, 0), saying_text, font=saying_font)
        saying_width = saying_bbox[2] - saying_bbox[0]
        saying_x = (width - saying_width) // 2
        saying_y = height - padding - 30

        draw.text((saying_x, saying_y), saying_text, font=saying_font, fill=(255, 255, 255, 200))

        # Add a subtle decorative line above the saying
        line_width = 100
        line_y = saying_y - 20
        line_x1 = (width - line_width) // 2
        line_x2 = line_x1 + line_width
        draw.line([(line_x1, line_y), (line_x2, line_y)], fill=(255, 255, 255, 150), width=2)

        # Convert to RGB for saving as JPEG/PNG
        final_img = img.convert("RGB")

        # Save to bytes
        output = io.BytesIO()
        final_img.save(output, format="PNG", quality=95)
        output.seek(0)

        return output.getvalue()

    def upload_to_firebase(self, image_bytes: bytes, post_id: str) -> Optional[str]:
        """
        Upload image bytes to Firebase Storage.

        Args:
            image_bytes: The image data to upload
            post_id: Post ID for naming the file

        Returns:
            Public URL of the uploaded image or None if failed
        """
        if not self.bucket:
            print("[ERROR] Firebase Storage not initialized")
            return None

        try:
            # Create blob path
            blob_path = f"Posts/images/{DHYANI_USER_ID}/{post_id}"
            blob = self.bucket.blob(blob_path)

            # Upload to Firebase Storage
            print(f"[INFO] Uploading to Firebase Storage...")
            blob.upload_from_string(
                image_bytes,
                content_type='image/png'
            )

            # Make the blob publicly accessible
            blob.make_public()

            # Create Firebase Storage URL with token
            blob.metadata = {'firebaseStorageDownloadTokens': post_id}
            blob.patch()

            firebase_url = f"https://firebasestorage.googleapis.com/v0/b/{FIREBASE_STORAGE_BUCKET}/o/{blob_path.replace('/', '%2F')}?alt=media&token={post_id}"

            print(f"[SUCCESS] Image uploaded to Firebase Storage")
            return firebase_url

        except Exception as e:
            print(f"[ERROR] Failed to upload to Firebase: {e}")
            return None

    def generate_and_upload(self, quote: str, saying: str, post_id: str) -> Optional[str]:
        """
        Generate a quote image with text overlay and upload it to Firebase Storage.

        Args:
            quote: The quote text
            saying: The theme/saying
            post_id: Post ID for the image

        Returns:
            Firebase Storage URL or None if failed
        """
        # Step 1: Generate background image with DALL-E
        background_bytes = self.generate_background_image(saying)

        if not background_bytes:
            print("[ERROR] Failed to generate background image")
            return None

        # Step 2: Add text overlay to the image
        print(f"[INFO] Adding text overlay to image...")
        final_image_bytes = self.add_text_to_image(background_bytes, quote, saying)
        print(f"[SUCCESS] Text overlay added")

        # Step 3: Upload to Firebase Storage
        firebase_url = self.upload_to_firebase(final_image_bytes, post_id)

        return firebase_url


# Singleton instance
_image_service = None


def get_image_generator_service() -> ImageGeneratorService:
    """Get the singleton instance of the image generator service."""
    global _image_service
    if _image_service is None:
        _image_service = ImageGeneratorService()
    return _image_service


if __name__ == "__main__":
    # Quick test
    service = get_image_generator_service()

    test_quote = "In the stillness of the mind, we discover the infinite peace that has always been within us. Each breath is a reminder of our connection to the universe."
    test_saying = "Inner Peace"
    test_post_id = str(uuid.uuid4())

    print(f"\nTest Quote: {test_quote}")
    print(f"Test Saying: {test_saying}")
    print(f"Test Post ID: {test_post_id}")

    url = service.generate_and_upload(test_quote, test_saying, test_post_id)

    if url:
        print(f"\n[SUCCESS] Final URL: {url}")
    else:
        print("\n[ERROR] Failed to generate and upload image")
