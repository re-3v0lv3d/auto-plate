#!/usr/bin/env bash
# Despliegue en Google Cloud Run + Firebase Hosting.
#
# Requisitos:
#   - gcloud CLI autenticado (gcloud auth login)
#   - proyecto con facturación ACTIVA (Blaze). El tramo siempre gratis cubre esto.
#   - firebase CLI (npm i -g firebase-tools) solo para el hosting.
#
# Uso:
#   PROJECT=mi-proyecto API_USER=ay API_PASSWORD=... ./deploy/gcp.sh
#   PROJECT=mi-proyecto API_USER=ay API_PASSWORD=... ./deploy/gcp.sh --with-hosting
set -euo pipefail

: "${PROJECT:?Define PROJECT=tu-proyecto}"
REGION="${REGION:-europe-west1}"
SERVICE="${SERVICE:-auto-plate}"
CORS_ORIGINS="${CORS_ORIGINS:-*}"
WITH_HOSTING=0
[[ "${1:-}" == "--with-hosting" ]] && WITH_HOSTING=1

ENV_VARS="STORAGE=firestore,CAPTCHA_PROVIDER=site,CORS_ORIGINS=${CORS_ORIGINS}"
if [[ -n "${API_USER:-}" && -n "${API_PASSWORD:-}" ]]; then
  ENV_VARS="${ENV_VARS},API_USER=${API_USER},API_PASSWORD=${API_PASSWORD}"
else
  echo "⚠  Sin API_USER/API_PASSWORD la API quedará abierta a cualquiera."
fi

cd "$(dirname "$0")/.."

echo "==> Habilitando APIs"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
  artifactregistry.googleapis.com firestore.googleapis.com --project "$PROJECT"

echo "==> Firestore (se ignora si ya existe)"
gcloud firestore databases create --project "$PROJECT" --location "$REGION" \
  --type firestore-native 2>/dev/null || echo "   ya existía"

echo "==> Desplegando $SERVICE en Cloud Run ($REGION)"
gcloud run deploy "$SERVICE" \
  --project "$PROJECT" \
  --source . \
  --region "$REGION" \
  --allow-unauthenticated \
  --memory 512Mi \
  --cpu 1 \
  --timeout 180 \
  --min-instances 0 \
  --max-instances 2 \
  --set-env-vars "$ENV_VARS"

URL=$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format='value(status.url)')
echo "==> API: $URL"
echo "==> Siguiente: actualiza la variable AUTOPLATE_API del repo con esa URL"

if [[ "$WITH_HOSTING" == "1" ]]; then
  echo "==> Publicando UI en Firebase Hosting"
  firebase deploy --project "$PROJECT" --only hosting
  echo "==> Listo."
fi
