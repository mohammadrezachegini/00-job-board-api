import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile

from jobs.validators import MAX_RESUME_SIZE, validate_resume

PDF = b"%PDF-1.4\nfake resume\n%%EOF\n"
DOCX = b"PK\x03\x04fake docx"


def upload(name, content):
    return SimpleUploadedFile(name, content)


@pytest.mark.parametrize(
    ("name", "content"),
    [("cv.pdf", PDF), ("cv.docx", DOCX), ("CV.PDF", PDF)],
)
def test_valid_resumes_pass(name, content):
    assert validate_resume(upload(name, content)) is None


@pytest.mark.parametrize("name", ["cv.txt", "cv.doc", "cv", "cv.pdf.exe"])
def test_other_extensions_are_rejected(name):
    with pytest.raises(ValidationError, match="Only PDF and DOCX"):
        validate_resume(upload(name, PDF))


@pytest.mark.parametrize(
    ("name", "content"),
    [("cv.pdf", DOCX), ("cv.docx", PDF), ("cv.pdf", b"just text"), ("cv.pdf", b"")],
)
def test_content_must_match_the_extension(name, content):
    with pytest.raises(ValidationError, match="Invalid file signature"):
        validate_resume(upload(name, content))


def test_exactly_5_mb_is_allowed():
    content = PDF[:5] + b"0" * (MAX_RESUME_SIZE - 5)
    assert validate_resume(upload("cv.pdf", content)) is None


def test_one_byte_over_5_mb_is_rejected():
    content = PDF[:5] + b"0" * (MAX_RESUME_SIZE - 4)
    with pytest.raises(ValidationError, match="5 MB"):
        validate_resume(upload("cv.pdf", content))


def test_file_is_rewound_after_validation():
    file = upload("cv.pdf", PDF)
    validate_resume(file)
    assert file.tell() == 0
    assert file.read() == PDF