from decimal import Decimal,ROUND_CEILING,ROUND_HALF_UP
from app.modules.contract.service import instant
from app.errors import RuleError

CENT=Decimal('.01')
POLICIES=('whole_call','per_period')

def select_tariff(zone,start,tariffs):
    t=instant(start);found=[r for r in tariffs if r['zone']==zone and instant(r['start'])<=t<instant(r['end'])]
    if len(found)!=1:raise RuleError('TARIFF','资费版本重叠或未覆盖')
    return found[0]

def charge_minutes(count,tiers):
    if not tiers or tiers[-1]['minutes'] is not None:raise RuleError('TARIFF','阶梯资费缺少最后无限档')
    remaining=count;fee=Decimal(0);parts=[]
    for tier in tiers:
        cap=tier['minutes'];take=remaining if cap is None else min(remaining,int(cap));rate=Decimal(tier['rate'])
        if rate<0 or (cap is not None and int(cap)<=0):raise RuleError('TARIFF','资费阶梯必须为正')
        fee+=take*rate;remaining-=take
        if take:parts.append({'minutes':take,'rate':str(rate),'fee':str(take*rate)})
    return {'fee':fee,'tiers':parts}

def charge(active_seconds,tiers):
    count=int((Decimal(active_seconds)/60).to_integral_value(rounding=ROUND_CEILING));bill=charge_minutes(count,tiers)
    return {'billed_minutes':count,'fee':str(bill['fee'].quantize(CENT,rounding=ROUND_HALF_UP)),'tiers':bill['tiers']}

def cut_periods(zone,windows,tariffs):
    versions=sorted((r for r in tariffs if r['zone']==zone),key=lambda r:instant(r['start']));periods=[]
    for w in windows:
        cursor=instant(w['start']);last=instant(w['end'])
        while cursor<last:
            found=[r for r in versions if instant(r['start'])<=cursor<instant(r['end'])]
            if len(found)!=1:raise RuleError('TARIFF','资费版本重叠或未覆盖')
            edge=min(instant(found[0]['end']),last)
            if periods and periods[-1]['version'] is found[0]:periods[-1]['end']=edge;periods[-1]['seconds']+=Decimal(str((edge-cursor).total_seconds()))
            else:periods.append({'version':found[0],'start':cursor,'end':edge,'seconds':Decimal(str((edge-cursor).total_seconds()))})
            cursor=edge
    return periods

def allocate(total_seconds,parts):
    total=int((Decimal(total_seconds)/60).to_integral_value(rounding=ROUND_CEILING))
    exact=[Decimal(p)/60 for p in parts];base=[int(e) for e in exact];rest=total-sum(base)
    order=sorted(range(len(parts)),key=lambda i:(exact[i]-base[i],-i),reverse=True)
    for i in order[:rest]:base[i]+=1
    return base

def bill_periods(session,tariffs):
    periods=cut_periods(session['zone'],session['windows'],tariffs)
    minutes=allocate(session['active_seconds'],[p['seconds'] for p in periods]);out=[]
    for p,count in zip(periods,minutes):
        bill=charge_minutes(count,p['version']['tiers'])
        out.append({'version':p['version']['version'],'start':p['start'].isoformat(),'end':p['end'].isoformat(),'active_seconds':str(p['seconds']),'billed_minutes':count,'fee':str(bill['fee'].quantize(CENT,rounding=ROUND_HALF_UP)),'tiers':bill['tiers']})
    return out
