def detect_document_type(raw_text: str) -> str:
    text = (raw_text or "").upper()
    if "INTERMEDIATE" in text:
        return "intermediate"
    return "matric"
