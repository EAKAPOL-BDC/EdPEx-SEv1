"""Pool compatible, disclosed F05 totals; never average subgroup averages."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from .f05_quantitative import VERSION
from .f05_registry import is_quantitative_version


def pooled_result(rows, rosters):
    """Caller supplies one compatibility group and frozen eligibility sets by run ID.

    Roster sets are checked only for overlap; they are never joined to answers or
    returned. Suppressed results cannot contribute to a pooled disclosure.
    """
    if not rows or any(not is_quantitative_version(r.get('form_version','')) or r.get('form')!='F05' for r in rows):return None
    def hidden(reason):return {'available':False,'reason':reason}
    if len(rows)!=2 or {r['group'] for r in rows}!={'ST1','ST2'}:
        return hidden('ต้องมีผลที่เข้ากันได้เพียงหนึ่งรอบต่อกลุ่ม ST1 และ ST2 / Require one compatible result per staff group.')
    if any(r.get('status')=='suppressed' or not r.get('has_value') for r in rows):
        return hidden('ยังรวมไม่ได้ เพราะผลบางกลุ่มถูกจำกัดการแสดงหรือยังไม่มีข้อมูล / A group result is restricted or unavailable.')
    seen=set()
    for row in rows:
        roster=rosters.get(str(row['run_id']))
        if roster is None or seen.intersection(roster):
            return hidden('รายชื่อผู้มีสิทธิ์ของรอบซ้ำกันหรือยังตรวจไม่ครบ กรุณาตรวจรอบต้นทาง / Overlapping or unverified eligibility rosters.')
        seen.update(roster)
    try:
        numerator=sum((Decimal(r['numerator']) for r in rows),Decimal(0))
        denominator=sum((Decimal(r['denominator']) for r in rows),Decimal(0))
        if not numerator.is_finite() or not denominator.is_finite() or denominator<=0:raise ValueError
        with localcontext() as ctx:
            ctx.prec=50
            value=numerator/denominator*(100 if rows[0]['unit']=='percent' else 1)
        shown=format(value.quantize(Decimal('0.01'),rounding=ROUND_HALF_UP),'f')
    except (InvalidOperation,ValueError,KeyError):return hidden('ข้อมูลผลรวมไม่ครบ / Totals are incomplete.')
    return {'available':True,'value':str(value),'display_value':shown,'numerator':str(numerator),'denominator':str(denominator),'suffix':rows[0]['suffix']}
