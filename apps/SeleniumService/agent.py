from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import asyncio
from selenium_claimSubmitWorker import AutomationMassHealth
from selenium_eligibilityCheckWorker import AutomationMassHealthEligibilityCheck
from selenium_claimStatusCheckWorker import AutomationMassHealthClaimStatusCheck
from selenium_preAuthWorker import AutomationMassHealthPreAuth
import os
import time
import helpers_ddma_eligibility as hddma
import helpers_dentaquest_eligibility as hdentaquest

# Import session clear functions for startup
from ddma_browser_manager import clear_ddma_session_on_startup
from dentaquest_browser_manager import clear_dentaquest_session_on_startup

from dotenv import load_dotenv
load_dotenv() 

# Clear all sessions on startup (after PC restart)
# This ensures users must login again after PC restart
print("=" * 50)
print("SELENIUM AGENT STARTING - CLEARING ALL SESSIONS")
print("=" * 50)
clear_ddma_session_on_startup()
clear_dentaquest_session_on_startup()
print("=" * 50)
print("SESSION CLEAR COMPLETE - FRESH LOGINS REQUIRED")
print("=" * 50)

app = FastAPI()
# Allow 1 selenium session at a time
semaphore = asyncio.Semaphore(1)

# Manual counters to track active & queued jobs
active_jobs = 0
waiting_jobs = 0
lock = asyncio.Lock()  # To safely update counters


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Replace with your frontend domain for security
    allow_methods=["*"],
    allow_headers=["*"],
)

# Endpoint: 1 — Start the automation of submitting Claim.
@app.post("/claimsubmit")
async def start_workflow(request: Request):
    global active_jobs, waiting_jobs
    data = await request.json()

    async with lock:
        waiting_jobs += 1

    async with semaphore: 
        async with lock:
            waiting_jobs -= 1
            active_jobs += 1

        try:
            bot = AutomationMassHealth(data)
            result = bot.main_workflow("https://providers.massdhp.com/providers_login.asp")

            if result.get("status") != "success":
                return {"status": "error", "message": result.get("message")}
            
            return result
        except Exception as e:
            return {"status": "error", "message": str(e)}
        finally:
            async with lock:
                active_jobs -= 1
    
# Endpoint: 2 — Start the automation of cheking eligibility
@app.post("/eligibility-check")
async def start_workflow(request: Request):
    global active_jobs, waiting_jobs
    data = await request.json()

    async with lock:
        waiting_jobs += 1

    async with semaphore:
        async with lock:
            waiting_jobs -= 1
            active_jobs += 1
        try:
            bot = AutomationMassHealthEligibilityCheck(data)
            result = bot.main_workflow("https://providers.massdhp.com/providers_login.asp")

            if result.get("status") != "success":
                return {"status": "error", "message": result.get("message")}
            
            return result
        except Exception as e:
            return {"status": "error", "message": str(e)}
        finally:
            async with lock:
                active_jobs -= 1
    
# Endpoint: 3 — Start the automation of cheking claim status
@app.post("/claim-status-check")
async def start_workflow(request: Request):
    global active_jobs, waiting_jobs
    data = await request.json()

    async with lock:
        waiting_jobs += 1

    async with semaphore:
        async with lock:
            waiting_jobs -= 1
            active_jobs += 1
        try:
            bot = AutomationMassHealthClaimStatusCheck(data)
            result = bot.main_workflow("https://providers.massdhp.com/providers_login.asp")

            if result.get("status") != "success":
                return {"status": "error", "message": result.get("message")}
            
            return result
        except Exception as e:
            return {"status": "error", "message": str(e)}
        finally:
            async with lock:
                active_jobs -= 1

# Endpoint: 4 — Start the automation of cheking claim pre auth
@app.post("/claim-pre-auth")
async def start_workflow(request: Request):
    global active_jobs, waiting_jobs
    data = await request.json()

    async with lock:
        waiting_jobs += 1

    async with semaphore:
        async with lock:
            waiting_jobs -= 1
            active_jobs += 1
        try:
            bot = AutomationMassHealthPreAuth(data)
            result = bot.main_workflow("https://providers.massdhp.com/providers_login.asp")

            if result.get("status") != "success":
                return {"status": "error", "message": result.get("message")}
            
            return result
        except Exception as e:
            return {"status": "error", "message": str(e)}
        finally:
            async with lock:
                active_jobs -= 1

# Endpoint:5 -  DDMA eligibility (background, OTP)

async def _ddma_worker_wrapper(sid: str, data: dict, url: str):
    """
    Background worker that:
      - acquires semaphore (to keep 1 selenium at a time),
      - updates active/queued counters,
      - runs the DDMA flow via helpers.start_ddma_run.
    """
    global active_jobs, waiting_jobs
    async with semaphore:
        async with lock:
            waiting_jobs -= 1
            active_jobs += 1
        try:
            await hddma.start_ddma_run(sid, data, url)
        finally:
            async with lock:
                active_jobs -= 1


@app.post("/ddma-eligibility")
async def ddma_eligibility(request: Request):
    """
    Starts a DDMA eligibility session in the background.
    Body: { "data": { ... }, "url"?: string }
    Returns: { status: "started", session_id: "<uuid>" }
    """
    global waiting_jobs

    body = await request.json()
    data = body.get("data", {})

    # create session
    sid = hddma.make_session_entry()
    hddma.sessions[sid]["type"] = "ddma_eligibility"
    hddma.sessions[sid]["last_activity"] = time.time()

    async with lock:
        waiting_jobs += 1

    # run in background (queued under semaphore)
    asyncio.create_task(_ddma_worker_wrapper(sid, data, url="https://providers.deltadentalma.com/onboarding/start/"))

    return {"status": "started", "session_id": sid}


# Endpoint:6 - DentaQuest eligibility (background, OTP)

async def _dentaquest_worker_wrapper(sid: str, data: dict, url: str):
    """
    Background worker that:
      - acquires semaphore (to keep 1 selenium at a time),
      - updates active/queued counters,
      - runs the DentaQuest flow via helpers.start_dentaquest_run.
    """
    global active_jobs, waiting_jobs
    async with semaphore:
        async with lock:
            waiting_jobs -= 1
            active_jobs += 1
        try:
            await hdentaquest.start_dentaquest_run(sid, data, url)
        finally:
            async with lock:
                active_jobs -= 1


@app.post("/dentaquest-eligibility")
async def dentaquest_eligibility(request: Request):
    """
    Starts a DentaQuest eligibility session in the background.
    Body: { "data": { ... }, "url"?: string }
    Returns: { status: "started", session_id: "<uuid>" }
    """
    global waiting_jobs

    body = await request.json()
    data = body.get("data", {})

    # create session
    sid = hdentaquest.make_session_entry()
    hdentaquest.sessions[sid]["type"] = "dentaquest_eligibility"
    hdentaquest.sessions[sid]["last_activity"] = time.time()

    async with lock:
        waiting_jobs += 1

    # run in background (queued under semaphore)
    asyncio.create_task(_dentaquest_worker_wrapper(sid, data, url="https://providers.dentaquest.com/onboarding/start/"))

    return {"status": "started", "session_id": sid}


@app.post("/dentaquest-submit-otp")
async def dentaquest_submit_otp(request: Request):
    """
    Body: { "session_id": "<sid>", "otp": "123456" }
    Node / frontend call this when user provides OTP for DentaQuest.
    """
    body = await request.json()
    sid = body.get("session_id")
    otp = body.get("otp")
    if not sid or not otp:
        raise HTTPException(status_code=400, detail="session_id and otp required")

    res = hdentaquest.submit_otp(sid, otp)
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res


@app.get("/dentaquest-session/{sid}/status")
async def dentaquest_session_status(sid: str):
    s = hdentaquest.get_session_status(sid)
    if s.get("status") == "not_found":
        raise HTTPException(status_code=404, detail="session not found")
    return s


@app.post("/submit-otp")
async def submit_otp(request: Request):
    """
    Body: { "session_id": "<sid>", "otp": "123456" }
    Node / frontend call this when user provides OTP.
    """
    body = await request.json()
    sid = body.get("session_id")
    otp = body.get("otp")
    if not sid or not otp:
        raise HTTPException(status_code=400, detail="session_id and otp required")

    res = hddma.submit_otp(sid, otp)
    if res.get("status") == "error":
        raise HTTPException(status_code=400, detail=res.get("message"))
    return res


@app.get("/session/{sid}/status")
async def session_status(sid: str):
    s = hddma.get_session_status(sid)
    if s.get("status") == "not_found":
        raise HTTPException(status_code=404, detail="session not found")
    return s


# ✅ Status Endpoint
@app.get("/status")
async def get_status():
    async with lock:
        return {
            "active_jobs": active_jobs,
            "queued_jobs": waiting_jobs,
            "status": "busy" if active_jobs > 0 or waiting_jobs > 0 else "idle"
        }

if __name__ == "__main__":
    host = os.getenv("HOST")
    port = int(os.getenv("PORT"))
    uvicorn.run(app, host=host, port=port)
