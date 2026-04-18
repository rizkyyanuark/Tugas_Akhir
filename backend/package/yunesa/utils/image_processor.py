"""
Image processing utility module.
Supports image format conversion, compression, thumbnail generation, and related features.
"""

import base64
import io

from PIL import ExifTags, Image

from yunesa.utils import logger


class ImageProcessor:
    """Image processing class."""

    # Supported image formats.
    SUPPORTED_FORMATS = {"JPEG", "PNG", "WebP", "GIF", "BMP"}

    # Maximum file size (5MB).
    MAX_FILE_SIZE = 5 * 1024 * 1024

    # Thumbnail dimensions.
    THUMBNAIL_SIZE = (200, 200)

    def process_image(self, image_data: bytes, original_filename: str = "") -> dict:
        """
        Process an uploaded image.

        Args:
            image_data: Binary image data.
            original_filename: Original filename.

        Returns:
            dict: A dictionary containing processing results.
        """
        try:
            # Validate image format.
            img_format, _ = self._validate_image_format(image_data)
            if img_format not in self.SUPPORTED_FORMATS:
                raise ValueError(f"Unsupported image format: {img_format}")

            # Load image.
            with Image.open(io.BytesIO(image_data)) as img:
                # Handle EXIF orientation.
                img = self._fix_image_orientation(img)

                # Generate thumbnail.
                thumbnail_data = self._generate_thumbnail(img)

                # Compress main image (if needed).
                processed_data, final_format = self._compress_image(
                    img, img_format)

                # Convert to base64.
                base64_data = base64.b64encode(processed_data).decode("utf-8")
                base64_thumbnail = base64.b64encode(
                    thumbnail_data).decode("utf-8")

                # Get image metadata.
                width, height = img.size
                mime_type = f"image/{final_format.lower()}"

                return {
                    "success": True,
                    "image_content": base64_data,
                    "thumbnail_content": base64_thumbnail,
                    "width": width,
                    "height": height,
                    "format": final_format,
                    "mime_type": mime_type,
                    "size_bytes": len(processed_data),
                    "original_filename": original_filename,
                }

        except Exception as e:
            logger.error(f"Image processing failed: {str(e)}")
            return {"success": False, "error": str(e)}

    def _validate_image_format(self, image_data: bytes) -> tuple[str, str]:
        """Validate image format and return format metadata."""
        try:
            with Image.open(io.BytesIO(image_data)) as img:
                return img.format, img.mode
        except Exception as e:
            raise ValueError(f"Invalid image format: {str(e)}")

    def _fix_image_orientation(self, img: Image.Image) -> Image.Image:
        """Fix image orientation based on EXIF metadata."""
        try:
            if hasattr(img, "_getexif"):
                exif = img._getexif()
                if exif is not None:
                    for tag, value in exif.items():
                        if tag in ExifTags.TAGS and ExifTags.TAGS[tag] == "Orientation":
                            if value == 3:
                                img = img.rotate(180, expand=True)
                            elif value == 6:
                                img = img.rotate(270, expand=True)
                            elif value == 8:
                                img = img.rotate(90, expand=True)
                            break
        except Exception as e:
            logger.warning(
                f"Failed to fix image orientation, using original orientation: {str(e)}")

        return img

    def _generate_thumbnail(self, img: Image.Image) -> bytes:
        """Generate a thumbnail image."""
        try:
            # Create a copy to avoid modifying the source image.
            thumbnail = img.copy()

            # Convert to RGB mode (for RGBA and other modes).
            if thumbnail.mode != "RGB":
                thumbnail = thumbnail.convert("RGB")

            # Generate thumbnail while preserving aspect ratio.
            thumbnail.thumbnail(self.THUMBNAIL_SIZE, Image.Resampling.LANCZOS)

            # Save as JPEG format.
            with io.BytesIO() as output:
                thumbnail.save(output, format="JPEG",
                               quality=85, optimize=True)
                return output.getvalue()

        except Exception as e:
            logger.error(f"Failed to generate thumbnail: {str(e)}")
            # If thumbnail generation fails, return a 1x1 white placeholder image.
            with io.BytesIO() as output:
                empty_img = Image.new("RGB", (1, 1), color="white")
                empty_img.save(output, format="JPEG", quality=85)
                return output.getvalue()

    def _compress_image(self, img: Image.Image, original_format: str) -> tuple[bytes, str]:
        """
        Compress image if it exceeds the size limit.

        Args:
            img: PIL Image object.
            original_format: Original format.

        Returns:
            Tuple[bytes, str]: (compressed image data, final format)
        """
        # Create a copy.
        processed_img = img.copy()

        # Convert to RGB mode if needed.
        if processed_img.mode in ("RGBA", "LA", "P"):
            processed_img = processed_img.convert("RGB")

        # Try to keep original format, but prefer JPEG for better compression.
        target_format = "JPEG" if original_format != "PNG" else "PNG"

        # Set initial quality.
        quality = 85

        with io.BytesIO() as output:
            # First save to check size.
            processed_img.save(output, format=target_format,
                               quality=quality, optimize=True)
            compressed_data = output.getvalue()

            # Return immediately if file size is acceptable.
            if len(compressed_data) <= self.MAX_FILE_SIZE:
                return compressed_data, target_format

            # If file is too large, reduce quality progressively.
            while len(compressed_data) > self.MAX_FILE_SIZE and quality > 10:
                quality -= 10
                output.seek(0)
                output.truncate(0)
                processed_img.save(output, format=target_format,
                                   quality=quality, optimize=True)
                compressed_data = output.getvalue()

            # If still too large at low quality, progressively resize dimensions.
            if len(compressed_data) > self.MAX_FILE_SIZE:
                # Reduce image dimensions step by step.
                scale_factor = 0.9
                while len(compressed_data) > self.MAX_FILE_SIZE and scale_factor > 0.3:
                    new_width = int(processed_img.width * scale_factor)
                    new_height = int(processed_img.height * scale_factor)
                    resized_img = processed_img.resize(
                        (new_width, new_height), Image.Resampling.LANCZOS)

                    output.seek(0)
                    output.truncate(0)
                    resized_img.save(output, format=target_format,
                                     quality=85, optimize=True)
                    compressed_data = output.getvalue()

                    scale_factor -= 0.1

            return compressed_data, target_format


# Global instance.
image_processor = ImageProcessor()


def process_uploaded_image(image_data: bytes, filename: str = "") -> dict:
    """
    Process an uploaded image (convenience function).

    Args:
        image_data: Binary image data.
        filename: Filename.

    Returns:
        dict: Processing result.
    """
    return image_processor.process_image(image_data, filename)
