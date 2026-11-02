import json
import os
import re
# BANDHOO_SKIP_DOTENV=1 lets tests import the app without reading .env.
if os.environ.get("BANDHOO_SKIP_DOTENV") != "1":
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
from contextlib import asynccontextmanager
import logging
from typing import Optional
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uvicorn

from complaint_engine import ComplaintStructureRequest, assess_point, structure_for_api

api_logger = logging.getLogger("bandhoo.api")
metrics_logger = logging.getLogger("bandhoo.metrics")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan context manager.
    Safely initializes persistent database schema on startup without silently swallowing failures.
    """
    try:
        from db.session import init_db
        init_db()
        api_logger.info("[Startup] Database tables initialized and verified successfully.")
    except Exception as exc:
        api_logger.error("[Startup] Database initialization failed: %s", exc, exc_info=True)
        raise
    yield


app = FastAPI(lifespan=lifespan)

# CORS restrictions: configurable via BANDHOO_CORS_ORIGINS; defaults to local development origins.
CORS_ORIGINS_ENV = os.environ.get("BANDHOO_CORS_ORIGINS", "")
ALLOWED_ORIGINS = [o.strip() for o in CORS_ORIGINS_ENV.split(",") if o.strip()] or [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:8001",
    "http://127.0.0.1:8001",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# ── Prometheus Metrics Instrumentation (MLOps Phase 1) ──
try:
    from prometheus_fastapi_instrumentator import Instrumentator
    Instrumentator(
        should_group_status_codes=False,
        should_ignore_untemplated=True,
        should_respect_env_var=True,
        should_instrument_requests_inprogress=True,
        excluded_handlers=["/metrics", "/health", "/api/health/db"],
        env_var_name="ENABLE_METRICS",
        inprogress_name="bandhoo_requests_in_progress",
        inprogress_labels=True,
    ).instrument(app).expose(app, endpoint="/metrics", include_in_schema=True)
    metrics_logger.info("[Metrics] Prometheus metrics instrumentation actively exposed at /metrics.")
except ImportError as imp_err:
    metrics_logger.error(
        "[Metrics] prometheus-fastapi-instrumentator is not installed. /metrics endpoint is unavailable: %s",
        imp_err
    )
    if os.environ.get("REQUIRE_METRICS") == "1" or os.environ.get("BANDHOO_ENV") == "production":
        raise
except Exception as exc:
    metrics_logger.error("[Metrics] Failed to initialize Prometheus instrumentation: %s", exc, exc_info=True)
    raise

@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc):
    import logging
    logger = logging.getLogger("bandhoo.api")
    logger.error("Unhandled API error on %s: %s", request.url.path, type(exc).__name__)
    return JSONResponse(
        status_code=500,
        content={"error": "An internal error occurred while processing the request."}
    )

from legal_engine.synonyms import DEFAULT_SYNONYM_MAP as SYNONYM_MAP


def translate_synonyms(text: str):
    """
    Scans the narrative text, locates matched synonyms, and outputs a 
    standardized format for classification (RAG & Logistic Regression).
    """
    if not text:
        return "", []
    
    translations = []
    standardized_text = text
    
    # Sort keys by length descending so that multi-word terms match before single words
    sorted_syns = sorted(SYNONYM_MAP.keys(), key=len, reverse=True)
    
    for syn in sorted_syns:
        pattern = r'\b' + re.escape(syn) + r'\b'
        if re.search(pattern, standardized_text, re.IGNORECASE):
            std_term = SYNONYM_MAP[syn]
            translations.append({
                "synonym": syn,
                "standard_term": std_term
            })
            standardized_text = re.sub(pattern, std_term, standardized_text, flags=re.IGNORECASE)
            
    return standardized_text, translations

# ── Load the police stations dataset ──
current_dir = os.path.dirname(os.path.abspath(__file__))
json_path = os.path.join(current_dir, "datasets", "police_stations_data.json")
if not os.path.exists(json_path):
    json_path = os.path.join(current_dir, "police_stations_data.json")

if not os.path.exists(json_path):
    raise FileNotFoundError(f"Required station dataset not found at: {json_path}")

with open(json_path, "r", encoding="utf-8") as f:
    stations_data = json.load(f)

# Filter for Subtype = 'Station'. Note: the coordinates are jurisdiction-polygon centroids, not station
# addresses, and the dataset has no contact details. Jurisdiction is assessed by polygon containment.
stations = [s for s in stations_data if s['subtype'] == 'Station']
stations_by_name = {s['name']: s for s in stations}

# ── Initialize Modular Legal Engine ──
from legal_engine import (
    BNSCorpus,
    BM25LegalRetriever,
    GeminiLegalClient,
    LegalAnalysisService,
    NarrativeInput,
    OffenceClassificationResponse
)

legal_corpus = BNSCorpus()
legal_retriever = BM25LegalRetriever(legal_corpus)
gemini_client = GeminiLegalClient()
legal_service = LegalAnalysisService(
    corpus=legal_corpus,
    retriever=legal_retriever,
    llm_client=gemini_client,
    synonym_map=SYNONYM_MAP
)

print(f"[LegalEngine] Loaded {len(legal_corpus.sections_by_num)} verified BNS sections.")
print(f"[LegalEngine] BM25 Index initialized: {legal_retriever.bm25 is not None}")
print(f"[LegalEngine] Gemini LLM active: {gemini_client.is_available} (Model: {gemini_client.model_name})")


# ── Pydantic Models ──

class Location(BaseModel):
    latitude: float
    longitude: float


# ── Endpoints ──

@app.post("/api/get-jurisdiction")
async def get_jurisdiction(loc: Location):
    """
    Polygon-containment jurisdiction estimate. A station is named only when the point lies inside exactly
    one polygon and is not near a boundary; otherwise station is null and confirmation is required.
    """
    result = assess_point(loc.latitude, loc.longitude)
    station_details = stations_by_name.get(result.station) if result.station else None
    station_email = None
    if result.station:
        clean = re.sub(r'[^a-zA-Z0-9]', '', result.station).lower()
        station_email = f"ps.{clean}.mum@mahapolice.gov.in"
        if station_details and not station_details.get("email"):
            station_details["email"] = station_email
    return {
        "station": result.station,
        "station_email": station_email,
        "status": result.status,
        "method": result.method,
        "distance_to_boundary_m": result.distance_to_boundary_m,
        "message": result.message,
        "boundary_data": result.boundary_data,
        "details": station_details,
    }



@app.post("/api/v1/complaints/structure")
async def structure_complaint(data: ComplaintStructureRequest):
    """
    Structures a complainant's account into a source-attributed record (LangGraph workflow).
    Deterministic extraction only: no external model or geocoding service is called. Nothing is stored,
    verified or submitted. Verification events cannot be supplied through this endpoint.
    If the statement could not be structured, the response is an error (500, or 503 when external tracing
    is configured) that returns the received statement verbatim with "review_status_unavailable".
    """
    status, body = structure_for_api(data)
    return body if status == 200 else JSONResponse(status_code=status, content=body)


@app.post("/api/v1/complaints/compile")
async def compile_complaint(data: ComplaintStructureRequest):
    """
    Compiles all relevant user information into a consistent, reviewable complaint record,
    integrating timeline, roles, missing persons, legal candidates, and database persistence.
    """
    from complaint_engine.compiler import compile_complaint_record
    from db.session import SessionLocal
    db = SessionLocal()
    try:
        record = compile_complaint_record(data, include_legal_candidates=True, db_session=db)
        return record
    finally:
        db.close()


@app.post("/api/v1/complaints/generate-pdf")
async def generate_pdf_endpoint(data: ComplaintStructureRequest):
    """
    Compiles complaint and generates a formal, paginated PDF document.
    """
    from fastapi.responses import Response
    from complaint_engine.compiler import compile_complaint_record
    from complaint_engine.pdf_generator import generate_complaint_pdf
    from db.session import SessionLocal
    db = SessionLocal()
    try:
        record = compile_complaint_record(data, include_legal_candidates=True, db_session=db)
        pdf_bytes, filename, file_size, sha256_hash = generate_complaint_pdf(record)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-Document-SHA256": sha256_hash,
                "X-Document-Size": str(file_size),
            }
        )
    finally:
        db.close()


@app.post("/api/v1/complaints/email-draft")
async def email_draft_endpoint(data: ComplaintStructureRequest, recipient_email: Optional[str] = None):
    """
    Prepares an email draft for user confirmation prior to transmission.
    """
    from complaint_engine.compiler import compile_complaint_record
    from complaint_engine.pdf_generator import generate_complaint_pdf
    from complaint_engine.email_draft import prepare_complaint_email_draft, EmailAttachmentMetadata
    from db.session import SessionLocal
    db = SessionLocal()
    try:
        record = compile_complaint_record(data, include_legal_candidates=True, db_session=db)
        pdf_bytes, filename, file_size, sha256_hash = generate_complaint_pdf(record)
        attachment = EmailAttachmentMetadata(
            file_name=filename,
            file_size_bytes=file_size,
            sha256_hash=sha256_hash
        )
        draft = prepare_complaint_email_draft(record, recipient_email=recipient_email, pdf_attachment=attachment)
        return draft.model_dump()
    finally:
        db.close()


@app.get("/health")
async def health():
    """
    Kubernetes liveness and readiness probe endpoint.
    Returns 200 OK with service and version status.
    """
    return {
        "status": "healthy",
        "service": "bandhoo-backend",
        "version": "1.0.0"
    }


@app.get("/api/health/db")
async def db_health_check():
    """Returns database connection status and health."""
    from db.session import check_db_health
    return check_db_health()



@app.post("/api/classify-offence", response_model=OffenceClassificationResponse)
async def classify_offence(data: NarrativeInput):
    """
    Intelligent BNS legal section classifier.
    Combines BM25 statutory retrieval with Google Gemini legal reasoning.
    Preserves complete backwards-compatibility with existing frontend.
    """
    result = legal_service.analyze_complaint(data)
    return result


@app.get("/api/bns-stats")
async def bns_stats():
    """Return health and statistics about the loaded BNS legal engine."""
    return {
        "sections_loaded": len(legal_corpus.sections_by_num),
        "bm25_ready": legal_retriever.bm25 is not None,
        "llm_available": gemini_client.is_available,
        "llm_model": gemini_client.model_name if gemini_client.is_available else "offline",
        "excluded_sections": legal_corpus.excluded_sections
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8001)