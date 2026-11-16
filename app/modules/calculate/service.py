from decimal import Decimal
from app.modules.calculate.tariff import POLICIES,select_tariff,charge,bill_periods
from app.errors import RuleError

def calculate(sessions,tariffs,policy='whole_call'):
    if policy not in POLICIES:raise RuleError('POLICY','计费策略应为 whole_call 或 per_period')
    rows=[];issues=[]
    for session in sessions:
        try:
            if policy=='per_period':
                periods=bill_periods(session,tariffs)
                bill={'billed_minutes':sum(p['billed_minutes'] for p in periods),'fee':str(sum((Decimal(p['fee']) for p in periods),Decimal(0)).quantize(Decimal('.01'))),'tiers':[dict(t,version=p['version']) for p in periods for t in p['tiers']]}
            else:
                version=select_tariff(session['zone'],session['start'],tariffs);bill=charge(session['active_seconds'],version['tiers'])
                periods=[{'version':version['version'],'start':session['windows'][0]['start'],'end':session['windows'][-1]['end'],'active_seconds':session['active_seconds'],'billed_minutes':bill['billed_minutes'],'fee':bill['fee'],'tiers':bill['tiers']}]
            rows.append(dict(session,**bill,periods=periods,tariff_version='→'.join(dict.fromkeys(p['version'] for p in periods)),currency='CNY'))
        except RuleError as e:
            issues.extend({'line':line,'code':e.code,'raw':session} for line in session['sources'])
    return {'rows':rows,'issues':issues,'policy':policy,'total_fee':str(sum((Decimal(r['fee']) for r in rows),Decimal(0)).quantize(Decimal('.01'))),'minutes':sum(r['billed_minutes'] for r in rows),'sessions':len(rows),'accepted_fragments':sum(r['fragments'] for r in rows)}
