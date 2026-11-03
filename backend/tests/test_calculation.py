import math
from datetime import date, timedelta
from types import SimpleNamespace
import pytest
from app.calculation import calculate, crop_stage

BASE = dict(taw=100,p=.4,previous_deficit=39,eto=4,kc=1,effective_rain=2,target_deficit=12,efficiency=.8,area=1)

def test_tz_reference():
    result=calculate(**BASE)
    assert result == dict(etc=4,deficit=41,raw=40,needed=True,net=29,gross=36.25,volume=362.5)

@pytest.mark.parametrize('key,value',[('efficiency',0),('efficiency',1.1),('area',0),('taw',0),('p',-1),('effective_rain',-1),('previous_deficit',101),('target_deficit',101),('eto',math.nan),('kc',math.inf)])
def test_invalid(key,value):
    with pytest.raises(ValueError):
        calculate(**{**BASE,key:value})

def test_no_irrigation_and_clamping():
    r=calculate(**{**BASE,'effective_rain':100})
    assert r['deficit']==0 and r['volume']==0 and not r['needed']
    assert calculate(**{**BASE,'eto':200})['deficit']==100

def test_threshold_equality():
    assert calculate(**{**BASE,'previous_deficit':38})['needed']

def test_stage_interpolation_and_season():
    c=SimpleNamespace(days_initial=20,days_development=30,days_mid=40,days_late=20,kc_initial=.3,kc_mid=1.2,kc_end=.4)
    start=date(2026,1,1)
    assert crop_stage(c,start,start-timedelta(days=1))[0] is None
    assert crop_stage(c,start,start+timedelta(days=35))[0]==pytest.approx(.75)
    assert crop_stage(c,start,start+timedelta(days=100))[0]==pytest.approx(.8)
    assert crop_stage(c,start,start+timedelta(days=110))[0] is None
