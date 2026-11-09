"""OpenTelemetry metrics integration for the Free AI Gateway.

Provides OpenTelemetry-based metrics collection and export for:
- Request count, duration, and errors by provider/model
- Token usage and estimated cost
- Circuit breaker state
- Cache hit/miss ratio

Exports via OTLP HTTP/gRPC to a collector (e.g., Jaeger, Prometheus, Datadog).
Configurable via environment variables:
  OTEL_ENABLED=1
  OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
  OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
  OTEL_SERVICE_NAME=free-ai-gateway
"""

from __future__ import annotations

import os
import time
from typing import Any, Optional

from opentelemetry import metrics as otel_metrics
from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
    OTLPMetricExporter as OTLPMetricExporterHTTP,
)
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
    OTLPMetricExporter as OTLPMetricExporterGRPC,
)
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.metrics.view import (
    View,
    ExplicitBucketHistogramAggregation,
)
from opentelemetry.sdk.metrics.view import View as SDKView

from .config import settings


_otel_initialized = False
_meter: Optional[otel_metrics.Meter] = None

# Instrumentation counters
_request_counter = None
_request_duration_histogram = None
_request_error_counter = None
_token_counter = None
_cost_counter = None
_cache_hit_counter = None
_cache_miss_counter = None
_circuit_breaker_gauge = None


def init_otel() -> None:
    """Initialize OpenTelemetry metrics provider."""
    global _otel_initialized, _meter, _request_counter, _request_duration_histogram
    global _request_error_counter, _token_counter, _cost_counter
    global _cache_hit_counter, _cache_miss_counter, _circuit_breaker_gauge

    if not getattr(settings, "otel_enabled", False):
        return

    if _otel_initialized:
        return

    try:
        endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
        protocol = os.environ.get("OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf")
        service_name = os.environ.get("OTEL_SERVICE_NAME", "free-ai-gateway")

        resource = Resource.create({"service.name": service_name})
        provider = MeterProvider(resource=resource)

        if protocol == "grpc":
            exporter = OTLPMetricExporterGRPC(endpoint=endpoint)
        else:
            exporter = OTLPMetricExporterHTTP(endpoint=endpoint)

        reader = PeriodicExportingMetricReader(exporter, export_interval_millis=5000)
        provider.add_metric_reader(reader)
        otel_metrics.set_meter_provider(provider)

        _meter = otel_metrics.get_meter(__name__, "1.0.0")

        # Define instruments
        _request_counter = _meter.create_counter(
            name="free_ai_requests_total",
            description="Total number of LLM requests",
            unit="1",
        )
        _request_duration_histogram = _meter.create_histogram(
            name="free_ai_request_duration_seconds",
            description="Request duration in seconds",
            unit="s",
            explicit_bucket_boundaries_advice=(0.001, 0.01, 0.1, 0.5, 1, 2, 5, 10, 30, 60),
        )
        _request_error_counter = _meter.create_counter(
            name="free_ai_request_errors_total",
            description="Total number of failed LLM requests",
            unit="1",
        )
        _token_counter = _meter.create_counter(
            name="free_ai_tokens_total",
            description="Total number of tokens processed",
            unit="1",
        )
        _cost_counter = _meter.create_counter(
            name="free_ai_cost_usd_total",
            description="Estimated cost in USD",
            unit="usd",
        )
        _cache_hit_counter = _meter.create_counter(
            name="free_ai_cache_hits_total",
            description="Total number of cache hits",
            unit="1",
        )
        _cache_miss_counter = _meter.create_counter(
            name="free_ai_cache_misses_total",
            description="Total number of cache misses",
            unit="1",
        )
        _circuit_breaker_gauge = _meter.create_gauge(
            name="free_ai_circuit_breaker_open",
            description="Circuit breaker state (1=open, 0=closed)",
            unit="1",
        )

        _otel_initialized = True
    except Exception as e:
        import logging
        logging.getLogger("free-ai.otel").warning(f"OpenTelemetry initialization failed: {e}")


def record_request(
    provider: str,
    model: str,
    status: str,
    duration_seconds: float,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    cost_usd: float = 0.0,
) -> None:
    """Record a completed LLM request."""
    if not _otel_initialized:
        return

    attrs = {
        "provider": provider,
        "model": model,
        "status": status,
    }

    _request_counter.add(1, attrs)
    _request_duration_histogram.record(duration_seconds, attrs)

    if status == "error":
        _request_error_counter.add(1, attrs)

    if prompt_tokens > 0 or completion_tokens > 0:
        _token_counter.add(prompt_tokens + completion_tokens, {**attrs, "type": "total"})
        if prompt_tokens > 0:
            _token_counter.add(prompt_tokens, {**attrs, "type": "prompt"})
        if completion_tokens > 0:
            _token_counter.add(completion_tokens, {**attrs, "type": "completion"})

    if cost_usd > 0:
        _cost_counter.add(cost_usd, attrs)


def record_cache_hit() -> None:
    """Record a cache hit."""
    if _otel_initialized and _cache_hit_counter:
        _cache_hit_counter.add(1)


def record_cache_miss() -> None:
    """Record a cache miss."""
    if _otel_initialized and _cache_miss_counter:
        _cache_miss_counter.add(1)


def record_circuit_breaker_state(provider: str, is_open: bool) -> None:
    """Record circuit breaker state."""
    if _otel_initialized and _circuit_breaker_gauge:
        _circuit_breaker_gauge.set(1 if is_open else 0, {"provider": provider})


def is_enabled() -> bool:
    """Check if OpenTelemetry is initialized and enabled."""
    return _otel_initialized


def get_meter() -> Optional[otel_metrics.Meter]:
    """Get the OpenTelemetry meter."""
    return _meter