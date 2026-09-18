#!/bin/bash
#
# Generate the self-signed TLS certificates that the QUIC servers require.
#
# Why this script exists
#   QUIC mandates TLS, so both simulation projects need a certificate and key
#   to start a server. These are throwaway localhost credentials with no value
#   outside this testbed, so they are generated on demand rather than committed
#   to version control (see .gitignore, "Certificates").
#
#   Run this once after cloning. The Generation 2 Docker image generates its
#   own certificates at build time and does not need this; every other path
#   (local runs of either project, and the Generation 1 container, which mounts
#   the host's code directory) reads the files produced here.
#
# Usage
#   ./generate_certs.sh           # generate only if missing
#   ./generate_certs.sh --force   # regenerate, replacing any existing pair
#
# Produces, in each project:
#   certs/cert.pem   self-signed X.509 certificate, CN=localhost, 365 days
#   certs/key.pem    unencrypted RSA-2048 private key
#
# The key is deliberately unencrypted (-nodes) so the servers can start without
# a passphrase prompt. That is acceptable only because these certificates are
# disposable and are never used outside localhost testing.

set -e

FORCE=0
if [ "$1" = "--force" ]; then
    FORCE=1
fi

ROOT="$(cd "$(dirname "$0")" && pwd)"

CERT_DIRS=(
    "$ROOT/QUIC_3conn_implementation/3_conn_code/certs"
    "$ROOT/QUIC_tuning_multistream/code/certs"
)

if ! command -v openssl >/dev/null 2>&1; then
    echo "Error: openssl not found. Install it and re-run."
    exit 1
fi

for dir in "${CERT_DIRS[@]}"; do
    mkdir -p "$dir"

    if [ -f "$dir/cert.pem" ] && [ -f "$dir/key.pem" ] && [ "$FORCE" -eq 0 ]; then
        echo "exists, skipping : $dir  (use --force to regenerate)"
        continue
    fi

    openssl req -x509 -newkey rsa:2048 -nodes \
        -keyout "$dir/key.pem" \
        -out "$dir/cert.pem" \
        -days 365 \
        -subj "/CN=localhost" \
        2>/dev/null

    # The private key is readable only by its owner; the certificate is public.
    chmod 600 "$dir/key.pem"
    chmod 644 "$dir/cert.pem"

    echo "generated        : $dir"
done

echo ""
echo "Done. Certificates are ignored by git and must not be committed."
