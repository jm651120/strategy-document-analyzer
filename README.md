# Strategy Document Analysis Agent

## Overview
This repository contains a generative AI agent built for the Roland Berger AI Lab. The agent ingests complex, visually dense strategy documents (PDFs) and produces a highly structured, objective consulting assessment in JSON format.

## 1. How to Run

### Prerequisites
- Python 3.10+
- A valid Google Gemini API Key.

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
   # Process a specific PDF and limit to the first 4 pages for testing
   python main.py data/your_pdf_name.pdf --max-pages 4
   
   # Process an entire document and save to a custom output file
   python main.py data/your_pdf_name.pdf --output assessment_results.json
   ```
   The final, strictly validated JSON will be saved to your specified output file (defaults to `output.json`).

---

## 2. Architecture & Decisions Made

### The "Vision-First" Multimodal Approach
Strategy documents (corporate roadmaps, market-entry studies) rely heavily on spatial reasoning (e.g., 2x2 competitor matrices, McKinsey-style waterfalls, operating-model diagrams). 
**Decision:** Rather than relying on traditional text extractors (like `pdfplumber` or `pypdf`) which notoriously mangle multi-column layouts and completely ignore visual semantics, I opted for a **Vision-First** approach. The PDF is converted into a sequence of high-resolution images and passed directly to a multimodal LLM. This ensures the model "sees" the document exactly as a human consultant would, directly solving the assignment's *Visual Content Challenge*.

### Zero-Dependency Execution via PyMuPDF
**Experiment:** I initially built the pipeline using `pdf2image` to handle the rasterization.
**Decision:** I pivoted to `PyMuPDF` (`fitz`). `pdf2image` requires system-level Poppler binaries to be installed and added to the OS `PATH`, which creates a brittle UX for evaluators. `PyMuPDF` is fully self-contained in its pip wheel. Furthermore, I explicitly pass a zoom matrix (`fitz.Matrix(2.0, 2.0)`) to upscale the rasterization to 144 DPI. This guarantees that small text within complex charts remains highly legible for the vision model.

### Prompt & Schema Design
To satisfy the strict JSON requirement while enforcing consulting rigor, I designed a nested Pydantic model. Rather than a detached list of references at the bottom of the JSON, the schema enforces a `ReferencedInsight` object. Every finding, recommendation, and metric must independently provide:
1. The extracted `insight`.
2. The 1-indexed `page_numbers` (grounding).
3. The `confidence` level (High/Medium/Low).
4. An `evidence_explanation` detailing the visual or textual proof.

---

## 3. Handling Visual Content & Uncertainty

The system prompt is explicitly engineered to handle the ambiguity inherent in scanned pages and complex charts:
- **Default to Logging, Not Guessing:** If a chart is too blurry or a table's structure is confusing, the prompt strictly instructs the model *not to guess*. 
- **Confidence Scoring:** It must mark the extraction's `confidence` as "Low".
- **Uncertainty Trapping:** It must explicitly log the unreadable visual element in the `missing_or_unclear_information` JSON array, ensuring transparency and trust with the end-user.

---

## 4. Problems Encountered & Engineering Resilience

During development, two major engineering hurdles were encountered and successfully mitigated:

### A. The SDK Schema Validation Bug
**Problem:** The new `google-genai` SDK's strict JSON schema enforcement (`response_schema`) currently throws `extra_forbidden` errors when parsing complex Pydantic models that utilize `$defs` and `$ref` pointers (such as our nested `ReferencedInsight` and Enums).
**Solution:** Instead of compromising the data structure by flattening the schema to appease the SDK, I pivoted to a resilient, client-side validation approach:
1. We use `response_mime_type="application/json"`.
2. We dynamically inject the exact schema into the system prompt via `DocumentAssessment.model_json_schema()`.
3. We manually parse and validate the raw response text using `DocumentAssessment.model_validate_json()`. If the model hallucinates a key, Pydantic catches it instantly and dumps the raw string to `debug_raw_output.json` for developer inspection.

### B. API Rate Limits & Cloud Availability
**Problem:** When scaling up to test on a 73-page thesis, preview models (`gemini-3.1-pro-preview`) triggered 429 Quota errors on the free tier, and `gemini-3.8-flash` triggered 503 UNAVAILABLE errors due to global demand spikes.
**Solution:** 
1. **Model Fallback:** I implemented a diagnostic script to ping the REST API and discover available free-tier models, successfully pivoting the primary engine to `gemini-3.1-flash-lite`, which processes images rapidly without quota blocks.
2. **Graceful Degradation:** I wrapped the API execution in a 3-attempt exponential backoff/retry loop to ensure transient 503 spikes do not crash the agent in a production environment.

---

## 5. Known Limitations & Future Improvements

1. **Token Cost Density:** Converting every page to a high-resolution image consumes significantly more tokens than pure text extraction. While acceptable for a high-value strategy analysis, it is expensive at scale.
2. **Next Step (Hybrid Pipeline):** With more time, I would implement a layout-detection model (like `unstructured.io` or IBM's `Docling`) to extract pure text cheaply, while selectively cropping and routing *only* the bounding boxes of charts/matrices to the vision model.
3. **Long-Context Grounding:** For documents exceeding 100 pages, even massive context windows might lose focus. Future iterations should implement a Multimodal RAG approach, embedding the page images using a model like ColPali for semantic retrieval prior to synthesis.
