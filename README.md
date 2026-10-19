# Voice AI Patient Registration Agent

Call a US phone number, talk to **Riley**, an AI intake coordinator, and get registered as a new patient. The agent collects U.S. demographic details in a natural conversation, reads them back for confirmation, and saves them to PostgreSQL through a FastAPI service. Records can be viewed through a REST API and a live dashboard. If you call again with the same phone number, it recognizes you and offers to update your record.

## Live demo

| | |
|---|---|
| 📞 **Phone number** | `+1 (XXX) XXX-XXXX` ← *fill in after provisioning* |
| 🌐 **API base URL** | `https://<your-app>.up.railway.app` |
| 📊 **Dashboard** | `https://<your-app>.up.railway.app/dashboard` |
| 📘 **Interactive API docs** | `https://<your-app>.up.railway.app/docs` |

The REST API needs no credentials. Two demo patients are seeded: Jane Doe `512-555-0101` and John Smith `312-555-0199`. If you say one of those numbers on a call, you'll hear the returning-patient flow.

---

## Architecture

```
 Caller ──PSTN──▶ Vapi  (phone number · Deepgram STT · GPT-4o · TTS · system prompt)
                   │
                   │ HTTPS POST (header X-Vapi-Secret) when the LLM calls a tool
                   ▼
 ┌──────────────────────── FastAPI on Railway ─────────────────────────┐
 │  /vapi/tools    → routers/vapi.py  → agent_tools.py ─┐                │
 │  /vapi/webhook  → call status + end-of-call report → logs (stdout)   │
 │  /patients      → routers/patients.py ──────────────┼─▶ services.py ──▶ PostgreSQL
 │  /dashboard     → static/dashboard.html (calls /patients)             │
 └──────────────────────────────────────────────────────────────────────┘
```

**Separation of concerns:**

| Layer | Where | Responsibility |
|---|---|---|
| Telephony, STT, TTS, turn-taking | Vapi (managed) | Phone number, speech, interruptions (barge-in) |
| Conversation logic | [`vapi_setup/prompt.py`](vapi_setup/prompt.py), [`vapi_setup/tools.py`](vapi_setup/tools.py) | Commented system prompt and tool schemas |
| Vapi protocol adapter | [`app/routers/vapi.py`](app/routers/vapi.py) | Parses `tool-calls`, always returns HTTP 200 + `results[]`, checks secret |
| Tool business logic | [`app/agent_tools.py`](app/agent_tools.py) | Lookup, register and update. Returns status-keyword strings for the LLM |
| REST API | [`app/routers/patients.py`](app/routers/patients.py) | CRUD endpoints, JSON envelope |
| Validation (single source of truth) | [`app/schemas.py`](app/schemas.py) | Pydantic models shared by the API **and** the voice tools |
| Data access | [`app/services.py`](app/services.py) | The only code that touches the DB. Soft delete, duplicate lookup |
| Schema | [`app/models.py`](app/models.py) | SQLAlchemy model, types, CHECK constraints, indexes |

The voice agent and the REST API run through the **same service layer and validators**, so a voice call can never store data the API would reject.

## Tech stack and why

| Choice | Why |
|---|---|
| **Vapi** | Handles the phone number, STT, TTS, barge-in and tool calling in one platform. That leaves time for the prompt, backend and error handling instead of audio plumbing. |
| **GPT-4o** (via Vapi) | Reliable at function calling and good at extracting structured fields from messy speech. Temperature 0.3 keeps data capture consistent. |
| **Deepgram nova-3** | Fast and accurate phone-audio transcription, which matters for names and numbers. |
| **FastAPI + Pydantic v2** | Typed validation, automatic OpenAPI docs at `/docs`, little boilerplate. |
| **PostgreSQL** (Railway plugin) | Real constraints, native UUID, ENUM and `timestamptz` types, and it survives restarts. Locally the app falls back to SQLite with no setup. |
| **SQLAlchemy 2** | The same models work on Postgres (prod) and SQLite (local). |
| **Railway** | Deploys from GitHub, Postgres in one click, and the service **never sleeps**. Free tiers that sleep would make the first tool call of a call time out. |

---

## Data model

`patients` table: `patient_id` (UUID PK), `first_name`/`last_name` (varchar 50), `date_of_birth` (date), `sex` (enum `Male | Female | Other | Decline to Answer`), `phone_number` (char 10, indexed), `email`, `address_line_1/2`, `city`, `state` (2), `zip_code` (5 or 10), `insurance_provider`, `insurance_member_id`, `preferred_language` (default `English`), `emergency_contact_name/phone`, plus `created_at`, `updated_at` and `deleted_at` (all `timestamptz`, UTC).

**Validation rules** in [`app/schemas.py`](app/schemas.py) accept spoken-style input and normalize it:

| Field | Accepts → stores |
|---|---|
| Names | letters, hyphens, apostrophes, spaces; 1–50 chars (`O'Neil-Davis` ✔) |
| Date of birth | `7/4/1990`, `07-04-1990`, `1990-07-04` → returned as `07/04/1990`; rejects future dates and dates over 120 years ago |
| Phone | `+1 (415) 555-0123` → `4155550123`; must be 10 digits, area code can't start with 0/1 |
| State | `California`, `ca`, `CA` → `CA` (50 states + DC + territories) |
| ZIP | `94105`, `94105-1234`, `941051234` → `94105-1234` |
| Sex | `f`, `female`, `woman`, `prefer not to say` → enum value |
| Member ID | `abc-123 45` → `ABC12345` (alphanumeric) |
| Email | RFC-valid email |

The database adds `CHECK` constraints on top (length of phone, state, ZIP and names) as defence in depth.

---

## REST API

All responses use one envelope: `{"data": ..., "error": null}` or `{"data": null, "error": {"code", "message", "details"}}`.

| Method | Endpoint | Notes | Status codes |
|---|---|---|---|
| GET | `/patients` | Optional filters `?last_name=` (case-insensitive), `?date_of_birth=`, `?phone_number=` (any format). Soft-deleted records are excluded. | 200, 400 |
| GET | `/patients/{id}` | | 200, 400 (bad UUID), 404 |
| POST | `/patients` | Returns the created record with `patient_id` | 201, 422 |
| PUT | `/patients/{id}` | Partial update: only the fields you send change | 200, 400, 404, 422 |
| DELETE | `/patients/{id}` | **Soft delete**: sets `deleted_at` | 200, 404 |
| GET | `/health` | Checks the DB connection (used by Railway's healthcheck) | 200, 503 |
| GET | `/dashboard` | Live patient table (bonus) | 200 |

Errors in the request body return 422. Malformed path or query values return 400. DB failures return 500.

```bash
BASE=https://<your-app>.up.railway.app

curl "$BASE/patients?last_name=doe"

curl -X POST "$BASE/patients" -H "Content-Type: application/json" -d '{
  "first_name":"Maria","last_name":"Davis","date_of_birth":"07/04/1990","sex":"Female",
  "phone_number":"(415) 555-0123","address_line_1":"1 Market St","city":"San Francisco",
  "state":"CA","zip_code":"94105"}'

curl -X PUT "$BASE/patients/<patient_id>" -H "Content-Type: application/json" -d '{"city":"Oakland"}'

curl -X DELETE "$BASE/patients/<patient_id>"
```

---

## How the Vapi tools connect to the API

A Vapi **function tool** is a JSON schema the LLM can "call", together with a **Server URL**. When GPT-4o decides to call a tool during the call, Vapi sends a POST to that URL:

```json
{ "message": { "type": "tool-calls", "call": { "id": "..." },
    "toolCallList": [ { "id": "call_abc", "type": "function",
        "function": { "name": "register_patient", "arguments": { "first_name": "Maria", "...": "..." } } } ] } }
```

Our endpoint `POST /vapi/tools` validates and saves the data, then replies with **HTTP 200**:

```json
{ "results": [ { "toolCallId": "call_abc", "result": "SUCCESS: Patient registered ... You're all set, Maria." } ] }
```

Vapi gives the `result` string back to the LLM, and the LLM speaks to the caller based on it. Any non-200 status would make the agent say "no result", so errors always come back **inside** `result`:

| Tool | Result keywords |
|---|---|
| `lookup_patient_by_phone(phone_number)` | `FOUND` (with patient_id + name), `NOT_FOUND`, `VALIDATION_ERROR` |
| `register_patient(...all fields, allow_duplicate?)` | `SUCCESS`, `VALIDATION_ERROR` (lists each bad field and why), `DUPLICATE_FOUND`, `SAVE_FAILED` |
| `update_patient(patient_id, ...changed fields)` | `SUCCESS`, `VALIDATION_ERROR`, `NOT_FOUND`, `SAVE_FAILED` |
| `endCall` (Vapi built-in) | Hangs up after the goodbye |

All three function tools point at the same Server URL, and the backend dispatches by `function.name`. The assistant also has a **server URL** `/vapi/webhook` that receives `status-update` and `end-of-call-report` (the transcript and the ended reason), which are logged.

**Auth:** Vapi sends the header `X-Vapi-Secret: <VAPI_SECRET>` through a dashboard **Custom Credential**, and the API rejects requests without it (401).

---

## Setup

### Environment variables

| Variable | Where | Required | Purpose |
|---|---|---|---|
| `DATABASE_URL` | API | prod | Postgres URL (Railway injects it). Unset means local SQLite `./patients.db` |
| `VAPI_SECRET` | API | recommended | Expected `X-Vapi-Secret` value. Empty disables the check |
| `LOG_LEVEL` | API | no | Default `INFO` |
| `SEED_DEMO_DATA` | API | no | Default `true`: seeds 2 demo patients into an empty table |
| `VAPI_API_KEY` | setup script | yes | Vapi **private** API key |
| `PUBLIC_BASE_URL` | setup script | yes | The deployed API URL |
| `VAPI_CREDENTIAL_ID` | setup script | recommended | ID of the Custom Credential that sends `X-Vapi-Secret` |
| `VAPI_PHONE_NUMBER_ID` | setup script | no | Attach the assistant to this number automatically |
| `VAPI_VOICE_ID` | setup script | no | Vapi voice, default `Elliot` |

Copy `.env.example` to `.env` for local use. No secrets are in the source code.

### 1. Run locally

```bash
# with the existing .venv activated
pip install -r requirements.txt        # or: uv sync
uvicorn app.main:app --reload
# → http://127.0.0.1:8000/docs  and  http://127.0.0.1:8000/dashboard
```

To test with real calls against your local server, expose it with `ngrok http 8000` and use the ngrok URL as `PUBLIC_BASE_URL`.

### 2. Deploy to Railway

1. Push this repo to GitHub.
2. In Railway, go to **New Project → Deploy from GitHub repo** and select the repo.
3. In the project, add the database: **+ New → Database → PostgreSQL**. Then in the web service, go to **Variables → Add Reference → `DATABASE_URL`** from Postgres.
4. Add the `VAPI_SECRET` variable (any long random string).
5. In the web service, go to **Settings → Networking → Generate Domain**. That URL is your API base URL.
6. Check that `https://<domain>/health` returns `{"data":{"status":"ok",...}}`.

[`railway.json`](railway.json) sets the start command (`uvicorn app.main:app --host 0.0.0.0 --port $PORT`) and the `/health` healthcheck. Tables are created on startup.

### 3. Configure Vapi

1. **Phone number:** in the [Vapi dashboard](https://dashboard.vapi.ai), go to **Phone Numbers → Create Phone Number → Free Vapi Number**, pick a US area code, and copy the number's **ID**.
2. **Credential:** go to **Integrations → Server Configuration → Add Custom Credential**. Choose **Bearer Token**, set Token = your `VAPI_SECRET`, Header Name = `X-Vapi-Secret`, and turn **Include Bearer Prefix** OFF. Save it and copy the credential **ID**.
3. **Create the tools and assistant, then attach the number:**
   ```bash
   # .env: VAPI_API_KEY, PUBLIC_BASE_URL, VAPI_CREDENTIAL_ID, VAPI_PHONE_NUMBER_ID
   python -m vapi_setup.setup_vapi
   ```
   The script is idempotent: re-run it after editing the prompt and it updates the existing tools and assistant in place.
4. Call the number.

<details>
<summary>Manual alternative (dashboard only, no script)</summary>

1. **Tools → Create Tool → Function** for each of `lookup_patient_by_phone`, `register_patient` and `update_patient`. Copy the parameter schema from [`vapi_setup/tools.py`](vapi_setup/tools.py). Set Server URL = `https://<domain>/vapi/tools` and pick your credential.
2. **Assistants → Create**:
   - Paste `SYSTEM_PROMPT` and `FIRST_MESSAGE` from [`vapi_setup/prompt.py`](vapi_setup/prompt.py). Print them with `python -c "from vapi_setup.prompt import SYSTEM_PROMPT; print(SYSTEM_PROMPT)"`.
   - Model: OpenAI gpt-4o, temperature 0.3.
   - Transcriber: Deepgram nova-3.
   - Tools tab: add the 3 tools and enable **End Call**.
   - Advanced: Server URL `https://<domain>/vapi/webhook`, with server messages `status-update` and `end-of-call-report`.
3. **Phone Numbers → your number → Inbound assistant →** select the assistant.
</details>

---

## Prompt engineering

The full prompt is in [`vapi_setup/prompt.py`](vapi_setup/prompt.py). It is split into sections, and each section has a comment explaining why it exists:

- **A persona with a concrete job:** "Riley at Sunrise Health Clinic" sounds like a front-desk person, not a phone menu.
- **Voice-first style rules:** one or two sentences per turn, one question at a time, no lists or markdown, dates said naturally, numbers read in groups, spelling only when confirming.
- **A checklist, not a script:** out-of-order and multi-field answers are captured, and nothing is asked twice. A full address given in one go is split into its parts automatically.
- **Caller ID:** `{{customer.number}}` lets the agent ask "is the number you're calling from the best one?" instead of dictating 10 digits.
- **Two layers of validation:** the LLM catches obvious problems right away (a future DOB, a wrong number of digits) and re-asks only that field. The server re-validates everything and returns field-specific `VALIDATION_ERROR`s, which the prompt says to turn into targeted re-prompts.
- **Corrections, interruptions and starting over:** the latest value always wins. "Start over" clears the collected data. Vapi's barge-in handles interruptions.
- **A hard confirmation gate:** the agent reads back everything, with the last name and email spelled out, and saves only after a clear "yes".
- **Each result keyword maps to a spoken behaviour:** this is why a DB failure becomes an honest apology plus one retry, never silence and never a false "you're all set".
- **A privacy guardrail for returning callers:** the agent says the name on file only (as the spec asks). It verifies the date of birth before revealing or changing anything.

## Edge cases and resilience

| Scenario | Behavior |
|---|---|
| Invalid DOB (future or impossible date) | The agent re-asks for that field. If it slips through, the server returns `VALIDATION_ERROR: date_of_birth (cannot be in the future)` |
| 3-digit phone number, bad ZIP or state | Same as above, with a field-specific message |
| Caller corrects a field | The latest value replaces the old one, and the read-back confirms it |
| Caller wants to start over | The agent clears its data and restarts from the name |
| DB write fails | The tool returns `SAVE_FAILED`. The agent apologizes, retries once, then says honestly that nothing was saved. The REST API returns 500 with the envelope |
| Unexpected exception in a tool | Caught, logged with a stack trace, returned as `SAVE_FAILED`. Never silence |
| Call drops mid-conversation | Nothing is written until the caller confirms, so there are no partial records. The `end-of-call-report` with `endedReason` and the transcript is logged |
| Returning caller (same phone) | `lookup_patient_by_phone` finds them, the agent offers to update, verifies DOB, then calls `update_patient` |
| Family member sharing a phone | The caller declines the update, and the agent registers a new record with `allow_duplicate=true` |
| Server restart or redeploy | Data lives in Railway Postgres. The seed only runs on an empty table |
| Spoofed tool calls | `X-Vapi-Secret` is checked (401 otherwise) |

## Observability

Logs go to stdout, which you can see in Railway → Deployments → Logs:
- `tool_call` / `tool_result`: every tool invocation with its arguments and outcome, keyed by Vapi `call_id`.
- `patient_registered` / `patient_updated`: the **final saved payload** as JSON.
- `call_status` and `call_ended`: ended reason, summary and the full transcript.

## Known limitations and trade-offs

- **`create_all` instead of migrations:** fine for a single-table take-home. Alembic would be needed before any schema change in production.
- **No auth on the REST API or dashboard:** intentional for reviewer access. Production would need API keys or OAuth and role-based access.
- **Not HIPAA-compliant:** PII is logged to stdout (as the spec asks for observability), with no encryption at rest beyond the provider's and no BAA with vendors. **Use only fake data.**
- **Duplicate detection is by phone number only:** a shared family phone is handled with `allow_duplicate`, but there's no fuzzy matching on name and DOB.
- **The agent's in-call state lives in the LLM context:** there's no server-side draft, so a dropped call means starting over (deliberate: no partial records).
- **Phone validation is NANP-shaped** (10 digits, area code 2–9). It doesn't check against real number assignments.
- **English only:** the transcriber is set to `en`. Spanish would need `language: "multi"` and a prompt rule.
- **`DELETE` is soft:** deleted records are hidden from the API but stay in the table (by design).

## Next steps

1. Automated tests (pytest + TestClient) for the validators, the endpoints and the Vapi tool contract, run in CI.
2. Store the call transcript and summary in a `call_logs` table linked to `patient_id`, and show them on the dashboard.
3. Spanish support (Deepgram `multi` plus a "switch language when the caller does" rule).
4. Offer a first appointment after registration (mock availability tool).
5. Alembic migrations, API-key auth for the REST API, and redacting PII in logs.
6. Vapi test suites and evals: scripted callers for corrections, invalid DOB and start-over, run on every prompt change.

## Project structure

```
app/
  main.py            FastAPI app, error envelope handlers, /health, /dashboard
  config.py          Env-based settings
  database.py        Engine/session (Postgres in prod, SQLite locally)
  models.py          Patient ORM model + constraints
  schemas.py         Pydantic validation shared by API and voice tools
  services.py        DB operations (CRUD, soft delete, phone lookup, seed)
  agent_tools.py     Voice tool handlers → status-keyword strings
  responses.py       JSON envelope helpers
  routers/patients.py  REST endpoints
  routers/vapi.py      Vapi tool-calls + webhook adapter
  static/dashboard.html
vapi_setup/
  prompt.py          Commented system prompt + first message
  tools.py           Tool JSON schemas
  setup_vapi.py      Creates/updates tools + assistant, attaches the number
railway.json         Railway start command + healthcheck
requirements.txt
.env.example
```
