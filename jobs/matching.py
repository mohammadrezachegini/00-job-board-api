def normalize_skills(skills):
    return {skill.strip().lower() for skill in skills if skill and skill.strip()}


def match_score(required_skills, candidate_skills):
    required = normalize_skills(required_skills)
    if not required:
        return None
    matches = required & normalize_skills(candidate_skills)
    return round(100 * len(matches) / len(required))