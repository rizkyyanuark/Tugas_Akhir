"""
PP-Structure-V3 documentparser

 PP-Structure-V3 rowdocumentparsecontentextract
"""

import base64
import os
import time
from pathlib import Path
from typing import Any

import requests

from yunesa.plugins.parser.base import BaseDocumentProcessor, DocumentParserException
from yunesa.utils import logger


class PPStructureV3Parser(BaseDocumentProcessor):
    """PP-Structure-V3 documentparser -  PP-Structure-V3 rowparse"""

    def __init__(self, server_url: str | None = None):
        self.server_url = server_url or os.getenv("PADDLEX_URI") or "http://localhost:8080"
        self.base_url = self.server_url.rstrip("/")
        self.endpoint = f"{self.base_url}/layout-parsing"

    def get_service_name(self) -> str:
        return "pp_structure_v3_ocr"

    def get_supported_extensions(self) -> list[str]:
        """PP-Structure-V3  PDF format"""
        return [".pdf", ".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"]

    def _encode_file_to_base64(self, file_path: str) -> str:
        """fileencodingBase64"""
        with open(file_path, "rb") as file:
            encoded = base64.b64encode(file.read()).decode("utf-8")
            return encoded

    def _process_file_input(self, file_input: str) -> str:
        """processfileinput：filepath、URLBase64content"""
        # checkwhetherfilepath
        if os.path.exists(file_input):
            logger.info(f"📁 file: {file_input}")
            logger.info(f"📏 filesize: {os.path.getsize(file_input) / 1024 / 1024:.2f} MB")
            return self._encode_file_to_base64(file_input)

        # checkwhetherURL
        elif file_input.startswith(("http://", "https://")):
            logger.info(f"🌐 URL: {file_input}")
            return file_input

        # Base64encodingcontent
        else:
            logger.info(f"📝 Base64encodingcontent，: {len(file_input)} character")
            return file_input

    def _call_layout_api(
        self,
        file_input: str,
        file_type: int | None = None,
        use_table_recognition: bool = True,
        use_formula_recognition: bool = True,
        use_seal_recognition: bool = False,
        **kwargs,
    ) -> dict[str, Any]:
        """PP-Structure-V3parseAPI"""
        # processfileinput
        processed_file_input = self._process_file_input(file_input)
        payload = {"file": processed_file_input}

        # addparameter
        optional_params = {
            "fileType": file_type,
            "useTableRecognition": use_table_recognition,
            "useFormulaRecognition": use_formula_recognition,
            "useSealRecognition": use_seal_recognition,
        }

        # addparameter
        for key, value in optional_params.items():
            if value is not None:
                payload[key] = value

        # addkwargsparameter
        for key, value in kwargs.items():
            if value is not None:
                payload[key] = value

        response = requests.post(self.endpoint, json=payload, headers={"Content-Type": "application/json"}, timeout=300)

        if response.status_code == 200:
            return response.json()
        else:
            error_msg = f"PP-Structure-V3 APIrequestfailed: {response.status_code}"
            try:
                error_result = response.json()
                raise DocumentParserException(f"{error_msg}: {error_result}", self.get_service_name(), "api_error")
            except Exception:
                raise DocumentParserException(f"{error_msg}: {response.text}", self.get_service_name(), "api_error")

    def _parse_api_result(self, api_result: dict[str, Any], file_path: str) -> dict[str, Any]:
        """parseAPIreturnresult"""
        # 
        parsed_result = {
            "success": True,
            "file_path": file_path,
            "file_name": os.path.basename(file_path),
            "log_id": api_result.get("logId"),
            "total_pages": 0,
            "pages": [],
            "full_text": "",
            "summary": {},
        }

        result_data = api_result.get("result", {})
        layout_results = result_data.get("layoutParsingResults", [])

        # data
        parsed_result["total_pages"] = len(layout_results)

        # statistics
        total_tables = 0
        total_formulas = 0
        all_text_content = []

        # parseresult
        for page_result in layout_results:
            # Markdowncontent
            if "markdown" in page_result:
                markdown = page_result["markdown"]
                if markdown.get("text"):
                    all_text_content.append(markdown["text"])

            # result
            if "prunedResult" in page_result:
                pruned = page_result["prunedResult"]

                # table
                table_result = pruned.get("table_result", [])
                total_tables += len(table_result)

                # 
                formula_result = pruned.get("formula_result", [])
                total_formulas += len(formula_result)

        # content
        parsed_result["full_text"] = "\n\n".join(all_text_content)

        # statistics
        parsed_result["summary"] = {
            "total_tables": total_tables,
            "total_formulas": total_formulas,
            "total_characters": len(parsed_result["full_text"]),
        }

        return parsed_result

    def check_health(self) -> dict:
        """check PP-Structure-V3 servicestatus"""
        try:
            response = requests.get(f"{self.base_url}/health", timeout=5)

            if response.status_code == 200:
                return {
                    "status": "healthy",
                    "message": "PP-Structure-V3 servicerow",
                    "details": {"server_url": self.server_url},
                }
            else:
                return {
                    "status": "unhealthy",
                    "message": f"PP-Structure-V3 serviceresponseexception: {response.status_code}",
                    "details": {"server_url": self.server_url},
                }

        except requests.exceptions.ConnectionError:
            return {
                "status": "unavailable",
                "message": "PP-Structure-V3 serviceunable to connect,checkservicewhetherstart",
                "details": {"server_url": self.server_url},
            }
        except requests.exceptions.Timeout:
            return {
                "status": "timeout",
                "message": "PP-Structure-V3 serviceconnecttimeout",
                "details": {"server_url": self.server_url},
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"PP-Structure-V3 checkfailed: {str(e)}",
                "details": {"server_url": self.server_url, "error": str(e)},
            }

    def process_file(self, file_path: str, params: dict | None = None) -> str:
        """
         PP-Structure-V3 processdocument

        Args:
            file_path: filepath
            params: processparameter
                - use_table_recognition: enabledtable (default: True)
                - use_formula_recognition: enabled (default: True)
                - use_seal_recognition: enabled (default: False)

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

        # checkservicestatus
        health = self.check_health()
        if health["status"] != "healthy":
            raise DocumentParserException(
                f"PP-Structure-V3 serviceunavailable: {health['message']}", self.get_service_name(), health["status"]
            )

        try:
            start_time = time.time()
            params = params or {}

            # filetype
            file_type = 0 if file_ext == ".pdf" else 1

            logger.info(f"PP-Structure-V3 startprocess: {os.path.basename(file_path)}")

            # API
            api_result = self._call_layout_api(
                file_input=file_path,
                file_type=file_type,
                use_table_recognition=params.get("use_table_recognition", True),
                use_formula_recognition=params.get("use_formula_recognition", True),
                use_seal_recognition=params.get("use_seal_recognition", False),
            )

            # checkAPIwhethersuccessful
            if api_result.get("errorCode") != 0:
                raise DocumentParserException(
                    f"PP-Structure-V3 APIerror: {api_result.get('errorMsg', 'error')}",
                    self.get_service_name(),
                    "api_error",
                )

            # parseresult
            result = self._parse_api_result(api_result, file_path)
            text = result.get("full_text", "")

            processing_time = time.time() - start_time
            logger.info(
                f"PP-Structure-V3 processsuccessful: {os.path.basename(file_path)} - {len(text)} character ({processing_time:.2f}s)"
            )

            # statistics
            summary = result.get("summary", {})
            if summary:
                logger.info(f"  statistics: {summary.get('total_tables', 0)} table, {summary.get('total_formulas', 0)} ")

            return text

        except DocumentParserException:
            raise
        except Exception as e:
            processing_time = time.time() - start_time
            error_msg = f"PP-Structure-V3 processfailed: {str(e)}"
            logger.error(f"{error_msg} ({processing_time:.2f}s)")
            raise DocumentParserException(error_msg, self.get_service_name(), "processing_failed")
