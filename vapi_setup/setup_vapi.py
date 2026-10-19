"""Create or update the Vapi tools + assistant and attach them to the phone number.

Usage (after the API is deployed):

    python -m vapi_setup.setup_vapi

Reads from the environment (or .env):
    VAPI_API_KEY          Vapi private API key (Dashboard -> Org -> API Keys)
    PUBLIC_BASE_URL       Public URL of the deployed API, e.g. https://xxx.up.railway.app
    VAPI_CREDENTIAL_ID    ID of a dashboard Custom Credential (Bearer, header X-Vapi-Secret,
                          no prefix) whose token equals the API's VAPI_SECRET
    VAPI_PHONE_NUMBER_ID  Optional: ID of the Vapi phone number to attach the assistant to
    VAPI_VOICE_ID         Optional: Vapi voice (default "Elliot")

Safe to re-run: tools and the assistant are matched by name and updated in place.
"""

import os
import sys

import httpx
from dotenv import load_dotenv

from vapi_setup.prompt import FIRST_MESSAGE, SYSTEM_PROMPT
from vapi_setup.tools import build_tools

VAPI_API = "https://api.vapi.ai"
ASSISTANT_NAME = "Riley - Patient Registration"


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        sys.exit(f"Missing required environment variable: {name}")
    return value


def _check(resp: httpx.Response, action: str) -> dict:
    if resp.is_error:
        sys.exit(f"{action} failed ({resp.status_code}): {resp.text}")
    return resp.json()


def _server(url: str, credential_id: str) -> dict:
    # The credential (created once in the dashboard) makes Vapi send our
    # VAPI_SECRET in the X-Vapi-Secret header on every request to `url`.
    server = {"url": url, "timeoutSeconds": 20}
    if credential_id:
        server["credentialId"] = credential_id
    return server


def build_assistant(tool_ids: list[str], base_url: str, credential_id: str) -> dict:
    return {
        "name": ASSISTANT_NAME,
        "firstMessage": FIRST_MESSAGE,
        "model": {
            "provider": "openai",
            "model": "gpt-4o",
            "temperature": 0.3,  # low: consistent, careful data capture
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}],
            "toolIds": tool_ids,
            "tools": [{"type": "endCall"}],  # built-in hang-up tool
        },
        "voice": {"provider": "vapi", "voiceId": os.getenv("VAPI_VOICE_ID", "Elliot")},
        "transcriber": {"provider": "deepgram", "model": "nova-3", "language": "en"},
        # Assistant-level webhook: call status + end-of-call report (transcript) for logging.
        "server": _server(f"{base_url}/vapi/webhook", credential_id),
        "serverMessages": ["status-update", "end-of-call-report"],
        "silenceTimeoutSeconds": 30,
        "maxDurationSeconds": 900,
    }


def main() -> None:
    load_dotenv()
    api_key = _require("VAPI_API_KEY")
    base_url = _require("PUBLIC_BASE_URL").rstrip("/")
    credential_id = os.getenv("VAPI_CREDENTIAL_ID", "").strip()
    phone_number_id = os.getenv("VAPI_PHONE_NUMBER_ID", "").strip()
    if not credential_id:
        print("WARNING: VAPI_CREDENTIAL_ID not set. Vapi will call the API without X-Vapi-Secret, "
              "so leave VAPI_SECRET empty on the server or requests will get 401.")

    headers = {"Authorization": f"Bearer {api_key}"}
    with httpx.Client(base_url=VAPI_API, headers=headers, timeout=30) as client:
        # 1. Function tools -> all point at our single /vapi/tools endpoint.
        existing_tools = {
            t.get("function", {}).get("name"): t["id"]
            for t in _check(client.get("/tool", params={"limit": 1000}), "List tools")
            if t.get("type") == "function"
        }
        tool_ids = []
        for tool in build_tools(_server(f"{base_url}/vapi/tools", credential_id)):
            name = tool["function"]["name"]
            if name in existing_tools:
                update = {k: v for k, v in tool.items() if k != "type"}
                saved = _check(client.patch(f"/tool/{existing_tools[name]}", json=update), f"Update tool {name}")
                print(f"Updated tool   {name:<26} {saved['id']}")
            else:
                saved = _check(client.post("/tool", json=tool), f"Create tool {name}")
                print(f"Created tool   {name:<26} {saved['id']}")
            tool_ids.append(saved["id"])

        # 2. Assistant (prompt, model, voice, transcriber, tools, webhook).
        assistant = build_assistant(tool_ids, base_url, credential_id)
        existing = next(
            (a for a in _check(client.get("/assistant", params={"limit": 1000}), "List assistants")
             if a.get("name") == ASSISTANT_NAME),
            None,
        )
        if existing:
            saved = _check(client.patch(f"/assistant/{existing['id']}", json=assistant), "Update assistant")
            print(f"Updated assistant {saved['id']}")
        else:
            saved = _check(client.post("/assistant", json=assistant), "Create assistant")
            print(f"Created assistant {saved['id']}")
        assistant_id = saved["id"]

        # 3. Route inbound calls on the phone number to the assistant.
        if phone_number_id:
            number = _check(
                client.patch(f"/phone-number/{phone_number_id}", json={"assistantId": assistant_id}),
                "Attach phone number",
            )
            print(f"Phone number {number.get('number', phone_number_id)} now routes to the assistant")
        else:
            print("VAPI_PHONE_NUMBER_ID not set: attach the assistant to your number in the dashboard.")


if __name__ == "__main__":
    main()
