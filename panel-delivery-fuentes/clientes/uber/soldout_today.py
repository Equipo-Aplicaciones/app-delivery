"""Mark 'Promo Fajita - Coca Cola - Benedictino' sold out until tomorrow 04:00 store-local
(same as Menu Maker 'hide_for_day'), via upsertMenus ITEM update. Touches only suspensionInfo."""
import sys,json,copy,datetime
from zoneinfo import ZoneInfo
sys.path.insert(0,'/workspace/uber_client')
from rw import c,MM
NAME='Promo Fajita - Coca Cola - Benedictino'
def call(op,sid,body):
    r=c.s.post(MM+op,params={"localeCode":"en","restaurantUUID":sid},json=body,timeout=120,allow_redirects=False)
    return r.json()
def find(sid):
    md=call('getMenuData',sid,{"storeUUID":sid,"shouldLoadItems":True,"offeringTypes":["INSTANT"]})
    if md.get('status')!='success': raise RuntimeError('getMenuData: '+str(md)[:200])
    d=md['data']; hits=[]
    for mu,m in d['menus'].items():
        for u,it in ((m.get('entities') or {}).get('itemsMap') or {}).items():
            if ((it.get('itemInfo') or {}).get('title') or {}).get('defaultValue','').strip().lower()==NAME.lower(): hits.append(it)
    return d,hits
def until_iso(tz):
    now=datetime.datetime.now(ZoneInfo(tz))
    t=(now+datetime.timedelta(days=1)).replace(hour=4,minute=0,second=0,microsecond=0)
    return t.isoformat()
def apply(sid):
    bl=call('hydrateBusinessLocation',sid,{"storeUUID":sid})['data']
    assert bl['restaurantUUID']==sid
    d,hits=find(sid)
    if not hits: return 'not_carried',None
    if len(hits)>1: return 'ambiguous',[h['uuid'] for h in hits]
    it=copy.deepcopy(hits[0]); iso=until_iso(bl.get('timezone') or 'America/Santiago')
    si=it.get('suspensionInfo') or {}
    it['suspensionInfo']={**si,"defaultValue":{**(si.get('defaultValue') or {}),"suspendUntil":"","suspendReason":"","suspendUntilMilliseconds":iso}}
    mt=d['menuMapping'][0]['menuType']
    body={"changes":[{"action":"update","menuType":mt,"type":"item","data":it}],"cityId":bl['regionId'],
          "internalTags":bl.get('internalTags') or [],"countryCode":bl['iso2'],"storeUUID":sid,"shouldLoadItems":True,"offeringTypes":["INSTANT"]}
    r=call('upsertMenus',sid,body)
    ok=r.get('status')=='success' and (r.get('data') or {}).get('meta',{}).get('success',True)!=False
    if not ok: return 'upsert_failed',str(r)[:300]
    _,h2=find(sid)
    v=(h2[0].get('suspensionInfo') or {}).get('defaultValue') or {}
    return ('ok' if v.get('suspendUntilMilliseconds') and datetime.datetime.fromisoformat(v['suspendUntilMilliseconds'].replace('Z','+00:00'))>datetime.datetime.now(datetime.timezone.utc) else 'verify_failed'), {"uuid":it['uuid'],"sent":iso,"read_back":v.get('suspendUntilMilliseconds')}
if __name__=='__main__':
    for sid in sys.argv[1:]:
        try: print(json.dumps([sid,*apply(sid)]),flush=True)
        except Exception as e: print(json.dumps([sid,'error',str(e)[:200]]),flush=True)
