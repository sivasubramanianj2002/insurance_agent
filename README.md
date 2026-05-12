# FNOL Claims Processing Agent

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

## PDF Support

The agent uses `pdfplumber` to extract text from PDF uploads. It works with:
- Standard ACORD loss notice forms
- Any machine-readable PDF with embedded text

> _Screenshot: place your UI screenshot here after first run._
