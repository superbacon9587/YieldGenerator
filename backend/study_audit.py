"""Verified PDF-to-extract matches, without changing the operating-cost model."""
import json
from functools import cache
from pathlib import Path

@cache
def studies():
    return json.loads((Path(__file__).resolve().parent.parent / 'data/reference/prices/cost_study_audit.json').read_text(encoding='utf-8'))['studies']

def match(crop, cost):
    if not cost:
        return None
    for study in studies():
        if (study['crop']==crop and cost['region'] in study['regions']
            and study['legacy_filename'] in cost['source']
            and abs(study['nonwater_cost_per_acre']-cost['cost_excl_water'])<1e-6):
            return study
    return None
