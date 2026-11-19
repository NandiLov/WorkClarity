"""AI-assisted schedule extraction and benchmarking pipeline for WorkClarity."""

from ai_extraction.orchestrator import (
    DEFAULT_FALLBACK_MODEL,
    DEFAULT_FALLBACK_PROVIDER,
    DEFAULT_PRIMARY_MODEL,
    DEFAULT_PRIMARY_PROVIDER,
    SUPPORTED_PROVIDERS,
    ExtractionOrchestrator,
    ExtractionServiceConfig,
    OrchestratedExtractionResult,
    run_provider_attempts,
)
from ai_extraction.pdf_utils import (
    IMAGE_PREPROCESSING_BACKEND_ORDER,
    PDF_RENDERING_BACKEND_ORDER,
    MissingRenderingDependencyError,
    get_available_image_preprocessing_backend,
    get_available_pdf_rendering_backend,
)
from ai_extraction.schema import (
    CONFIRMATION_CSV_COLUMNS,
    CSV_COLUMNS,
    EXTRACTION_FIELDS,
    DocumentExtractionResult,
    ExtractedShiftRecord,
    SharedShiftSchema,
    parse_and_validate_model_json,
    resolve_conflict_group,
)

__all__ = [
    "CONFIRMATION_CSV_COLUMNS",
    "CSV_COLUMNS",
    "DEFAULT_FALLBACK_MODEL",
    "DEFAULT_FALLBACK_PROVIDER",
    "DEFAULT_PRIMARY_MODEL",
    "DEFAULT_PRIMARY_PROVIDER",
    "IMAGE_PREPROCESSING_BACKEND_ORDER",
    "PDF_RENDERING_BACKEND_ORDER",
    "SUPPORTED_PROVIDERS",
    "DocumentExtractionResult",
    "EXTRACTION_FIELDS",
    "ExtractedShiftRecord",
    "ExtractionOrchestrator",
    "ExtractionServiceConfig",
    "MissingRenderingDependencyError",
    "OrchestratedExtractionResult",
    "SharedShiftSchema",
    "get_available_image_preprocessing_backend",
    "get_available_pdf_rendering_backend",
    "parse_and_validate_model_json",
    "resolve_conflict_group",
    "run_provider_attempts",
]
