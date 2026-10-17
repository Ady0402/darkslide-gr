"""Explicit synthetic identities for boundary tests; never alter production guards."""
from contextlib import contextmanager
from dataclasses import replace
from unittest.mock import patch
from darkslide import models

@contextmanager
def base_identity(sha):
    original=models.from_sha
    with patch.object(models,'from_sha',side_effect=lambda value: models.GR3 if value==sha else original(value)):
        yield

@contextmanager
def http_identity(sha,size,template):
    model=replace(models.GR3,input_sha=sha,input_size=size)
    original=models.template_for
    with patch.object(models,'GR3',model), patch.object(models,'ALL',(model,models.GR3X)), \
         patch.object(models,'template_for',side_effect=lambda m:template() if m==model else original(m)):
        yield
