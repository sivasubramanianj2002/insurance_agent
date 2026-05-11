import os
import json
import re
from huggingface_hub import InferenceClient
from dotenv import load_dotenv

load_dotenv()
HF_TOKEN = os.getenv("HF_TOKEN")
HF_TIMEOUT_SECONDS = int(os.getenv("HF_TIMEOUT_SECONDS", "60"))
HF_MODEL = os.getenv("HF_MODEL", "Qwen/Qwen2.5-VL-7B-Instruct")
HF_FALLBACK_MODELS = [
    model.strip()
    for model in os.getenv(
        "HF_FALLBACK_MODELS",
        "meta-llama/Llama-3.1-8B-Instruct,mistralai/Mistral-7B-Instruct-v0.3,Qwen/Qwen2.5-7B-Instruct"
    ).split(",")
    if model.strip()
]
client = InferenceClient(token=HF_TOKEN, timeout=HF_TIMEOUT_SECONDS)


EXPECTED_KEYS = [
    "policy_number",
    "policyholder_name",
    "policy_effective_date",
    "policy_expiry_date",
    "incident_date",
    "incident_time",
    "incident_location",
    "incident_description",
    "claimant_name",
    "third_parties",
    "contact_details",
    "asset_type",
    "asset_id",
    "estimated_damage",
    "claim_type",
    "attachments",
    "initial_estimate",
]


def _empty_schema() -> dict:
    return {
        "policy_number": "",
        "policyholder_name": "",
        "policy_effective_date": "",
        "policy_expiry_date": "",
        "incident_date": "",
        "incident_time": "",
        "incident_location": "",
        "incident_description": "",
        "claimant_name": "",
        "third_parties": [],
        "contact_details": "",
        "asset_type": "",
        "asset_id": "",
        "estimated_damage": None,
        "claim_type": "",
        "attachments": [],
        "initial_estimate": None,
    }


def _cleanup(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "")).strip(" -:\n\t")


def _first_group(text: str, patterns: list) -> str:
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE | re.DOTALL)
        if match:
            return _cleanup(match.group(1))
    return ""


def _parse_amount(raw: str):
    cleaned = re.sub(r"[^\d.]", "", raw or "")
    if not cleaned:
        return None
    try:
        return int(float(cleaned))
    except ValueError:
        return None


def _normalize_numeric(value):
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    return _parse_amount(str(value))


def _rule_based_extract(fnol_text: str) -> dict:
    extracted = _empty_schema()

    # ── Policy number ─────────────────────────────────────────────────────────
    # Handles label and value on same line OR on separate lines (pdfplumber layout mode)
    policy_number = _first_group(fnol_text, [
        r"POLICY NUMBER[:\s]+([A-Z]{2,}[A-Z0-9\-\/]+)",          # same line
        r"POLICY NUMBER\s*[\n\r]+\s*([A-Z]{2,}[A-Z0-9\-\/]+)",   # next line
        r"POLICY NUMBER\s+([A-Z0-9\-\/]+)",
        r"Policy Number[:\s]+([A-Z0-9\-\/]+)",
    ])
    if policy_number:
        extracted["policy_number"] = policy_number

    # ── Policyholder name ─────────────────────────────────────────────────────
    policyholder_name = _first_group(fnol_text, [
        r"NAME OF INSURED[^\n]*\n\s*([A-Za-z][A-Za-z\s\.\-']{2,})",
        r"INSURED\s+NAME[:\s]+([A-Za-z][A-Za-z\s\.\-']{2,})",
    ])
    if policyholder_name:
        extracted["policyholder_name"] = policyholder_name

    # ── Policy dates ──────────────────────────────────────────────────────────
    extracted["policy_effective_date"] = _first_group(fnol_text, [
        # Some PDFs expose this top date input as a generic AcroForm field name.
        # Keep this first so user-entered form value wins when multiple dates exist.
        r"Text1[:\s]+([0-9]{2}\/[0-9]{2}\/[0-9]{4})",
        # ACORD header date field (label + value in same or next line)
        r"(?:AUTOMOBILE LOSS NOTICE\s+)?DATE \(MM\/DD\/YYYY\)[:\s]*([0-9]{2}\/[0-9]{2}\/[0-9]{4})",
        r"(?:AUTOMOBILE LOSS NOTICE\s+)?DATE \(MM\/DD\/YYYY\)\s*[\r\n]+\s*([0-9]{2}\/[0-9]{2}\/[0-9]{4})",
        r"EFFECTIVE DATE[:\s]+([0-9]{2}\/[0-9]{2}\/[0-9]{4})",
    ])

    # ── Incident date / time ──────────────────────────────────────────────────
    extracted["incident_date"] = _first_group(fnol_text, [
        r"DATE OF LOSS[^\n]*?(\d{2}\/\d{2}\/\d{4})",
        r"DATE OF LOSS AND TIME\s+(\d{2}\/\d{2}\/\d{4})",
    ])
    extracted["incident_time"] = _first_group(fnol_text, [
        r"DATE OF LOSS AND TIME\s+(?:\d{2}\/\d{2}\/\d{4}\s+)?([0-9]{1,2}:[0-9]{2}\s*(?:AM|PM))",
        r"\b(\d{1,2}:\d{2}\s*(?:AM|PM))\b",
    ])

    # ── Location ──────────────────────────────────────────────────────────────
    street = _first_group(fnol_text, [r"STREET:\s*([^\n]+)"])
    city   = _first_group(fnol_text, [r"CITY,\s*STATE,\s*ZIP:\s*([^\n]+)"])
    country = _first_group(fnol_text, [r"COUNTRY:\s*([^\n]+)"])
    location = ", ".join([part for part in [street, city, country] if part])
    if location:
        extracted["incident_location"] = location

    # ── Incident description — FIX: use [\s\S] to capture multiple lines ─────
    extracted["incident_description"] = _first_group(fnol_text, [
        # Between the description header and the next major section header
        r"DESCRIPTION OF ACCIDENT[^\n]*\n([\s\S]+?)\n(?:INSURED VEHICLE|INJURED|WITNESSES)",
        # Fallback: grab everything after the header (up to ~500 chars)
        r"DESCRIPTION OF ACCIDENT[^\n]*\n([\s\S]{10,500})",
    ])

    # ── Claimant name ─────────────────────────────────────────────────────────
    extracted["claimant_name"] = _first_group(fnol_text, [
        r"NAME OF CONTACT[^\n]*\n\s*([A-Za-z][A-Za-z\s\.\-']{2,})",
        r"Name:\s*([A-Za-z][A-Za-z\s\.\-']{2,})\s+Address:",
    ])

    # ── Contact details ───────────────────────────────────────────────────────
    phone = _first_group(fnol_text, [r"\b(\d{10})\b", r"\b(\d{3}[-.\s]\d{3}[-.\s]\d{4})\b"])
    email = _first_group(fnol_text, [r"\b([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})\b"])
    if phone or email:
        extracted["contact_details"] = ", ".join([part for part in [phone, email] if part])

    # ── Asset type — FIX: also check BODY TYPE field ──────────────────────────
    extracted["asset_type"] = _first_group(fnol_text, [
        r"BODY\s*TYPE[:\s\/]*([A-Za-z][A-Za-z\s\-]{1,30}?)(?:\s{2,}|\t|$)",
        r"TYPE:\s*([A-Za-z][A-Za-z\s\-]{1,30})\s+PLATE NUMBER",
        r"ASSET TYPE[:\s]+([A-Za-z][A-Za-z\s\-]{1,30})",
    ])

    # ── Asset ID (VIN / plate) ────────────────────────────────────────────────
    extracted["asset_id"] = _first_group(fnol_text, [
        r"V\.I\.N\.:\s*([A-Za-z0-9\-]{5,})",
        r"PLATE NUMBER\s+STATE\s*\n?([A-Za-z0-9\-]+)",
        r"DRIVER'S LICENSE NUMBER\s+STATE[^\n]*\n[^\n]*?([A-Za-z0-9\-]{6,})",
    ])

    # ── Estimated damage ──────────────────────────────────────────────────────
    damage_str = _first_group(fnol_text, [
        r"ESTIMATE AMOUNT[:\s]*\$?\s*([0-9,]+(?:\.\d+)?)",
        r"ESTIMATED DAMAGE[:\s]+\$?([0-9,]+(?:\.\d+)?)",
    ])
    if damage_str:
        extracted["estimated_damage"] = _parse_amount(damage_str)

    # ── Claim type ────────────────────────────────────────────────────────────
    injury_hint = bool(re.search(
        r"extent of injury|injured|medical|hospital", fnol_text, re.IGNORECASE
    ))
    if injury_hint:
        extracted["claim_type"] = "injury"
    elif re.search(r"\b(vehicle|car|auto|collision|accident)\b", fnol_text, re.IGNORECASE):
        extracted["claim_type"] = "auto"

    # ── Third parties / witnesses ─────────────────────────────────────────────
    third_parties = re.findall(
        r"WITNESSES OR PASSENGERS.*?(?:Name:\s*)?([A-Za-z][A-Za-z\s\.\-']{2,})",
        fnol_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if third_parties:
        extracted["third_parties"] = [
            _cleanup(name) for name in third_parties[:3] if _cleanup(name)
        ]

    return extracted


def _normalize_and_fill(extracted: dict, fallback: dict) -> dict:
    normalized = _empty_schema()

    for key in EXPECTED_KEYS:
        value = extracted.get(key)
        if value in (None, "", []):
            value = fallback.get(key)
        normalized[key] = value

    normalized["estimated_damage"] = _normalize_numeric(normalized.get("estimated_damage"))
    normalized["initial_estimate"] = _normalize_numeric(normalized.get("initial_estimate"))

    # Prefer deterministic regex/form extraction for policy effective date.
    # LLM output can pick another nearby date field on dense ACORD forms.
    fallback_effective_date = _cleanup(str(fallback.get("policy_effective_date", "")))
    if fallback_effective_date:
        normalized["policy_effective_date"] = fallback_effective_date

    # Derive initial_estimate from estimated_damage if not set
    if normalized["initial_estimate"] is None and normalized["estimated_damage"] is not None:
        normalized["initial_estimate"] = normalized["estimated_damage"]

    claim_type = _cleanup(str(normalized.get("claim_type", ""))).lower()
    if claim_type not in {"auto", "property", "injury", "other"}:
        claim_type = ""

    if not claim_type:
        if normalized.get("asset_type"):
            claim_type = "auto"
        elif re.search(
            r"\binjur|medical|hospital\b",
            normalized.get("incident_description", ""),
            re.IGNORECASE,
        ):
            claim_type = "injury"
        else:
            claim_type = "other"
    normalized["claim_type"] = claim_type

    if not normalized.get("claimant_name"):
        normalized["claimant_name"] = normalized.get("policyholder_name", "")

    if not isinstance(normalized.get("attachments"), list):
        normalized["attachments"] = []
    if not isinstance(normalized.get("third_parties"), list):
        normalized["third_parties"] = []

    for key in [
        "policy_number", "policyholder_name", "policy_effective_date", "policy_expiry_date",
        "incident_date", "incident_time", "incident_location", "incident_description",
        "claimant_name", "contact_details", "asset_type", "asset_id",
    ]:
        normalized[key] = _cleanup(str(normalized.get(key, "")))

    return normalized


def extract_fields(fnol_text: str) -> dict:
    fallback = _rule_based_extract(fnol_text)
    if not HF_TOKEN:
        return _normalize_and_fill({}, fallback)

    schema_prompt = f"""You are an insurance claims analyst. Extract all fields from this FNOL document.

Return ONLY valid JSON with exactly these keys:
{{
  "policy_number": "",
  "policyholder_name": "",
  "policy_effective_date": "",
  "policy_expiry_date": "",
  "incident_date": "",
  "incident_time": "",
  "incident_location": "",
  "incident_description": "",
  "claimant_name": "",
  "third_parties": [],
  "contact_details": "",
  "asset_type": "",
  "asset_id": "",
  "estimated_damage": null,
  "claim_type": "",
  "attachments": [],
  "initial_estimate": null
}}

Rules:
- estimated_damage and initial_estimate must be plain numbers (no currency symbols)
- claim_type must be one of: auto, property, injury, other
- Use null for missing numeric fields, empty string for missing text fields
- For contact_details combine phone and email into one string
- incident_description must capture the FULL multi-line description verbatim
- Return ONLY the JSON, no explanation, no markdown, no code fences

FNOL Document:
{fnol_text}"""

    models_to_try = [HF_MODEL, *HF_FALLBACK_MODELS]
    seen = set()
    ordered_models = []
    for model_name in models_to_try:
        if model_name not in seen:
            ordered_models.append(model_name)
            seen.add(model_name)

    errors = []
    for model_name in ordered_models:
        try:
            chat_response = client.chat_completion(
                model=model_name,
                messages=[
                    {"role": "system", "content": "You extract structured insurance claim data."},
                    {"role": "user", "content": schema_prompt},
                ],
                max_tokens=800,
                temperature=0.1,
            )
            text = (chat_response.choices[0].message.content or "").strip()
            if isinstance(text, list):
                text = "".join(
                    part.get("text", "") if isinstance(part, dict) else str(part)
                    for part in text
                ).strip()

            text = re.sub(r'```(?:json)?', '', text).strip()
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                parsed = json.loads(match.group())
                return _normalize_and_fill(parsed, fallback)
            raise RuntimeError(f"Model '{model_name}' response did not contain valid JSON.")
        except Exception as e:
            errors.append(f"{model_name}: {e}")

    if any(v not in ("", None, []) for v in fallback.values()):
        return _normalize_and_fill({}, fallback)

    raise RuntimeError(
        "HuggingFace extraction failed for all configured models and regex fallback found no usable fields. "
        f"Tried: {', '.join(ordered_models)}. Errors: {' | '.join(errors)}"
    )