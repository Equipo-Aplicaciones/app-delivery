import os,requests,json,sys
sys.path.insert(0,'/workspace/uber_client')
from api_client import UberEatsClient
c=UberEatsClient()
def post(op,body):
    r=c.s.post("https://merchants.ubereats.com/manager/api/"+op,params={"localeCode":"en"},json=body,timeout=60,allow_redirects=False)
    try: return r.status_code,r.json()
    except Exception: return r.status_code,r.text[:300]
MM="https://merchants.ubereats.com/manager/menumaker/api/"
def mm(op,body):
    r=c.s.post(MM+op,params={"localeCode":"en"},json=body,timeout=90,allow_redirects=False)
    try: return r.status_code,r.json()
    except Exception: return r.status_code,{"raw":r.text[:300]}
def title(it):
    t=(it.get('itemInfo') or {}).get('title') or it.get('title') or {}
    return t.get('defaultValue') if isinstance(t,dict) else t
