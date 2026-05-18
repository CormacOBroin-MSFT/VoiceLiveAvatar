#!/usr/bin/env bash
# Interactive setup for Voice Live Avatar.
# - Prompts for Azure credentials and common conversation defaults.
# - Writes .env at the project root.
# - Seeds defaults/instructions.txt and defaults/priming.json from the *.example
#   templates if they do not already exist (so personal content stays local).
#
# Re-run safely: existing .env values are shown as defaults and kept on <Enter>.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

ENV_FILE=".env"
DEFAULTS_DIR="defaults"

# --- helpers ---------------------------------------------------------------
get_existing() {
    # Read a key from current .env (if any), echo its value (no surrounding quotes).
    local key="$1"
    [[ -f "$ENV_FILE" ]] || return 0
    local line
    line="$(grep -E "^${key}=" "$ENV_FILE" | tail -n1 || true)"
    [[ -z "$line" ]] && return 0
    local val="${line#*=}"
    # strip optional surrounding double quotes
    val="${val%\"}"
    val="${val#\"}"
    printf '%s' "$val"
}

prompt() {
    # prompt VAR_NAME "Question text" "fallback default"
    local var="$1" question="$2" fallback="${3:-}"
    local current
    current="$(get_existing "$var")"
    local default="${current:-$fallback}"
    local answer
    if [[ -n "$default" ]]; then
        read -r -p "${question} [${default}]: " answer || true
    else
        read -r -p "${question}: " answer || true
    fi
    printf -v "$var" '%s' "${answer:-$default}"
}

prompt_secret() {
    local var="$1" question="$2"
    local current
    current="$(get_existing "$var")"
    local display
    if [[ -n "$current" ]]; then
        display="${current:0:4}…(keep existing, press Enter)"
    else
        display=""
    fi
    local answer
    if [[ -n "$display" ]]; then
        read -r -s -p "${question} [${display}]: " answer || true
    else
        read -r -s -p "${question}: " answer || true
    fi
    echo
    printf -v "$var" '%s' "${answer:-$current}"
}

prompt_bool() {
    local var="$1" question="$2" fallback="$3"
    local current
    current="$(get_existing "$var")"
    local default="${current:-$fallback}"
    local answer
    read -r -p "${question} (true/false) [${default}]: " answer || true
    answer="${answer:-$default}"
    case "${answer,,}" in
        1|true|yes|y|on)   answer="true"  ;;
        0|false|no|n|off)  answer="false" ;;
        *) echo "  ! '${answer}' is not a boolean, using '${default}'."; answer="$default" ;;
    esac
    printf -v "$var" '%s' "$answer"
}

# --- collect values --------------------------------------------------------
echo "=== Voice Live Avatar setup ==="
echo "Press Enter to accept the value shown in [brackets]."
echo

prompt        AZURE_VOICELIVE_ENDPOINT  "Azure AI Services endpoint URL"  ""
prompt_secret AZURE_VOICELIVE_API_KEY   "Azure AI Services API key (input hidden)"

prompt        VOICELIVE_MODEL          "Default model"                 "gpt-realtime"
prompt        VOICELIVE_VOICE          "Default voice"                 "en-US-AvaMultilingualNeural"
prompt        VOICELIVE_VOICE_SPEED    "Default voice speed (50-150)"  "100"

prompt_bool   VOICELIVE_AVATAR_ENABLED   "Enable avatar by default"             "true"
prompt_bool   VOICELIVE_ENABLE_PROACTIVE "Enable proactive responses by default" "true"
prompt_bool   VOICELIVE_ENABLE_PRIMING   "Enable priming context by default"     "false"

# --- write .env ------------------------------------------------------------
TMP_ENV="$(mktemp)"
cat >"$TMP_ENV" <<EOF
AZURE_VOICELIVE_ENDPOINT=${AZURE_VOICELIVE_ENDPOINT}
AZURE_VOICELIVE_API_KEY=${AZURE_VOICELIVE_API_KEY}
VOICELIVE_MODEL=${VOICELIVE_MODEL}
VOICELIVE_VOICE=${VOICELIVE_VOICE}
VOICELIVE_VOICE_SPEED=${VOICELIVE_VOICE_SPEED}
VOICELIVE_AVATAR_ENABLED=${VOICELIVE_AVATAR_ENABLED}
VOICELIVE_ENABLE_PROACTIVE=${VOICELIVE_ENABLE_PROACTIVE}
VOICELIVE_ENABLE_PRIMING=${VOICELIVE_ENABLE_PRIMING}
# Long-form defaults are loaded from defaults/instructions.txt and defaults/priming.json
EOF
mv "$TMP_ENV" "$ENV_FILE"
chmod 600 "$ENV_FILE" || true
echo "Wrote ${ENV_FILE}"

# --- seed defaults/ from templates ----------------------------------------
seed_from_template() {
    local target="$1" template="$2"
    if [[ -s "$target" ]]; then
        echo "  - ${target} already exists, leaving untouched."
        return
    fi
    if [[ ! -f "$template" ]]; then
        echo "  ! ${template} missing, skipping."
        return
    fi
    cp "$template" "$target"
    echo "  + ${target} seeded from ${template}"
}

mkdir -p "$DEFAULTS_DIR"
echo "Seeding default content files (only if empty/missing):"
seed_from_template "${DEFAULTS_DIR}/instructions.txt" "${DEFAULTS_DIR}/instructions.txt.example"
seed_from_template "${DEFAULTS_DIR}/priming.json"     "${DEFAULTS_DIR}/priming.json.example"

echo
echo "Setup complete."
echo "Next steps:"
echo "  pip install -r requirements.txt"
echo "  python app.py"
