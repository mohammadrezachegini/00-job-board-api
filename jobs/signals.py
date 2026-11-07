from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from .cache import invalidate_job_list
from .models import Company, Job


@receiver([post_save, post_delete], sender=Job)
@receiver([post_save, post_delete], sender=Company)
def job_list_changed(sender, **kwargs):
    invalidate_job_list()
