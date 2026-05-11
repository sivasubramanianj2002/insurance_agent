import os
import io
import json
import time
import uuid

import pdfplumber
import pypdf
from flask import Flask, render_template, request, jsonify

from extractor import extract_fields
from validator import validate_fields
from router import route_claim

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB max upload


def read_pdf(file_bytes: bytes) -> str:
    """Extract text from FNOL PDFs.

    Strategy:
      1. AcroForm fields (pypdf)  — filled/interactive PDFs store typed values
         here, NOT in the text stream. Without this step you only get label text
         like "POLICY NUMBER" instead of the actual value "NSC-2023-98232".
      2. pdfplumber text + tables — fallback for scanned or flattened PDFs where
         there are no form fields; also captures printed text on early pages.
    """
    text_parts = []

    # ── Step 1: AcroForm field values ─────────────────────────────────────────
    # ACORD PDFs are fillable forms. Filled data lives in /V keys of AcroForm
    # field objects, not in the visible text stream that pdfplumber reads.
    # This pass produces "label: value" lines the extractor regexes can match.
    try:
        reader = pypdf.PdfReader(io.BytesIO(file_bytes))
        fields = reader.get_fields()
        if fields:
            form_lines = []
            for field_name, field_obj in fields.items():
                value = field_obj.get("/V") or field_obj.get("/DV") or ""
                value_str = str(value).strip()
                # Skip empty values and values that are just the field name itself
                if value_str and value_str != field_name and value_str != "Off":
                    clean_name = field_name.replace("_", " ").replace(".", " ").strip()
                    form_lines.append(f"{clean_name}: {value_str}")
            if form_lines:
                text_parts.append("\n".join(form_lines))
                app.logger.debug("AcroForm extracted %d field values", len(form_lines))

        # Some ACORD variants expose widgets that do not appear in get_fields().
        # Read page annotations directly so generic keys like Text1 are captured.
        widget_lines = []
        seen_widget_keys = set()
        for page in reader.pages:
            annots = page.get("/Annots") or []
            for annot in annots:
                try:
                    obj = annot.get_object()
                except Exception:
                    continue
                field_name = obj.get("/T")
                if not field_name:
                    continue
                value = obj.get("/V") or obj.get("/DV") or ""
                value_str = str(value).strip()
                key = str(field_name).strip()
                if (
                    value_str
                    and value_str != key
                    and value_str != "Off"
                    and key not in seen_widget_keys
                ):
                    clean_name = key.replace("_", " ").replace(".", " ").strip()
                    widget_lines.append(f"{clean_name}: {value_str}")
                    seen_widget_keys.add(key)
        if widget_lines:
            text_parts.append("\n".join(widget_lines))
            app.logger.debug("Widget extraction captured %d field values", len(widget_lines))
    except Exception:
        # Non-fatal: fall through to pdfplumber extraction below
        app.logger.debug("AcroForm extraction skipped (not a fillable PDF or pypdf error)")

    # ── Step 2: pdfplumber text + table extraction ────────────────────────────
    # Kept as fallback for scanned / flattened PDFs and to capture any printed
    # text not stored in form fields (e.g. pre-printed header data).
    try:
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for idx, page in enumerate(pdf.pages, start=1):
                page_text = page.extract_text(layout=True) or page.extract_text() or ""
                page_text = page_text.strip()
                if not page_text:
                    continue

                # ACORD pages 3+ are legal disclaimers; skip them to avoid
                # polluting the extractor with low-signal boilerplate.
                if "Applicable in Alabama:" in page_text and idx >= 3:
                    continue

                text_parts.append(page_text)

                # Include table cells — some fillable PDFs store data in tables
                try:
                    tables = page.extract_tables() or []
                    for table in tables:
                        flattened = [
                            cell.strip()
                            for row in table
                            for cell in row
                            if cell and cell.strip()
                        ]
                        if flattened:
                            text_parts.append(" | ".join(flattened))
                except Exception:
                    pass  # Non-fatal: continue with text already extracted
    except Exception as e:
        app.logger.warning("pdfplumber extraction failed: %s", e)

    return "\n".join(text_parts)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/favicon.ico")
def favicon():
    return ("", 204)


@app.route("/process", methods=["POST"])
def process():
    start = time.perf_counter()
    req_id = str(uuid.uuid4())[:8]
    app.logger.info("[req:%s] /process start", req_id)
    filename = "unknown"
    fnol_text = ""

    uploaded = request.files.get("fnol_file")
    if not uploaded or not uploaded.filename:
        app.logger.warning("[req:%s] No file uploaded", req_id)
        return jsonify({"error": "Please upload a PDF or TXT file."}), 400

    filename = uploaded.filename
    file_bytes = uploaded.read()
    app.logger.info(
        "[req:%s] Uploaded file detected: name=%s size_bytes=%s",
        req_id,
        filename,
        len(file_bytes),
    )

    if filename.lower().endswith(".pdf"):
        try:
            pdf_start = time.perf_counter()
            fnol_text = read_pdf(file_bytes)
            app.logger.info(
                "[req:%s] PDF extraction complete in %d ms",
                req_id,
                int((time.perf_counter() - pdf_start) * 1000),
            )
        except Exception as e:
            app.logger.exception("[req:%s] PDF extraction failed", req_id)
            return jsonify({"error": f"Failed to read PDF: {e}"}), 400
    else:
        try:
            fnol_text = file_bytes.decode("utf-8")
            app.logger.info("[req:%s] Text file decoded", req_id)
        except Exception as e:
            app.logger.exception("[req:%s] Text decode failed", req_id)
            return jsonify({"error": f"Failed to decode file: {e}"}), 400

    if not fnol_text.strip():
        app.logger.warning("[req:%s] Input text is empty after extraction/decoding", req_id)
        return jsonify({"error": "The document appears to be empty or unreadable."}), 400

    # ── Pipeline ──────────────────────────────────────────────────────────────
    try:
        ext_start = time.perf_counter()
        app.logger.info("[req:%s] Calling extract_fields", req_id)
        extracted = extract_fields(fnol_text)
        app.logger.info(
            "[req:%s] extract_fields complete in %d ms",
            req_id,
            int((time.perf_counter() - ext_start) * 1000),
        )
    except Exception as e:
        app.logger.exception("[req:%s] extract_fields failed", req_id)
        return jsonify({"error": str(e)}), 504

    app.logger.info("[req:%s] Running validate_fields", req_id)
    missing = validate_fields(extracted)
    app.logger.info("[req:%s] validate_fields complete: missing_count=%d", req_id, len(missing))

    app.logger.info("[req:%s] Running route_claim", req_id)
    route, reasoning = route_claim(extracted, missing)
    app.logger.info("[req:%s] route_claim complete: route=%s", req_id, route)

    result = {
        "file": filename,
        "extractedFields": extracted,
        "missingFields": missing,
        "recommendedRoute": route,
        "reasoning": reasoning,
    }

    elapsed_ms = int((time.perf_counter() - start) * 1000)
    app.logger.info("[req:%s] Completed '%s' in %d ms", req_id, filename, elapsed_ms)

    return render_template(
        "index.html",
        result=result,
        result_json=json.dumps(result, indent=2),
    )


if __name__ == "__main__":
    app.run(debug=True, port=5000)