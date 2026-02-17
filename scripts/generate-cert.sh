#!/bin/bash
# Generate a self-signed certificate for local HTTPS
# Usage: ./scripts/generate-cert.sh

CERT_DIR="./certs"
mkdir -p "$CERT_DIR"

openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout "$CERT_DIR/key.pem" \
  -out "$CERT_DIR/cert.pem" \
  -days 365 \
  -subj "/CN=plex-spoiler-shield/O=Local"

echo "Certificates generated in $CERT_DIR/"
echo "  cert: $CERT_DIR/cert.pem"
echo "  key:  $CERT_DIR/key.pem"
echo ""
echo "Add to .env:"
echo "  SSL_CERTFILE=/certs/cert.pem"
echo "  SSL_KEYFILE=/certs/key.pem"
