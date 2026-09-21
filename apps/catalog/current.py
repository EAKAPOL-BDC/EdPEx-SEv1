from .models import InstrumentVersion

def visible_versions(scope,mode='current'):
    all_versions=InstrumentVersion.objects.filter(instrument__scope=scope)
    synthetic=all_versions.filter(source_metadata__synthetic_only=True)
    if mode=='simulation':return synthetic
    real=all_versions.exclude(pk__in=synthetic)
    if mode=='history':return real
    chosen={}
    candidates=list(real.exclude(status='retired').select_related('instrument').order_by('instrument__code','-created_at','-pk'))
    has_quantitative=any(v.instrument.code=='F05' and v.version=='2.1-quantitative' for v in candidates)
    for v in candidates:
        if has_quantitative and v.instrument.code=='F05' and v.version!='2.1-quantitative':continue
        chosen.setdefault(v.instrument_id,v.pk)
    return real.filter(pk__in=chosen.values())
