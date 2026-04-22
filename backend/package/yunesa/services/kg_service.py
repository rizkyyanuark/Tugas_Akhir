import threading
import asyncio
import os
from enum import Enum
from typing import Dict, Any, Optional
from datetime import datetime

from yunesa.knowledge.kg.services.kg_pipeline import KGPipeline
from yunesa.knowledge.kg.config import LLM_BATCH_SIZE
from yunesa.models.chat import split_model_spec
from yunesa.utils.logging_config import logger
from yunesa.config.app import Config


class BuildStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


class KGConstructionService:
    """Managed service for Knowledge Graph construction tracking."""

    def __init__(self, config: Config):
        self.config = config
        self._status = BuildStatus.IDLE
        self._progress = 0
        self._last_message = "Ready"
        self._start_time: Optional[datetime] = None
        self._end_time: Optional[datetime] = None
        self._last_result: Dict[str, Any] = {}
        self._error: Optional[str] = None
        self._lock = threading.Lock()
        self._stop_requested = False
        self._listeners = []
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = None

    def get_status(self) -> Dict[str, Any]:
        """Get the current construction status (matches graph_router expectation)."""
        with self._lock:
            return {
                "status": self._status.value,
                "progress": self._progress,
                "message": self._last_message,
                "start_time": self._start_time.isoformat() if self._start_time else None,
                "end_time": self._end_time.isoformat() if self._end_time else None,
                "last_result": self._last_result,
                "error": self._error,
                "duration": self._get_duration()
            }

    def _get_duration(self) -> float:
        if not self._start_time:
            return 0.0
        end = self._end_time or datetime.now()
        return (end - self._start_time).total_seconds()

    async def start_build(
        self,
        test_mode: bool = False,
        max_papers: Optional[int] = None,
        clear_db: bool = False,
        llm_model_spec: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Start the Knowledge Graph construction in a background thread."""
        selected_llm_spec = (
            llm_model_spec or self.config.default_model or "").strip()
        if not selected_llm_spec:
            return {"error": "No LLM model configured. Please set a default model first."}

        try:
            resolved_llm_config = self._resolve_llm_runtime_config(
                selected_llm_spec)
        except ValueError as exc:
            return {"error": str(exc)}

        with self._lock:
            if self._status == BuildStatus.RUNNING:
                return {"error": "Build already in progress."}

            self._reset_state()
            self._status = BuildStatus.RUNNING
            self._start_time = datetime.now()
            self._last_message = f"Initializing pipeline with {selected_llm_spec}..."

        # Using a thread for CPU/IO heavy pipeline execution
        self._current_thread = threading.Thread(
            target=self._run_pipeline,
            args=(test_mode, max_papers, clear_db,
                  resolved_llm_config, selected_llm_spec),
            daemon=True
        )
        self._current_thread.start()

        return {
            "message": "Knowledge Graph construction started in background.",
            "test_mode": test_mode,
            "llm_model_spec": selected_llm_spec,
            "start_time": self._start_time.isoformat()
        }

    async def stop_build(self) -> Dict[str, Any]:
        """Request the current build to stop."""
        with self._lock:
            if self._status == BuildStatus.RUNNING:
                self._stop_requested = True
                self._last_message = "Stop requested..."
                return {"message": "Stop request sent to pipeline."}
            return {"message": "No active build to stop."}

    def _reset_state(self):
        self._progress = 0
        self._last_message = "Ready"
        self._error = None
        self._end_time = None
        self._stop_requested = False

    def _resolve_llm_runtime_config(self, llm_model_spec: str) -> Dict[str, str]:
        provider, model_name = split_model_spec(llm_model_spec)
        if not provider or not model_name:
            raise ValueError(
                f"Invalid llm_model_spec '{llm_model_spec}'. Use provider/model format."
            )

        model_info = self.config.model_names.get(provider)
        if model_info is None:
            raise ValueError(f"Unknown model provider: {provider}")

        raw_env = model_info.env or ""
        no_key_sentinels = {"NO_API_KEY", "no_api_key"}
        if raw_env not in no_key_sentinels and not model_info.custom and not os.environ.get(raw_env):
            raise ValueError(
                f"Provider '{provider}' is not configured. Missing environment variable: {raw_env}"
            )

        api_key = os.environ.get(raw_env, raw_env) if raw_env else ""

        return {
            "provider": provider,
            "model": model_name,
            "base_url": model_info.base_url,
            "api_key": api_key,
        }

    def _on_progress(self, data: dict):
        with self._lock:
            self._progress = data.get("percentage", self._progress)
            self._last_message = data.get("message", data.get("step", ""))
            logger.info(
                f"[KG Build Progress] {self._progress}%: {self._last_message}")

        if self._loop:
            for q in self._listeners:
                self._loop.call_soon_threadsafe(q.put_nowait, data)

    def _run_pipeline(
        self,
        test_mode: bool,
        max_papers: Optional[int],
        clear_db: bool,
        llm_config: Dict[str, str],
        llm_model_spec: str,
    ):
        try:
            # Backward-compatible config lookup:
            # - New flow: KG settings are environment-based inside yunesa.knowledge.kg.config
            # - Legacy flow: self.config.kg.max_papers / self.config.kg.llm.batch_size
            legacy_kg = getattr(self.config, "kg", None)
            legacy_max_papers = getattr(
                legacy_kg, "max_papers", None) if legacy_kg is not None else None
            legacy_llm = getattr(
                legacy_kg, "llm", None) if legacy_kg is not None else None
            legacy_batch_size = (
                getattr(legacy_llm, "batch_size",
                        None) if legacy_llm is not None else None
            )

            effective_max_papers = max_papers if max_papers is not None else legacy_max_papers
            effective_batch_size = legacy_batch_size or LLM_BATCH_SIZE

            # Create pipeline using service config
            pipeline = KGPipeline(
                test_mode=test_mode,
                max_papers=effective_max_papers,
                clear_db=clear_db,
                batch_size=effective_batch_size,
                llm_config=llm_config,
            )
            pipeline.progress_callback = self._on_progress

            # Run it
            result = pipeline.run()

            with self._lock:
                self._status = BuildStatus.COMPLETED
                self._last_result = {
                    **result,
                    "llm_model_spec": llm_model_spec,
                }
                self._progress = 100
                self._last_message = "Construction completed successfully."
                self._end_time = datetime.now()

            # Send final completion event if it hasn't been sent
            self._on_progress({"step": "Pipeline", "status": "completed",
                              "percentage": 100, "message": "Construction completed successfully."})

        except Exception as e:
            logger.error(f"KG Construction failed: {str(e)}", exc_info=True)
            with self._lock:
                self._status = BuildStatus.FAILED
                self._error = str(e)
                self._last_message = f"Error: {str(e)}"
                self._end_time = datetime.now()

            self._on_progress(
                {"step": "Pipeline", "status": "failed", "percentage": 100, "message": str(e)})


_kg_service_instance: Optional[KGConstructionService] = None


def get_kg_service(config: Config) -> KGConstructionService:
    """Get or create the singleton KGConstructionService instance."""
    global _kg_service_instance
    if _kg_service_instance is None:
        _kg_service_instance = KGConstructionService(config)
    return _kg_service_instance
