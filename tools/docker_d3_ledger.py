"""Bounded private accounting evidence for the two owned D3 browser jobs.

The installed probe never imports the application, changes SQL rows, or returns
prompts, settings, credentials, raw metadata, or truncated identifier matches.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import time

from tools.docker_shadow_product import ProductFlow, path_id, require

QUERY = r'''
import hashlib,json,re,sqlite3,time
def capture(conn,owner,job_ids):
 def check(ok):
  if not ok: raise RuntimeError('D3_PRIVATE_LEDGER_INVALID')
 def identifier(value):
  check(isinstance(value,str) and re.fullmatch(r'[A-Za-z0-9_-]{1,120}',value))
  return hashlib.sha256(value.encode()).hexdigest()
 def optional(value): return None if value is None else identifier(value)
 check(isinstance(owner,list) and len(owner)==2)
 owner_hashes=[identifier(value) for value in owner]
 check(isinstance(job_ids,list) and len(job_ids)<=2 and len(set(job_ids))==len(job_ids))
 wanted={identifier(value) for value in job_ids}
 started=time.monotonic()
 conn.row_factory=sqlite3.Row
 conn.set_progress_handler(lambda: int(time.monotonic()-started>3),1000)
 conn.execute('PRAGMA query_only=ON')
 check(conn.execute('PRAGMA query_only').fetchone()[0]==1)
 conn.execute('BEGIN')
 try:
  user=conn.execute('SELECT token_balance,daily_tokens_used,tokens_used,generation_count,last_daily_reset '
      'FROM users WHERE id=? AND internal_user_id=?',owner).fetchone()
  check(user is not None)
  account=dict(user)
  check(all(type(value) is int and value>=0 for key,value in account.items() if key!='last_daily_reset'))
  check(isinstance(account['last_daily_reset'],str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}',account['last_daily_reset']))
  marks=','.join('?' for _ in job_ids) or 'NULL'
  jobs={identifier(row['id']):{'mode':row['mode'],'provider':row['provider'],'status':row['status']}
      for row in conn.execute('SELECT id,mode,provider,status FROM jobs WHERE user_id=? AND id IN ('+marks+')',
                              [owner[0],*job_ids])}
  check(set(jobs)==wanted)
  check(all(row['mode'] in {'text_to_image','text_to_video','edit','paint','faceswap'} and row['provider'] in {'comfyui','local_ltx'}
      and row['status'] in {'queued','submitting','running','uploading','sent_to_comfyui','pending','finalizing',
                           'completed','failed','cancelled'} for row in jobs.values()))
  rows=conn.execute('SELECT id,delta,reason,created_at,length(CAST(meta_json AS BLOB)) AS meta_bytes,'
      'CASE WHEN length(CAST(meta_json AS BLOB))<=16384 THEN meta_json ELSE NULL END AS meta_json '
      'FROM token_ledger WHERE user_id=? ORDER BY id LIMIT 65',(owner[0],)).fetchall()
  check(len(rows)<=64)
  ledger=[]
  for row in rows:
   check(type(row['delta']) is int and type(row['meta_bytes']) is int and 0<=row['meta_bytes']<=16384)
   meta=json.loads(row['meta_json'] or '{}');check(isinstance(meta,dict))
   job=meta.get('jobId',meta.get('job_id'))
   check('jobId' not in meta or 'job_id' not in meta or meta['jobId']==meta['job_id'])
   reason=row['reason'] if row['reason'] in {'generation','daily_generation','generation_refund',
       'daily_generation_refund','free_chat','chat_refund'} else 'OTHER'
   item={'idSha256':identifier(row['id']),
       'rowSha256':hashlib.sha256(json.dumps(dict(row),sort_keys=True,separators=(',',':')).encode()).hexdigest(),
       'jobSha256':optional(job),'requestSha256':optional(meta.get('request_id')),
       'chargedLedgerSha256':optional(meta.get('charged_ledger_id')),'delta':row['delta'],'reason':reason,
       'mode':meta.get('mode') if meta.get('mode') in {'text_to_image','text_to_video','phone_chat','edit','paint','faceswap'} else None,
       'provider':meta.get('provider') if meta.get('provider') in {'comfyui','local_ltx','local'} else None}
   for field,key in (('tokenCost','token_cost'),('dailyPart','daily_part'),('balancePart','balance_part'),
                     ('refundTokens','refund_tokens')):
    value=meta.get(key)
    check(value is None or (type(value) in {int,float} and value==value and 0<=value<=2**53-1))
    item[field]=value
   ledger.append(item)
  active=conn.execute("SELECT COUNT(*) FROM jobs WHERE user_id=? AND status NOT IN ('completed','failed','cancelled')",
                      (owner[0],)).fetchone()[0]
  return {'version':1,'ownerSha256':owner_hashes,'requestedJobSha256':sorted(wanted),'account':account,'jobs':jobs,
      'ledger':ledger,'activeOwnedJobs':active,'queryOnly':True,'capturedAt':time.time()}
 finally:
  conn.rollback();conn.set_progress_handler(None,0)
'''

READ_LEDGER = QUERY + r'''
import os,stat,sys
try:
 payload=json.loads(sys.argv[1])
 assert isinstance(payload,list) and len(payload)==2
 info=os.lstat('/home/izo/data/app.sqlite3')
 assert stat.S_ISREG(info.st_mode) and info.st_uid==10001
 conn=sqlite3.connect('file:/home/izo/data/app.sqlite3?mode=ro',uri=True,timeout=2)
 try: result=capture(conn,*payload)
 finally: conn.close()
 data=json.dumps(result,separators=(',',':'),allow_nan=False).encode()
 assert len(data)<=65536
 sys.stdout.buffer.write(data)
except Exception:
 print('D3_PRIVATE_LEDGER_READ_FAILED',file=sys.stderr)
 sys.exit(1)
'''


def identifier_sha(value):
    return hashlib.sha256(path_id(value).encode()).hexdigest()


def validated(value):
    code = "D3_PRIVATE_LEDGER_RECEIPT_INVALID"
    fields = {"version", "ownerSha256", "requestedJobSha256", "account", "jobs", "ledger",
              "activeOwnedJobs", "queryOnly", "capturedAt"}
    require(isinstance(value, dict) and set(value) in (fields, fields | {"sourceSha", "project", "api"})
            and type(value.get("version")) is int and value["version"] == 1 and value.get("queryOnly") is True
            and type(value.get("activeOwnedJobs")) is int and value["activeOwnedJobs"] >= 0
            and type(value.get("capturedAt")) in {int, float} and math.isfinite(value["capturedAt"])
            and isinstance(value.get("account"), dict) and isinstance(value.get("jobs"), dict)
            and isinstance(value.get("ledger"), list) and len(value["ledger"]) <= 64, code)
    require(isinstance(value.get("ownerSha256"), list) and isinstance(value.get("requestedJobSha256"), list), code)
    hashes = value["ownerSha256"] + value["requestedJobSha256"]
    require(len(value["ownerSha256"]) == 2 and len(value["requestedJobSha256"]) <= 2
            and set(value["jobs"]) == set(value["requestedJobSha256"])
            and all(isinstance(item, str) and re.fullmatch(r"[a-f0-9]{64}", item) for item in hashes), code)
    fields = {"token_balance", "daily_tokens_used", "tokens_used", "generation_count", "last_daily_reset"}
    require(set(value["account"]) == fields and all(type(value["account"][key]) is int
            and value["account"][key] >= 0 for key in fields - {"last_daily_reset"})
            and isinstance(value["account"]["last_daily_reset"], str)
            and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value["account"]["last_daily_reset"]), code)
    for row in value["ledger"]:
        require(isinstance(row, dict) and type(row.get("delta")) is int
                and set(row) == {"idSha256", "rowSha256", "jobSha256", "requestSha256", "chargedLedgerSha256",
                    "delta", "reason", "mode", "provider", "tokenCost", "dailyPart", "balancePart", "refundTokens"}, code)
        for key in ("idSha256", "rowSha256", "jobSha256", "requestSha256", "chargedLedgerSha256"):
            require((row[key] is None and key not in {"idSha256", "rowSha256"})
                    or isinstance(row[key], str) and re.fullmatch(r"[a-f0-9]{64}", row[key]), code)
        require(row["reason"] in {"generation", "daily_generation", "generation_refund", "daily_generation_refund",
                    "free_chat", "chat_refund", "OTHER"}
                and row["mode"] in {None, "text_to_image", "text_to_video", "phone_chat", "edit", "paint", "faceswap"}
                and row["provider"] in {None, "comfyui", "local_ltx", "local"}, code)
        for key in ("tokenCost", "balancePart", "dailyPart", "refundTokens"):
            require(row[key] is None or type(row[key]) in {int, float}
                    and math.isfinite(row[key]) and 0 <= row[key] <= 2**53 - 1, code)
    require(len({row["idSha256"] for row in value["ledger"]}) == len(value["ledger"]), code)
    return value


def private_ledger_reader(shadow, images, flow, *, api_identity, wallclock):
    """Recheck the existing full owned API admission before each bounded read."""
    require(isinstance(flow, ProductFlow) and flow.project == shadow.project and flow.source_sha == shadow.sha
            and flow.owner.origin == flow.origin == f"http://127.0.0.1:{shadow.web_port}"
            and shadow.fixture is True, "D3_PRIVATE_LEDGER_OWNER_REQUIRED")
    principal = flow.owner.request("GET", "/api/me-v2")
    owner = [path_id(principal[key]) for key in ("legacy_user_id", "internal_user_id")]
    config = shadow.config()["services"]["backend"]
    require(config["environment"]["IZO_SHADOW_FIXTURE"] == "controlled-chat-video-v1",
            "D3_PRIVATE_LEDGER_PROFILE_REQUIRED")
    identity = api_identity(shadow, images, config)
    def read(job_ids):
        require(isinstance(job_ids, list) and len(job_ids) <= 2 and len(set(job_ids)) == len(job_ids),
                "D3_PRIVATE_LEDGER_JOB_BOUND")
        wanted = sorted(identifier_sha(value) for value in job_ids)
        with wallclock(8):
            require(api_identity(shadow, images, config) == identity, "D3_PRIVATE_LEDGER_API_CHANGED")
            raw = shadow.docker("exec", identity["containerId"], "python", "-c", READ_LEDGER,
                json.dumps([owner, job_ids]), timeout=8)
            require(isinstance(raw, str) and len(raw) <= 65536 and len(raw.encode("utf-8")) <= 65536,
                    "D3_PRIVATE_LEDGER_RECEIPT_LIMIT")
            value = validated(json.loads(raw))
            require(not any(key in value for key in ("sourceSha", "project", "api"))
                    and value["ownerSha256"] == [identifier_sha(item) for item in owner]
                    and value["requestedJobSha256"] == wanted and -1 <= time.time() - value["capturedAt"] <= 5,
                    "D3_PRIVATE_LEDGER_IDENTITY_MISMATCH")
            envelope = {**value, "sourceSha": shadow.sha, "project": shadow.project, "api": identity}
            require(len(json.dumps(envelope, separators=(",", ":")).encode()) <= 65536,
                    "D3_PRIVATE_LEDGER_RECEIPT_LIMIT")
            return envelope
    return read


def browser_job_ids(report):
    browser = report.get("browser", {})
    values = [report.get("image", {}).get("jobId"), browser.get("checks", {}).get("video", {}).get("jobId")]
    return [path_id(value) for value in values if value is not None]


def settle_private_ledger(before, after, browser):
    """Full-ID evidence supplements the public balance/summary browser checks."""
    validated(before); validated(after)
    require(all(key in before and key in after for key in ("sourceSha", "project", "api"))
            and all(before[key] == after[key] for key in ("ownerSha256", "sourceSha", "project", "api"))
            and before["requestedJobSha256"] == [] and before["activeOwnedJobs"] == after["activeOwnedJobs"] == 0
            and before["account"]["last_daily_reset"] == after["account"]["last_daily_reset"],
            "D3_PRIVATE_LEDGER_BASELINE_CHANGED")
    checks, image = browser["checks"], browser["image"]
    require(browser.get("status") == "PASS" and checks["chatImage"].get("jobId") == image["jobId"],
            "D3_PRIVATE_LEDGER_BROWSER_INCOMPLETE")
    specs = {"image": {"jobId": image["jobId"], "mode": "text_to_image", "provider": "comfyui",
                       "cost": image["tokenCost"], "accounting": checks["chatImage"]["accounting"]},
             "video": {"jobId": checks["video"]["jobId"], "mode": "text_to_video", "provider": "local_ltx",
                       "cost": checks["video"]["tokenCost"], "accounting": checks["video"]["accounting"]}}
    wanted = {identifier_sha(row["jobId"]) for row in specs.values()}
    require(len(wanted) == 2 and set(after["requestedJobSha256"]) == wanted, "D3_PRIVATE_LEDGER_JOBS_MISMATCH")
    old = {row["idSha256"]: row for row in before["ledger"]}
    current = {row["idSha256"]: row for row in after["ledger"]}
    require(all(current.get(key) == row for key, row in old.items())
            and not any(row["jobSha256"] in wanted for row in old.values()), "D3_PRIVATE_LEDGER_PRIOR_ROWS_CHANGED")
    added = [row for key, row in current.items() if key not in old]
    result, total_cost, total_balance, total_daily = {}, 0, 0, 0
    for name, spec in specs.items():
        job_hash = identifier_sha(spec["jobId"])
        rows = [row for row in added if row["jobSha256"] == job_hash]
        require(after["jobs"][job_hash] == {"mode": spec["mode"], "provider": spec["provider"], "status": "completed"}
                and len(rows) == 1, "D3_PRIVATE_LEDGER_SINGLE_CHARGE_NOT_PROVEN")
        row, public, cost = rows[0], spec["accounting"], spec["cost"]
        require(type(cost) is int and cost > 0 and type(row["tokenCost"]) is int and row["tokenCost"] == cost
                and all(type(row[key]) is int and row[key] >= 0 for key in ("balancePart", "dailyPart"))
                and row["balancePart"] + row["dailyPart"] == cost and row["delta"] == -row["balancePart"]
                and row["reason"] == ("daily_generation" if row["dailyPart"] == cost else "generation")
                and (row["mode"], row["provider"]) == (spec["mode"], spec["provider"])
                and row["refundTokens"] is None and row["requestSha256"] is None
                and row["chargedLedgerSha256"] is None, "D3_PRIVATE_LEDGER_DEBIT_INVALID")
        require(public.get("status") == "PASS" and type(public.get("tokenCost")) is int and public["tokenCost"] == cost
                and type(public.get("mainBalanceDebit")) is int and public["mainBalanceDebit"] == row["balancePart"]
                and type(public.get("dailyBudgetDebit")) is int and public["dailyBudgetDebit"] == row["dailyPart"]
                and type(public.get("refundDelta")) is int and public["refundDelta"] == 0,
                "D3_PRIVATE_PUBLIC_ACCOUNTING_MISMATCH")
        result[name] = {"jobIdSha256": job_hash, "chargeLedgerIdSha256": row["idSha256"],
            "fullIdMatch": True, "chargeCount": 1, "refundCount": 0, "tokenCost": cost,
            "mainBalanceDebit": row["balancePart"], "dailyBudgetDebit": row["dailyPart"]}
        total_cost += cost; total_balance += row["balancePart"]; total_daily += row["dailyPart"]
    chat = checks["chat"]
    requests = [chat[key] for key in ("firstRequestId", "secondRequestId", "failedRequestId")]
    requests.append(checks["chatImage"]["requestId"])
    request_hashes = {identifier_sha(value) for value in requests}
    free = [row for row in added if row["reason"] == "free_chat"]
    refunds = [row for row in added if row["reason"] == "chat_refund"]
    require(len(request_hashes) == len(free) == 4 and {row["requestSha256"] for row in free} == request_hashes
            and all(row["delta"] == row["tokenCost"] == row["dailyPart"] == row["balancePart"] == 0
                    and row["mode"] == "phone_chat" and row["provider"] == "local"
                    and row["jobSha256"] is row["chargedLedgerSha256"] is row["refundTokens"] is None for row in free)
            and len(refunds) == 1 and len(added) == 7, "D3_PRIVATE_LEDGER_EXTRA_OPERATIONS")
    failed = next(row for row in free if row["requestSha256"] == identifier_sha(chat["failedRequestId"]))
    refund = refunds[0]
    require(refund["requestSha256"] == failed["requestSha256"] and refund["chargedLedgerSha256"] == failed["idSha256"]
            and refund["delta"] == refund["dailyPart"] == refund["balancePart"] == 0
            and all(refund[key] is None for key in ("jobSha256", "tokenCost", "refundTokens", "mode", "provider")),
            "D3_PRIVATE_CHAT_REFUND_MISMATCH")
    left, right = before["account"], after["account"]
    require(left["token_balance"] - right["token_balance"] == total_balance
            and right["daily_tokens_used"] - left["daily_tokens_used"] == total_daily
            and right["tokens_used"] - left["tokens_used"] == total_cost
            and right["generation_count"] - left["generation_count"] == 2
            and sum(row["delta"] for row in added) == -total_balance, "D3_PRIVATE_ACCOUNT_DEBIT_MISMATCH")
    return {"status": "PASS", "fullJobLedgerLinkage": "PASS", "jobs": result,
            "priorRowsUnchanged": len(old), "freeChatRequests": 4, "zeroTokenChatRefunds": 1,
            "accountDebit": {"mainBalance": total_balance, "dailyBudget": total_daily, "tokensUsed": total_cost}}


def prove_browser_ledger(shadow, images, flow, directory, *, browser_probe, api_identity, wallclock, save):
    """Save both real snapshots before matching; a private failure cannot hide a completed image."""
    directory = Path(directory)
    directory.mkdir(mode=0o700, exist_ok=False)
    proof = {"status": "FAIL", "fullJobLedgerLinkage": "NOT_VERIFIED",
             "sourceSha": shadow.sha, "project": shadow.project}
    def persist(name, value):
        path = directory / (name + ".json")
        save(path, value)
        return {"receipt": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    with wallclock(8):
        reader = private_ledger_reader(shadow, images, flow, api_identity=api_identity, wallclock=wallclock)
        before = reader([])
        proof["before"] = persist("before", before)
    save(directory / "receipt.json", proof)
    # Browser keeps its original bounded supervisor and returns partial image evidence on late failure.
    result = browser_probe()
    require(isinstance(result, dict), "D3_PRIVATE_LEDGER_BROWSER_INCOMPLETE")
    try:
        after = reader(browser_job_ids(result))
        proof["after"] = persist("after", after)
        proof.update(settle_private_ledger(before, after, result["browser"]))
    except Exception:
        proof.update(status="FAIL", errorCode="D3_PRIVATE_LEDGER_PROOF_FAILED")
    result["privateLedger"] = proof
    if proof["status"] != "PASS":
        result["status"] = "FAIL"
    save(directory / "receipt.json", proof)
    return result
