"""FastAPI application: wiring, error envelope, health check and dashboard."""

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import text
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import services
from app.config import settings
from app.database import Base, SessionLocal, engine
from app.responses import ApiError, failure, success
from app.routers import patients, vapi
from app.schemas import format_errors

logging.basicConfig(
    level=settings.log_level,
    stream=sys.stdout,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("app")

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    # create_all is idempotent; good enough for a single-table take-home (see README trade-offs).
    Base.metadata.create_all(bind=engine)
    if settings.seed_demo_data:
        with SessionLocal() as db:
            services.seed_demo_patients(db)
    logger.info("Startup complete (database: %s)", engine.url.get_backend_name())
    yield


app = FastAPI(
    title="Patient Registration API",
    description="REST API and Vapi tool endpoints for the voice patient-registration agent.",
    version="1.0.0",
    lifespan=lifespan,
)
app.include_router(patients.router)
app.include_router(vapi.router)


# --------------------------------------------------------------------------- #
# Error handlers: every error uses the {"data": null, "error": {...}} envelope
# --------------------------------------------------------------------------- #


@app.exception_handler(ApiError)
async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
    return failure(exc.status_code, exc.code, exc.message, exc.details)


@app.exception_handler(services.NotFoundError)
async def _not_found(_: Request, exc: services.NotFoundError) -> JSONResponse:
    return failure(404, "not_found", str(exc))


@app.exception_handler(services.DatabaseError)
async def _database_error(_: Request, exc: services.DatabaseError) -> JSONResponse:
    return failure(500, "database_error", str(exc))


@app.exception_handler(RequestValidationError)
async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
    errors = exc.errors()
    # Malformed path/query params (e.g. a non-UUID id) are a bad request (400);
    # a well-formed body that breaks field rules is unprocessable (422).
    in_body = any(err.get("loc", ("",))[0] == "body" for err in errors)
    if in_body:
        return failure(422, "validation_error", "One or more fields are invalid", format_errors(errors))
    return failure(400, "bad_request", "Invalid request parameters", format_errors(errors))


@app.exception_handler(StarletteHTTPException)
async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = "not_found" if exc.status_code == 404 else "http_error"
    return failure(exc.status_code, code, str(exc.detail))


@app.exception_handler(Exception)
async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error", exc_info=exc)
    return failure(500, "internal_error", "An unexpected error occurred")


# --------------------------------------------------------------------------- #
# Misc routes
# --------------------------------------------------------------------------- #


@app.get("/", include_in_schema=False)
def index() -> JSONResponse:
    return success({
        "service": "Patient Registration API",
        "docs": "/docs",
        "dashboard": "/dashboard",
        "patients": "/patients",
        "health": "/health",
    })


@app.get("/health", tags=["meta"])
def health() -> JSONResponse:
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
    except Exception:
        logger.exception("Health check failed")
        return failure(503, "unhealthy", "Database unreachable")
    return success({"status": "ok", "database": "ok"})


@app.get("/dashboard", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "dashboard.html")
