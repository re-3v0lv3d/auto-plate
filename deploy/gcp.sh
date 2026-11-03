#!/usr/bin/env bash
# Despliegue en Google Cloud Run + Firebase Hosting.
#
# Requisitos:
#   - gcloud CLI autenticado (gcloud auth login)
#   - proyecto con facturación (Blaze). El tramo siempre gratis cubre esto.
#   - firebase CLI (npm i -g firebase-tools) solo para el hosting.
#
# Uso:
#   PROJECT=mi-proyecto ./deploy/gcp.sh
#   PROJECT=mi-proyecto ./deploy/gcp.sh --with-hosting
set -euo pipefail

: "${PROJECT:?Define PROJECT=tu-proyecto}"
REGION="${REGION:-europe-west1}"
SERVICE="${SERVICE:-auto-plate}"
WITH_HOSTING=0
[[ "${1:-}" == "--with-hosting" ]] && WITH_HOSTING=1

cd "$(dirname "$0")/.."

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
  --set-env-vars "STORAGE=firestore,CAPTCHA_PROVIDER=site,CORS_ORIGINS=*"

URL=$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format='value(status.url)')
echo "==> API: $URL"
echo "==> Recuerda: Firestore en modo Native y el service account con roles/datastore.user"

if [[ "$WITH_HOSTING" == "1" ]]; then
  echo "==> Publicando UI en Firebase Hosting"
  firebase deploy --project "$PROJECT" --only hosting
  echo "==> Listo. Abre la URL de Hosting (Firebase te la muestra arriba)."
else
  echo "==> Para publicar también la UI: ./deploy/gcp.sh --with-hosting"
fi
