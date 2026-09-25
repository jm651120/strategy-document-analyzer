# Strategy Document Analysis Agent

## Overview
This repository contains a generative AI agent built for the Roland Berger AI Lab. The agent ingests complex, visually dense strategy documents (PDFs) and produces a highly structured, objective assessment in JSON format.

## 1. How to Run

### Prerequisites
- Python 3.10+
- A valid Google Gemini API Key

### Setup Instructions
1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
2. **Environment Variables**:
   Create a `.env` file in the root directory and add your API key:
   ```env
   GEMINI_API_KEY=your_api_key_here
   ```
3. **Execution**:
   The script uses a command-line interface. You must provide the path to the PDF.
   ```bash
   # Process a specific PDF and limit to pages 1 through 4 for testing
   python main.py data/your_pdf_name.pdf --start-page 1 --end-page 4
   
   # Process an entire document and save to a custom output file
   python main.py data/your_pdf_name.pdf --output assessment_results.json
   ```
   The strictly validated JSON will be saved to your specified output file (defaults to `output.json`).

---

## 2. Architecture & Decisions Made

### The "Vision-First" Multimodal Approach
Strategy documents rely heavily on spatial reasoning (e.g., 2x2 competitor matrices, complex waterfall charts, operating-model diagrams, and strategic roadmaps). 
**Decision:** Rather than relying on traditional text extractors (like `pdfplumber` or `pypdf`) which often misinterpret multi-column layouts and ignore visual semantics, this solution utilizes a **Vision-First** approach. The PDF is converted into a sequence of high-resolution images and passed directly to a multimodal LLM. This ensures the model processes the document visually, directly solving the assignment's *Visual Content Challenge*.

### Zero-Dependency Execution via PyMuPDF
**Experiment:** The pipeline was initially built using `pdf2image` to handle the rasterization.
**Decision:** The architecture was pivoted to `PyMuPDF` (`fitz`). The `pdf2image` library requires system-level Poppler binaries to be installed and added to the OS `PATH`, creating external system dependencies. `PyMuPDF` is fully self-contained. Furthermore, a zoom matrix (`fitz.Matrix(2.0, 2.0)`) is explicitly passed to upscale the rasterization to 144 DPI. This guarantees that small text within complex charts remains highly legible for the vision model.

### Prompt & Schema Design
To satisfy the strict JSON requirement while maintaining data integrity, a nested Pydantic model is used. Rather than a detached list of references at the bottom of the JSON, the schema enforces a `ReferencedInsight` object. Every finding, recommendation, and metric must independently provide:
1. The extracted `insight`.
2. The 1-indexed `page_numbers` (grounding).
3. The `confidence` level (High/Medium/Low).
4. An `evidence_explanation` detailing the visual or textual proof.

---

## 3. Handling Visual Content & Uncertainty

The system prompt is explicitly engineered to handle the ambiguity inherent in scanned pages and complex charts:
- **Default to Logging, Not Guessing:** If a chart is too blurry or a table's structure is confusing, the prompt strictly instructs the model not to guess. 
- **Confidence Scoring:** The extraction's `confidence` is marked as "Low".
- **Uncertainty Trapping:** Unreadable visual elements are explicitly logged in the `missing_or_unclear_information` JSON array, ensuring data transparency.

---

## 4. Problems Encountered & Engineering Resilience

During development, two engineering challenges were encountered and mitigated:

### A. The SDK Schema Validation Bug
**Problem:** The `google-genai` SDK's strict JSON schema enforcement (`response_schema`) currently throws `extra_forbidden` errors when parsing complex Pydantic models that utilize `$defs` and `$ref` pointers (such as the nested `ReferencedInsight` and Enums).
**Solution:** A resilient, client-side validation approach was implemented:
1. The configuration uses `response_mime_type="application/json"`.
2. The exact schema is dynamically injected into the system prompt via `DocumentAssessment.model_json_schema()`.
3. The raw response text is manually parsed and validated using `DocumentAssessment.model_validate_json()`. If a key is hallucinated, Pydantic catches the validation error and logs the raw string to `debug_raw_output.json` for inspection.

### B. API Rate Limits & Cloud Availability
**Problem:** When scaling up to test on longer documents, preview models triggered 429 Quota errors on the free tier, and `gemini-3.8-flash` triggered 503 UNAVAILABLE errors due to global demand spikes.
**Solution:** 
1. **Model Fallback:** The primary engine was pivoted to `gemini-3.1-flash-lite`, which processes images rapidly and reliably.
2. **Graceful Degradation:** The API execution is wrapped in a 3-attempt exponential backoff/retry loop to ensure transient 503 spikes do not crash the agent during execution.

---

## 5. Known Limitations & Future Improvements

1. **Token Cost Density:** Converting every page to a high-resolution image consumes significantly more tokens than pure text extraction. While acceptable for a targeted strategy analysis, it increases operational costs at scale.
2. **Next Step (Hybrid Pipeline):** Future iterations would implement a layout-detection model (e.g., `unstructured.io` or `Docling`) to extract pure text efficiently, while selectively cropping and routing only the bounding boxes of charts and matrices to the vision model.
3. **Long-Context Grounding:** For documents exceeding 100 pages, even large context windows can lose focus. Future architecture should implement a Multimodal RAG approach, embedding the page images using a model like ColPali for semantic retrieval prior to synthesis.
