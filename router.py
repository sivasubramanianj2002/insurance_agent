FRAUD_KEYWORDS = [
    "fraud", "staged", "inconsistent", "suspicious",
    "fabricated", "fake"
]


def route_claim(extracted: dict, missing_fields: list) -> tuple:
    description = (extracted.get("incident_description") or "").lower()
    damage = extracted.get("estimated_damage")
    claim_type = (extracted.get("claim_type") or "").lower()

    # 1. Fraud check — highest priority
    for kw in FRAUD_KEYWORDS:
        if kw in description:
            return (
                "Investigation Flag",
                f"Incident description contains fraud-indicator keyword: '{kw}'"
            )

    # 2. Missing fields → manual review
    if missing_fields:
        return (
            "Manual Review",
            f"The following mandatory fields are missing: {', '.join(missing_fields)}"
        )

    # 3. Injury claims → specialist
    if claim_type == "injury":
        return (
            "Specialist Queue",
            "Injury claims require specialist medical and legal assessment"
        )

    # 4. Low-damage fast-track
    if damage is not None and damage < 25000:
        return (
            "Fast-Track",
            f"Estimated damage of {damage:,} is below the 25,000 fast-track threshold"
        )

    # 5. Default standard review
    return (
        "Standard Review",
        f"Claim meets standard processing criteria. Estimated damage: {damage:,}" if damage else
        "Claim meets standard processing criteria."
    )
