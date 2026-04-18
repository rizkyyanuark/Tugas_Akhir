"""
MinerU documentparser

 MinerU servicerowdocumentcontentextract
"""

import os
import tempfile
import time
from pathlib import Path

import requests

from yunesa.plugins.parser.base import BaseDocumentProcessor, DocumentParserException
from yunesa.plugins.parser.zip_utils import process_zip_file_sync
from yunesa.utils import logger


class MinerUParser(BaseDocumentProcessor):
    """MinerU documentparser -  HTTP API rowdocumentparse"""

    def __init__(self, server_url: str | None = None):
        self.server_url = server_url or os.getenv("MINERU_API_URI") or "http://localhost:30001"
        self.parse_endpoint = f"{self.server_url}/file_parse"

    def get_service_name(self) -> str:
        return "mineru_ocr"

    def get_supported_extensions(self) -> list[str]:
        """MinerU  PDF format"""
        return [".pdf", ".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"]

    def check_health(self) -> dict:
        """check MinerU servicestatus"""
        try:
            #  OpenAPI JSON checkservicewhether
            health_url = f"{self.server_url}/openapi.json"
            response = requests.get(health_url, timeout=5)

            if response.status_code == 200:
                try:
                    openapi_data = response.json()
                    # checkwhether file_parse 
                    has_file_parse = "/file_parse" in openapi_data.get("paths", {})

                    if has_file_parse:
                        return {
                            "status": "healthy",
                            "message": "MinerU servicerow",
                            "details": {
                                "server_url": self.server_url,
                                "api_version": openapi_data.get("info", {}).get("version", "unknown"),
                            },
                        }
                    else:
                        return {
                            "status": "unhealthy",
                            "message": "MinerU service",
                            "details": {"server_url": self.server_url},
                        }
                except Exception as e:
                    return {
                        "status": "unhealthy",
                        "message": f"MinerU responseformaterror: {str(e)}",
                        "details": {"server_url": self.server_url},
                    }
            else:
                return {
                    "status": "unhealthy",
                    "message": f"MinerU serviceresponseexception: {response.status_code}",
                    "details": {"server_url": self.server_url},
                }

        except requests.exceptions.ConnectionError:
            return {
                "status": "unavailable",
                "message": "MinerU serviceunable to connect,checkservicewhetherstart",
                "details": {"server_url": self.server_url},
            }
        except requests.exceptions.Timeout:
            return {
                "status": "timeout",
                "message": "MinerU serviceconnecttimeout",
                "details": {"server_url": self.server_url},
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"MinerU checkfailed: {str(e)}",
                "details": {"server_url": self.server_url, "error": str(e)},
            }

    def process_file(self, file_path: str, params: dict | None = None) -> str:
        """
         MinerU processdocument

        Args:
            file_path: filepath
            params: processparameter
                - lang_list: list (default: ["ch"])
                - backend: type (default: "pipeline",  "vlm-*" column)
                - parse_method: parse (default: "auto")
                - start_page_id: page number (default: 0)
                - end_page_id: endpage number (default: 99999)
                - formula_enable: enabledparse (default: True)
                - table_enable: enabledtableparse (default: True)
                - server_url: VLM server (vlm-http-client )

        Returns:
            str: extract Markdown 
        """
        if not os.path.exists(file_path):
            raise DocumentParserException(f"filedoes not exist: {file_path}", self.get_service_name(), "file_not_found")

        file_ext = Path(file_path).suffix.lower()
        if not self.supports_file_type(file_ext):
            raise DocumentParserException(
                f"not supportedfiletype: {file_ext}", self.get_service_name(), "unsupported_file_type"
            )

        # parseparameter
        params = params or {}

        # buildrequestdata - parameter
        data = {
            "lang_list": params.get("lang_list", ["ch"]),
            "backend": params.get("backend", "vlm-http-client"),
            "parse_method": params.get("parse_method", "auto"),
            # return markdown format
            "return_md": True,
            # addparse
            "response_format_zip": True,
            "return_images": True,
        }

        # vlm-http-client  server_url
        if data["backend"] == "vlm-http-client":
            mineru_vl_server = os.environ.get("MINERU_VL_SERVER")
            assert mineru_vl_server, "MINERU_VL_SERVER environmentconfigure"
            data["server_url"] = mineru_vl_server

        try:
            start_time = time.time()

            logger.info(
                f"MinerU startprocess: {os.path.basename(file_path)} (backend={data['backend']}, lang={data['lang_list']})"
            )

            # filesendrequest
            with open(file_path, "rb") as f:
                files = {"files": (os.path.basename(file_path), f, "application/octet-stream")}

                # send POST request
                response = requests.post(
                    self.parse_endpoint,
                    files=files,
                    data=data,
                    timeout=os.environ.get("MINERU_TIMEOUT", 1800),  # 30timeout
                )

            # checkresponsestatus
            logger.debug(
                f"MinerU responsestatus: {response.status_code}, Content-Type: {response.headers.get('content-type')}"
            )

            if response.status_code != 200:
                error_detail = "error"
                try:
                    error_data = response.json()
                    error_detail = error_data.get("detail", str(error_data))
                except Exception:
                    error_detail = response.text or f"HTTP {response.status_code}"

                logger.error(f"MinerU HTTPerror {response.status_code}: {error_detail}")
                raise DocumentParserException(
                    f"MinerU processfailed: {error_detail}",
                    self.get_service_name(),
                    f"http_{response.status_code}",
                )

            # parseresponse
            try:
                # responsecontentget ZIP data
                zip_data = response.content

                # savefileprocess
                with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp_zip:
                    tmp_zip.write(zip_data)
                    tmp_zip.flush()

                    try:
                        image_bucket = params.get("image_bucket") or "public"
                        image_prefix = params.get("image_prefix") or "unknown/kb-images"

                        processed = process_zip_file_sync(
                            tmp_zip.name,
                            image_bucket=image_bucket,
                            image_prefix=image_prefix,
                        )
                        text = processed["markdown_content"]
                    finally:
                        os.unlink(tmp_zip.name)

                if not text:
                    logger.error("MinerU returncontent")
                    raise DocumentParserException(
                        "MinerU returncontent",
                        self.get_service_name(),
                        "no_content",
                    )

                processing_time = time.time() - start_time
                logger.info(
                    f"MinerU processsuccessful: {os.path.basename(file_path)} - {len(text)} character ({processing_time:.2f}s)"
                )

                return text

            except Exception as e:
                raise DocumentParserException(
                    f"MinerU responseparsefailed: {str(e)}",
                    self.get_service_name(),
                    "response_parse_error",
                )

        except DocumentParserException:
            raise
        except requests.exceptions.Timeout:
            error_msg = f"MinerU processtimeout ({time.time() - start_time:.2f}s), configure MINERU_TIMEOUT environment。"
            logger.error(error_msg)
            raise DocumentParserException(error_msg, self.get_service_name(), "timeout")
        except requests.exceptions.ConnectionError:
            error_msg = "MinerU connection failed,checkservicewhetherrow"
            logger.error(error_msg)
            raise DocumentParserException(error_msg, self.get_service_name(), "connection_error")
        except Exception as e:
            error_msg = f"MinerU processfailed: {str(e)}"
            logger.error(f"{error_msg} ({time.time() - start_time:.2f}s)")
            raise DocumentParserException(error_msg, self.get_service_name(), "processing_failed")
