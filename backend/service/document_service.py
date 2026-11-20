
from io import BytesIO

from pypdf import PdfReader
from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph


def iter_block_items(parent):
    """
    Read paragraphs and tables in their original document order.
    Supports both document bodies and table cells.
    """
    if hasattr(parent, "element") and hasattr(parent.element, "body"):
        parent_element = parent.element.body
    else:
        parent_element = parent._tc

    for child in parent_element.iterchildren():
        if child.tag.endswith("}p"):
            yield Paragraph(child, parent)
        elif child.tag.endswith("}tbl"):
            yield Table(child, parent)


def extract_table_text(table):
    """
    Extract text from table cells, including nested tables.
    """
    extracted = []

    for row in table.rows:
        for cell in row.cells:
            for block in iter_block_items(cell):
                if isinstance(block, Paragraph):
                    value = block.text.strip()

                    if value:
                        extracted.append(value)

                elif isinstance(block, Table):
                    nested_text = extract_table_text(block)

                    if nested_text:
                        extracted.append(nested_text)

    return "\n".join(extracted)


def extract_docx_text(file_content):
    """
    Extract paragraphs, tables, headers and footers from DOCX.
    """
    document = Document(BytesIO(file_content))
    extracted = []

    # Extract paragraphs and tables in document order.
    for block in iter_block_items(document):
        if isinstance(block, Paragraph):
            value = block.text.strip()

            if value:
                extracted.append(value)

        elif isinstance(block, Table):
            table_text = extract_table_text(block)

            if table_text:
                extracted.append(table_text)

    # Extract headers and footers.
    for section in document.sections:

        for paragraph in section.header.paragraphs:
            value = paragraph.text.strip()

            if value:
                extracted.append(value)

        for table in section.header.tables:
            value = extract_table_text(table)

            if value:
                extracted.append(value)

        for paragraph in section.footer.paragraphs:
            value = paragraph.text.strip()

            if value:
                extracted.append(value)

        for table in section.footer.tables:
            value = extract_table_text(table)

            if value:
                extracted.append(value)

    return "\n".join(extracted)


def extract_text(file_content: bytes, filename: str) -> str:
    """
    Extract readable text from PDF, DOCX and TXT files.
    Includes PDF debugging to identify extraction problems.
    """

    extension = filename.lower().rsplit(".", 1)[-1]

    try:

        # PDF extraction
        if extension == "pdf":

            reader = PdfReader(BytesIO(file_content))

            print("\n========== PDF EXTRACTION DEBUG ==========")
            print("Filename:", filename)
            print("File size:", len(file_content))
            print("Number of pages:", len(reader.pages))

            extracted = []

            for page_number, page in enumerate(reader.pages, start=1):

                page_text = page.extract_text() or ""

                print(f"\nPage {page_number}:")
                print("Extracted length:", len(page_text))
                print("Preview:", repr(page_text[:300]))

                if page_text.strip():
                    extracted.append(page_text)

            text = "\n".join(extracted)

            print("\nTotal extracted length:", len(text))
            print("==========================================\n")

        # DOCX extraction
        elif extension == "docx":

            text = extract_docx_text(file_content)

        # TXT extraction
        elif extension == "txt":

            text = file_content.decode("utf-8-sig")

        else:

            raise ValueError("Unsupported document format")

        text = text.strip()

        if not text:

            raise ValueError(
                "No readable text found. The document may contain only "
                "images, scanned pages, or unsupported text elements."
            )

        return text

    except ValueError:

        raise

    except Exception as error:

        raise ValueError(
            f"Could not extract document text: {str(error)}"
        ) from error
