import sys,json,copy,datetime
sys.path.insert(0,'/workspace/uber_client')
from soldout_today import call,find
def apply(sid):
    bl=call('hydrateBusinessLocation',sid,{"storeUUID":sid})['data']; assert bl['restaurantUUID']==sid
    d,hits=find(sid)
    if len(hits)!=1: return 'not_found',len(hits)
    it=copy.deepcopy(hits[0]); si=it.get('suspensionInfo') or {}
    it['suspensionInfo']={**si,"defaultValue":{**(si.get('defaultValue') or {}),"suspendUntil":None,"suspendReason":None,"suspendUntilMilliseconds":None}}
    body={"changes":[{"action":"update","menuType":d['menuMapping'][0]['menuType'],"type":"item","data":it}],"cityId":bl['regionId'],
          "internalTags":bl.get('internalTags') or [],"countryCode":bl['iso2'],"storeUUID":sid,"shouldLoadItems":True,"offeringTypes":["INSTANT"]}
    r=call('upsertMenus',sid,body)
    if r.get('status')!='success' or (r.get('data') or {}).get('meta',{}).get('success',True)==False: return 'upsert_failed',str(r)[:300]
    _,h2=find(sid); v=((h2[0].get('suspensionInfo') or {}).get('defaultValue') or {}).get('suspendUntilMilliseconds')
    active=not v or datetime.datetime.fromisoformat(v.replace('Z','+00:00'))<=datetime.datetime.now(datetime.timezone.utc)
    return ('ok' if active else 'verify_failed'),v
for sid in sys.argv[1:]:
    for a in range(2):
        try: res=apply(sid); break
        except Exception as e: res=('error',str(e)[:150])
    print(json.dumps([sid,*res]),flush=True)
