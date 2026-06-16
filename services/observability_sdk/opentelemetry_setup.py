from __future__ import annotations

import os

from loguru import logger

try:
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

    HAS_OTEL = True
except ImportError:
    HAS_OTEL = False


def setup_opentelemetry(app=None, service_name: str | None = None) -> None:
    if not HAS_OTEL:
        logger.warning("OpenTelemetry packages not installed — tracing disabled")
        return

    service_name = service_name or os.environ.get("OTEL_SERVICE_NAME", "unknown")
    otel_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")

    resource = Resource.create({
        "service.name": service_name,
        "service.version": os.environ.get("SERVICE_VERSION", "1.0.0"),
        "deployment.environment": os.environ.get("DEPLOY_ENV", "production"),
    })

    provider = TracerProvider(resource=resource)

    if os.environ.get("OTEL_CONSOLE_EXPORTER", "").lower() in ("1", "true"):
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    try:
        exporter = OTLPSpanExporter(endpoint=otel_endpoint, insecure=True)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        logger.info("OTLP exporter configured -> {}", otel_endpoint)
    except Exception as exc:
        logger.warning("Failed to configure OTLP exporter: {}", exc)

    trace.set_tracer_provider(provider)

    if app is not None:
        try:
            FastAPIInstrumentor.instrument_app(app)
            HTTPXClientInstrumentor().instrument()
            logger.info("FastAPI and httpx auto-instrumentation enabled")
        except Exception as exc:
            logger.warning("Auto-instrumentation failed: {}", exc)

    logger.info("OpenTelemetry initialized for service={}", service_name)


def get_tracer(name: str = "raven") -> trace.Tracer:
    return trace.get_tracer(name)
