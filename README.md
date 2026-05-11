# FNOL Claims Processing Agent

An autonomous **First Notice of Loss (FNOL)** processing agent built with Flask and the HuggingFace free Inference API. Upload a PDF or TXT claim document and the agent will:

1. **Extract** all structured fields using an LLM (Qwen2.5-VL-7B)
2. **Validate** mandatory fields
3. **Route** the claim based on fraud signals, injury type, damage thresholds, and completeness

---

## Setup

Install dependencies into the same Python you will use to run the app (no virtual environment is required).

```bash
# 1. Clone / download the project, then go to the project folder
cd fnol-agent

# 2. Install dependencies (use the same python3 you will run app.py with)
python3 -m pip install -r requirements.txt

# 3. Create your .env file
echo "HF_TOKEN=your_huggingface_token_here" > .env
```

> Get a free HuggingFace token at https://huggingface.co/settings/tokens

---

## Run

```bash
python3 app.py
```

Then open **http://localhost:5000** in your browser.

---

## Usage

- **Upload a PDF or TXT file** — supports ACORD standard FNOL forms and free-text FNOL documents

The agent returns:
- A **colored route badge** (see table below)
- **Reasoning** for the routing decision
- **Extracted fields** table
- **Missing fields** list (if any)
- **Raw JSON** output toggle

---

## Routing Rules

| Route | Condition | Badge Color |
|---|---|---|
| 🚨 **Investigation Flag** | Incident description contains fraud keywords: `fraud`, `staged`, `inconsistent`, `suspicious`, `fabricated`, `fake` | Red |
| ⚠️ **Manual Review** | One or more mandatory fields are missing | Orange |
| 🏥 **Specialist Queue** | `claim_type` is `injury` | Blue |
| ✅ **Fast-Track** | `estimated_damage` < 25,000 | Green |
| 📋 **Standard Review** | All other complete claims | Gray |

Rules are evaluated **in priority order** — fraud check always wins.

---

## Mandatory Fields

The following fields must be present for a claim to avoid Manual Review:

`policy_number`, `policyholder_name`, `policy_effective_date`, `incident_date`, `incident_location`, `incident_description`, `claimant_name`, `contact_details`, `asset_type`, `estimated_damage`, `claim_type`, `initial_estimate`

---

## Sample FNOLs

| File | Scenario | Expected Route |
|---|---|---|
| `fnol_001.txt` | Auto claim, damage $18k, no injury | Fast-Track |
| `fnol_002.txt` | Property claim, missing `initial_estimate` | Manual Review |
| `fnol_003.txt` | Auto claim, staged accident language | Investigation Flag |
| `fnol_004.txt` | Injury claim, damage $55k | Specialist Queue |
| `fnol_005.txt` | Auto claim, damage $80k | Standard Review |

---

## PDF Support

The agent uses `pdfplumber` to extract text from PDF uploads. It works with:
- Standard ACORD loss notice forms
- Any machine-readable PDF with embedded text

> _Screenshot: place your UI screenshot here after first run._
