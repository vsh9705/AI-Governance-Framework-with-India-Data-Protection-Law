# server.py — Groq version with data rights endpoints
import json, logging, os
from fastapi import FastAPI, Request, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

from chat import process_submission
from workflows import run_loan_approval_workflow

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO,
    handlers=[logging.FileHandler("server.log"), logging.StreamHandler()]
)

app = FastAPI(
    title="AI Governance API — India IT Act & Data Protection Edition",
    description="Loan AI governance with IT Act 2000, DPDPA 2023, and GDPR compliance.",
    version="2.0",
)

DECISION_FILE = "loan_decisions.json"


def load_decisions():
    if os.path.exists(DECISION_FILE):
        with open(DECISION_FILE, "r") as f:
            try: return json.load(f)
            except json.JSONDecodeError: return []
    return []


def save_decisions(decisions):
    with open(DECISION_FILE, "w") as f:
        json.dump(decisions, f, indent=4)


class LoanApplication(BaseModel):
    text: str


class ErasureRequest(BaseModel):
    """GDPR Art. 17 + DPDPA Sec 13 — Right to erasure."""
    applicant_id: str
    reason: str


@app.middleware("http")
async def log_requests(request: Request, call_next):
    logging.info(f"{request.method} {request.url}")
    response = await call_next(request)
    logging.info(f"Status: {response.status_code}")
    return response


# ORIGINAL endpoint
@app.post("/submit")
async def submit_application(application: LoanApplication):
    logging.info(f"Received application: {application.text[:100]}")
    try:
        processed = await process_submission(application.text)
        final_state = await run_loan_approval_workflow(processed)
        return {"status": "success", "final_state": final_state}
    except Exception as e:
        logging.error(f"Error: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


# NEW: GDPR Art. 17 + DPDPA Sec 13 — Right to erasure
@app.post("/rights/erasure")
async def request_erasure(req: ErasureRequest):
    """Right to be forgotten — GDPR Article 17 + DPDPA 2023 Section 13."""
    decisions = load_decisions()
    remaining = [d for d in decisions if d.get("applicant_id") != req.applicant_id]
    if len(remaining) == len(decisions):
        raise HTTPException(status_code=404, detail={
            "message": f"No record for applicant_id={req.applicant_id}.",
            "gdpr_note": "GDPR Art. 12: request acknowledged. No data held.",
            "dpdpa_note": "DPDPA 2023 Section 13: request registered."
        })
    save_decisions(remaining)
    return {
        "status": "erased",
        "applicant_id": req.applicant_id,
        "records_deleted": len(decisions) - len(remaining),
        "reason": req.reason,
        "legal_compliance": {
            "gdpr": "Article 17 — Right to erasure honored.",
            "dpdpa": "Section 13 — Data Principal erasure right fulfilled.",
            "it_act": "Rule 5.5 — Data not retained beyond purpose."
        }
    }


# NEW: GDPR Art. 15 + DPDPA Sec 12 — Right of access
@app.get("/rights/access/{applicant_id}")
async def request_access(applicant_id: str):
    """Right of access — GDPR Article 15 + DPDPA 2023 Section 12."""
    decisions = load_decisions()
    record = next((d for d in decisions if d.get("applicant_id") == applicant_id), None)
    if not record:
        raise HTTPException(status_code=404, detail={
            "message": f"No data held for applicant_id={applicant_id}.",
            "gdpr_note": "GDPR Art. 15: No personal data is held for this ID.",
            "dpdpa_note": "DPDPA Section 12: No processing record exists."
        })
    exposed = {k: v for k, v in record.items() if not k.startswith("_")}
    return {
        "status": "data_provided",
        "applicant_id": applicant_id,
        "personal_data": exposed,
        "processing_info": {
            "purpose": "Loan eligibility assessment.",
            "legal_basis_gdpr": "Article 6(1)(b) — Contract.",
            "legal_basis_dpdpa": "Section 4 — Lawful purpose with consent.",
            "retention_period": "3 years from application date.",
            "automated_decision_making": {
                "used": True,
                "human_review_available": True,
                "gdpr_safeguard": "Human override always available per Art. 22(2)(b)."
            },
            "cross_border_transfer": "None. All processing within India.",
            "your_rights": {
                "erasure": "POST /rights/erasure",
                "complaint_india": "Data Protection Board of India (DPBI)",
                "complaint_eu": "EU supervisory authority (if applicable)"
            }
        },
        "legal_compliance": {
            "gdpr": "Article 15 — Right of access honored.",
            "dpdpa": "Section 12 — Data Principal access right fulfilled.",
            "it_act": "Rule 5.7 — Review right fulfilled."
        }
    }