from celery import Celery
from yaptide.admin import git_submodules

# celery.tasks is importing the converter module which is cloned as submodule.
git_submodules.check_submodules()
celery_app = Celery("celery", include=['yaptide.celery.tasks', 'yaptide.celery.utils.manage_tasks'])
