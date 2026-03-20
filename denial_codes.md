# Common RCM Denial Code Reference

This document covers the most frequently encountered claim denial codes in healthcare revenue cycle management. Used by the Denial Resolution agent to answer payer representative questions during appeal calls.

---

## CO Codes (Contractual Obligation — write-offs per contract)

### CO-4 — The service is inconsistent with the modifier.
The procedure code modifier submitted does not match the service billed. This is typically a claim edit failure, not a clinical denial.

**Common causes:**
- Modifier billed does not apply to the procedure code under NCCI or payer-specific edits
- Bilateral modifier (50) submitted when payer requires two line items instead
- Global period modifier missing or incorrect

**Resolution:** Review the remittance advice for the specific CARC/RARC pair. Correct the modifier and submit a corrected claim (frequency code 7). Do not file a formal appeal — this is a billing correction.

---

### CO-16 — Claim/service lacks information which is needed for adjudication.
One or more required fields are missing or invalid. The payer cannot process the claim as submitted.

**Common missing elements:**
- Rendering provider NPI (box 24J on the CMS-1500)
- Referring provider NPI when required by the plan
- Primary diagnosis code (ICD-10) missing or invalid
- Place of service code incorrect or missing
- Authorization number not included when prior auth was required

**Resolution:** Pull the full remittance advisory remark codes (RARCs) to identify exactly which field is missing. Submit a corrected claim with the required information. If the denial is for a missing authorization, obtain the authorization retroactively if the payer allows it, then resubmit.

---

### CO-22 — This care may be covered by another payer per coordination of benefits.
The payer believes the patient has primary coverage with another carrier and has not received that payer's adjudication first.

**Resolution:** Submit the claim to the primary payer. Once the primary EOB or ERA (835) is received, resubmit to this payer with the primary payer's adjudication attached. On electronic claims, include the coordination of benefits loop (2320) with the primary payer's payment information.

---

### CO-45 — Charges exceed your contracted/legislated fee arrangement.
The billed amount exceeds the allowable under the provider's contract with the payer. The difference is a contractual write-off, not collectible from the patient.

**Note:** This is not an error — it is the normal contractual adjustment. No appeal or corrected claim is warranted unless the allowed amount appears lower than the contracted rate, in which case a contractual dispute may be appropriate.

---

### CO-97 — The benefit for this service is included in the payment/allowance for another service/procedure that has already been adjudicated.

**This is a bundling denial.** The procedure code submitted was bundled into another procedure code already paid on the same claim or date of service. The payer is applying CCI (Correct Coding Initiative) edits or their own proprietary bundling rules.

**How CCI bundling works:**
The National Correct Coding Initiative (NCCI) defines "column 1 / column 2" code pairs. The column 2 code is considered a component of the column 1 code and cannot be billed separately unless a specific clinical circumstance allows unbundling. The NCCI edits are updated quarterly by CMS and may be adopted by commercial payers.

**Common CO-97 scenarios:**
- Evaluation and management (E&M) visit bundled into a procedure performed on the same day (e.g., 99213 bundled into a minor surgical procedure)
- Lab panel components billed individually when a panel code was already paid
- Imaging guidance (e.g., 76942) bundled into an interventional procedure
- Two related procedures billed separately where one is considered integral to the other

**When unbundling is appropriate:**
If the services were genuinely separate and distinct — performed in a different session, on a different anatomical site, or for a different diagnosis — the claim may be unbundled with a modifier:

| Modifier | Meaning | When to use |
|---|---|---|
| **-59** | Distinct Procedural Service | General unbundling; different session, site, or indication |
| **-XE** | Separate Encounter | Service in a separate encounter on the same date |
| **-XS** | Separate Structure | Service performed on a separate organ or structure |
| **-XP** | Separate Practitioner | Service performed by a different practitioner |
| **-XU** | Unusual Non-Overlapping Service | Not normally encountered on the same day |

**CMS preference:** CMS prefers the X modifiers (XE, XS, XP, XU) over -59 when the specific circumstance applies. Use -59 only when no X modifier accurately describes the situation.

**Resolution path:**
1. Look up the specific code pair in the NCCI table (available at CMS.gov)
2. Determine if the pair has a "0" modifier indicator (bundling cannot be overridden) or a "1" indicator (modifier may allow separate payment)
3. If modifier indicator is "1" and clinical circumstances support unbundling: submit a corrected claim with the appropriate modifier on the column 2 code
4. If clinical documentation supports a formal appeal: attach the operative note, progress note, or other documentation showing the services were distinct

**Appeal tips for CO-97:**
- Reference the specific NCCI edit pair and the modifier indicator in the appeal letter
- Attach supporting clinical documentation (operative note, procedure note)
- Cite the specific clinical circumstances that justify separate billing
- If the payer is applying proprietary bundling beyond NCCI, request the specific CCI or proprietary edit reference number

---

### CO-4 / CO-97 Combined Denials
Often seen together when a modifier that would allow unbundling under CCI rules was missing from the original claim. The CO-4 identifies the modifier problem; the CO-97 reflects the bundling result.

**Resolution:** Append the appropriate unbundling modifier (typically -59, -XE, -XS, -XP, or -XU) to the column 2 code and submit a corrected claim.

---

## PR Codes (Patient Responsibility — patient owes this amount)

### PR-1 — Deductible amount.
The patient has not met their annual deductible, or has not fully met it. The denied amount applies toward the deductible and is the patient's financial responsibility.

**Resolution:** No payer appeal is available. Bill the patient for the deductible amount. Verify the patient's deductible accumulator with the payer if the amount seems incorrect.

---

### PR-2 — Coinsurance amount.
The patient's coinsurance share after the deductible has been met. Calculated as a percentage of the allowed amount per the patient's plan.

**Resolution:** Bill the patient. No payer appeal warranted unless the coinsurance percentage appears inconsistent with the plan's benefit structure.

---

### PR-27 — Expenses incurred after coverage terminated.

**The patient's insurance was not active on the date of service.** The payer is indicating that coverage ended before the claim's date of service (DOS).

**Why this happens:**
- Employer terminated benefits and payer processed the termination retroactively
- Patient lost eligibility due to non-payment of premium (COBRA or marketplace plan)
- Patient aged off a parent's plan (turning 26 under ACA)
- Open enrollment gap — patient's new plan did not start until after the DOS
- Administrative error by the employer or payer

**Steps to resolve PR-27:**
1. **Verify the termination date** — Ask the payer representative to confirm the exact date coverage terminated and the reason code. Get their reference number.
2. **Check for retroactive reinstatement** — Some payers will reinstate coverage retroactively if the termination was an administrative error or if the employer submitted a late enrollment update.
3. **Secondary coverage** — If the patient has a secondary payer, submit the claim there with this denial EOB attached.
4. **Patient eligibility re-check** — Flag the account for the eligibility team to re-run eligibility and investigate whether coverage was terminated in error.
5. **Patient responsibility** — If coverage was legitimately terminated, the full balance is patient responsibility. Contact the patient to explain and set up a payment arrangement.

**Documentation to request from the payer:**
- Exact termination date and effective date of termination
- Reason code for termination (voluntary, non-payment, administrative, etc.)
- Whether a reinstatement request is possible and the process for requesting it

**Appeal strategy for PR-27:**
- If the patient believes they had active coverage, file a formal appeal with supporting documentation: insurance card, employer benefits letter, COBRA election notice, or marketplace enrollment confirmation
- Request the payer pull the eligibility record as of the DOS and compare against the enrollment file submitted by the employer

---

## OA Codes (Other Adjustment — neither payer nor patient owes)

### OA-23 — The impact of prior payer(s) adjudication including payments and/or adjustments.
Used in coordination of benefits. The secondary payer has adjusted the claim based on what the primary payer already paid. No additional action is typically required unless the secondary payment calculation appears incorrect.

**If the COB calculation seems wrong:** Request the secondary payer's COB worksheet and compare it against the primary EOB. File a formal appeal if the secondary is not paying the correct crossover amount.

---

### OA-109 — Claim not covered by this payer/contractor. You must send the claim to the correct payer/contractor.
The claim was submitted to the wrong insurance company or the wrong product line within a payer (e.g., Medicare Advantage vs. original Medicare).

**Resolution:**
1. Verify the patient's correct insurance as of the DOS (call eligibility line or check payer portal)
2. Identify the correct payer and plan
3. Resubmit the claim to the correct carrier
4. Check whether timely filing limits with the correct payer have been impacted

---

### OA-18 — Exact duplicate claim/service.
A claim for this exact service was already received and adjudicated. The second submission is being denied as a duplicate.

**Resolution:** Locate the original claim and its adjudication. If the original was paid correctly, no action needed. If the original was denied or underpaid, file an appeal on the original claim — do not resubmit.

---

## Appeal Guidance by Code

| Code | Best Resolution Path | Corrected Claim? | Formal Appeal? |
|---|---|---|---|
| CO-4 | Fix modifier, resubmit corrected claim | Yes | No |
| CO-16 | Add missing info, resubmit corrected claim | Yes | No |
| CO-22 | Submit to primary first; resubmit with primary EOB | Yes (after primary) | No |
| CO-45 | Contractual write-off; verify contracted rate | No | Only if rate is wrong |
| CO-97 | Corrected claim with unbundling modifier, or formal appeal with clinical docs | Yes (with modifier) | If modifier indicator = 1 |
| PR-1 / PR-2 | Bill patient; no payer appeal | No | No |
| PR-27 | Verify termination date; reinstatement or secondary claim; bill patient | No | Yes, if coverage terminated in error |
| OA-18 | Locate original adjudication; appeal original if underpaid | No | On original claim |
| OA-23 | Review COB calculation; appeal if secondary payment is incorrect | No | If COB is wrong |
| OA-109 | Identify correct payer; resubmit to correct carrier | Yes (new payer) | No |

---

## Appeal Deadlines (General)

| Payer Type | Typical Appeal Window |
|---|---|
| Commercial (BCBS, UHC, Aetna, Cigna) | 180 days from date of denial |
| Medicare (Redetermination — Level 1) | 120 days from date of denial |
| Medicare (Reconsideration — Level 2, QIC) | 180 days from Level 1 denial |
| Medicaid | Varies by state — typically 90 to 180 days |
| TRICARE | 90 days from date of denial |
| Workers' Comp | Varies by state — typically 30 to 90 days |

**Always confirm the specific deadline with the payer representative on the call.** Deadlines are measured from the date of the original denial, not from the date of a subsequent inquiry. Missing an appeal deadline typically forfeits the right to appeal.

---

## Timely Filing Limits (for Reference)

| Payer Type | Timely Filing Limit |
|---|---|
| Medicare | 1 year from date of service |
| Medicaid | Varies — typically 90 to 365 days from DOS |
| Commercial plans | Varies — typically 90 to 180 days from DOS; check contract |
| TRICARE | 1 year from date of service |

If a claim is denied for CO-29 (timely filing) rather than CO-97 or PR-27, the appeal must include proof of timely filing: clearinghouse submission report, 277 acknowledgment, or electronic payer acknowledgment.

---

## Modifier Reference for Billing Staff

| Modifier | Full Name | Common Use |
|---|---|---|
| -25 | Significant, Separately Identifiable E&M | E&M on same day as procedure |
| -57 | Decision for Surgery | E&M leading to surgery decision |
| -59 | Distinct Procedural Service | General unbundling modifier |
| -76 | Repeat Procedure by Same Physician | Same procedure, same day, same provider |
| -77 | Repeat Procedure by Another Physician | Same procedure, same day, different provider |
| -79 | Unrelated Procedure During Postop Period | Unrelated service during global period |
| -XE | Separate Encounter | Preferred over -59 for separate encounters |
| -XS | Separate Structure | Preferred over -59 for separate anatomical sites |
| -XP | Separate Practitioner | Preferred over -59 for different practitioner |
| -XU | Unusual Non-Overlapping Service | Preferred over -59 when none of the above fit |
| -GA | Waiver of Liability on File | ABN on file for potentially non-covered service |
| -GZ | Item/Service Expected to be Denied | No ABN; write-off patient liability |
| -GX | Notice of Exclusions from Medicare Benefits | Voluntary ABN signed |
