"use client";

let configured = false;

const COLLECTOR =
  process.env.NEXT_PUBLIC_OTEL_COLLECTOR_URL ?? "http://localhost:4318/v1/traces";

const SERVICE_NAME =
  process.env.NEXT_PUBLIC_OTEL_SERVICE_NAME ?? "context-switcher-web";

export async function configureTracing(): Promise<void> {
  if (configured) return;
  if (typeof window === "undefined") return;
  configured = true;

  try {
    const [
      { WebTracerProvider },
      { OTLPTraceExporter },
      { BatchSpanProcessor },
      { Resource },
      { ZoneContextManager },
    ] = await Promise.all([
      import("@opentelemetry/sdk-trace-web"),
      import("@opentelemetry/exporter-trace-otlp-http"),
      import("@opentelemetry/sdk-trace-web"),
      import("@opentelemetry/resources"),
      import("@opentelemetry/context-zone"),
    ]);

    const resource = new Resource({ "service.name": SERVICE_NAME });
    const provider = new WebTracerProvider({ resource });

    const exporter = new OTLPTraceExporter({ url: COLLECTOR });
    provider.addSpanProcessor(new BatchSpanProcessor(exporter));
    provider.register({ contextManager: new ZoneContextManager() });
  } catch {
    // tracing is optional — never block the app
  }
}
