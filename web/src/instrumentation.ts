import { WebTracerProvider } from "@opentelemetry/sdk-trace-web";
import { Resource } from "@opentelemetry/resources";
import { SEMRESATTRS_SERVICE_NAME } from "@opentelemetry/semantic-conventions";
import { OTLPTraceExporter } from "@opentelemetry/exporter-trace-otlp-http";
import { ZoneContextManager } from "@opentelemetry/context-zone";
import { registerInstrumentations } from "@opentelemetry/instrumentation";
import { FetchInstrumentation } from "@opentelemetry/instrumentation-fetch";
import { XMLHttpRequestInstrumentation } from "@opentelemetry/instrumentation-xml-http-request";
import { DocumentLoadInstrumentation } from "@opentelemetry/instrumentation-document-load";

const otelEndpoint =
  import.meta.env.VITE_OTEL_ENDPOINT || "http://localhost:4318/v1/traces";

const provider = new WebTracerProvider({
  resource: new Resource({
    [SEMRESATTRS_SERVICE_NAME]: "raven-web",
  }),
});

const exporter = new OTLPTraceExporter({ url: otelEndpoint });
provider.addSpanProcessor({ forceFlush: async () => {}, onStart: () => {}, onEnd: (span) => { exporter.export([span], () => {}); }, shutdown: async () => {} });

provider.register({
  contextManager: new ZoneContextManager(),
});

registerInstrumentations({
  instrumentations: [
    new DocumentLoadInstrumentation(),
    new FetchInstrumentation(),
    new XMLHttpRequestInstrumentation(),
  ],
});

export function getTracer() {
  return provider.getTracer("raven-web");
}
