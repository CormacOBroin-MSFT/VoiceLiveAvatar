#!/usr/bin/env bash
# deploy.sh — Provision Azure resources for the Voice Live Avatar sample
# Usage: ./deploy.sh [--write-env]
#   --write-env   Write endpoint and key to a .env file after provisioning

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration — edit these before running
# ---------------------------------------------------------------------------
RESOURCE_GROUP="rg-voicelive-avatar"
LOCATION="swedencentral"     # Supported: southeastasia, northeurope, westeurope,
                             #            swedencentral, southcentralus, eastus2, westus2
AI_SERVICES_NAME="ai-voicelive-$RANDOM"   # also used as the custom subdomain
WRITE_ENV=false

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
for arg in "$@"; do
  case $arg in
    --write-env) WRITE_ENV=true ;;
    *) echo "Unknown argument: $arg"; exit 1 ;;
  esac
done

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
info()    { echo "[INFO]  $*"; }
success() { echo "[OK]    $*"; }
error()   { echo "[ERROR] $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------
command -v az &>/dev/null || error "Azure CLI not found. Install from https://aka.ms/installazurecli"

info "Checking Azure CLI login status..."
az account show --output none 2>/dev/null || {
  info "Not logged in — running 'az login'..."
  az login
}

SUBSCRIPTION=$(az account show --query "name" -o tsv)
info "Using subscription: $SUBSCRIPTION"

# ---------------------------------------------------------------------------
# Resource Group
# ---------------------------------------------------------------------------
info "Creating resource group '$RESOURCE_GROUP' in '$LOCATION'..."
az group create \
  --name "$RESOURCE_GROUP" \
  --location "$LOCATION" \
  --output none
success "Resource group ready."

# ---------------------------------------------------------------------------
# Azure AI Services (Foundry / multi-service) resource
# The Voice Live API is exposed through the AIServices kind endpoint.
# ---------------------------------------------------------------------------
info "Creating Azure AI Services resource '$AI_SERVICES_NAME'..."
az cognitiveservices account create \
  --name "$AI_SERVICES_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --kind "AIServices" \
  --sku "S0" \
  --location "$LOCATION" \
  --custom-domain "$AI_SERVICES_NAME" \
  --yes \
  --output none

# Disable local auth (API keys) immediately so Azure Policy enforcement (if any)
# never blocks the keys list call below, and we consistently use DefaultAzureCredential.
az cognitiveservices account update \
  --name "$AI_SERVICES_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --set properties.disableLocalAuth=true \
  --output none 2>/dev/null || true

success "Azure AI Services resource created."

# ---------------------------------------------------------------------------
# Retrieve endpoint and key
# ---------------------------------------------------------------------------
info "Retrieving endpoint and checking auth mode..."

ENDPOINT=$(az cognitiveservices account show \
  --name "$AI_SERVICES_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --query "properties.endpoint" \
  -o tsv)

DISABLE_LOCAL_AUTH=$(az cognitiveservices account show \
  --name "$AI_SERVICES_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --query "properties.disableLocalAuth" \
  -o tsv)

API_KEY=""
if [ "$DISABLE_LOCAL_AUTH" = "true" ]; then
  info "Local auth (API keys) is disabled by policy — configuring Entra ID (DefaultAzureCredential) access..."
  USER_OBJECT_ID=$(az ad signed-in-user show --query id -o tsv)
  RESOURCE_ID=$(az cognitiveservices account show \
    --name "$AI_SERVICES_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --query id -o tsv)
  az role assignment create \
    --assignee "$USER_OBJECT_ID" \
    --role "Cognitive Services User" \
    --scope "$RESOURCE_ID" \
    --output none 2>/dev/null || true
  success "Cognitive Services User role assigned to signed-in user."
else
  API_KEY=$(az cognitiveservices account keys list \
    --name "$AI_SERVICES_NAME" \
    --resource-group "$RESOURCE_GROUP" \
    --query "key1" \
    -o tsv)
fi

# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------
echo ""
echo "============================================================"
echo "  Azure AI Services resource provisioned successfully"
echo "============================================================"
echo "  Resource Group : $RESOURCE_GROUP"
echo "  Resource Name  : $AI_SERVICES_NAME"
echo "  Location       : $LOCATION"
echo "  Endpoint       : $ENDPOINT"
if [ -n "$API_KEY" ]; then
  echo "  Auth           : API Key"
  echo ""
  echo "  Export for current shell session:"
  echo "    export AZURE_VOICELIVE_ENDPOINT=\"$ENDPOINT\""
  echo "    export AZURE_VOICELIVE_API_KEY=\"$API_KEY\""
else
  echo "  Auth           : DefaultAzureCredential (Entra ID — run 'az login' before starting app)"
  echo ""
  echo "  Export for current shell session:"
  echo "    export AZURE_VOICELIVE_ENDPOINT=\"$ENDPOINT\""
fi
echo "============================================================"
echo ""

# ---------------------------------------------------------------------------
# Optional: write .env file
# ---------------------------------------------------------------------------
if [ "$WRITE_ENV" = true ]; then
  ENV_FILE="$(dirname "$0")/.env"
  info "Writing to $ENV_FILE..."
  if [ -n "$API_KEY" ]; then
    cat > "$ENV_FILE" <<EOF
AZURE_VOICELIVE_ENDPOINT=$ENDPOINT
AZURE_VOICELIVE_API_KEY=$API_KEY
VOICELIVE_MODEL=gpt-realtime
VOICELIVE_VOICE=en-US-AvaMultilingualNeural
EOF
  else
    cat > "$ENV_FILE" <<EOF
AZURE_VOICELIVE_ENDPOINT=$ENDPOINT
VOICELIVE_MODEL=gpt-realtime
VOICELIVE_VOICE=en-US-AvaMultilingualNeural
EOF
  fi
  success ".env file written to $ENV_FILE"
  echo ""
  echo "  Run the app with:"
  echo "    python app.py"
fi
