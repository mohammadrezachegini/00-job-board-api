import django_filters

from .models import Job


class JobFilter(django_filters.FilterSet):
    location = django_filters.CharFilter(lookup_expr="icontains")
    skills = django_filters.CharFilter(method="filter_skills")

    class Meta:
        model = Job
        fields = ["job_type", "location", "skills"]

    def filter_skills(self, queryset, name, value):
        skills = [skill.strip().lower() for skill in value.split(",") if skill.strip()]
        if not skills:
            return queryset
        return queryset.filter(required_skills__overlap=skills)
