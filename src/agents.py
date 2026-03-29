# agents.py — Groq API version
# Requires: GROQ_API_KEY in .env

import json
import os
from typing import List, Optional

from groq import AsyncGroq
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()

_client = AsyncGroq(api_key=os.environ.get("GROQ_API_KEY"))
GROQ_MODEL = "llama-3.3-70b-versatile"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

async def _chat(system: str, user: str) -> str:
    resp = await _client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        temperature=0.1,
        max_tokens=512,
    )
    return resp.choices[0].message.content.strip()


async def _chat_json(system: str, user: str) -> dict:
    resp = await _client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": system + "\n\nRespond with valid JSON only. No markdown fences, no explanation outside JSON."},
            {"role": "user",   "content": user},
        ],
        temperature=0.0,
        max_tokens=800,
        response_format={"type": "json_object"},
    )
    raw = resp.choices[0].message.content.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        cleaned = raw.replace("```json", "").replace("```", "").strip()
        return json.loads(cleaned)


# ===========================================================================
# ORIGINAL AGENT 1: SafetyControlAgent
# ===========================================================================
class SafetyControlAgent:
    _SYSTEM = (
        "You are a bias detection agent. Given a loan application's demographic group, "
        "decide if the decision criteria could constitute unlawful discrimination.\n"
        "Output exactly one line per demographic group:\n"
        '  "Bias likely for: [group]"  — only if there is explicit discriminatory criterion\n'
        '  "No bias for: [group]"       — if criteria appear neutral\n'
        "Do NOT flag bias just because the group is a minority. Only flag if a specific "
        "criterion in the data is explicitly discriminatory."
    )

    async def monitor_loan_data(self, loan_applications: list) -> str:
        demographics = ", ".join(a.get("demographic", "unknown") for a in loan_applications)
        criteria     = ", ".join(
            str(a.get("loan_criteria", "Standard Risk Assessment"))
            for a in loan_applications
        )
        user_text = f"Demographic groups: {demographics}\nLoan criteria applied: {criteria}"
        result = await _chat(self._SYSTEM, user_text)
        print("SafetyControlAgent:", result)
        return result


# ===========================================================================
# ORIGINAL AGENT 2: EthicsAgent
# ===========================================================================
_ethics_path = os.path.join(os.getcwd(), "acme_bank_ethics_guidelines.txt")
with open(_ethics_path, "r") as f:
    _acme_ethics = f.read()

_ETHICS_SYSTEM = f"""You are an Ethics Agent for Acme Bank.

Acme Bank Ethical Guidelines:
{_acme_ethics}

Your job: evaluate the loan APPLICATION CRITERIA AND DECISION against the guidelines.
Do NOT penalise an application for missing system-level compliance documents — those are 
the bank's responsibility, not the applicant's.
Focus only on: Is the loan purpose ethical? Are the criteria fair? Is there predatory intent?

Output exactly one of:
  "ETHICAL"
  "UNETHICAL: <one-sentence reason citing which guideline>"
"""


class EthicsAgent:
    async def review_decision_criteria(self, loan_application_data_json: str) -> dict:
        try:
            text = await _chat(_ETHICS_SYSTEM, loan_application_data_json)
            print("EthicsAgent:", text)
            if "UNETHICAL" in text.upper():
                return {"ethical": False, "reasons": [text]}
            return {"ethical": True, "reasons": []}
        except Exception as e:
            return {"ethical": False, "reasons": [f"Error: {e}"]}

    def _flag_criteria(self, result: dict):
        if not result["ethical"]:
            print("EthicsAgent ALERT: UNETHICAL —", result["reasons"])
        else:
            print("EthicsAgent: ETHICAL.")


# ===========================================================================
# ORIGINAL AGENT 3: ComplianceAgent
# ===========================================================================
class ComplianceReportSchema(BaseModel):
    is_compliant: bool
    non_compliant_regulations: Optional[List[str]] = None
    reasons: Optional[List[str]] = None


_fin_regs_path = os.path.join(os.getcwd(), "financial_regulations.txt")
try:
    with open(_fin_regs_path, "r") as f:
        _fin_regs = f.read()
except FileNotFoundError:
    _fin_regs = "Financial regulations file not found."

_COMPLIANCE_SYSTEM = f"""You are a financial regulations compliance agent for Acme Bank.

Financial Regulations:
{_fin_regs}

You are auditing a LOAN DECISION (not an applicant's documents).
Check whether the decision itself — the approval/rejection and the stated criteria — 
complies with the regulations. Do NOT flag violations just because the JSON lacks 
documentation fields. Only flag a regulation if the decision or criteria explicitly 
violates it.

Respond with JSON:
{{
  "is_compliant": true or false,
  "non_compliant_regulations": ["only regulations explicitly violated"],
  "reasons": ["specific reason tied to what is IN the data, not what is missing"]
}}
"""


class ComplianceAgent:
    async def audit_for_compliance(self, loan_decision_json: str) -> dict:
        print("ComplianceAgent: auditing...")
        try:
            data = await _chat_json(_COMPLIANCE_SYSTEM, loan_decision_json)
            report = ComplianceReportSchema.model_validate(data)
            if report.is_compliant:
                return {"is_compliant": True, "non_compliant_regulations": [], "reasons": []}
            return {
                "is_compliant": False,
                "non_compliant_regulations": report.non_compliant_regulations or [],
                "reasons": report.reasons or []
            }
        except Exception as e:
            print(f"ComplianceAgent Error: {e}")
            return {"is_compliant": False, "non_compliant_regulations": ["Error"], "reasons": [str(e)]}


# ===========================================================================
# ORIGINAL AGENT 4: HumanCollaborationAgent
# ===========================================================================
class HumanCollaborationAgent:
    def facilitate_human_review(self, loan_application: dict, ai_decision: str) -> str:
        if ai_decision.lower() == "approved":
            return "approved"
        try:
            ui = input(f"Review {loan_application.get('applicant_id','N/A')} "
                       f"(AI: {ai_decision}). Override? (yes/no): ")
        except Exception:
            ui = "no"
        final = "approved" if ui.lower() == "yes" else ai_decision
        print(f"HumanCollaborationAgent: Final: {final}")
        return final


# ===========================================================================
# NEW AGENT 1: DataPrivacyClassifierAgent
# Unit I §1.1 | Unit III §1.1–1.2
#
# FIXED: classify only known SPDI categories from IT Act Rule 2(1)(i).
# Do NOT mark fields SPDI just because they contain numbers.
# ===========================================================================

# These are the legally defined SPDI categories under IT Act Rule 2(1)(i)
_SPDI_CATEGORIES = """
SENSITIVE PERSONAL DATA (SPDI) under IT Act 2000 Rule 2(1)(i) — classify as SENSITIVE_PERSONAL_DATA ONLY if the field clearly falls into one of these categories:
  1. Passwords
  2. Financial information: bank account number, credit card number, debit card number, other payment instrument details
  3. Physical / physiological / mental health condition
  4. Sexual orientation
  5. Medical records and history
  6. Biometric information (fingerprint, iris scan, face scan, etc.)

PERSONAL DATA — classify fields that identify a natural person but are NOT in the SPDI list above:
  Examples: name, age, email, phone, address, Aadhaar number, PAN, date of birth, gender, demographic group, employment status, credit score, loan amount requested, loan purpose, income

NON_PERSONAL DATA — classify fields that are non-identifying, operational, or metadata:
  Examples: loan_status, risk_flag, loan_criteria, processing flags (boolean consent fields, processing location strings), application IDs, timestamps
"""

_CLASSIFIER_SYSTEM = f"""You are a Data Privacy Classification Agent under India's IT Act 2000.

{_SPDI_CATEGORIES}

IMPORTANT RULES:
- loan_amount and income are PERSONAL_DATA (not SPDI — they are requested values, not existing financial account details)
- credit_score is PERSONAL_DATA
- account_number / credit_card_number / debit_card_number are SENSITIVE_PERSONAL_DATA
- health_condition / medical_history / biometric_data / mental_health_status are SENSITIVE_PERSONAL_DATA
- spdi_consent, loan_status, risk_flag, boolean flags are NON_PERSONAL_DATA
- demographic, age, employment_status, loan_purpose are PERSONAL_DATA

Count only true SPDI fields. Set:
  consent_required = true  if spdi_count > 0 AND the field "spdi_consent" is false or absent
  dpia_required    = true  if spdi_count >= 5

Respond with JSON:
{{
  "classifications": {{
    "<field_name>": {{"class": "<SENSITIVE_PERSONAL_DATA|PERSONAL_DATA|NON_PERSONAL_DATA>", "reason": "<cite IT Act Rule 2(1)(i) category or explain>"}}
  }},
  "spdi_count": <integer>,
  "consent_required": <true|false>,
  "dpia_required": <true|false>
}}
"""


class DataPrivacyClassifierAgent:
    """NEW — Pre-pipeline field taxonomy. Unit I §1.1, Unit III §1.1–1.2."""

    async def classify_application_fields(self, loan_application: dict) -> dict:
        print("DataPrivacyClassifierAgent: classifying fields...")
        # Exclude internal pipeline fields injected by workflow
        exclude = {"loan_status", "risk_flag", "_gdpr_context", "_data_classification", "privacy_classification"}
        clean_app = {k: v for k, v in loan_application.items() if k not in exclude}

        field_listing = json.dumps(
            {k: str(v)[:80] for k, v in clean_app.items()},
            indent=2
        )
        try:
            data = await _chat_json(_CLASSIFIER_SYSTEM, f"Classify these fields:\n{field_listing}")
            data.setdefault("spdi_count", 0)
            data.setdefault("consent_required", False)
            data.setdefault("dpia_required", False)
            data.setdefault("classifications", {})

            # Fallback for any field not classified
            for key in clean_app:
                if key not in data["classifications"]:
                    data["classifications"][key] = {
                        "class": "PERSONAL_DATA", "reason": "Default fallback"
                    }

            # Enforce rules deterministically (don't trust LLM counting)
            actual_spdi = sum(
                1 for v in data["classifications"].values()
                if v.get("class") == "SENSITIVE_PERSONAL_DATA"
            )
            data["spdi_count"] = actual_spdi
            data["consent_required"] = (actual_spdi > 0) and not bool(clean_app.get("spdi_consent", False))
            data["dpia_required"] = actual_spdi >= 5

            print(f"DataPrivacyClassifierAgent: {actual_spdi} SPDI | consent_required={data['consent_required']} | dpia_required={data['dpia_required']}")
            return data
        except Exception as e:
            print(f"DataPrivacyClassifierAgent Error: {e}")
            return {
                "classifications": {k: {"class": "PERSONAL_DATA", "reason": "Error fallback"} for k in clean_app},
                "spdi_count": 0, "consent_required": False, "dpia_required": False
            }


# ===========================================================================
# NEW AGENT 2: ITActDPDPAComplianceAgent
# Unit II §1.1/1.3 | Unit III §1.1–1.5
#
# FIXED: check specific observable facts in the data.
# Do NOT flag a violation just because a documentation field is absent.
# ===========================================================================

_india_regs_path = os.path.join(os.getcwd(), "india_regulations.txt")
try:
    with open(_india_regs_path, "r") as f:
        _india_regs = f.read()
except FileNotFoundError:
    _india_regs = "india_regulations.txt not found."


class IndiaComplianceReportSchema(BaseModel):
    is_compliant: bool
    violated_sections: Optional[List[str]] = None
    reasons: Optional[List[str]] = None
    cross_border_risk: Optional[bool] = False
    children_data_risk: Optional[bool] = False


_INDIA_SYSTEM = f"""You are an India Data Protection Compliance Agent (IT Act 2000 + DPDPA 2023).

Regulations Reference (use for accurate section citations only):
{_india_regs}

You are reviewing a loan application data object that also contains a "_data_classification" block 
produced by a prior classification agent.

STRICT RULES — only flag a violation if the DATA EXPLICITLY shows a problem:

1. CONSENT (DPDPA §6, IT Act Rule 5.3):
   - Violation ONLY if: spdi_count > 0 AND spdi_consent == false or absent
   - NOT a violation if: spdi_consent == true OR spdi_count == 0

2. CROSS-BORDER RISK (DPDPA §16):
   - Violation ONLY if: a field like "data_processing_location" or "analytics_vendor" or "cloud_storage" 
     contains a non-India location string (e.g. "USA", "Europe", "UK", "AWS us-east")
   - NOT a violation just because those fields are absent

3. CHILDREN DATA (DPDPA §9):
   - Violation ONLY if: age field is present AND age < 18

4. KYC / IDENTITY (IT Act §43A, BSA):
   - Violation ONLY if: kyc_status field is present AND equals "incomplete" or "failed"

5. PURPOSE LIMITATION (DPDPA §4):
   - Violation ONLY if: loan_purpose is "undisclosed" or empty

6. ALL OTHER CHECKS (security practices, breach notification, erasure, etc.):
   - These are SYSTEM-LEVEL obligations of the bank, NOT verifiable from application data
   - Do NOT flag these unless the data explicitly mentions a failure

Set cross_border_risk = true ONLY if rule 2 above is triggered.
Set children_data_risk = true ONLY if rule 3 above is triggered.

Respond with JSON:
{{
  "is_compliant": true or false,
  "violated_sections": ["only sections with confirmed violations from rules above"],
  "reasons": ["specific reason tied to a specific field value in the data"],
  "cross_border_risk": true or false,
  "children_data_risk": true or false
}}
"""


class ITActDPDPAComplianceAgent:
    """NEW — India IT Act 2000 + DPDPA 2023. Unit II §1.1/1.3, Unit III §1.1–1.5."""

    async def audit_india_compliance(self, loan_decision_json: str,
                                     classification_report: dict = None) -> dict:
        print("ITActDPDPAComplianceAgent: auditing...")
        try:
            decision_data = json.loads(loan_decision_json)
        except json.JSONDecodeError:
            decision_data = {"raw": loan_decision_json}

        if classification_report:
            decision_data["_data_classification"] = {
                "spdi_count": classification_report.get("spdi_count", 0),
                "consent_required": classification_report.get("consent_required", False),
                "dpia_required": classification_report.get("dpia_required", False),
                "sensitive_fields": [
                    f for f, info in classification_report.get("classifications", {}).items()
                    if info.get("class") == "SENSITIVE_PERSONAL_DATA"
                ]
            }

        try:
            data = await _chat_json(_INDIA_SYSTEM, json.dumps(decision_data, indent=2))
            report = IndiaComplianceReportSchema.model_validate(data)

            # ── deterministic overrides so LLM can't hallucinate these ──
            orig = json.loads(loan_decision_json) if isinstance(loan_decision_json, str) else loan_decision_json

            # Cross-border: only if explicit non-India location
            xb_fields = ["data_processing_location", "analytics_vendor", "cloud_storage"]
            xb_keywords = ["usa", "us-east", "us-west", "europe", "uk", "germany", "singapore",
                           "australia", "japan", "china", "aws", "gcp", "azure"]
            cross_border = any(
                any(kw in str(orig.get(f, "")).lower() for kw in xb_keywords)
                for f in xb_fields
            )

            # Children: only if age < 18
            age_val = orig.get("age")
            children = isinstance(age_val, (int, float)) and age_val < 18

            # Consent: only if SPDI present and not granted
            spdi_count = classification_report.get("spdi_count", 0) if classification_report else 0
            consent_issue = spdi_count > 0 and not bool(orig.get("spdi_consent", False))

            # Build final violated sections
            violated = []
            reasons = []
            if consent_issue:
                violated.append("DPDPA Section 6 / IT Act Rule 5.3")
                reasons.append(f"Application contains {spdi_count} SPDI field(s) but spdi_consent is not true.")
            if cross_border:
                violated.append("DPDPA Section 16")
                reasons.append("Data processing location or vendor is outside India.")
            if children:
                violated.append("DPDPA Section 9")
                reasons.append(f"Applicant age is {age_val} (minor). Parental consent required.")
            if orig.get("kyc_status") in ["incomplete", "failed"]:
                violated.append("IT Act Section 43A / BSA Rule 3.1")
                reasons.append(f"KYC status is '{orig.get('kyc_status')}'.")
            if orig.get("loan_purpose", "").lower() in ["undisclosed", ""]:
                violated.append("DPDPA Section 4")
                reasons.append("Loan purpose is undisclosed — no lawful purpose established.")

            is_compliant = len(violated) == 0

            result = {
                "is_compliant": is_compliant,
                "violated_sections": violated,
                "reasons": reasons,
                "cross_border_risk": cross_border,
                "children_data_risk": children,
            }
            if not is_compliant:
                print(f"ITActDPDPAComplianceAgent ALERT: {violated}")
            else:
                print("ITActDPDPAComplianceAgent: COMPLIANT.")
            return result

        except Exception as e:
            print(f"ITActDPDPAComplianceAgent Error: {e}")
            return {
                "is_compliant": False,
                "violated_sections": ["Error during India compliance check"],
                "reasons": [str(e)],
                "cross_border_risk": False,
                "children_data_risk": False,
            }


# ===========================================================================
# NEW AGENT 3: GDPRComplianceAgent
# Unit IV §1.1, §1.2, §1.3
#
# FIXED: deterministic checks first, LLM only for nuanced issues.
# Art.22 check uses the injected human_review_available flag, not guesswork.
# ===========================================================================

_gdpr_regs_path = os.path.join(os.getcwd(), "gdpr_regulations.txt")
try:
    with open(_gdpr_regs_path, "r") as f:
        _gdpr_regs = f.read()
except FileNotFoundError:
    _gdpr_regs = "gdpr_regulations.txt not found."


class GDPRComplianceReportSchema(BaseModel):
    is_compliant: bool
    violated_articles: Optional[List[str]] = None
    reasons: Optional[List[str]] = None
    automated_decision_risk: Optional[bool] = False
    right_to_be_forgotten_applicable: Optional[bool] = False
    lawful_basis_documented: Optional[bool] = True


_GDPR_SYSTEM = f"""You are a GDPR EU 2016/679 compliance agent.

GDPR Reference:
{_gdpr_regs}

You are reviewing a loan decision object that contains a "_gdpr_context" block.
The "_gdpr_context" block is injected by the system and is authoritative.

STRICT RULES — check only what is observable in the data:

1. ARTICLE 22 (automated decisions):
   - Violation ONLY if: _gdpr_context.human_review_available == false
   - NOT a violation if human_review_available == true (our system always offers human override)

2. ARTICLE 6 (lawful basis):
   - Violation ONLY if: a field "lawful_basis_for_processing" exists AND equals "none" or "none documented"
   - If the field is absent, assume lawful basis is contract (Art.6(1)(b)) — NOT a violation

3. ARTICLE 13/14 (right to be informed):
   - Violation ONLY if: privacy_notice_given field is present AND equals false

4. ARTICLE 17 (right to erasure — right_to_be_forgotten_applicable):
   - Set to true ONLY if: spdi_consent was false (consent withdrawn scenario) 
     OR erasure_mechanism field is present AND equals "none"

5. ALL OTHER GDPR checks (storage limitation, data minimisation, DPIA, etc.):
   - These are SYSTEM-LEVEL obligations. Do NOT flag them based on absence of documentation
     in the application JSON.

Respond with JSON:
{{
  "is_compliant": true or false,
  "violated_articles": ["only articles with confirmed violations from rules above"],
  "reasons": ["specific reason tied to a specific field value"],
  "automated_decision_risk": true or false,
  "right_to_be_forgotten_applicable": true or false,
  "lawful_basis_documented": true or false
}}
"""


class GDPRComplianceAgent:
    """NEW — GDPR checker. Unit IV §1.1, §1.2, §1.3."""

    async def audit_gdpr_compliance(self, loan_decision_json: str,
                                    final_decision: str = "unknown",
                                    human_review_available: bool = True) -> dict:
        print("GDPRComplianceAgent: auditing...")
        try:
            decision_data = json.loads(loan_decision_json)
        except json.JSONDecodeError:
            decision_data = {"raw": loan_decision_json}

        decision_data["_gdpr_context"] = {
            "final_decision": final_decision,
            "human_review_available": human_review_available,
            "note": "Art.22: human_review_available=true means our system offers human override — NOT a violation."
        }

        try:
            data = await _chat_json(_GDPR_SYSTEM, json.dumps(decision_data, indent=2))
            report = GDPRComplianceReportSchema.model_validate(data)

            # ── deterministic overrides ──
            orig = json.loads(loan_decision_json) if isinstance(loan_decision_json, str) else loan_decision_json

            # Art.22: trust the flag we inject, not LLM inference
            art22_violation = not human_review_available

            # Art.6: only if explicitly set to "none"
            lb = orig.get("lawful_basis_for_processing", "")
            art6_violation = lb.lower() in ["none", "none documented"] if lb else False

            # Art.13: only if explicitly false
            art13_violation = orig.get("privacy_notice_given") is False

            # Right to erasure: consent withdrawn or erasure=none
            rtbf = (not bool(orig.get("spdi_consent", True)) and orig.get("spdi_consent") is not None) \
                   or orig.get("erasure_mechanism", "") == "none"

            violated = []
            reasons = []
            if art22_violation:
                violated.append("Article 22")
                reasons.append("Loan decision is fully automated with no human review option.")
            if art6_violation:
                violated.append("Article 6")
                reasons.append(f"lawful_basis_for_processing is set to '{lb}'.")
            if art13_violation:
                violated.append("Article 13/14")
                reasons.append("privacy_notice_given is explicitly false.")

            is_compliant = len(violated) == 0

            result = {
                "is_compliant": is_compliant,
                "violated_articles": violated,
                "reasons": reasons,
                "automated_decision_risk": art22_violation,
                "right_to_be_forgotten_applicable": rtbf,
                "lawful_basis_documented": not art6_violation,
            }
            if not is_compliant:
                print(f"GDPRComplianceAgent ALERT: {violated}")
            else:
                print("GDPRComplianceAgent: GDPR COMPLIANT.")
            return result

        except Exception as e:
            print(f"GDPRComplianceAgent Error: {e}")
            return {
                "is_compliant": False,
                "violated_articles": ["Error during GDPR check"],
                "reasons": [str(e)],
                "automated_decision_risk": False,
                "right_to_be_forgotten_applicable": False,
                "lawful_basis_documented": True,
            }