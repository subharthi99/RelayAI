"""RelayAI's policy-aware voice pipeline core."""

__version__ = "0.4.1"

from .credentials import CredentialResolver, MappingCredentialResolver
from .engine import PipelineEngine, PreparedRun
from .destinations import (
    FileDestination,
    ResultDestination,
    ScriptDestination,
    WebhookDestination,
)
from .errors import ConfigurationError, PolicyViolation, ProviderError
from .models import (
    AdapterRef,
    CaptureConfig,
    DestinationEffect,
    Exposure,
    PipelineDefinition,
    PipelinePolicy,
    PipelineRun,
    RefinementConfig,
    RunStatus,
)
from .serialization import export_pipeline, load_pipeline
from .storage import SQLiteStore
from .whisper_cpp import WhisperCppModel, WhisperCppSpeechProvider
from .openai_compatible import (
    HTTPTransport,
    OpenAICompatibleRefinementProvider,
    OpenAICompatibleSpeechProvider,
    StandardLibraryHTTPTransport,
)

__all__ = [
    "AdapterRef",
    "CaptureConfig",
    "ConfigurationError",
    "CredentialResolver",
    "DestinationEffect",
    "Exposure",
    "FileDestination",
    "HTTPTransport",
    "MappingCredentialResolver",
    "OpenAICompatibleRefinementProvider",
    "OpenAICompatibleSpeechProvider",
    "PipelineDefinition",
    "PipelineEngine",
    "PipelinePolicy",
    "PipelineRun",
    "PolicyViolation",
    "PreparedRun",
    "ProviderError",
    "RefinementConfig",
    "ResultDestination",
    "RunStatus",
    "ScriptDestination",
    "SQLiteStore",
    "StandardLibraryHTTPTransport",
    "WebhookDestination",
    "WhisperCppModel",
    "WhisperCppSpeechProvider",
    "__version__",
    "export_pipeline",
    "load_pipeline",
]
