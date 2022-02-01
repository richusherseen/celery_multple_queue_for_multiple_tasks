from celery import Celery
import os

print('in celery')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'graph_delta.settings')

app = Celery('graph_delta')
# app.config_from_object(Config)
app.config_from_object('django.conf:settings', namespace='CELERY')


app.autodiscover_tasks()