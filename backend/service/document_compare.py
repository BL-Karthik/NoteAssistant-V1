
from google.genai import types

from service.gemini_client import client, GEMINI_MODEL

# COMPARE UPLOADED DOCUMENTS

def compare_documents(documents):

    if client is None:
        raise RuntimeError(
            "GEMINI_API_KEY is missing. Configure it in your backend .env file."
        )

    if not isinstance(documents, list) or len(documents) != 2:
        raise ValueError(
            "Exactly two documents are required for comparison."
        )

    document_sections = []

    for index, document in enumerate(documents, start=1):

        filename = document.get("filename", f"Document {index}")
        content = document.get("content", "")

        if not content or not content.strip():
            raise ValueError(
                f"The document '{filename}' has no extracted text to compare."
            )

        document_sections.append(
            f"""
DOCUMENT {index}
Filename: {filename}

FULL EXTRACTED CONTENT:
{content}
"""
        )

    prompt = f"""
You are an expert document comparison assistant.

Compare the following two uploaded documents carefully.

{document_sections[0]}

{document_sections[1]}

COMPARISON REQUIREMENTS:

1. Give a short overview of each document.
2. Identify the main similarities between the documents.
3. Identify the important differences.
4. Highlight key findings from both documents.
5. Identify information present in one document but missing
   from the other.
6. Identify conflicting statements, dates, figures or decisions.
7. Do not assume that the documents describe the same subject.
8. Do not invent facts or information.
9. Use the actual filenames when referring to documents.
10. If a comparison category is not applicable, say so clearly.
11. Distinguish confirmed facts from observations.
12. Keep the comparison clear, structured and easy to understand.

RESPONSE FORMAT:

## Document Comparison

### 1. Overview
Briefly explain what each document contains.

### 2. Similarities
Explain the common information, subjects or objectives.

### 3. Differences
Explain the important differences between the documents.

### 4. Key Findings
Highlight the most important findings from both documents.

### 5. Missing or Conflicting Information
Identify information that appears in only one document
or statements that contradict each other.

### 6. Overall Conclusion
Give a concise conclusion based only on the supplied content.

Return a readable response using Markdown headings and bullet points.
Do not return JSON.
"""

    try:

        result = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.2
            )
        )

        response_text = (result.text or "").strip()

        if not response_text:
            raise RuntimeError(
                "Gemini returned an empty document comparison."
            )

        return response_text

    except Exception as error:

        raise RuntimeError(
            f"Document comparison failed: {error}"
        ) from error


# -----------------------------------
# SUMMARIZE UPLOADED DOCUMENT
# -----------------------------------

def summarize_document(filename, extracted_text):

    if client is None:
        raise RuntimeError(
            "GEMINI_API_KEY is missing. Configure it in your backend .env file."
        )

    if not extracted_text or not extracted_text.strip():
        raise ValueError(
            "No extracted document content is available for summarization."
        )

    prompt = f"""
You are an intelligent document understanding assistant.

A user has uploaded a document to Note Assistant.

DOCUMENT FILENAME:
{filename}

EXTRACTED DOCUMENT CONTENT:
{extracted_text}

YOUR TASK:

Read and understand the actual document content.

Generate a concise but meaningful summary that explains:
1. What the document is about.
2. Its most important information.
3. Its key requirements, findings, decisions or objectives,
   depending on the document type.

Then ask EXACTLY ONE relevant follow-up question.

FOLLOW-UP QUESTION RULES:

- The question must be based on the actual document.
- It should help the user explore the document further.
- It must be specific and meaningful.
- Do not ask a generic question like "Anything else?"
- Do not ask multiple questions.
- Do not invent information.

IMPORTANT:

- Do not provide a technical upload confirmation.
- Do not mention embeddings, chunks, vectors or Qdrant.
- Do not simply repeat the filename.
- Do not invent information that is not present in the document.
- If the document has limited information, clearly explain that.
- Keep the summary easy to understand.
- Use Markdown headings and bullet points where useful.
- Include exactly ONE follow-up question at the end.

RESPONSE FORMAT:

## Summary
Provide the actual document summary.

## Key Points
Provide the most important points from the document.

## Follow-up
Ask exactly one relevant question.

Return a natural conversational response in Markdown.
Do not return JSON.
"""

    try:

        result = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.2
            )
        )

        response_text = (result.text or "").strip()

        if not response_text:
            raise RuntimeError(
                "Gemini returned an empty document summary."
            )

        return response_text

    except Exception as error:

        raise RuntimeError(
            f"Document summarization failed: {error}"
        ) from error
