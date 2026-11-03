from datetime import date, timedelta
from unittest.mock import patch
import httpx

def demo(client):
    r=client.post('/api/auth/demo')
    assert r.status_code==200,r.text
    return client.get('/api/fields').json()[0]

def test_demo_reference_and_idempotent_calculation(client):
    f=demo(client); r=f['recommendation']
    assert r['deficit']==41 and r['volume']==362.5
    path=f"/api/fields/{f['id']}/calculate"
    data={'day':r['day'],'eto':4/1.2,'effective_rain':2}
    for _ in range(2):
        result=client.post(path,json=data).json()
        assert result['deficit']==41 and result['volume']==362.5

def test_irrigation_replay_edit_delete_and_deduplication(client):
    f=demo(client); base=f"/api/fields/{f['id']}"; day=f['recommendation']['day']
    data=dict(day=day,status='planned',planned_volume=362.5,actual_volume=None,request_key='unique-operation-1')
    planned=client.post(base+'/irrigations',json=data).json()
    assert client.get(base).json()['recommendation']['deficit']==41
    assert client.post(base+'/irrigations',json=data).json()['id']==planned['id']
    data.update(status='completed',actual_volume=362.5)
    assert client.put(base+f"/irrigations/{planned['id']}",json=data).status_code==200
    assert client.get(base).json()['recommendation']['deficit']==12
    assert client.get(base).json()['recommendation']['volume']==0
    client.post(base+'/calculate',json={'day':day,'eto':4/1.2,'effective_rain':2})
    assert client.get(base).json()['recommendation']['deficit']==12
    data['actual_volume']=125
    client.put(base+f"/irrigations/{planned['id']}",json=data)
    assert client.get(base).json()['recommendation']['deficit']==31
    client.delete(base+f"/irrigations/{planned['id']}")
    assert client.get(base).json()['recommendation']['deficit']==41

def test_isolation(client):
    f=demo(client); fid=f['id']; crop=f['crop_id']
    client.post('/api/auth/logout')
    assert client.get(f'/api/fields/{fid}').status_code==401
    demo(client)
    for suffix in ['', '/weather','/recommendations','/irrigations','/analytics','/balance-days']:
        assert client.get(f'/api/fields/{fid}'+suffix).status_code==404
    assert client.delete(f'/api/fields/{fid}').status_code==404
    assert client.post(f'/api/fields/{fid}/calculate',json={'day':f['balance_start'],'eto':4,'effective_rain':0}).status_code==404
    c=client.get('/api/crops').json()[0]
    assert client.put(f'/api/crops/{crop}',json=c).status_code==404

def test_register_login_password_profile(client):
    data=dict(email='farmer@example.com',name='Фермер',password='Password123!')
    response=client.post('/api/auth/register',json=data)
    assert response.status_code==201,response.text
    assert 'HttpOnly' in response.headers['set-cookie']
    assert client.get('/api/crops').status_code==200
    assert client.put('/api/auth/profile',json={'name':'Богдан'}).json()['name']=='Богдан'
    assert client.post('/api/auth/password',json={'current_password':data['password'],'new_password':'NewPassword123!'}).status_code==200
    client.post('/api/auth/logout')
    assert client.post('/api/auth/login',json=data).status_code==401
    data['password']='NewPassword123!'
    assert client.post('/api/auth/login',json=data).status_code==200
    assert client.get('/api/auth/me').json()['name']=='Богдан'

def test_field_validation_and_missing_parameters(client):
    f=demo(client)
    f['name']='Новый участок'
    for key,value in [('area',0),('efficiency',0),('efficiency',1.1),('initial_deficit',101),('p',-1),('timezone','Wrong/Zone')]:
        assert client.post('/api/fields',json={**f,key:value}).status_code==422
    f.update(taw=None,p=None,initial_deficit=None,target_deficit=None)
    response=client.post('/api/fields',json=f)
    assert response.status_code==201,response.text
    field=response.json()
    assert field['recommendation']['status']=='insufficient'
    assert client.post(f"/api/fields/{field['id']}/calculate",json={'day':field['balance_start'],'eto':4,'effective_rain':0}).status_code==422

def test_gap_and_forecast_never_changes_today(client):
    f=demo(client);base=f"/api/fields/{f['id']}";day=date.fromisoformat(f['balance_start'])
    data={'day':(day+timedelta(days=2)).isoformat(),'eto':5,'effective_rain':0}
    assert client.post(base+'/calculate',json=data).json()['status']=='insufficient'
    assert client.get(base).json()['recommendation']['deficit']==41
    data['day']=(day+timedelta(days=1)).isoformat()
    assert client.post(base+'/calculate',json=data).json()['forecast']
    assert len(client.get(base+'/recommendations').json())==3
    assert client.get(base).json()['recommendation']['deficit']==41

def test_future_and_negative_irrigation(client):
    f=demo(client);path=f"/api/fields/{f['id']}/irrigations"
    data=dict(day=(date.fromisoformat(f['balance_start'])+timedelta(days=1)).isoformat(),status='completed',planned_volume=1,actual_volume=1,request_key='invalid-operation')
    assert client.post(path,json=data).status_code==422
    data.update(day=f['balance_start'],actual_volume=-1)
    assert client.post(path,json=data).status_code==422
    data['actual_volume']=None
    assert client.post(path,json=data).status_code==422

def test_csrf_and_rate_limit(client):
    assert client.post('/api/auth/demo',headers={'Origin':'https://evil.example'}).status_code==403
    for _ in range(10):
        assert client.post('/api/auth/login',json={'email':'x@example.com','password':'wrong'}).status_code==401
    assert client.post('/api/auth/login',json={'email':'x@example.com','password':'wrong'}).status_code==429

def test_weather_failure_retains_cache(client):
    f=demo(client)
    # A normal account uses the external provider; create its field from demo parameters.
    client.post('/api/auth/logout')
    client.post('/api/auth/register',json={'email':'weather@example.com','name':'Погода','password':'Password123!'})
    f['crop_id']=client.get('/api/crops').json()[1]['id']
    f=client.post('/api/fields',json=f).json()
    path=f"/api/fields/{f['id']}"
    with patch('app.main.httpx.Client.get',side_effect=httpx.ConnectError('offline')):
        w=client.post(path+'/weather/refresh').json()
    assert w['error'] and w['days']==[] and w['stale']
    assert client.post(path+'/calculate',json={'day':f['balance_start'],'effective_rain':0}).status_code==422
    assert client.post(path+'/calculate',json={'day':f['balance_start'],'eto':4,'effective_rain':0}).status_code==200

def test_openapi_routes(client):
    paths=client.get('/openapi.json').json()['paths']
    assert '/api/fields/{field_id}/calculate' in paths
    assert '/api/fields/{field_id}/analytics' in paths

def test_location_change_requires_new_weather_and_calculation(client):
    f=demo(client)
    f['latitude']+=1
    changed=client.put(f"/api/fields/{f['id']}",json=f)
    assert changed.status_code==200
    assert changed.json()['recommendation']['status']=='insufficient'
    assert client.get(f"/api/fields/{f['id']}/weather").json()['days']==[]
    result=client.post(f"/api/fields/{f['id']}/calculate",json={'day':f['balance_start'],'eto':4/1.2,'effective_rain':2})
    assert result.json()['deficit']==41

def test_timestamps_include_timezone(client):
    f=demo(client)
    assert f['recommendation']['computed_at'].endswith('+00:00')
    history=client.get(f"/api/fields/{f['id']}/recommendations").json()
    assert history[0]['computed_at'].endswith('+00:00')
