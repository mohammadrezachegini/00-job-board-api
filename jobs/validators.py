from pathlib import Path
from django.core.exceptions import ValidationError

MAX_RESUME_SIZE = 5 * 1024 * 1024  # 5 MB
RESUME_SIGNATURES = {
    ".pdf": b"%PDF-",
    ".docx": b"PK\x03\x04",
}


def validate_resume(file):
    extension = Path(file.name).suffix.lower()
    if extension not in RESUME_SIGNATURES:
        raise ValidationError("Only PDF and DOCX files are allowed.")
    if file.size > MAX_RESUME_SIZE:
        raise ValidationError("Resume file size should not exceed 5 MB.")
    signatures = RESUME_SIGNATURES[extension]
    file.seek(0)
    header = file.read(len(signatures))
    file.seek(0)
    if header != signatures:
        raise ValidationError("Invalid file signature.")