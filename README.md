# AI Governance Framework — India Data Protection Edition

An extended version of the [AI Governance Framework](https://github.com/ruslanmv/ai-governance-framework) by Ruslan Magana Vsevolodovna, modified to add compliance checks for **India's IT Act 2000**, **DPDPA 2023**, and **GDPR EU 2016/679**.

The original project had zero Indian law awareness. This version adds three new AI agents that screen every loan application against Indian data protection law before a decision is made.

---

## What this project does

A loan application is submitted through a web portal. Seven AI agents run in sequence, each checking a different aspect of the application. The result — compliant or flagged — is shown in an auditor dashboard with detailed breakdowns per legal framework.

### The 7-agent pipeline

| Step | Agent | What it checks | Law |
|------|-------|---------------|-----|
| 0 | DataPrivacyClassifierAgent | Classifies every field as SPDI / Personal / Non-personal | IT Act Rule 2(1)(i) |
| 1 | SafetyControlAgent | Demographic bias in loan criteria | Anti-discrimination |
| 2 | EthicsAgent | Ethical alignment with bank guidelines | Acme Bank Ethics Guidelines |
| 3 | ComplianceAgent | Generic financial regulations | CF123, ADA456, BSA789, TILA101 |
| 4 | ITActDPDPAComplianceAgent | Consent, cross-border transfer, minors, KYC, purpose | IT Act 2000 + DPDPA 2023 |
| 5 | GDPRComplianceAgent | Lawful basis, privacy notice, automated decisions | GDPR EU 2016/679 |
| 6 | HumanCollaborationAgent | Final approve / escalate decision | — |

Agents 0, 4, and 5 are new. Agents 1–3 and 6 are from the original project.

---

## Key differences from the original

| | Original | This version |
|--|----------|-------------|
| LLM | IBM Granite 8B (local, ~5 GB) | LLaMA 3.3 70B via Groq API |
| Framework | BeeAI + Ollama | Direct Groq Python client |
| Storage needed | ~8 GB | ~150 MB |
| Indian law compliance | None | IT Act 2000 + DPDPA 2023 |
| GDPR compliance | None | Art. 5, 6, 13, 15, 17, 22 |
| Data subject rights | None | /rights/erasure + /rights/access |
| Portal | 2 separate Flask apps | 1 unified portal |

---

## What gets checked (India-specific)

- **Consent** (DPDPA Section 6, IT Act Rule 5.3) — if SPDI fields are present and `spdi_consent` is not true, flagged
- **Cross-border transfer** (DPDPA Section 16) — if `data_processing_location` or `analytics_vendor` contains a non-India location (AWS, UK, USA, Europe etc.), flagged
- **Minors' data** (DPDPA Section 9) — if `age < 18`, parental consent required, flagged
- **KYC** (IT Act Section 43A) — if `kyc_status` is incomplete or failed, flagged
- **Purpose limitation** (DPDPA Section 4) — if `loan_purpose` is undisclosed, flagged

## What gets checked (GDPR)

- **Article 6** — if `lawful_basis_for_processing` is "none" or "none documented", flagged
- **Article 13/14** — if `privacy_notice_given` is false, flagged
- **Article 22** — if `human_review_available` is false (automated decision with no human recourse), flagged

---

## Prerequisites

- Python 3.11+
- Conda or any virtual environment manager
- A free Groq API key from [console.groq.com](https://console.groq.com)

---

## Setup

**1. Clone the repo**
```bash
git clone <your-repo-url>
cd ai-governance-framework
```

**2. Create and activate conda environment**
```bash
conda activate rag   # if using the existing rag env
# OR
conda create -n governance python=3.11
conda activate governance
```

**3. Install the one missing package**
```bash
pip install Flask
```
Everything else (groq, fastapi, pydantic, uvicorn, python-dotenv) is already in the rag env. If using a fresh env:
```bash
pip install -r requirements.txt
```

**4. Create your .env file**
```bash
echo "GROQ_API_KEY=gsk_your_key_here" > src/.env
```
Get your key at [console.groq.com](https://console.groq.com) → API Keys → Create New Key. Free, no credit card needed.

**5. Run the portal**
```bash
cd src
python auditor.py
```

Open `http://localhost:5001` in your browser.

---

## Usage

### Structured form
Go to `http://localhost:5001/apply` — fill in the form fields directly. Good for standard submissions.

### Raw JSON (for testing specific compliance checks)
Go to `http://localhost:5001/submit-raw` — paste a JSON object and run the full pipeline.

### Test cases

**Clean application (should pass everything)**
```json
{
  "applicant_id": "CLEAN-001",
  "demographic": "general",
  "loan_amount": 300000,
  "income": 75000,
  "age": 32,
  "loan_purpose": "home renovation",
  "account_number": "HDFC-00123456",
  "employment_status": "Employed",
  "credit_score": 720,
  "spdi_consent": true
}
```

**Triggers DPDPA Section 6 (no consent for SPDI)**
```json
{
  "applicant_id": "CONSENT-FAIL-002",
  "demographic": "general",
  "loan_amount": 500000,
  "income": 90000,
  "age": 28,
  "loan_purpose": "business expansion",
  "account_number": "SBI-00987654",
  "credit_card_number": "4111-1111-1111-1234",
  "spdi_consent": false
}
```

**Triggers DPDPA Section 16 (cross-border transfer)**
```json
{
  "applicant_id": "CROSSBORDER-003",
  "demographic": "NRI",
  "loan_amount": 2000000,
  "income": 200000,
  "age": 40,
  "loan_purpose": "property purchase",
  "account_number": "SBI-NRI-00334455",
  "data_processing_location": "AWS us-east-1 USA",
  "analytics_vendor": "Experian UK Ltd",
  "spdi_consent": true
}
```

**Triggers GDPR Article 6 + Article 13**
```json
{
  "applicant_id": "GDPR-ART6-007",
  "demographic": "general",
  "loan_amount": 250000,
  "income": 55000,
  "age": 27,
  "loan_purpose": "personal loan",
  "lawful_basis_for_processing": "none documented",
  "privacy_notice_given": false,
  "spdi_consent": true
}
```

---

## Data subject rights endpoints

These are available via the FastAPI server (`uvicorn server:app --reload` from `src/`).

**Right of access** — GDPR Article 15 + DPDPA Section 12
```
GET http://localhost:8000/rights/access/{applicant_id}
```

**Right to erasure** — GDPR Article 17 + DPDPA Section 13
```bash
curl -X POST http://localhost:8000/rights/erasure \
  -H "Content-Type: application/json" \
  -d '{"applicant_id": "CLEAN-001", "reason": "Consent withdrawn under DPDPA Section 6.4"}'
```

---

## File structure

```
src/
├── agents.py                    # All 7 agent classes
├── workflows.py                 # 7-step pipeline
├── auditor.py                   # Unified Flask portal (port 5001)
├── server.py                    # FastAPI backend with rights endpoints (port 8000)
├── chat.py                      # Parses raw submission text
├── utils.py                     # Save/load loan_decisions.json
├── india_regulations.txt        # IT Act 2000 + DPDPA 2023 reference (injected into agent prompts)
├── gdpr_regulations.txt         # GDPR EU 2016/679 reference (injected into agent prompts)
├── financial_regulations.txt    # Original generic financial regulations
├── acme_bank_ethics_guidelines.txt  # Bank ethics document
├── loan_decisions.json          # All processed applications (auto-created)
├── .env                         # Your GROQ_API_KEY goes here
└── templates/
    ├── auditor.html             # Full portal UI
    └── application.html         # Structured loan form
```

---

## How the compliance checking works

The India and GDPR agents use a hybrid approach. The LLM reads the full regulation text (injected from the `.txt` files) and classifies fields or reasons about compliance. But the final yes/no violation decision is made by Python conditional checks, not the LLM. This prevents the LLM from hallucinating violations based on missing documentation fields.

```python
# Example: consent check is Python, not LLM
if spdi_count > 0 and not bool(orig.get("spdi_consent", False)):
    violated.append("DPDPA Section 6 / IT Act Rule 5.3")

is_compliant = len(violated) == 0
```

---

## References

1. Original project: [ruslanmv/ai-governance-framework](https://github.com/ruslanmv/ai-governance-framework)
2. Information Technology Act, 2000 — Ministry of Electronics and IT, Government of India
3. IT (SPDI) Rules, 2011 — Ministry of Electronics and IT, Government of India
4. Digital Personal Data Protection Act, 2023 — Ministry of Electronics and IT, Government of India
5. GDPR EU 2016/679 — European Parliament, Official Journal of the EU
6. LLaMA 3.3 70B — Meta AI, 2024
7. Groq API — [console.groq.com/docs](https://console.groq.com/docs)

---

## Course context

Built as part of the **IT Act and Data Protection (ECE-4272)** course at Manipal Institute of Technology, Manipal. The project maps to:

- Unit I §1.1 — Defining personal data, SPDI, non-personal data (DataPrivacyClassifierAgent)
- Unit II §1.1, §1.3 — IT Act offences, controller duties (ITActDPDPAComplianceAgent)
- Unit III §1.1–1.5 — Data protection obligations, DPDPA 2023 (ITActDPDPAComplianceAgent)
- Unit IV §1.1–1.3 — GDPR principles, data subject rights, penalties (GDPRComplianceAgent)