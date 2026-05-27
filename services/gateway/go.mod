module github.com/ssrjkk/raven/services/gateway

go 1.22

require (
	github.com/nats-io/nats.go v1.37.0
	github.com/prometheus/client_golang v1.20.0
	github.com/rs/cors v1.11.0
	go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp v0.54.0
	go.opentelemetry.io/otel v1.29.0
	go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracegrpc v1.29.0
	go.opentelemetry.io/otel/sdk v1.29.0
	go.opentelemetry.io/otel/trace v1.29.0
	google.golang.org/grpc v1.65.0
)
