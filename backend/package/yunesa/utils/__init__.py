import hashlib
import os
import time
import uuid

from yunesa.utils.logging_config import logger


def is_text_pdf(pdf_path):
    import fitz

    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    if total_pages == 0:
        return False

    text_pages = 0
    for page_num in range(total_pages):
        page = doc.load_page(page_num)
        text = page.get_text()
        if text.strip():  # check whether the page has text content
            text_pages += 1

    # Calculate the ratio of pages containing text.
    text_ratio = text_pages / total_pages
    # If more than 50% of pages contain text, treat it as a text PDF.
    return text_ratio > 0.5


def hashstr(input_string, length=None, with_salt=False, salt=None):
    """Generate a hash value for a string.

    Args:
        input_string: Input string.
        length: Truncation length. Default None means no truncation.
        with_salt: Whether to use salt. Default is False.
    """
    try:
        # Try direct encoding first.
        encoded_string = str(input_string).encode("utf-8")
    except UnicodeEncodeError:
        # If encoding fails, replace invalid characters.
        encoded_string = str(input_string).encode("utf-8", errors="replace")

    if with_salt:
        if not salt:
            # Use timestamp + random suffix as salt to ensure uniqueness.
            salt = f"{time.time()}_{uuid.uuid4().hex[:8]}"
        encoded_string = (encoded_string.decode(
            "utf-8") + salt).encode("utf-8")

    hash = hashlib.sha256(encoded_string).hexdigest()
    if length:
        return hash[:length]
    return hash


def get_docker_safe_url(base_url):
    if not base_url:
        return base_url

    if os.getenv("RUNNING_IN_DOCKER") == "true":
        # Replace all common local host address variants.
        base_url = base_url.replace(
            "http://localhost", "http://host.docker.internal")
        base_url = base_url.replace(
            "http://127.0.0.1", "http://host.docker.internal")
        logger.info(f"Running in docker, using {base_url} as base url")
    return base_url
