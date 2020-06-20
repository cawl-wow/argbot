import os
import traceback
import logging
import models
import pytz
from constants import *

from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.executors.pool import ThreadPoolExecutor


jobstores = {
  'default': SQLAlchemyJobStore(url=models.get_db_uri())
}
executors = {
  'default': ThreadPoolExecutor(max_workers=5)
}
job_defaults = {
  'coalesce': False,
  'max_instances': 1,
  'misfire_grace_time': MISFIRE_GRACE_SECONDS
}

scheduler = BackgroundScheduler(jobstores=jobstores, executors=executors, job_defaults=job_defaults, timezone=pytz.utc)
