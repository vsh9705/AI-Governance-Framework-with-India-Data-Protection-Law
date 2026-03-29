# workflows.py — Groq version
# Pipeline: 7 steps (4 original + 3 new India/GDPR agents)

import json
from agents import (
    SafetyControlAgent, EthicsAgent, ComplianceAgent, HumanCollaborationAgent,
    DataPrivacyClassifierAgent, ITActDPDPAComplianceAgent, GDPRComplianceAgent,
)
from utils import save


async def run_loan_approval_workflow(processed_submission: dict) -> str:
    """
    Step 0 [NEW]      DataPrivacyClassifierAgent  — IT Act / DPDPA field taxonomy
    Step 1 [ORIGINAL] SafetyControlAgent          — bias detection
    Step 2 [ORIGINAL] EthicsAgent                 — ethics review
    Step 3 [ORIGINAL] ComplianceAgent             — generic financial regulations
    Step 4 [NEW]      ITActDPDPAComplianceAgent   — India IT Act 2000 + DPDPA 2023
    Step 5 [NEW]      GDPRComplianceAgent         — GDPR Art. 5, 6, 13, 17, 22
    Step 6 [ORIGINAL] HumanCollaborationAgent     — human oversight / override
    """
    loan_application = processed_submission.copy()
    loan_application.setdefault("loan_criteria", ["Standard Risk Assessment", "Income Verification"])

    # ------------------------------------------------------------------
    # STEP 0 [NEW]: Data Privacy Classification
    # ------------------------------------------------------------------
    print("\n=== STEP 0: Data Privacy Classification (IT Act / DPDPA) ===")
    clf_report = await DataPrivacyClassifierAgent().classify_application_fields(loan_application)
    loan_application["privacy_classification"] = {
        "spdi_count": clf_report["spdi_count"],
        "consent_required": clf_report["consent_required"],
        "dpia_required": clf_report["dpia_required"],
        "field_classes": {f: i["class"] for f, i in clf_report["classifications"].items()}
    }

    # ------------------------------------------------------------------
    # STEP 1 [ORIGINAL]: Safety / Bias Detection
    # ------------------------------------------------------------------
    print("\n=== STEP 1: Safety Control (Bias Detection) ===")
    bias_result = await SafetyControlAgent().monitor_loan_data([loan_application])
    loan_application["risk_flag"] = bias_result

    # ------------------------------------------------------------------
    # STEP 2 [ORIGINAL]: Ethics Review
    # ------------------------------------------------------------------
    print("\n=== STEP 2: Ethics Review ===")
    ethics_agent = EthicsAgent()
    ethics_result = await ethics_agent.review_decision_criteria(json.dumps(loan_application))
    ethics_agent._flag_criteria(ethics_result)
    loan_application["ethics_review"] = ethics_result

    # ------------------------------------------------------------------
    # STEP 3 [ORIGINAL]: Generic Financial Regulations Compliance
    # ------------------------------------------------------------------
    print("\n=== STEP 3: Generic Financial Compliance ===")
    ai_decision = (
        "requires further review"
        if ("Bias likely" in bias_result or not ethics_result.get("ethical", True))
        else "approved"
    )
    loan_decision = {
        "decision_id":   "LD-" + str(loan_application.get("applicant_id", "unknown")),
        "applicant_id":  loan_application.get("applicant_id"),
        "decision":      ai_decision,
        "reason":        "discriminatory_criterion" if ai_decision != "approved" else "",
        "criteria":      loan_application.get("loan_criteria"),
    }
    compliance_report = await ComplianceAgent().audit_for_compliance(json.dumps(loan_decision))
    loan_application["compliance_report"] = compliance_report

    # ------------------------------------------------------------------
    # STEP 4 [NEW]: India IT Act 2000 + DPDPA 2023
    # Pass full loan_application so deterministic checks can read
    # spdi_consent, age, loan_purpose, kyc_status, data_processing_location etc.
    # ------------------------------------------------------------------
    print("\n=== STEP 4 [NEW]: India IT Act + DPDPA 2023 Compliance ===")
    india_context = {**loan_decision, **{
        k: loan_application[k] for k in (
            "spdi_consent", "age", "loan_purpose", "kyc_status",
            "data_processing_location", "analytics_vendor", "cloud_storage",
            "lawful_basis_for_processing", "privacy_notice_given",
            "human_review_available", "erasure_mechanism",
        ) if k in loan_application
    }}
    india_report = await ITActDPDPAComplianceAgent().audit_india_compliance(
        json.dumps(india_context), classification_report=clf_report
    )
    loan_application["india_compliance_report"] = india_report
    if not india_report["is_compliant"] and ai_decision == "approved":
        ai_decision = "requires further review"
        print("Workflow: India law violation — escalating to human review.")

    # ------------------------------------------------------------------
    # STEP 5 [NEW]: GDPR Compliance
    # Same — pass full context so Art.22/6/13 checks read the right fields.
    # ------------------------------------------------------------------
    print("\n=== STEP 5 [NEW]: GDPR Compliance ===")
    gdpr_context = {**loan_decision, **{
        k: loan_application[k] for k in (
            "spdi_consent", "lawful_basis_for_processing", "privacy_notice_given",
            "erasure_mechanism", "human_review_available",
        ) if k in loan_application
    }}
    gdpr_report = await GDPRComplianceAgent().audit_gdpr_compliance(
        json.dumps(gdpr_context),
        final_decision=ai_decision,
        human_review_available=loan_application.get("human_review_available", True)
    )
    loan_application["gdpr_compliance_report"] = gdpr_report
    if gdpr_report.get("automated_decision_risk") and ai_decision == "approved":
        print("CRITICAL: GDPR Art. 22 automated decision risk — forcing human review.")
        ai_decision = "requires further review"
        loan_application["gdpr_art22_override"] = True

    # ------------------------------------------------------------------
    # STEP 6 [ORIGINAL]: Final Decision
    # ------------------------------------------------------------------
    print("\n=== STEP 6: Final Decision ===")
    if ai_decision.lower() == "approved":
        final_decision = "approved"
    elif ai_decision.lower() == "requires further review":
        print("Flagged for later human override.")
        final_decision = "requires further review"
    else:
        final_decision = HumanCollaborationAgent().facilitate_human_review(loan_application, ai_decision)

    loan_application["final_decision"] = final_decision
    save(loan_application)

    return (
        f"applicant_id={loan_application.get('applicant_id')} "
        f"india_compliant={india_report.get('is_compliant')} "
        f"gdpr_compliant={gdpr_report.get('is_compliant')} "
        f"final_decision='{final_decision}'"
    )