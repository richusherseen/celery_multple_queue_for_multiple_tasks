from django.db import models

class RunmybotSetting(models.Model):
    conf_key = models.TextField()
    conf_value = models.TextField()
    conf_description = models.TextField()