"""Lectura de evidencia (fotos del cliente / evidencia de disputa) de pedidos Uber Eats. Solo lectura."""
import json, os, re
import requests
SV2 = "issueType itemIssueType subIssueType quantity isChargeback imageFeedbacks { url processedUrl accepted source } resolutionFeedback { text } isMerchantAtFault aiExplanation commentFeedbacks { text source }"
Q_OD = """query OrderDetails($workflowUUID: ID!, $shouldEnableChargebackComms: Boolean, $detailsRequestedByRestaurantUUID: ID) {
 orderDetails(workflowUUID: $workflowUUID, shouldEnableChargebackComms: $shouldEnableChargebackComms, detailsRequestedByRestaurantUUID: $detailsRequestedByRestaurantUUID) {
  orderId orderUUID requestedAt restaurant { name uuid } storeInstructions
  issueSummaryV2 { issueType itemIssueType postDeliveryState statusDescription isMerchantAtFault aiExplanation imageFeedbacks resolutionFeedback chargebackIssuedAt }
  items { name quantity price specialInstructions supportV2 { %s } }
  chargebackDisputeV2 { disputeUuid value disputeStatus disputeAmount disputedItems { name quantity } }
  disputeEligibilityCheck { disputeEligibility disputeFlow }
 } }""" % SV2
Q_DS = """query DisputeStatus($workflowUUID: ID!, $restaurantUUID: ID!) { disputeStatus(workflowUUID: $workflowUUID, restaurantUUID: $restaurantUUID) {
 issueType disputeUuid value disputeStatus disputeCreatedAt disputeResolvedAt disputeReason disputeDescription evidenceUrls disputedItems { name quantity } disputeAmount } }"""

def collect(gql, workflow_uuid, order_uuid, restaurant_uuid):
    out = {"workflow_uuid": workflow_uuid}
    try:
        out["order"] = gql("OrderDetails", Q_OD, {"workflowUUID": workflow_uuid, "shouldEnableChargebackComms": True,
                                                  "detailsRequestedByRestaurantUUID": restaurant_uuid})["orderDetails"]
    except Exception as e: out["order_error"] = str(e)[:200]
    order_uuid = order_uuid or (out.get("order") or {}).get("orderUUID")
    try:
        out["dispute"] = gql("DisputeStatus", Q_DS, {"workflowUUID": order_uuid, "restaurantUUID": restaurant_uuid})["disputeStatus"]
    except Exception as e: out["dispute_error"] = str(e)[:200]
    cust, store, comments = [], [], []
    def walk(x):
        if isinstance(x, dict):
            for f in x.get("imageFeedbacks") or []:
                u = f if isinstance(f, str) else (isinstance(f, dict) and (f.get("processedUrl") or f.get("url")))
                if u and u not in cust: cust.append(u)
            rf = x.get("resolutionFeedback")
            if isinstance(rf, dict) and rf.get("text") and rf not in comments: comments.append({"text": rf["text"], "source": "resolutionFeedback"})
            for c in x.get("commentFeedbacks") or []:
                if isinstance(c, dict) and c.get("text"): comments.append(c)
            for v in x.values(): walk(v)
        elif isinstance(x, list):
            for v in x: walk(v)
    walk(out.get("order"))
    store = list((out.get("dispute") or {}).get("evidenceUrls") or [])
    out["customer_images"], out["customer_comments"], out["store_evidence"] = cust, comments, store
    return out

def download(urls, folder, session=None):
    os.makedirs(folder, exist_ok=True); saved = []
    s = session or requests.Session()
    for i, u in enumerate(urls, 1):
        r = s.get(u, timeout=60)
        ct = r.headers.get("content-type", "")
        ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "video/mp4": ".mp4", "image/heic": ".heic"}.get(ct.split(";")[0], os.path.splitext(u.split("?")[0])[1] or ".bin")
        p = os.path.join(folder, f"{i:02d}{ext}")
        if r.status_code == 200 and r.content:
            open(p, "wb").write(r.content); saved.append({"path": p, "content_type": ct, "bytes": len(r.content)})
        else: saved.append({"url_status": r.status_code})
    return saved
