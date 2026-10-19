"""JSON-schema definitions of the function tools registered with Vapi.

The descriptions matter: they're what the LLM reads to decide when to call a
tool and how to format its arguments. Validation itself happens server-side
in app/schemas.py.
"""

PATIENT_FIELDS: dict[str, dict] = {
    "first_name": {"type": "string", "description": "Legal first name, spelled as the caller confirmed."},
    "last_name": {"type": "string", "description": "Legal last name, spelled as the caller confirmed."},
    "date_of_birth": {"type": "string", "description": "Date of birth in MM/DD/YYYY format."},
    "sex": {"type": "string", "enum": ["Male", "Female", "Other", "Decline to Answer"]},
    "phone_number": {"type": "string", "description": "10-digit U.S. phone number, digits only, e.g. 5125550101."},
    "email": {"type": "string", "description": "Email address, if provided."},
    "address_line_1": {"type": "string", "description": "Street address, e.g. 100 Congress Ave."},
    "address_line_2": {"type": "string", "description": "Apartment, suite or unit, if any."},
    "city": {"type": "string"},
    "state": {"type": "string", "description": "2-letter U.S. state abbreviation, e.g. TX."},
    "zip_code": {"type": "string", "description": "5-digit ZIP or ZIP+4 (12345-6789)."},
    "insurance_provider": {"type": "string", "description": "Insurance company name, if provided."},
    "insurance_member_id": {"type": "string", "description": "Insurance member/subscriber ID (letters and digits)."},
    "preferred_language": {"type": "string", "description": "Preferred language. Omit to default to English."},
    "emergency_contact_name": {"type": "string", "description": "Emergency contact's full name, if provided."},
    "emergency_contact_phone": {"type": "string", "description": "Emergency contact's 10-digit U.S. phone number."},
}

REQUIRED_FIELDS = [
    "first_name", "last_name", "date_of_birth", "sex", "phone_number",
    "address_line_1", "city", "state", "zip_code",
]


def build_tools(server: dict) -> list[dict]:
    """Return the Vapi `POST /tool` payloads. `server` holds the URL and auth header."""
    return [
        {
            "type": "function",
            "function": {
                "name": "lookup_patient_by_phone",
                "description": (
                    "Check whether a patient with this phone number is already registered. "
                    "Call this as soon as you know the caller's phone number."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {"phone_number": PATIENT_FIELDS["phone_number"]},
                    "required": ["phone_number"],
                },
            },
            "server": server,
        },
        {
            "type": "function",
            "function": {
                "name": "register_patient",
                "description": (
                    "Save a NEW patient record. Only call this after reading all details back "
                    "to the caller and getting a clear confirmation."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        **PATIENT_FIELDS,
                        "allow_duplicate": {
                            "type": "boolean",
                            "description": "Set true only if the caller chose to create a separate record "
                                           "even though their phone number is already registered.",
                        },
                    },
                    "required": REQUIRED_FIELDS,
                },
            },
            "messages": [{"type": "request-start", "content": "Great, let me save that for you."}],
            "server": server,
        },
        {
            "type": "function",
            "function": {
                "name": "update_patient",
                "description": (
                    "Update an EXISTING patient record. Send the patient_id plus only the fields that "
                    "changed. Only call this after the caller confirms the changes."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "patient_id": {"type": "string", "description": "patient_id from lookup_patient_by_phone."},
                        **PATIENT_FIELDS,
                    },
                    "required": ["patient_id"],
                },
            },
            "messages": [{"type": "request-start", "content": "One moment while I update your record."}],
            "server": server,
        },
    ]
