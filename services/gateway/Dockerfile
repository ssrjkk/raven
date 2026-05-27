FROM golang:1.22-alpine AS builder
WORKDIR /build
COPY . .
RUN go mod tidy
RUN CGO_ENABLED=0 GOOS=linux go build -o /gateway .

FROM alpine:3.20
RUN apk add --no-cache ca-certificates tzdata
COPY --from=builder /gateway /gateway
EXPOSE 8000
ENTRYPOINT ["/gateway"]
