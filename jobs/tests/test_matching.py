import pytest

from jobs.matching import match_score, normalize_skills


def test_normalize_skills_strips_lowercases_and_drops_blanks():
    assert normalize_skills([" AWS ", "aws", "Terraform", "", "   ", None]) == {"aws", "terraform"}


@pytest.mark.parametrize(
    ("required", "candidate", "expected"),
    [
        (["aws", "terraform", "python"], ["aws", "terraform", "python"], 100),
        (["aws", "terraform", "python"], ["aws", "terraform"], 67),
        (["aws", "terraform", "python"], ["aws"], 33),
        (["aws", "terraform"], ["go", "rust"], 0),
        (["aws", "terraform"], [], 0),
        (["AWS", " Terraform "], ["aws", "TERRAFORM"], 100),
        (["aws", "AWS", "aws "], ["aws"], 100),
        (["aws"], ["aws", "go", "rust", "k8s"], 100),
    ],
)
def test_match_score(required, candidate, expected):
    assert match_score(required, candidate) == expected


@pytest.mark.parametrize("required", [[], ["", "   "]])
def test_match_score_is_none_when_job_requires_no_skills(required):
    assert match_score(required, ["aws"]) is None


def test_match_score_rounds_halves_to_even():
    eight = [f"skill{i}" for i in range(8)]
    assert match_score(eight, eight[:1]) == 12   # 12.5 → 12
    assert match_score(eight, eight[:3]) == 38   # 37.5 → 38