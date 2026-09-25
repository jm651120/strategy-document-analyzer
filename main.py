import os
import io
import json
import time
from typing import List, Optional
from enum import Enum

# 1. LOAD ENVIRONMENT VARIABLES FIRST
from dotenv import load_dotenv
load_dotenv()

# 2. STANDARD IMPORTS
import fitz  # PyMuPDF
from PIL import Image
from pydantic import BaseModel, Field, ValidationError
from google import genai
from google.genai import types

# ==========================================
# 1. Pydantic Schema Definition
# ==========================================
class ConfidenceLevel(str, Enum):
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"

class DocumentType(str, Enum):
    CORPORATE_STRATEGY = "Corporate Strategy"
    MARKET_ENTRY = "Market Entry Study"
    BUSINESS_PLAN = "Business Plan"
    TRANSFORMATION_ROADMAP = "Transformation Roadmap"
    MARKET_RESEARCH = "Market Research Report"
    OTHER = "Other"

class ReferencedInsight(BaseModel):
    insight: str = Field(description="The specific finding, recommendation, assumption, or risk.")
    page_numbers: List[int] = Field(description="List of page numbers (1-indexed) where this is found.")
    confidence: ConfidenceLevel = Field(description="Confidence level in the accuracy of this extraction.")
    evidence_explanation: str = Field(
        description="Brief explanation of the evidence. E.g., 'Waterfall chart on page 5 shows...', 'Explicitly stated in text'."
    )

class DocumentAssessment(BaseModel):
    document_title: str
    document_type: DocumentType
    executive_summary: str = Field(description="A 2-3 paragraph synthesis of the entire document.")
    strategic_objective: str = Field(description="The primary goal or objective of the document.")
    key_findings: List[ReferencedInsight]
    main_recommendations: List[ReferencedInsight]
    important_business_metrics: List[ReferencedInsight]
    assumptions: List[ReferencedInsight]
    risks_or_concerns: List[ReferencedInsight]
    missing_or_unclear_information: List[str] = Field(
        description="List of things that were unreadable, blurry, missing, or logically incomplete."
    )
    recommended_follow_up_questions: List[str] = Field(
        description="Questions a consultant should ask the client based on gaps in this document."
    )
    visual_elements_processed: List[str] = Field(
        description="A list of complex visual elements (e.g., 'Competitor 2x2 Matrix on page 3') that were successfully analyzed."
    )

# ==========================================
# 2. System Prompt Base
# ==========================================
SYSTEM_PROMPT = """You are an elite Strategy Consultant and AI Data Analyst. 
Your task is to analyze a strategy-related document (provided as a sequence of page images) and produce a highly structured, objective assessment.

You will be provided with images of the document's pages in sequential order. 
(Page 1 is the first image, Page 2 is the second, etc.)

Follow these core directives:

1. COMPREHENSIVE VISUAL ANALYSIS: 
Pay extreme attention to non-textual elements. Carefully analyze market-sizing waterfall charts, financial tables, 2x2 competitor matrices, operating-model diagrams, and transformation roadmaps. When referencing insights derived from these elements, explicitly mention the visual structure in your `evidence_explanation` (e.g., "The top-right quadrant of the matrix on page 4 indicates...").

2. FACTS VS. ASSUMPTIONS:
Distinguish strictly between what is presented as factual evidence ("Key Findings" / "Metrics") and what the document assumes to be true ("Assumptions"). Do not present a forecast or a target as a historical fact.

3. UNCERTAINTY AND LIMITATIONS (CRITICAL):
If a page is scanned poorly, a chart is too blurry to read accurately, or a table's structure is confusing, DO NOT GUESS. 
Instead:
- Mark the `confidence` level as "Low" for any partial extractions.
- Explicitly log the unreadable or ambiguous content in the `missing_or_unclear_information` array (e.g., "The financial projections table on page 8 is blurry and numbers cannot be reliably extracted.").

4. STRICT STRUCTURE:
You must output ONLY valid JSON that strictly conforms to the provided schema. Ensure every insight is accurately tagged with the correct 1-indexed page number corresponding to the image sequence.
"""

# ==========================================
# 3. Main Execution Logic
# ==========================================
def process_document(pdf_path: str, output_path: str, start_page: Optional[int] = None, end_page: Optional[int] = None):
    print(f"Starting analysis for: {pdf_path}")
    
    # 1. Validation
    if not os.path.exists(pdf_path):
        print(f"Error: The file '{pdf_path}' does not exist.")
        return
        
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key or api_key == "your_key_here":
        print("Error: Valid GEMINI_API_KEY not found in environment variables. Please check your .env file.")
        return

    # 2. Convert PDF to Images using PyMuPDF
    print("Converting PDF pages to images using PyMuPDF...")
    page_images = []
    try:
        doc = fitz.open(pdf_path)
        start_idx = max(0, start_page - 1) if start_page else 0
        end_idx = min(len(doc), end_page) if end_page else len(doc)
        
        for page_num in range(start_idx, end_idx):
            page = doc.load_page(page_num)
            zoom = 2.0
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat)
            
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            page_images.append(img)
            
        print(f"Successfully extracted {len(page_images)} pages ({start_idx+1} to {end_idx}) as high-resolution images.")
    except Exception as e:
        print(f"Error converting PDF to images: {e}")
        return

    # 3. Prepare Dynamic Schema Injection
    schema_json_str = json.dumps(DocumentAssessment.model_json_schema(), indent=2)
    dynamic_system_prompt = f"{SYSTEM_PROMPT}\n\nOutput STRICTLY valid JSON matching this schema:\n{schema_json_str}"

    # 4. Call Gemini API
    print("Sending to Gemini 3.1 Flash Lite for multimodal analysis...")
    try:
        client = genai.Client(api_key=api_key)
        
        contents = [
            "Here are the pages of the strategy document in sequential order. Please analyze them and provide the JSON assessment."
        ]
        contents.extend(page_images)
        
        config = types.GenerateContentConfig(
            system_instruction=dynamic_system_prompt,
            response_mime_type="application/json",
            temperature=0.1,
        )
        
        # Add retry loop for 503 UNAVAILABLE errors during high demand
        max_retries = 3
        response = None
        for attempt in range(max_retries):
            try:
                print(f"API Call Attempt {attempt + 1}...")
                response = client.models.generate_content(
                    model="gemini-3.1-flash-lite",
                    contents=contents,
                    config=config
                )
                break
            except Exception as e:
                print(f"Attempt {attempt + 1} failed: {e}")
                if attempt < max_retries - 1:
                    print("Retrying in 5 seconds...")
                    time.sleep(5)
                else:
                    raise Exception(f"Failed after {max_retries} attempts. Last error: {e}")
        
        # 5. Parse and Validate Output using Pydantic
        print("Validating JSON output against Pydantic schema...")
        try:
            parsed_data = DocumentAssessment.model_validate_json(response.text)
            
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(parsed_data.model_dump_json(indent=2))
                
            print(f"Analysis complete and strictly validated! Results saved to: {output_path}")
            
        except ValidationError as val_err:
            print("Validation Error: The model output did not match the expected schema.")
            print(f"Details:\n{val_err}")
            debug_path = "debug_raw_output.json"
            with open(debug_path, "w", encoding="utf-8") as f:
                f.write(response.text)
            print(f"Raw output saved to {debug_path} for debugging.")

    except Exception as e:
        print(f"Error during API call or processing: {e}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Strategy Document Analysis Agent")
    parser.add_argument("pdf_path", help="Path to the strategy document PDF")
    parser.add_argument("--output", default="output.json", help="Path to save the JSON output")
    parser.add_argument("--start-page", type=int, default=None, help="Start page for analysis (1-indexed)")
    parser.add_argument("--end-page", type=int, default=None, help="End page for analysis (1-indexed, inclusive)")
    
    args = parser.parse_args()
    process_document(args.pdf_path, args.output, start_page=args.start_page, end_page=args.end_page)
