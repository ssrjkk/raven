FROM golang:1.22-alpine AS builder
WORKDIR /build
COPY . .
RUN go mod tidy
RUN CGO_ENABLED=0 GOOS=linux go build -o /auth .

FROM alpine:3.20
RUN apk add --no-cache ca-certificates tzdata
COPY --from=builder /auth /auth
EXPOSE 8001
ENTRYPOINT ["/auth"]
