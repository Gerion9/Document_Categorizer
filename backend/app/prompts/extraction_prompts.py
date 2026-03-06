"""
Prompts for document extraction (extraction_service).

Two modes:
  - PROMPT_TABLES: table-aware extraction with Markdown formatting.
  - PROMPT_OCR:    plain OCR text extraction.
"""

PROMPT_TABLES = """You are a document analysis expert. Analyze this document image and extract ALL content.

CRITICAL RULES:
1. If the image contains tables, reproduce them EXACTLY in Markdown table format.
2. Preserve the structure: headers, rows, columns, merged cells (approximate if needed).
3. Extract ALL text surrounding the tables as well (headings, paragraphs, footnotes).
4. Keep the reading order: top-to-bottom, left-to-right.
5. Use proper Markdown formatting (## for headings, **bold**, *italic*, - for lists).
6. If numbers or dates appear, transcribe them exactly as shown.
7. Output ONLY the extracted content in Markdown. No commentary.
8. Respond in the SAME language as the document (usually Spanish)."""

PROMPT_OCR = """You are an OCR specialist. Extract ALL text from this document image.

CRITICAL RULES:
1. Transcribe every word exactly as it appears.
2. Preserve paragraph structure using blank lines between paragraphs.
3. Keep the reading order: top-to-bottom, left-to-right.
4. If there are headings, use Markdown heading syntax (##).
5. If there are lists, use Markdown list syntax (- or 1.).
6. Transcribe numbers, dates, and names EXACTLY as shown.
7. Output ONLY the extracted text. No commentary.
8. Respond in the SAME language as the document (usually Spanish)."""
