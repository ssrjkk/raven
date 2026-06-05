FROM golang:1.26-alpine AS builder
WORKDIR /build

COPY services/proto/go services/proto/go
COPY services/gateway services/gateway

WORKDIR /build/services/gateway
RUN go mod tidy && CGO_ENABLED=0 GOOS=linux go build -o /gateway .

FROM alpine:3.23
RUN apk add --no-cache ca-certificates tzdata
COPY --from=builder /gateway /gateway
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --retries=3 CMD wget -qO- http://localhost:8000/health || exit 1
ENTRYPOINT ["/gateway"]
