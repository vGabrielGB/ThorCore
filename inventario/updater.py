from apscheduler.schedulers.background import BackgroundScheduler
import os

def start_updater():
    if os.environ.get('RUN_MAIN', None) == 'true' or not os.environ.get('RUN_MAIN'):
        from .utils import update_rates_job
        scheduler = BackgroundScheduler()
        # Run every 60 minutes
        scheduler.add_job(update_rates_job, 'interval', minutes=60, id='rates_updater', replace_existing=True)
        scheduler.start()
