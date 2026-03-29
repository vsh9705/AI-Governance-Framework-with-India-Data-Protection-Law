# auditor.py — Unified portal on port 5001
# Routes:
#   GET  /                          → dashboard
#   GET  /apply                     → structured loan form (application.html)
#   POST /apply                     → handle structured form, run workflow
#   GET  /submit-raw                → raw JSON submission form (auditor.html page=submit)
#   POST /submit-raw                → handle raw JSON, run workflow
#   GET  /all                       → all decisions table
#   GET  /review                    → pending review list
#   GET  /review/<id>               → review detail
#   POST /review/<id>               → auditor submits decision
#   POST /clear-old                 → remove pre-migration records
#   POST /rights/erasure/<id>       → GDPR Art.17 + DPDPA §13

import os, json, logging, asyncio, datetime
from flask import Flask, render_template, request, redirect, url_for, flash

from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)
app.secret_key = "acme_bank_secret_2024"

DECISION_FILE = "loan_decisions.json"


# ============================================================ helpers

def load_decisions():
    if os.path.exists(DECISION_FILE):
        with open(DECISION_FILE, "r") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return []
    return []


def save_decisions(decisions):
    with open(DECISION_FILE, "w") as f:
        json.dump(decisions, f, indent=4)


def get_pending_reviews():
    return [d for d in load_decisions()
            if d.get("final_decision") == "requires further review"]


def get_decision_by_applicant(applicant_id):
    return next(
        (d for d in load_decisions() if d.get("applicant_id") == applicant_id),
        None
    )


def update_auditor_decision(applicant_id, final_decision, auditor_comments):
    decisions = load_decisions()
    for d in decisions:
        if d.get("applicant_id") == applicant_id:
            d["final_decision"] = final_decision
            d["auditor_comments"] = (
                "Auditor: " + auditor_comments.strip()
                if auditor_comments and auditor_comments.strip()
                else ""
            )
            save_decisions(decisions)
            return True
    return False


def load_example_file(filename):
    path = os.path.join(os.getcwd(), filename)
    if os.path.exists(path):
        with open(path, "r") as f:
            try:
                return json.load(f)
            except Exception:
                return None
    return None


def run_workflow_sync(application_text: str):
    """Run the async workflow synchronously inside Flask."""
    from chat import process_submission
    from workflows import run_loan_approval_workflow

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        processed = loop.run_until_complete(process_submission(application_text))
        final_state = loop.run_until_complete(run_loan_approval_workflow(processed))
        return final_state
    finally:
        loop.close()


# ============================================================ routes

@app.route("/")
def dashboard():
    all_dec = load_decisions()
    pending = [d for d in all_dec if d.get("final_decision") == "requires further review"]
    return render_template(
        "auditor.html",
        page="dashboard",
        pending_count=len(pending),
        total_count=len(all_dec)
    )


@app.route("/apply", methods=["GET", "POST"])
def apply_form():
    """
    Structured form submission — application.html.
    GET:  render the form (optionally pre-fill with example data).
    POST: build a loan dict from form fields, run the 7-step workflow.
    """
    if request.method == "GET":
        example_type = request.args.get("example_type", "")
        if example_type == "positive":
            example_data = load_example_file("example_positive.json")
        elif example_type == "negative":
            example_data = load_example_file("example_negative.json")
            if example_data:
                example_data["demographic"] = ""
        else:
            example_data = load_example_file("example.json")
        return render_template(
            "application.html",
            example_data=example_data,
            USE_EXAMPLE_SELECTOR=True
        )

    # --- POST ---
    applicant_id      = request.form.get("applicant_id", "unknown").strip()
    demographic       = request.form.get("demographic", "unknown")
    loan_amount       = request.form.get("loan_amount", "0")
    loan_purpose      = request.form.get("loan_purpose", "").strip()
    description       = request.form.get("description", "").strip()
    credit_score      = request.form.get("credit_score", "0")
    annual_income     = request.form.get("annual_income", "0")
    employment_status = request.form.get("employment_status", "")
    age               = request.form.get("age", "").strip()
    account_number    = request.form.get("account_number", "").strip()
    spdi_consent      = request.form.get("spdi_consent") == "on"
    loan_criteria_raw = request.form.get("loan_criteria", "")

    if not all([applicant_id, demographic, loan_amount, loan_purpose,
                credit_score, annual_income, employment_status]):
        flash("Please fill in all required fields.", "error")
        return redirect(url_for("apply_form"))

    # append timestamp to applicant_id (same as original client.py)
    time_suffix = datetime.datetime.now().strftime("%Y-%m-%d-%H-%M")
    modified_id = f"{applicant_id}+{time_suffix}"

    try:
        loan_application = {
            "applicant_id":      modified_id,
            "demographic":       demographic,
            "loan_amount":       float(loan_amount),
            "loan_purpose":      loan_purpose,
            "description":       description,
            "credit_score":      int(credit_score),
            "income":            float(annual_income),
            "employment_status": employment_status,
            "loan_criteria":     [c.strip() for c in loan_criteria_raw.split(",") if c.strip()],
        }
        if age:
            loan_application["age"] = int(age)
        if account_number:
            loan_application["account_number"] = account_number
        loan_application["spdi_consent"] = spdi_consent
    except ValueError as e:
        flash(f"Invalid input — ensure numeric fields contain valid numbers. ({e})", "error")
        return redirect(url_for("apply_form"))

    try:
        final_state = run_workflow_sync(json.dumps(loan_application))
        flash(f"Application submitted! Result: {final_state}", "success")
        return redirect(url_for("all_decisions"))
    except Exception as e:
        flash(f"Error processing application: {e}", "error")
        return redirect(url_for("apply_form"))


@app.route("/submit-raw", methods=["GET", "POST"])
def submit_raw():
    """
    Raw JSON submission form (for testers / advanced use).
    """
    if request.method == "GET":
        return render_template("auditor.html", page="submit_raw")

    raw_text = request.form.get("application_text", "").strip()
    if not raw_text:
        flash("Please enter application JSON.", "error")
        return redirect(url_for("submit_raw"))

    try:
        final_state = run_workflow_sync(raw_text)
        flash(f"Submitted! Result: {final_state}", "success")
        return redirect(url_for("all_decisions"))
    except Exception as e:
        flash(f"Error: {e}", "error")
        return redirect(url_for("submit_raw"))


@app.route("/all")
def all_decisions():
    decisions = load_decisions()
    return render_template("auditor.html", page="all_decisions", decisions=decisions)


@app.route("/review")
def review_list():
    pending = get_pending_reviews()
    return render_template("auditor.html", page="review_list", reviews=pending)


@app.route("/review/<path:applicant_id>", methods=["GET", "POST"])
def review_detail(applicant_id):
    decision = get_decision_by_applicant(applicant_id)
    if not decision:
        flash("Application not found.", "error")
        return redirect(url_for("review_list"))

    if request.method == "POST":
        final_decision   = request.form.get("final_decision", "").strip()
        auditor_comments = request.form.get("auditor_comments", "").strip()
        if not final_decision:
            flash("Please select a final decision.", "error")
            return redirect(url_for("review_detail", applicant_id=applicant_id))
        if update_auditor_decision(applicant_id, final_decision, auditor_comments):
            flash(f"Decision updated to '{final_decision}'.", "success")
        else:
            flash("Error updating decision.", "error")
        return redirect(url_for("review_list"))

    return render_template("auditor.html", page="review_detail", review=decision)


@app.route("/clear-old", methods=["POST"])
def clear_old():
    decisions = load_decisions()
    clean = [d for d in decisions
             if "india_compliance_report" in d or "gdpr_compliance_report" in d]
    removed = len(decisions) - len(clean)
    save_decisions(clean)
    flash(f"Removed {removed} pre-migration record(s). Submit fresh applications.", "success")
    return redirect(url_for("dashboard"))


@app.route("/rights/erasure/<path:applicant_id>", methods=["POST"])
def erasure(applicant_id):
    """GDPR Art.17 + DPDPA §13 — Right to erasure."""
    decisions = load_decisions()
    remaining = [d for d in decisions if d.get("applicant_id") != applicant_id]
    deleted = len(decisions) - len(remaining)
    if deleted == 0:
        flash(f"No record found for '{applicant_id}'.", "error")
    else:
        save_decisions(remaining)
        flash(
            f"All data for '{applicant_id}' permanently erased "
            f"(GDPR Art.17 + DPDPA §13).",
            "success"
        )
    return redirect(url_for("all_decisions"))


# ============================================================ main

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s"
    )
    app.run(debug=True, port=5001)