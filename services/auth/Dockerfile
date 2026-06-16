FROM golang:1.26-alpine AS builder
WORKDIR /build
RUN apk add --no-cache gcc musl-dev
COPY services/proto/go services/proto/go
COPY services/auth services/auth
WORKDIR /build/services/auth
RUN go mod tidy && \
    CGO_ENABLED=1 GOOS=linux go build -ldflags="-s -w -linkmode external -extldflags -static" -o /auth .

FROM alpine:3.20
RUN adduser -D -g '' -u 1001 nonroot && \
    apk add --no-cache wget ca-certificates
COPY --from=builder /auth /auth
USER nonroot
EXPOSE 8001 9001
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://127.0.0.1:8001/health || exit 1
ENTRYPOINT ["/auth"]
