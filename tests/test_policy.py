from decimal import Decimal
import pytest
from app import store
from app.pipeline import execute,sample_bytes
from app.modules.calculate.service import calculate
from app.modules.calculate.tariff import allocate
from app.errors import RuleError

@pytest.fixture
def boundary():return execute(sample_bytes('boundary'),'per_period')
@pytest.fixture
def boundary_whole():return execute(sample_bytes('boundary'))

def row(bundle,sid):return next(r for r in bundle['calculate']['rows'] if r['session']==sid)

def test_allocate_rounds_once():
    """TRAP-27:整通只向上取整一次,分钟按最大余数法分摊"""
    assert allocate(60,[Decimal(30),Decimal(30)])==[1,0]
    assert allocate(90,[Decimal(60),Decimal(30)])==[1,1]
    assert sum(allocate(150,[Decimal(45),Decimal(45),Decimal(60)]))==3

def test_split_at_version_boundary(boundary):
    s=row(boundary,'B00001')
    assert [p['version'] for p in s['periods']]==['国内-2026','国内-2026B']
    assert [p['active_seconds'] for p in s['periods']]==['60.0','30.0']
    assert [p['billed_minutes'] for p in s['periods']]==[1,1]
    assert s['fee']=='0.45' and s['tariff_version']=='国内-2026→国内-2026B'

def test_whole_call_keeps_start_version(boundary_whole):
    s=row(boundary_whole,'B00001')
    assert s['tariff_version']=='国内-2026' and s['fee']=='0.40' and len(s['periods'])==1

def test_no_double_ceiling(boundary):
    """TRAP-27:两段各20秒跨生效点,整通40秒只计1分钟"""
    s=row(boundary,'B00004')
    assert s['billed_minutes']==1 and s['fee']=='0.20'
    assert [p['billed_minutes'] for p in s['periods']]==[1,0]

def test_gap_merges_same_version(boundary):
    s=row(boundary,'B00003')
    assert [p['version'] for p in s['periods']]==['漫游-2026','漫游-2026B']
    assert [p['active_seconds'] for p in s['periods']]==['60.0','40.0']
    assert s['fee']=='3.10'

def test_policy_totals(boundary,boundary_whole):
    assert boundary['calculate']['total_fee']=='3.95'
    assert boundary_whole['calculate']['total_fee']=='3.80'
    assert boundary['calculate']['minutes']==boundary_whole['calculate']['minutes']==6

def test_segments_tie_out(boundary):
    assert boundary['reconcile']['segments_balanced'] and boundary['reconcile']['balanced']
    for r in boundary['calculate']['rows']:
        assert sum((Decimal(p['fee']) for p in r['periods']),Decimal(0))==Decimal(r['fee'])
        assert sum(p['billed_minutes'] for p in r['periods'])==r['billed_minutes']
        assert sum((Decimal(p['active_seconds']) for p in r['periods']),Decimal(0))==Decimal(r['active_seconds'])

def test_uncovered_span_isolated(clean):
    session={'session':'X1','subscriber':'00000001','zone':'国内','start':'2026-12-31T23:59:00+08:00','sources':[7,8],'fragments':2,'active_seconds':'120.0','raw_seconds':'120.0','overlap_seconds':'0.0','gap_seconds':'0.0','windows':[{'start':'2026-12-31T23:59:00+08:00','end':'2027-01-01T00:01:00+08:00'}]}
    tariffs=clean['contract']['tariffs'];r=calculate([session],tariffs,'per_period')
    assert r['rows']==[] and sorted(i['line'] for i in r['issues'])==[7,8]
    assert len(calculate([session],tariffs,'whole_call')['rows'])==1

def test_unknown_policy_rejected(clean):
    with pytest.raises(RuleError) as e:calculate(clean['model']['sessions'],clean['contract']['tariffs'],'bogus')
    assert e.value.code=='POLICY'

def test_rerun_same_batch_no_double_billing(client):
    a=client.post('/api/runs',json={'sample':'boundary','policy':'per_period'}).json()
    b=client.post('/api/runs',json={'sample':'boundary','policy':'per_period'}).json()
    assert a['manifest']['run_id']==b['manifest']['run_id'] and b['calculate']['total_fee']=='3.95'
    ids=[h['id'] for h in store.history()];assert len(ids)==len(set(ids))

def test_policy_switch_creates_new_run(client):
    a=client.post('/api/runs',json={'sample':'boundary'}).json()
    b=client.post('/api/runs',json={'sample':'boundary','policy':'per_period'}).json()
    assert a['manifest']['run_id']!=b['manifest']['run_id']
    assert {h['id'] for h in store.history()}>={a['manifest']['run_id'],b['manifest']['run_id']}

def test_failed_switch_preserves_previous(client):
    """TRAP-28:切换失败保留上一版与全部分片"""
    client.post('/api/runs',json={'sample':'clean'})
    before=store.latest();depth=len(store.history())
    assert client.post('/api/runs',json={'sample':'boundary','policy':'bogus'}).status_code==422
    assert client.post('/api/runs',json={'csv_text':'invalid','policy':'per_period'}).status_code==422
    after=store.latest()
    assert after['manifest']['run_id']==before['manifest']['run_id'] and len(store.history())==depth
    assert after['model']['rows']==before['model']['rows']
    assert after['calculate']['accepted_fragments']==before['calculate']['accepted_fragments']
    assert after['quarantine']['total']==before['quarantine']['total']

def test_reconcile_page_lists_segments(client):
    client.post('/api/runs',json={'sample':'boundary','policy':'per_period'})
    r=client.get('/reconcile')
    assert r.status_code==200 and '国内-2026B' in r.text and 'per_period' in r.text
