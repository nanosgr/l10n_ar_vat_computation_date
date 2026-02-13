# Testing Guide - VAT Credit Deferred Computation

This guide provides comprehensive testing scenarios for the
`l10n_ar_vat_computation_date` module.

## Prerequisites

Before testing, ensure:

- Odoo 18.0 Enterprise with Argentina localization installed
- `l10n_ar_vat_computation_date` module installed
- At least one company configured with Argentina localization
- User has accounting rights and access to configuration

## Test Environment Setup

### Initial Configuration

1. **Navigate to Accounting Settings**

   - Go to: Accounting > Configuration > Settings
   - Scroll to "Argentina" section
   - Locate "VAT Credit Deferred Computation" subsection

2. **Create Required Accounts** (if not exist)

   a. IVA Crédito Fiscal Account (definitive):

   - Code: 111.03.001
   - Name: IVA Crédito Fiscal
   - Type: Current Assets
   - Reconcilable: No

   b. IVA Crédito Fiscal a Computar Account (temporary):

   - Code: 111.03.002
   - Name: IVA Crédito Fiscal a Computar
   - Type: Current Assets
   - Reconcilable: No

3. **Configure Module Settings**

   - Set "IVA Crédito Fiscal Account" → Select definitive account
   - Set "IVA Crédito Fiscal a Computar Account" → Select temporary account
   - Click "Save"

4. **Verify AJIVA Journal Creation**
   - Go to: Accounting > Configuration > Journals
   - Search for journal with code "AJIVA"
   - Verify it exists with:
     - Type: General
     - Name: Ajustes de IVA Crédito Fiscal

## Test Scenarios

### Scenario 1: Configuration Validations

**Objective:** Verify configuration constraints work correctly

**Steps:**

1. Go to Accounting > Configuration > Settings > Argentina
2. Try to set both accounts to the same value
3. Click "Save"
4. **Expected:** Error message "VAT Credit accounts must be different"

5. Try to set an account of type "Expenses" as VAT Credit account
6. **Expected:** Domain restriction prevents selection

**Pass Criteria:**

- Cannot save identical accounts
- Can only select Current Asset accounts

---

### Scenario 2: Normal Invoice (Open Period)

**Objective:** Verify module doesn't interfere with normal posting

**Prerequisites:**

- No fiscal period locks configured
- Configuration completed

**Steps:**

1. Create Supplier Invoice:

   - Vendor: Any supplier
   - Invoice Date: Today's date
   - Accounting Date: Today's date
   - Product: Any product with 21% VAT
   - Amount: $1000 + $210 VAT = $1210

2. Click "Confirm"

3. **Verify Invoice Entry:**

   - Open Journal Items tab
   - Locate VAT line
   - **Expected:** Account = "IVA Crédito Fiscal" (definitive account, not temporary)

4. **Verify No Adjustment Entry:**

   - Check for "VAT Adjustment Entry" button
   - **Expected:** No button visible or button shows "No adjustment entry"

5. **Verify Computation Date:**
   - Check `l10n_ar_vat_computation_date` field
   - **Expected:** Same as invoice date

**Pass Criteria:**

- Uses definitive VAT account
- No adjustment entry created
- Computation date equals invoice date

---

### Scenario 3: Invoice in Locked Period

**Objective:** Test core functionality with deferred VAT computation

**Prerequisites:**

- Configuration completed
- AJIVA journal exists

**Setup:**

1. Lock a fiscal period:
   - Go to: Accounting > Accounting > Lock Dates
   - Set "Lock Date for Non-Advisers" to: 2026-01-31
   - Save

**Steps:**

1. Create Supplier Invoice:

   - Vendor: Any supplier
   - Invoice Date: 2026-01-15 (in locked period)
   - Accounting Date: 2026-01-15
   - Product: Any product with 21% VAT
   - Amount: $1000 + $210 VAT = $1210

2. **Before Posting - Verify Computation Date Calculation:**

   - Check `l10n_ar_vat_computation_date` field
   - **Expected:** 2026-02-01 (first day of next open period)

3. Click "Confirm" to post the invoice

4. **Verify Original Entry:**

   - Open "Journal Items" tab
   - Find the VAT debit line (210.00)
   - **Expected Account:** "IVA Crédito Fiscal a Computar" (temporary account)
   - **Expected Date:** 2026-01-15

5. **Verify Adjustment Entry Creation:**

   - Look for "VAT Adjustment Entry" smart button (should show count: 1)
   - Click the button
   - **Expected:** Opens the adjustment entry

6. **Verify Adjustment Entry Details:**

   - **State:** Posted
   - **Date:** 2026-02-01 (computation date)
   - **Journal:** AJIVA
   - **Reference:** Contains "VAT Adjustment" and original invoice name
   - **Journal Items:**
     - Debit Line: Account = "IVA Crédito Fiscal" (definitive), Amount = 210.00
     - Credit Line: Account = "IVA Crédito Fiscal a Computar" (temporary), Amount =
       210.00

7. **Verify Traceability:**
   - From adjustment entry, look for "Source Invoice" button
   - Click button
   - **Expected:** Returns to original invoice

**Pass Criteria:**

- Original entry uses temporary account
- Adjustment entry created on computation date
- Adjustment entry is posted
- Bidirectional navigation works
- Amounts match exactly
- Total debit = total credit in adjustment

---

### Scenario 4: Multiple VAT Lines

**Objective:** Test correct handling of invoices with multiple VAT rates

**Prerequisites:**

- Lock date set to 2026-01-31
- Configuration completed

**Steps:**

1. Create Supplier Invoice with multiple VAT rates:

   - Invoice Date: 2026-01-20 (locked period)
   - Line 1: Product A, Amount $1000, VAT 21% = $210
   - Line 2: Product B, Amount $500, VAT 10.5% = $52.50
   - Line 3: Product C, Amount $300, VAT 0% = $0
   - Total: $1800 + $262.50 VAT = $2062.50

2. Post the invoice

3. **Verify Original Entry:**

   - Should have 2 VAT lines (21% and 10.5%)
   - Both should use "IVA Crédito Fiscal a Computar" account

4. **Verify Adjustment Entry:**
   - Open adjustment entry
   - **Expected Debit:** $262.50 (210 + 52.50)
   - **Expected Credit:** $262.50
   - Verify accounts are correct

**Pass Criteria:**

- All VAT lines replaced in original entry
- Total VAT computed correctly in adjustment
- Adjustment balances (debit = credit)

---

### Scenario 5: Invoice Without VAT

**Objective:** Verify no adjustment created when VAT = 0

**Prerequisites:**

- Lock date set to 2026-01-31

**Steps:**

1. Create Supplier Invoice:

   - Invoice Date: 2026-01-20 (locked period)
   - Product: Tax-exempt product (0% VAT)
   - Amount: $1000 (no VAT)

2. Post the invoice

3. **Verify:**
   - No "VAT Adjustment Entry" button visible
   - `l10n_ar_vat_computation_date` may still be calculated but no entry created

**Pass Criteria:**

- No adjustment entry created
- No errors during posting

---

### Scenario 6: Multi-Company Configuration

**Objective:** Verify each company uses its own accounts

**Prerequisites:**

- Two companies created (Company A and Company B)
- Different VAT accounts per company

**Steps:**

1. **Configure Company A:**

   - Switch to Company A
   - Set VAT Credit Account → Account A1
   - Set VAT Credit to Compute Account → Account A2

2. **Configure Company B:**

   - Switch to Company B
   - Set VAT Credit Account → Account B1
   - Set VAT Credit to Compute Account → Account B2

3. **Test Company A Invoice:**

   - Create invoice for Company A in locked period
   - Verify uses Account A2 (temporary)
   - Verify adjustment uses Account A1 (definitive)

4. **Test Company B Invoice:**
   - Create invoice for Company B in locked period
   - Verify uses Account B2 (temporary)
   - Verify adjustment uses Account B1 (definitive)

**Pass Criteria:**

- Each company uses its own configured accounts
- No cross-company interference
- AJIVA journal exists per company

---

### Scenario 7: Missing Configuration

**Objective:** Verify clear error when configuration incomplete

**Prerequisites:**

- Remove configuration (set accounts to empty)

**Steps:**

1. Go to Settings, clear VAT Credit Account
2. Create supplier invoice in locked period with VAT
3. Try to post

4. **Expected:**
   - Error message: "VAT Credit accounts must be configured..."
   - Invoice not posted

**Pass Criteria:**

- Clear, actionable error message
- Posting blocked
- No partial entries created

---

### Scenario 8: Reset to Draft (Warning)

**Objective:** Verify warning when resetting posted invoice with adjustment

**Steps:**

1. Post invoice in locked period (creates adjustment)
2. Click "Reset to Draft" button
3. **Expected:** Warning message about existing adjustment entry
4. Confirm the reset
5. **Verify:**
   - Invoice returns to draft
   - Adjustment entry remains posted (independent)
   - Link between invoice and adjustment preserved

**Pass Criteria:**

- Warning displayed
- User can proceed after warning
- Adjustment entry not auto-reversed

---

### Scenario 9: Navigation and Traceability

**Objective:** Test user interface elements

**Steps:**

1. Create and post invoice in locked period
2. From invoice form:
   - Verify "VAT Adjustment Entry" button shows count (1)
   - Click button → opens adjustment entry
3. From adjustment entry:
   - Verify "Source Invoice" button visible
   - Click button → returns to invoice
4. Test multiple times to verify no errors

**Pass Criteria:**

- Smart buttons visible and functional
- Correct counts displayed
- No broken links
- Smooth navigation

---

## Regression Testing

After any code changes, run abbreviated test suite:

1. Normal invoice (Scenario 2) - 5 min
2. Locked period invoice (Scenario 3) - 10 min
3. Multiple VAT lines (Scenario 4) - 5 min
4. Configuration validation (Scenario 1) - 3 min

**Total time:** ~25 minutes

## Automated Testing

If implementing automated tests (Python unittests):

```python
# Key test methods to implement:
test_configuration_validation()
test_normal_invoice_no_adjustment()
test_locked_period_creates_adjustment()
test_multiple_vat_lines_aggregation()
test_zero_vat_no_adjustment()
test_multi_company_isolation()
test_missing_configuration_error()
test_traceability_fields()
```

## Troubleshooting

**Issue:** Adjustment entry not created

- Verify `l10n_ar_vat_computation_date` != invoice date
- Check VAT amount > 0
- Verify AJIVA journal exists
- Check logs for errors

**Issue:** Wrong account used

- Verify company configuration
- Check account domains (must be asset_current)
- Ensure working in correct company context

**Issue:** Navigation buttons missing

- Refresh page
- Verify view inheritance loaded correctly
- Check field values in database

## Test Sign-off

| Scenario                     | Tester | Date | Result | Notes |
| ---------------------------- | ------ | ---- | ------ | ----- |
| 1. Configuration Validations |        |      |        |       |
| 2. Normal Invoice            |        |      |        |       |
| 3. Locked Period Invoice     |        |      |        |       |
| 4. Multiple VAT Lines        |        |      |        |       |
| 5. Invoice Without VAT       |        |      |        |       |
| 6. Multi-Company             |        |      |        |       |
| 7. Missing Configuration     |        |      |        |       |
| 8. Reset to Draft            |        |      |        |       |
| 9. Navigation                |        |      |        |       |

**Overall Status:** [ ] Pass [ ] Fail [ ] Partial

**Sign-off:**

- Developer: \***\*\*\*\*\***\_\***\*\*\*\*\*** Date: **\_\_\_**
- QA: \***\*\*\*\*\***\_\***\*\*\*\*\*** Date: **\_\_\_**
- Business Analyst: \***\*\*\*\*\***\_\***\*\*\*\*\*** Date: **\_\_\_**
