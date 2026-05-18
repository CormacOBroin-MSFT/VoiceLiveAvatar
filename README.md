# Instructions to run Microsoft Azure Voice Live with Avatar sample code (Python)

This sample demonstrates the usage of Azure Voice Live API with avatar, implemented in Python. The **Voice Live SDK logic runs entirely on the server side** (Python/FastAPI), while the browser handles UI, audio capture/playback, and avatar video rendering.

## Architecture

```
┌─────────────────────────┐         ┌─────────────────────────┐         ┌──────────────────┐
│    Browser (Frontend)   │◄──WS───►│  Python Server (FastAPI)│◄──SDK──►│ Azure Voice Live │
│                         │         │                         │         │     Service      │
│  • Audio capture (mic)  │         │  • Session management   │         └──────────────────┘
│  • Audio playback       │         │  • Voice Live SDK calls │                  │
│  • Avatar video         │◄──WebRTC (peer-to-peer video)────────────────────────┘
│  • Settings UI          │         │  • Event relay          │
│  • Chat messages        │         │  • Avatar SDP relay     │
└─────────────────────────┘         └─────────────────────────┘
```

**Key design:** The Python backend acts as a bridge between the browser and Azure Voice Live service. All SDK operations (session creation, configuration, audio forwarding, event processing) happen in Python. The browser only handles:
- Microphone capture → sends PCM16 audio via WebSocket
- Audio playback ← receives PCM16 audio via WebSocket  
- WebRTC signaling relay for avatar video (SDP offer/answer exchanged through Python backend)
- Avatar video rendering via direct WebRTC peer connection to Azure
- WebSocket video mode: receives fMP4 video chunks via WebSocket for MediaSource Extensions playback

### Prerequisites

- Python 3.10+
- An active Azure account. If you don't have an Azure account, you can create an account [here](https://azure.microsoft.com/free/ai-services).
- A Microsoft Foundry resource created in one of the supported regions. For more information about region availability, see the [voice live overview documentation](https://learn.microsoft.com/azure/ai-services/speech-service/voice-live).

### Avatar available locations

The avatar feature is currently available in the following service regions: Southeast Asia, North Europe, West Europe, Sweden Central, South Central US, East US 2, and West US 2.

### Setup and run the sample

1. **Install dependencies:**

   ```bash
   pip install -r requirements.txt
   ```

2. **Configure environment and defaults (recommended):**

   Run the interactive setup script. It prompts for your Azure credentials and common conversation defaults, writes `.env`, and seeds `defaults/instructions.txt` / `defaults/priming.json` from their `.example` templates (only if those files don't already exist, so your local edits are never overwritten):

   ```bash
   ./setup.sh
   ```

   You can re-run `./setup.sh` at any time — existing values are shown in brackets and kept by pressing Enter.

   If you prefer to configure manually, copy `.env.example` to `.env` and edit it directly. See the next section for what each value does and what to put inside the long-form default files.

3. **Run the server:**

   ```bash
   python app.py
   ```

   Or with uvicorn directly:

   ```bash
   uvicorn app:app --host 0.0.0.0 --port 3000 --reload
   ```

4. **Open the browser:**

   Navigate to [http://localhost:3000](http://localhost:3000)

### Configuration files

The frontend form is pre-populated on page load from three local files. The backend exposes their values via `GET /api/config` (see `app.py`).

#### `.env`

Short scalar settings and credentials. Tracked template: `.env.example`. Your real `.env` is gitignored.

| Variable | Purpose | Example |
|---|---|---|
| `AZURE_VOICELIVE_ENDPOINT` | Your Azure AI Services endpoint URL. | `https://<name>.cognitiveservices.azure.com/` |
| `AZURE_VOICELIVE_API_KEY` | API key for the resource above. Never commit this. | `abc123…` |
| `VOICELIVE_MODEL` | Default model selected in the UI. | `gpt-realtime` |
| `VOICELIVE_VOICE` | Default voice name. | `en-US-AvaMultilingualNeural` |
| `VOICELIVE_VOICE_SPEED` | Default voice speed (50–150). | `100` |
| `VOICELIVE_AVATAR_ENABLED` | Avatar toggle default. | `true` / `false` |
| `VOICELIVE_ENABLE_PROACTIVE` | "Enable proactive responses" default. | `true` / `false` |
| `VOICELIVE_ENABLE_PRIMING` | "Enable priming context" default. | `true` / `false` |
| `VOICELIVE_INSTRUCTIONS` *(optional)* | Inline override for the instructions file. If set, takes precedence over `defaults/instructions.txt`. | *(usually unset)* |
| `VOICELIVE_PRIMING_MESSAGE` *(optional)* | Inline override for the priming file. If set, takes precedence over `defaults/priming.json`. | *(usually unset)* |

#### `defaults/instructions.txt`  *(your default system prompt)*

The full contents of this file are loaded into the **Model instructions** textarea on page load. This is the system prompt that shapes the assistant's role, tone, task, and constraints. Tracked template: `defaults/instructions.txt.example`. The live file is gitignored.

- **Put inside:** plain-text instructions describing the assistant's role and behaviour — for example, an interviewer persona, a customer-support script, a coaching agent, etc. Markdown formatting is fine (it's just text to the model).
- **When it's used:** sent as `instructions` on `session.update` at the start of every session in `Model` mode.
- **To customise:** open `defaults/instructions.txt` in your editor and replace the placeholder with your own prompt. No restart is needed for new sessions — the file is read fresh on each `/api/config` request, which happens on every page load.

Minimal example:

```
You are a friendly virtual receptionist for Contoso Dental. Greet the caller,
identify yourself, and ask how you can help. Keep replies under 30 words. If
they want to book an appointment, collect their name, preferred date, and
phone number, in that order, one question at a time.
```

#### `defaults/priming.json`  *(your default priming message)*

The full contents of this file are loaded into the **Priming Message** textarea on page load. When **Enable priming context** is on, the contents are injected into the conversation as the **first user-role message** before the assistant's first response, so the model replies as if the user had said this. Tracked template: `defaults/priming.json.example`. The live file is gitignored.

- **Put inside:** anything you want the model to treat as the user's opening turn. Despite the `.json` extension, the file is sent verbatim as a string — structured JSON is just a convenient way to hand the model rich context (a customer record, a student profile, a ticket payload, etc.), but plain text works equally well.
- **When it's used:** only when the **Enable priming context** toggle is on. If both proactive and priming are on, the assistant produces a single response that replies to the priming message.
- **To customise:** open `defaults/priming.json` in your editor and replace the placeholder with your payload.

Minimal example (structured):

```json
{
  "customer": {
    "name": "Jane Doe",
    "accountId": "A-10472",
    "openTickets": [
      { "id": "T-882", "subject": "Cannot log in", "openedDays": 3 }
    ]
  }
}
```

Minimal example (plain text — also valid even though the file ends in `.json`):

```
Pretend the user just said: "Hi, I'm calling because my internet has been
down since yesterday morning and I've already tried restarting the router."
```

> **Tip:** because `defaults/instructions.txt` and `defaults/priming.json` are gitignored, you can keep per-deployment or per-customer prompts locally without polluting the repo. Update the `.example` templates when you want to ship a new default to other clones.


### Build and run with Docker

To run the sample using Docker, navigate to the folder containing this README.md:

```bash
cd ./python/voice-live-avatar/
```

Build the Docker image:

```bash
docker build -t voice-live-avatar-python .
```

Start the container:

```bash
docker run --rm -p 3000:3000 voice-live-avatar-python
```

Then open your web browser and navigate to [http://localhost:3000](http://localhost:3000).

### Configure and play the sample

* Step 1: Under the `Connection Settings` section, fill `Azure AI Services Endpoint` and `Subscription Key`, which can be obtained from the `Keys and Endpoint` tab in your Azure AI Services resource. The endpoint can be the regional endpoint (e.g., `https://<region>.api.cognitive.microsoft.com/`) or a custom domain endpoint (e.g., `https://<custom-domain>.cognitiveservices.azure.com/`).

* Step 2: Under `Conversation Settings` section, configure the avatar:
  - **Enable Avatar**: Toggle the `Avatar` switch to enable the avatar feature.
  - **Avatar Type**: By default, a prebuilt avatar is used. Select a character from the `Avatar Character` dropdown list.
    - To use a **photo avatar**, toggle the `Use Photo Avatar` switch and select a prebuilt photo avatar character from the dropdown list.
    - To use a **custom avatar**, toggle the `Use Custom Avatar` switch and enter the character name in the `Character` field.
  - **Avatar Output Mode**: Choose between `WebRTC` (default, real-time streaming) and `WebSocket` (streams video data over the WebSocket connection).
  - **Avatar Background Image URL** *(optional)*: Enter a URL to set a custom background image for the avatar.
  - **Scene Settings** *(photo avatar only)*: When using a photo avatar, adjust scene parameters such as `Zoom`, `Position X/Y`, `Rotation X/Y/Z`, and `Amplitude`. These settings can also be adjusted live after connecting.

* Step 3: Click `Connect` button to start the conversation. Once connected, you should see the avatar appearing on the page, and you can click `Turn on microphone` and start talking with the avatar with speech.

* Step 4: On top of the page, you can toggle the `Developer mode` switch to enable developer mode, which will show chat history in text and additional logs useful for debugging.

### Deployment

This sample can be deployed to cloud for global access. The recommended hosting platform is [Azure Container Apps](https://learn.microsoft.com/azure/container-apps/overview). Here are the steps to deploy this sample to `Azure Container Apps`:

* Step 1: Push the Docker image to a container registry, such as [Azure Container Registry](https://learn.microsoft.com/azure/container-registry/). You can use the following command to push the image to Azure Container Registry:
  ```bash
  docker tag voice-live-avatar-python <your-registry-name>.azurecr.io/voice-live-avatar-python:latest
  docker push <your-registry-name>.azurecr.io/voice-live-avatar-python:latest
  ```

* Step 2: Create an `Azure Container App` and deploy the Docker image built from above steps, following [Deploy from an existing container image](https://learn.microsoft.com/azure/container-apps/quickstart-portal).

* Step 3: Once the `Azure Container App` is created, you can access the sample by navigating to the URL of the `Azure Container App` in your browser.

## Project Structure

```
voice-live-avatar/
├── app.py                          # FastAPI server, WebSocket endpoint, /api/config, static file serving
├── voice_handler.py                # Voice Live SDK session management, event processing, priming injection
├── setup.sh                        # Interactive setup: writes .env and seeds defaults/ from templates
├── requirements.txt                # Python dependencies
├── Dockerfile                      # Docker container configuration
├── README.md                       # This file
├── .env.example                    # Template for .env (credentials + simple defaults)
├── defaults/
│   ├── instructions.txt.example    # Template for the default system prompt (Model instructions)
│   ├── priming.json.example        # Template for the default priming message
│   ├── instructions.txt            # Your local system prompt (gitignored, seeded by setup.sh)
│   └── priming.json                # Your local priming payload (gitignored, seeded by setup.sh)
└── static/
    ├── index.html                  # Main UI page
    ├── style.css                   # Styles
    └── app.js                      # Client-side JS (audio, WebRTC, WebSocket, UI, /api/config consumer)
```

## WebSocket Protocol

### Frontend → Backend

| Message Type | Description |
|---|---|
| `start_session` | Start Voice Live session with configuration |
| `stop_session` | Stop the active session |
| `audio_chunk` | Send microphone audio (base64 PCM16) |
| `send_text` | Send a text message |
| `avatar_sdp_offer` | Forward WebRTC SDP offer for avatar |
| `interrupt` | Cancel current assistant response |
| `update_scene` | Update photo avatar scene settings (live) |

### Backend → Frontend

| Message Type | Description |
|---|---|
| `session_started` | Session ready |
| `session_error` | Error starting/during session |
| `ice_servers` | ICE server config for avatar WebRTC |
| `avatar_sdp_answer` | Server's SDP answer for avatar WebRTC |
| `audio_data` | Assistant audio (base64 PCM16, 24kHz) |
| `video_data` | Avatar video chunk (base64 fMP4, WebSocket mode) |
| `transcript_delta` | Streaming transcript text |
| `transcript_done` | Completed transcript |
| `text_delta` | Streaming text response |
| `text_done` | Text response completed |
| `response_created` | New response started |
| `response_done` | Response completed |
| `speech_started` | User started speaking (barge-in) |
| `speech_stopped` | User stopped speaking |
| `avatar_connecting` | Avatar WebRTC connection in progress |
| `session_closed` | Session ended |
