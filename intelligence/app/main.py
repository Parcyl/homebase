"""FastAPI entrypoint. Single /intake endpoint plus /health."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from . import pipeline_state
from .graph import build_graph
from .models import (
    ErrorResponse,
    IntakeRequest,
    IntakeResponse,
)
from .settings import get_settings


def _configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)

    class JsonFormatter(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:
            payload: dict[str, Any] = {
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
            if record.exc_info:
                payload["exc"] = self.formatException(record.exc_info)
            return json.dumps(payload)

    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(get_settings().log_level)


_configure_logging()
log = logging.getLogger("homebase.langgraph")

app = FastAPI(title="Homebase LangGraph", version="0.1.0")
_graph = build_graph()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/intake", response_model=IntakeResponse)
def intake(req: IntakeRequest) -> IntakeResponse:
    settings = get_settings()
    recording = Path(req.recording_path)
    if not recording.exists():
        log.warning(
            "recording_path_missing",
            extra={"session_id": req.session_id, "path": req.recording_path},
        )

    initial_state: dict[str, Any] = {
        "session_id": req.session_id,
        "recording_path": req.recording_path,
        "transcript": req.transcript,
        "keyframe_paths": req.keyframe_paths,
        "context_cue": req.context_cue,
        "target_repo": req.target_repo,
    }

    try:
        final_state = _graph.invoke(initial_state)
    except Exception as exc:
        log.exception("graph_failed", extra={"session_id": req.session_id})
        pipeline_state.update("error", req.session_id, error=str(exc))
        raise HTTPException(
            status_code=502,
            detail={"error_code": "graph_failed", "message": str(exc)},
        ) from exc

    classification = final_state["classification"]
    comparison = final_state["comparison"]
    output_paths = final_state["output_paths"]

    response = IntakeResponse(
        session_id=req.session_id,
        classification=classification,
        library_path=comparison.target_library_path,
        outputs=output_paths,
        pattern_match=comparison,
        low_confidence=bool(final_state.get("low_confidence", False)),
    )
    log.info(
        "intake_complete",
        extra={
            "session_id": req.session_id,
            "deal_type": classification.deal_type,
            "match": comparison.match,
            "low_confidence": response.low_confidence,
        },
    )
    _ = settings  # silence unused
    return response


@app.exception_handler(ValueError)
async def value_error_handler(_request, exc: ValueError):
    return JSONResponse(
        status_code=400,
        content=ErrorResponse(
            error_code="validation_failed", message=str(exc)
        ).model_dump(),
    )
