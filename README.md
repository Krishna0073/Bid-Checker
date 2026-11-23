# BidCheck – Public Procurement Bid Compliance Verification Assistant

**SIH26100 | Smart India Hackathon Project**

BidCheck is a Streamlit-based application designed to assist procurement officers in checking the eligibility and compliance information submitted by bidders during the government tendering process.

It automates initial compliance checks using a Python-based rule engine, identifies missing or invalid information, and flags ambiguous cases for manual verification.

## Problem Statement

Procurement officers manually verify statutory, tax and eligibility documents submitted by bidders. This process can be time-consuming and may lead to human errors.

BidCheck aims to reduce repetitive manual verification by automating initial eligibility checks and providing clear, explainable results.

## Key Features

- **Automated Compliance Checking:** Checks eight important bidder eligibility criteria.
- **Three-Level Verdict System:** Classifies each rule as PASS, FAIL or ESCALATE.
- **Ambiguity Detection:** Flags pending registrations, unclear information, attached-only evidence and other cases requiring human verification.
- **Evidence and Explanations:** Displays the reason and supporting text for each result.
- **Multiple Input Formats:** Supports TXT, PDF, JSON and Markdown files, along with manual text input.
- **Synthetic Bid Generator:** Generates sample bid documents with predefined labels for testing.
- **Evaluation Dashboard:** Compares the rule engine with a basic keyword-based baseline.
- **CSV Report:** Allows users to download individual bid-checking results.

## Eligibility Checks

| Rule | What it checks | Current threshold |
|---|---|---|
| GSTIN | GST registration number format and state code | 15-character format |
| PAN | PAN format and consistency with GSTIN | Valid PAN structure |
| Turnover | Average annual turnover over the last three financial years | ₹5 Crore |
| Experience | Experience in similar works | 3 years |
| EMD | Earnest Money Deposit as a percentage of estimated bid value | 2% |
| Bid Validity | Validity period of the submitted bid | 90 days |
| Udyam | Udyam registration when MSE benefits are claimed | Valid Udyam format |
| Debarment | Declaration regarding blacklisting or debarment | Clean declaration |

*These are the prototype's predefined thresholds and checks. Actual tender requirements may vary.*

## How It Works

1. The user uploads a bid document or enters bid information manually.
2. The application extracts the available text.
3. The rule engine processes the text using Python functions and regular expressions.
4. Each eligibility criterion receives a PASS, FAIL or ESCALATE result.
5. The application calculates an overall verdict.
6. The user reviews the explanations and supporting evidence.
7. The results can be downloaded as a CSV report.

### Verdict System

| Verdict | Meaning |
|---|---|
| PASS | The available information satisfies the predefined rule. |
| FAIL | The information is missing, malformed or does not meet the rule. |
| ESCALATE | The case is ambiguous and requires manual verification. |

**Overall decision logic:**

- If any rule returns FAIL, the overall result is FAIL.
- Otherwise, if any rule returns ESCALATE, the overall result is ESCALATE.
- If all rules return PASS, the overall result is PASS.

## Technology Stack

| Technology | Purpose |
|---|---|
| Python | Core application logic |
| Streamlit | Web application interface |
| Pandas | Data processing and evaluation |
| Regular Expressions (Regex) | Pattern matching and information validation |
| pypdf | PDF text extraction |
| JSON | Structured input processing |

## Project Structure

```text
BidCheck/
│
├── bidcheck_app.py
│
├── requirements.txt
│
└── README.md
```

## Installation and Setup

### 1. Clone the repository

```bash
git clone <YOUR_GITHUB_REPOSITORY_URL>
```

### 2. Navigate to the project directory

```bash
cd BidCheck
```

### 3. Install dependencies

```bash
pip install streamlit pandas pypdf
```

### 4. Run the application

```bash
streamlit run bidcheck_app.py
```

The application will open in your browser, usually at:

```text
http://localhost:8501
```

## Application Modules

### 1. Check a Bid

- Upload a bid document.
- Alternatively, select a synthetic sample bid.
- Review or edit the extracted text.
- Run the compliance checker.
- View individual rule results and the overall verdict.
- Download the report in CSV format.

### 2. Evaluation Dashboard

The application generates synthetic bid documents with predefined expected labels.

It evaluates the rule engine against a basic keyword-checking baseline.

The dashboard includes:

- Accuracy
- Precision
- Recall
- Escalation rate
- Escalation recall
- False clears
- Auto-clear precision
- Wrongly cleared bids

The default evaluation uses 300 synthetic bids with a fixed random seed of 7.

**Note:** These metrics are calculated using synthetic test data. They do not represent verified performance on actual government procurement bids.

### 3. Rules and Method

Displays the predefined eligibility rules, thresholds, escalation policy and known limitations of the system.

## Human-in-the-Loop Approach

BidCheck does not attempt to automatically approve every ambiguous case.

For example:
- If a registration application is still pending, the case is escalated.
- If turnover figures are provisional or unaudited, manual verification is requested.
- If experience depends on a parent company or JV partner, the case is escalated.
- If a document contains unclear or potentially misread information, human review is required.

This approach helps prevent uncertain information from being treated as automatically verified.

## Current Limitations

The current version is a working prototype and has the following limitations:

- Uses predefined rules and regular expressions rather than a trained AI/ML model.
- Does not authenticate GSTIN, PAN or Udyam details against official government databases.
- Does not independently verify whether a bidder is actually blacklisted.
- PDF processing extracts available text; scanned documents requiring OCR are not fully supported.
- May fail to interpret unusual wording, complex tables or information spread across multiple documents.
- Uses predefined thresholds rather than automatically extracting requirements from every tender.
- Requires human verification for ambiguous cases.

## Future Scope

Potential improvements include:

- OCR integration for scanned tender documents.
- NLP and AI-based document understanding.
- Automatic extraction of eligibility requirements from tender documents.
- Integration with authorized government verification APIs.
- Cross-document information consistency checks.
- Configurable tender-specific eligibility rules.
- Human review workflow and audit trail.
- Improved support for complex PDF and DOCX documents.

## Project Objective

The objective of BidCheck is to make initial procurement compliance verification faster, more consistent and easier to review.

By combining automated rule-based validation with human oversight, the prototype demonstrates how technology can assist procurement officers in reducing repetitive verification work while keeping important decisions reviewable.

---

**Project:** BidCheck – Public Procurement Bid Compliance Verification Assistant  
**Hackathon:** Smart India Hackathon (SIH)  
**Problem ID:** SIH26100  
**Status:** Working Prototype
