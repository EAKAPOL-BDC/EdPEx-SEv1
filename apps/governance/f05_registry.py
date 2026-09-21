"""Explicit F05 version routing; old algorithms remain byte-for-byte unchanged."""
from django.core.exceptions import ValidationError
from . import f05_contract, f05_quantitative

MODULES=(f05_contract,f05_quantitative)

def for_version(version):
    if is_quantitative_version(version):return f05_quantitative
    for module in MODULES:
        if version==module.VERSION:return module
    raise ValidationError('ไม่รองรับรุ่น F05 นี้ / Unsupported F05 version.')

def is_quantitative_version(version):
    return isinstance(version,str) and (version==f05_quantitative.VERSION or version.startswith(f05_quantitative.VERSION+'-sim-'))

def for_contract(contract):
    for module in MODULES:
        if contract==module.CONTRACT:return module
    from apps.calculations.types import CalculationInputError
    raise CalculationInputError('Unknown F05 snapshot contract.')
