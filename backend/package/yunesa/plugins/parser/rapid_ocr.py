"""
RapidOCR parser - pure OCR text recognition.

Uses RapidOCR (PP-OCRv4) for text recognition.
"""

import os
import tempfile
import time
from pathlib import Path

import fitz
import numpy as np
from PIL import Image
from rapidocr_onnxruntime import RapidOCR

from yunesa.plugins.parser.base import BaseDocumentProcessor, OCRException
from yunesa.utils import logger


class RapidOCRParser(BaseDocumentProcessor):
    """RapidOCR parser using ONNX models for text recognition."""

    def __init__(self, det_box_thresh: float = 0.3):
        self.ocr = None
        self.det_box_thresh = det_box_thresh
        self.model_dir_root = (
            os.getenv("MODEL_DIR") if not os.getenv(
                "RUNNING_IN_DOCKER") else os.getenv("MODEL_DIR_IN_DOCKER")
        )

    def get_service_name(self) -> str:
        return "rapid_ocr"

    def get_supported_extensions(self) -> list[str]:
        return [".pdf", ".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"]

    def _get_model_paths(self) -> tuple[str, str]:
        """Get model file paths."""
        model_dir = os.path.join(self.model_dir_root, "SWHL/RapidOCR")
        det_model_path = os.path.join(
            model_dir, "PP-OCRv4/ch_PP-OCRv4_det_infer.onnx")
        rec_model_path = os.path.join(
            model_dir, "PP-OCRv4/ch_PP-OCRv4_rec_infer.onnx")
        return det_model_path, rec_model_path

    def check_health(self) -> dict:
        """Check whether RapidOCR models are available."""
        try:
            det_model_path, rec_model_path = self._get_model_paths()
            model_dir = os.path.dirname(os.path.dirname(det_model_path))

            if not os.path.exists(model_dir):
                return {
                    "status": "unavailable",
                    "message": f"modeldirectorydoes not exist: {model_dir}",
                    "details": {"model_dir": model_dir},
                }

            if not os.path.exists(det_model_path) or not os.path.exists(rec_model_path):
                return {
                    "status": "unavailable",
                    "message": "Model files are missing",
                    "details": {"det_model": det_model_path, "rec_model": rec_model_path},
                }

            # Try loading model
            try:
                test_ocr = RapidOCR(
                    det_box_thresh=self.det_box_thresh, det_model_path=det_model_path, rec_model_path=rec_model_path
                )
                del test_ocr  # Release resources
                return {
                    "status": "healthy",
                    "message": "RapidOCR model is available",
                    "details": {"model_path": self._get_model_paths()},
                }
            except Exception as e:
                return {"status": "error", "message": f"modelloadfailed: {str(e)}", "details": {"error": str(e)}}

        except Exception as e:
            return {"status": "error", "message": f"Health check failed: {str(e)}", "details": {"error": str(e)}}

    def _load_model(self):
        """Lazily load OCR model."""
        if self.ocr is not None:
            return

        logger.info("load RapidOCR model...")

        # Check health status first
        health = self.check_health()
        if health["status"] != "healthy":
            raise OCRException(
                health["message"], self.get_service_name(), health["status"])

        try:
            det_model_path, rec_model_path = self._get_model_paths()
            self.ocr = RapidOCR(
                det_box_thresh=self.det_box_thresh, det_model_path=det_model_path, rec_model_path=rec_model_path
            )
            logger.info(
                f"RapidOCR modelloadsuccessful (det_box_thresh={self.det_box_thresh})")
        except Exception as e:
            raise OCRException(
                f"RapidOCRmodelloadfailed: {str(e)}", self.get_service_name(), "load_failed")

    def process_image(self, image, params: dict | None = None) -> str:
        """
        Process a single image and extract text.

        Args:
            image: Image data. Supports:
                  - str: image file path
                  - PIL.Image: PIL image object
                  - numpy.ndarray: numpy image array
            params: Processing parameters (currently unused)

        Returns:
            str: Extracted text content
        """
        self._load_model()

        try:
            # Process different input types
            if isinstance(image, str):
                image_path = image
                cleanup_needed = False
            else:
                # Create temporary file
                image_path = self._create_temp_image_file(image)
                cleanup_needed = True

            try:
                # execute OCR
                start_time = time.time()
                result, _ = self.ocr(image_path)
                processing_time = time.time() - start_time

                # Extract text
                if result:
                    text = "\n".join([line[1] for line in result])
                    logger.info(
                        f"RapidOCR successful: {os.path.basename(image_path) if isinstance(image, str) else 'temp_image'}"
                        f" ({processing_time:.2f}s)"
                    )
                    return text
                else:
                    logger.warning(
                        f"RapidOCR did not detect any text: {image_path}")
                    return ""

            finally:
                # Clean up temporary file
                if cleanup_needed and os.path.exists(image_path):
                    try:
                        os.remove(image_path)
                    except Exception as e:
                        logger.warning(
                            f"Failed to clean up temporary file: {image_path} - {e}")

        except Exception as e:
            error_msg = f"Image OCR processing failed: {str(e)}"
            logger.error(error_msg)
            raise OCRException(
                error_msg, self.get_service_name(), "processing_failed")

    def _create_temp_image_file(self, image) -> str:
        """Save image data to a temporary file."""
        try:
            # Use system temporary directory
            with tempfile.NamedTemporaryFile(mode="wb", suffix=".png", delete=False) as tmp_file:
                temp_path = tmp_file.name

                if isinstance(image, Image.Image):
                    image.save(temp_path)
                elif isinstance(image, np.ndarray):
                    Image.fromarray(image).save(temp_path)
                else:
                    raise ValueError(
                        "Unsupported image type, must be PIL.Image or numpy.ndarray")

                return temp_path

        except Exception as e:
            raise OCRException(
                f"Failed to create temporary image file: {str(e)}", self.get_service_name(), "temp_file_error")

    def process_pdf(self, pdf_path: str, params: dict | None = None) -> str:
        """
        Process PDF file and extract text (streaming mode to avoid high memory usage).

        Args:
            pdf_path: PDF file path
            params: Processing parameters
                - zoom_x: Horizontal zoom (default 2)
                - zoom_y: Vertical zoom (default 2)

        Returns:
            str: Extracted text
        """
        if not os.path.exists(pdf_path):
            raise OCRException(
                f"PDF filedoes not exist: {pdf_path}", self.get_service_name(), "file_not_found")

        params = params or {}
        zoom_x = params.get("zoom_x", 2)
        zoom_y = params.get("zoom_y", 2)

        try:
            all_text = []
            pdf_doc = fitz.open(pdf_path)
            total_pages = pdf_doc.page_count

            logger.info(
                f"Start processing PDF: {os.path.basename(pdf_path)} ({total_pages} pages)")

            # Process each page in streaming mode to avoid loading all images into memory at once.
            for page_num in range(total_pages):
                page = pdf_doc[page_num]

                # Convert to image
                mat = fitz.Matrix(zoom_x, zoom_y)
                pix = page.get_pixmap(matrix=mat, alpha=False)
                img_pil = Image.frombytes(
                    "RGB", [pix.width, pix.height], pix.samples)

                # Process immediately instead of buffering images.
                text = self.process_image(img_pil)
                all_text.append(text)

                if (page_num + 1) % 10 == 0:
                    logger.info(
                        f"Processed {page_num + 1}/{total_pages} pages")

            pdf_doc.close()

            result_text = "\n\n".join(all_text)
            logger.info(
                f"PDF OCR completed: {os.path.basename(pdf_path)} - {len(result_text)} character")
            return result_text

        except OCRException:
            raise
        except Exception as e:
            error_msg = f"PDF OCR processfailed: {str(e)}"
            logger.error(error_msg)
            raise OCRException(
                error_msg, self.get_service_name(), "pdf_processing_failed")

    def process_file(self, file_path: str, params: dict | None = None) -> str:
        """
        Process file (PDF or image).

        Args:
            file_path: File path
            params: Processing parameters

        Returns:
            str: Extracted text
        """
        file_ext = Path(file_path).suffix.lower()

        if not self.supports_file_type(file_ext):
            raise OCRException(f"Unsupported file type: {file_ext}", self.get_service_name(
            ), "unsupported_file_type")

        if file_ext == ".pdf":
            return self.process_pdf(file_path, params)
        else:
            return self.process_image(file_path, params)
