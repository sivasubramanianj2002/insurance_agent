# Fields that must be present for a claim to proceed without manual review.
# NOTE: initial_estimate is intentionally excluded — it is a derived field
# computed from estimated_damage inside extractor.py and should never be
# treated as a raw input requirement.
MANDATORY = [
    "policy_number",
    "policyholder_name",
    "policy_effective_date",
    "incident_date",
    "incident_location",
    "incident_description",
    "claimant_name",
    "contact_details",
    "asset_type",
    "estimated_damage",
    "claim_type",
]


def validate_fields(extracted: dict) -> list:
    missing = []
    for field in MANDATORY:
        val = extracted.get(field)
        if val is None or val == "" or val == []:
            missing.append(field)
    return missing