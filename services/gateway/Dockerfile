FROM golang:1.26-alpine AS builder
WORKDIR /build
RUN apk add --no-cache gcc musl-dev
COPY services/proto/go services/proto/go
COPY services/gateway services/gateway
WORKDIR /build/services/gateway
RUN go mod tidy && \
    CGO_ENABLED=0 GOOS=linux go build -ldflags="-s -w -extldflags=-static" -o /gateway .

FROM alpine:3.20
ARG SERVICE_VERSION=0.0.0
ENV SERVICE_VERSION=$SERVICE_VERSION
RUN adduser -D -g '' -u 1001 nonroot && \
    apk add --no-cache wget ca-certificates
COPY --from=builder /gateway /gateway
USER nonroot
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://127.0.0.1:8000/health || exit 1
ENTRYPOINT ["/gateway"]
