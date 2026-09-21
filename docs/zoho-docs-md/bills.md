# Bills

When your vendor supplies goods/services to you on credit, you're sent an invoice that details the amount of money you owe him. You can record this as a bill in Zoho Books and track it until it's paid.

### End Points

| Method     | URL                                           | Description                                       |
| :--------- | :-------------------------------------------- | :------------------------------------------------ |
| **POST**   | `/bills`                                      | Create a bill                                     |
| **PUT**    | `/bills`                                      | Update a bill using a custom field's unique value |
| **GET**    | `/bills`                                      | List bills                                        |
| **PUT**    | `/bills/{bill_id}`                            | Update a bill                                     |
| **GET**    | `/bills/{bill_id}`                            | Get a bill                                        |
| **DELETE** | `/bills/{bill_id}`                            | Delete a bill                                     |
| **PUT**    | `/bill/{bill_id}/customfields`                | Update custom field in existing bills             |
| **POST**   | `/bills/{bill_id}/status/void`                | Void a bill                                       |
| **POST**   | `/bills/{bill_id}/status/open`                | Mark a bill as open                               |
| **POST**   | `/bills/{bill_id}/submit`                     | Submit a bill for approval                        |
| **POST**   | `/bills/{bill_id}/approve`                    | Approve a bill                                    |
| **PUT**    | `/bills/{bill_id}/address/billing`            | Update billing address                            |
| **GET**    | `/bills/{bill_id}/payments`                   | List bill payments                                |
| **POST**   | `/bills/{bill_id}/credits`                    | Apply credits                                     |
| **DELETE** | `/bills/{bill_id}/payments/{bill_payment_id}` | Delete a payment                                  |
| **POST**   | `/bills/{bill_id}/attachment`                 | Add attachment to a bill                          |
| **GET**    | `/bills/{bill_id}/attachment`                 | Get a bill attachment                             |
| **DELETE** | `/bills/{bill_id}/attachment`                 | Delete an attachment                              |
| **POST**   | `/bills/{bill_id}/comments`                   | Add comment                                       |
| **GET**    | `/bills/{bill_id}/comments`                   | List bill comments & history                      |
| **DELETE** | `/bills/{bill_id}/comments/{comment_id}`      | Delete a comment                                  |
| **GET**    | `/bills/editpage/frompurchaseorders`          | Convert PO to Bill                                |

---

## Attributes

| Attribute                         | Data Type | Description                                                                                                 |
| :-------------------------------- | :-------- | :---------------------------------------------------------------------------------------------------------- |
| **bill_id**                       | string    | ID of the Bill                                                                                              |
| **purchaseorder_ids**             | array     | Array of purchase order identifiers linked to this bill for tracking purposes.                              |
| **vendor_id**                     | string    | Unique identifier for the vendor who supplied the goods/services. Can be fetched from the Get Contacts API. |
| **vendor_name**                   | string    | Name of the Vendor                                                                                          |
| **vat_treatment**                 | string    | **[UK only]** VAT treatment for the bill. Values: `uk`, `eu_vat_registered`, `overseas`.                    |
| **vat_reg_no**                    | string    | **[UK, Avalara only]** VAT Registration number of a contact.                                                |
| **source_of_supply**              | string    | **[India only]** State code where goods/services originate.                                                 |
| **destination_of_supply**         | string    | **[India only]** State code where goods/services are delivered.                                             |
| **place_of_supply**               | string    | **[GCC only]** The place of supply (e.g., `AB`, `DU`, `SA`).                                                |
| **permit_number**                 | string    | **[UAE only]** The permit number for the bill.                                                              |
| **gst_no**                        | string    | **[India only]** 15 digit GST identification number of the vendor.                                          |
| **gst_treatment**                 | string    | **[India only]** GST treatment (e.g., `business_gst`, `consumer`).                                          |
| **tax_treatment**                 | string    | **[GCC, Mexico, Kenya, South Africa only]** VAT treatment for the bill (e.g., `vat_registered`, `non_gcc`). |
| **is_pre_gst**                    | boolean   | **[India only]** Applicable for transactions that fall before July 1, 2017.                                 |
| **pricebook_id**                  | string    | Identifier for the price book containing item rates and pricing rules.                                      |
| **pricebook_name**                | string    | Name of the price book.                                                                                     |
| **is_reverse_charge_applied**     | boolean   | **[India only]** Applicable for transactions where you pay reverse charge.                                  |
| **unused_credits_payable_amount** | integer   | Unused Credits for this Vendor.                                                                             |
| **status**                        | string    | Status of the Bill.                                                                                         |
| **bill_number**                   | string    | Unique sequential identifier for the bill.                                                                  |
| **date**                          | string    | Date when the bill was issued by the vendor. Format: yyyy-mm-dd.                                            |
| **due_date**                      | string    | Date when payment is due for the bill.                                                                      |
| **payment_terms**                 | integer   | Numeric identifier for payment terms configuration (e.g., 15 for Net 15).                                   |
| **payment_terms_label**           | string    | Label of the Payment Terms.                                                                                 |
| **payment_expected_date**         | string    | Expected Payment date of the Bill.                                                                          |
| **reference_number**              | string    | External reference number from vendor invoice or purchase order.                                            |
| **recurring_bill_id**             | string    | Identifier linking this bill to a recurring bill template.                                                  |
| **due_by_days**                   | string    | Days by which Bill is Due.                                                                                  |
| **due_in_days**                   | integer   | Days in which Bill will be Due.                                                                             |
| **currency_id**                   | string    | Unique identifier for the currency used in the bill transaction.                                            |
| **currency_code**                 | string    | Code of the Currency.                                                                                       |
| **currency_symbol**               | string    | Symbol of the Currency.                                                                                     |
| **documents**                     | array     | Array containing `document_id` and `file_name`.                                                             |
| **price_precision**               | integer   | Precision for the values.                                                                                   |
| **exchange_rate**                 | double    | Exchange rate from bill currency to organization base currency.                                             |
| **adjustment**                    | double    | Additional amount added to or subtracted from bill total.                                                   |
| **adjustment_description**        | string    | Text description explaining the reason for bill adjustment.                                                 |
| **custom_fields**                 | array     | Array of Custom Fields (`custom_field_id`, `index`, `label`, `value`).                                      |
| **is_tds_applied**                | boolean   | **[India, Global, Australia only]** Check if TDS is applied.                                                |
| **is_item_level_tax_calc**        | boolean   | Flag indicating whether taxes are calculated at individual line item level.                                 |
| **is_inclusive_tax**              | boolean   | **[Not applicable for US]** Flag indicating whether line item rates include tax amounts.                    |
| **filed_in_vat_return_id**        | string    | **[UK only]** ID of the VAT Return the Vendor Credit is filed in.                                           |
| **filed_in_vat_return_name**      | string    | **[UK only]** Name of the VAT Return the Vendor Credit is filed in.                                         |
| **filed_in_vat_return_type**      | string    | **[UK only]** Type of the VAT Return the Vendor Credit is filed in.                                         |
| **is_abn_quoted**                 | string    | **[Australia only]**                                                                                        |
| **line_items**                    | array     | Individual items/expenses. Details below.                                                                   |
| **location_id**                   | string    | Unique identifier for the business location where the bill transaction occurs.                              |
| **location_name**                 | string    | Name of the location.                                                                                       |
| **sub_total**                     | integer   | Sub Total of the Bill.                                                                                      |
| **tax_total**                     | integer   | Tax Total of the Bill.                                                                                      |
| **total**                         | integer   | Total of the Bill.                                                                                          |
| **payment_made**                  | integer   | Amount of Payment made.                                                                                     |
| **vendor_credits_applied**        | integer   | Amount of credits applied.                                                                                  |
| **is_line_item_invoiced**         | boolean   | Check if line item is invoiced.                                                                             |
| **purchaseorders**                | array     | List of associated Purchase Orders details.                                                                 |
| **taxes**                         | array     | List of taxes applied.                                                                                      |
| **acquisition_vat_summary**       | array     | **[UK, Europe only]** Summary of the VAT Acquisition.                                                       |
| **acquisition_vat_total**         | double    | **[UK, Europe only]** Total of the VAT Acquisition.                                                         |
| **reverse_charge_vat_summary**    | array     | **[UK, Europe only]** Summary of the Reverse Charge.                                                        |
| **reverse_charge_vat_total**      | double    | **[UK, Europe only]** Total of the Reverse Charge.                                                          |
| **balance**                       | integer   | Balance in the Bill.                                                                                        |
| **billing_address**               | object    | Address object (`address`, `city`, `state`, `zip`, `country`, etc.).                                        |
| **payments**                      | array     | List of payments made (`payment_id`, `payment_mode`, `amount`, etc.).                                       |
| **vendor_credits**                | array     | List of vendor credits applied (`vendor_credit_id`, `vendor_credit_number`, `amount`).                      |
| **created_time**                  | string    | Created time of the bill.                                                                                   |
| **created_by_id**                 | string    | Name of User who created the Bill.                                                                          |
| **last_modified_time**            | string    | Last Modified Time of the Bill.                                                                             |
| **reference_id**                  | string    |                                                                                                             |
| **notes**                         | string    | Additional information or comments.                                                                         |
| **terms**                         | string    | Terms and conditions.                                                                                       |
| **attachment_name**               | string    | Name of the Attachment.                                                                                     |
| **open_purchaseorders_count**     | integer   | Number of Open Purchase Orders.                                                                             |

**Line Item Attributes:**
*   `line_item_id`, `item_id`, `sku`, `name`, `description`, `account_id`, `account_name`, `quantity`, `rate`, `unit`, `item_total`, `tax_id` (and related tax fields), `hsn_or_sac` (India/Kenya/SA), `project_id`, `customer_id`, `billable_status`.

---

## Create a bill

Create a bill received from your vendor.
**OAuth Scope:** `ZohoBooks.bills.CREATE`

### Arguments

| Argument                   | Type    | Required | Description                                                  |
| :------------------------- | :------ | :------- | :----------------------------------------------------------- |
| **vendor_id**              | string  | Required | Unique identifier for the vendor.                            |
| **bill_number**            | string  | Required | Unique sequential identifier for the bill.                   |
| **currency_id**            | string  | Optional | Unique identifier for the currency.                          |
| **vat_treatment**          | string  | Optional | **[UK only]** VAT treatment.                                 |
| **is_update_customer**     | boolean | Optional | Flag to determine if customer information should be updated. |
| **purchaseorder_ids**      | array   | Optional | Array of linked purchase order identifiers.                  |
| **documents**              | array   | Optional | Documents attached to the bill.                              |
| **source_of_supply**       | string  | Optional | **[India only]** State code of origin.                       |
| **destination_of_supply**  | string  | Optional | **[India only]** State code of delivery.                     |
| **place_of_supply**        | string  | Optional | **[GCC only]** Place of supply.                              |
| **permit_number**          | string  | Optional | **[UAE only]** Permit number.                                |
| **gst_treatment**          | string  | Optional | **[India only]** GST treatment.                              |
| **tax_treatment**          | string  | Optional | **[GCC, Mexico, Kenya, SA only]** Tax treatment.             |
| **gst_no**                 | string  | Optional | **[India only]** 15 digit GST ID.                            |
| **pricebook_id**           | string  | Optional | Identifier for the price book.                               |
| **reference_number**       | string  | Optional | External reference number.                                   |
| **date**                   | string  | Optional | Bill issue date (yyyy-mm-dd).                                |
| **due_date**               | string  | Optional | Payment due date.                                            |
| **payment_terms**          | integer | Optional | Payment terms configuration.                                 |
| **payment_terms_label**    | string  | Optional | Label of the Payment Terms.                                  |
| **recurring_bill_id**      | string  | Optional | Identifier linking to a recurring bill template.             |
| **exchange_rate**          | double  | Optional | Exchange rate.                                               |
| **is_item_level_tax_calc** | boolean | Optional | Calculate tax at line item level.                            |
| **is_inclusive_tax**       | boolean | Optional | **[Not for US]** Rates include tax.                          |
| **adjustment**             | double  | Optional | Additional adjustment amount.                                |
| **adjustment_description** | string  | Optional | Description for adjustment.                                  |
| **location_id**            | string  | Optional | Business location ID.                                        |
| **custom_fields**          | array   | Optional | Custom fields.                                               |
| **line_items**             | array   | Optional | Line items of a bill.                                        |
| **taxes**                  | array   | Optional | **[Not for US]** Taxes applied.                              |
| **notes**                  | string  | Optional | Notes.                                                       |
| **terms**                  | string  | Optional | Terms.                                                       |
| **approvers**              | array   | Optional | Approvers list.                                              |

### Query Parameters

| Parameter           | Type   | Required | Description                                                                       |
| :------------------ | :----- | :------- | :-------------------------------------------------------------------------------- |
| **organization_id** | string | Required | ID of the organization                                                            |
| **attachment**      | binary | Optional | File to attach. Allowed Extensions: `gif`, `png`, `jpeg`, `jpg`, `bmp` and `pdf`. |

### Request Example

```json
{
    "vendor_id": "460000000038029",
    "currency_id": "460000000000099",
    "bill_number": "00454",
    "date": "2013-09-11",
    "due_date": "2013-09-26",
    "line_items": [
        {
            "item_id": "460000000054135",
            "account_id": "460000000000403",
            "rate": 10,
            "quantity": 1
        }
    ]
}
```

---

## Update a bill using a custom field's unique value

Update a bill by identifying it via a unique custom field.
**OAuth Scope:** `ZohoBooks.bills.UPDATE`

### Headers

| Header                        | Type    | Required | Description                                        |
| :---------------------------- | :------ | :------- | :------------------------------------------------- |
| **X-Unique-Identifier-Key**   | string  | Required | API name of the custom field with unique values.   |
| **X-Unique-Identifier-Value** | string  | Required | Value of the custom field to identify the bill.    |
| **X-Upsert**                  | boolean | Optional | If true, creates a new bill if no record is found. |

### Query Parameters

| Parameter           | Type   | Required | Description            |
| :------------------ | :----- | :------- | :--------------------- |
| **organization_id** | string | Required | ID of the organization |

### Arguments
(Same as Create Bill)

### Request Example
```bash
curl --request PUT \
  --url 'https://www.zohoapis.com/books/v3/bills?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken ...' \
  --header 'X-Unique-Identifier-Key: cf_unique_cf' \
  --header 'X-Unique-Identifier-Value: unique Value' \
  --header 'X-Upsert: true' \
  --header 'content-type: application/json' \
  --data '{"field1":"value1","field2":"value2"}'
```

---

## List bills

List all bills with pagination.
**OAuth Scope:** `ZohoBooks.bills.READ`

### Query Parameters

| Parameter              | Type    | Required | Description                                                            |
| :--------------------- | :------ | :------- | :--------------------------------------------------------------------- |
| **organization_id**    | string  | Required | ID of the organization                                                 |
| **bill_number**        | string  | Optional | Filter by bill number (supports startswith/contains).                  |
| **reference_number**   | string  | Optional | Filter by reference number (supports startswith/contains).             |
| **date**               | string  | Optional | Filter by date (YYYY-MM-DD). Supports start/end/before/after.          |
| **status**             | string  | Optional | Filter by status: `paid`, `open`, `overdue`, `void`, `partially_paid`. |
| **description**        | string  | Optional | Filter by description.                                                 |
| **vendor_name**        | string  | Optional | Filter by vendor name.                                                 |
| **total**              | double  | Optional | Filter by total amount (less_than, greater_than, etc.).                |
| **vendor_id**          | long    | Optional | Filter by vendor ID.                                                   |
| **item_id**            | long    | Optional | Filter by item ID.                                                     |
| **recurring_bill_id**  | long    | Optional | Filter by recurring bill ID.                                           |
| **purchaseorder_id**   | long    | Optional | Filter by purchase order ID.                                           |
| **last_modified_time** | string  | Optional | Filter by last modified time.                                          |
| **filter_by**          | string  | Optional | Filter by status constants (e.g., `Status.All`, `Status.Open`).        |
| **search_text**        | string  | Optional | General search text.                                                   |
| **page**               | integer | Optional | Page number.                                                           |
| **per_page**           | integer | Optional | Records per page (Default 200).                                        |
| **sort_column**        | string  | Optional | Sort by column.                                                        |
| **sort_order**         | string  | Optional | Sort order (`A` or `D`).                                               |

### Request Example
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/bills?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken ...'
```

---

## Update a bill

Update a bill. To delete a line item just remove it from the line_items list.
**OAuth Scope:** `ZohoBooks.bills.UPDATE`

### Path Parameters

| Parameter   | Type   | Required | Description                    |
| :---------- | :----- | :------- | :----------------------------- |
| **bill_id** | string | Required | Unique identifier of the bill. |

### Query Parameters

| Parameter           | Type   | Required | Description            |
| :------------------ | :----- | :------- | :--------------------- |
| **organization_id** | string | Required | ID of the organization |
| **attachment**      | binary | Optional | File to attach.        |

### Arguments
(Same as Create Bill)

### Request Example
```bash
curl --request PUT \
  --url 'https://www.zohoapis.com/books/v3/bills/460000000098765?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken ...' \
  --header 'content-type: application/json' \
  --data '{"field1":"value1","field2":"value2"}'
```

---

## Get a bill

Get the details of a bill.
**OAuth Scope:** `ZohoBooks.bills.READ`

### Path Parameters

| Parameter   | Type   | Required | Description                    |
| :---------- | :----- | :------- | :----------------------------- |
| **bill_id** | string | Required | Unique identifier of the bill. |

### Query Parameters

| Parameter           | Type   | Required | Description            |
| :------------------ | :----- | :------- | :--------------------- |
| **organization_id** | string | Required | ID of the organization |

### Request Example
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/bills/460000000098765?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken ...'
```

---

## Delete a bill

Delete an existing bill. Bills which have payments applied cannot be deleted.
**OAuth Scope:** `ZohoBooks.bills.DELETE`

### Path Parameters

| Parameter   | Type   | Required | Description                    |
| :---------- | :----- | :------- | :----------------------------- |
| **bill_id** | string | Required | Unique identifier of the bill. |

### Query Parameters

| Parameter           | Type   | Required | Description            |
| :------------------ | :----- | :------- | :--------------------- |
| **organization_id** | string | Required | ID of the organization |

### Request Example
```bash
curl --request DELETE \
  --url 'https://www.zohoapis.com/books/v3/bills/460000000098765?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken ...'
```

---

## Update custom field in existing bills

Update the value of the custom field in existing bills.
**OAuth Scope:** `ZohoBooks.bills.UPDATE`

### Path Parameters

| Parameter   | Type   | Required | Description                    |
| :---------- | :----- | :------- | :----------------------------- |
| **bill_id** | string | Required | Unique identifier of the bill. |

### Query Parameters

| Parameter           | Type   | Required | Description            |
| :------------------ | :----- | :------- | :--------------------- |
| **organization_id** | string | Required | ID of the organization |

### Arguments

| Argument            | Type    | Required | Description               |
| :------------------ | :------ | :------- | :------------------------ |
| **custom_field_id** | long    | Optional |                           |
| **index**           | integer | Optional | Index of the custom field |
| **label**           | string  | Optional | Label of the Custom Field |
| **value**           | string  | Optional | Value of the Custom Field |

### Request Example
```bash
curl --request PUT \
  --url 'https://www.zohoapis.com/books/v3/bill/460000000098765/customfields?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken ...' \
  --header 'content-type: application/json' \
  --data '[{"custom_field_id":0,"index":0,"label":"string","value":"string"}]'
```

---

## Void a bill

Mark a bill status as void.
**OAuth Scope:** `ZohoBooks.bills.CREATE`

### Path Parameters

| Parameter   | Type   | Required | Description                    |
| :---------- | :----- | :------- | :----------------------------- |
| **bill_id** | string | Required | Unique identifier of the bill. |

### Query Parameters

| Parameter           | Type   | Required | Description            |
| :------------------ | :----- | :------- | :--------------------- |
| **organization_id** | string | Required | ID of the organization |

### Request Example
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/bills/460000000098765/status/void?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken ...'
```

---

## Mark a bill as open

Mark a void bill as open.
**OAuth Scope:** `ZohoBooks.bills.CREATE`

### Path Parameters

| Parameter   | Type   | Required | Description                    |
| :---------- | :----- | :------- | :----------------------------- |
| **bill_id** | string | Required | Unique identifier of the bill. |

### Query Parameters

| Parameter           | Type   | Required | Description            |
| :------------------ | :----- | :------- | :--------------------- |
| **organization_id** | string | Required | ID of the organization |

### Request Example
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/bills/460000000098765/status/open?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken ...'
```

---

## Submit a bill for approval

Submit a bill for approval.
**OAuth Scope:** `ZohoBooks.bills.CREATE`

### Path Parameters

| Parameter   | Type   | Required | Description                    |
| :---------- | :----- | :------- | :----------------------------- |
| **bill_id** | string | Required | Unique identifier of the bill. |

### Query Parameters

| Parameter           | Type   | Required | Description            |
| :------------------ | :----- | :------- | :--------------------- |
| **organization_id** | string | Required | ID of the organization |

### Request Example
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/bills/460000000098765/submit?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken ...'
```

---

## Approve a bill

Approve a bill.
**OAuth Scope:** `ZohoBooks.bills.CREATE`

### Path Parameters

| Parameter   | Type   | Required | Description                    |
| :---------- | :----- | :------- | :----------------------------- |
| **bill_id** | string | Required | Unique identifier of the bill. |

### Query Parameters

| Parameter           | Type   | Required | Description            |
| :------------------ | :----- | :------- | :--------------------- |
| **organization_id** | string | Required | ID of the organization |

### Request Example
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/bills/460000000098765/approve?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken ...'
```

---

## Update billing address

Updates the billing address for this bill.
**OAuth Scope:** `ZohoBooks.bills.UPDATE`

### Path Parameters

| Parameter   | Type   | Required | Description                    |
| :---------- | :----- | :------- | :----------------------------- |
| **bill_id** | string | Required | Unique identifier of the bill. |

### Query Parameters

| Parameter           | Type   | Required | Description            |
| :------------------ | :----- | :------- | :--------------------- |
| **organization_id** | string | Required | ID of the organization |

### Arguments

| Argument               | Type    | Required | Description                                                  |
| :--------------------- | :------ | :------- | :----------------------------------------------------------- |
| **address**            | string  | Optional | Address involved in the Bill                                 |
| **city**               | string  | Optional | City in the Address                                          |
| **state**              | string  | Optional | State involved in the Address                                |
| **zip**                | string  | Optional | ZIP Code involved in the Address                             |
| **country**            | string  | Optional | Country Involved in the Address                              |
| **fax**                | string  | Optional | Fax of the Vendor                                            |
| **attention**          | string  | Optional |                                                              |
| **is_update_customer** | boolean | Optional | Flag to determine if customer information should be updated. |

### Request Example
```bash
curl --request PUT \
  --url 'https://www.zohoapis.com/books/v3/bills/460000000098765/address/billing?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken ...' \
  --header 'content-type: application/json' \
  --data '{"address":"string","city":"string","state":"string","zip":"string","country":"string","fax":"string","attention":"string","is_update_customer":false}'
```

---

## List bill payments

Get the list of payments made for a bill.
**OAuth Scope:** `ZohoBooks.bills.READ`

### Path Parameters

| Parameter   | Type   | Required | Description                    |
| :---------- | :----- | :------- | :----------------------------- |
| **bill_id** | string | Required | Unique identifier of the bill. |

### Query Parameters

| Parameter           | Type   | Required | Description            |
| :------------------ | :----- | :------- | :--------------------- |
| **organization_id** | string | Required | ID of the organization |

### Request Example
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/bills/460000000098765/payments?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken ...'
```

---

## Apply credits

Apply the vendor credits from excess vendor payments to a bill. Multiple credits can be applied at once.
**OAuth Scope:** `ZohoBooks.bills.CREATE`

### Path Parameters

| Parameter   | Type   | Required | Description                    |
| :---------- | :----- | :------- | :----------------------------- |
| **bill_id** | string | Required | Unique identifier of the bill. |

### Query Parameters

| Parameter           | Type   | Required | Description            |
| :------------------ | :----- | :------- | :--------------------- |
| **organization_id** | string | Required | ID of the organization |

### Arguments

| Argument                 | Type  | Required | Description                                                               |
| :----------------------- | :---- | :------- | :------------------------------------------------------------------------ |
| **bill_payments**        | array | Optional | List of payments. Contains `payment_id` and `amount_applied`.             |
| **apply_vendor_credits** | array | Optional | List of vendor credits. Contains `vendor_credit_id` and `amount_applied`. |

### Request Example
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/bills/460000000098765/credits?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken ...' \
  --header 'content-type: application/json' \
  --data '{"bill_payments":[{"payment_id":"460000000042059","amount_applied":31.25}],"apply_vendor_credits":[{"vendor_credit_id":"4600000053221","amount_applied":31.25}]}'
```

---

## Delete a payment

Delete a payment made to a bill.
**OAuth Scope:** `ZohoBooks.bills.DELETE`

### Path Parameters

| Parameter           | Type   | Required | Description                            |
| :------------------ | :----- | :------- | :------------------------------------- |
| **bill_id**         | string | Required | Unique identifier of the bill.         |
| **bill_payment_id** | string | Required | Unique identifier of the bill payment. |

### Query Parameters

| Parameter           | Type   | Required | Description            |
| :------------------ | :----- | :------- | :--------------------- |
| **organization_id** | string | Required | ID of the organization |

### Request Example
```bash
curl --request DELETE \
  --url 'https://www.zohoapis.com/books/v3/bills/460000000098765/payments/460000000042061?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken ...'
```

---

## Add attachment to a bill

Attach a file to a bill.
**OAuth Scope:** `ZohoBooks.bills.CREATE`

### Path Parameters

| Parameter   | Type   | Required | Description                    |
| :---------- | :----- | :------- | :----------------------------- |
| **bill_id** | string | Required | Unique identifier of the bill. |

### Query Parameters

| Parameter           | Type   | Required | Description                                                                       |
| :------------------ | :----- | :------- | :-------------------------------------------------------------------------------- |
| **organization_id** | string | Required | ID of the organization                                                            |
| **attachment**      | binary | Optional | File to attach. Allowed Extensions: `gif`, `png`, `jpeg`, `jpg`, `bmp` and `pdf`. |

### Request Example
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/bills/460000000098765/attachment?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken ...'
```

---

## Get a bill attachment

Returns the file attached to the bill.
**OAuth Scope:** `ZohoBooks.bills.READ`

### Path Parameters

| Parameter   | Type   | Required | Description                    |
| :---------- | :----- | :------- | :----------------------------- |
| **bill_id** | string | Required | Unique identifier of the bill. |

### Query Parameters

| Parameter           | Type    | Required | Description                          |
| :------------------ | :------ | :------- | :----------------------------------- |
| **organization_id** | string  | Required | ID of the organization               |
| **preview**         | boolean | Optional | Get the thumbnail of the attachment. |

### Request Example
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/bills/460000000098765/attachment?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken ...'
```

---

## Delete an attachment

Delete the file attached to a bill.
**OAuth Scope:** `ZohoBooks.bills.DELETE`

### Path Parameters

| Parameter   | Type   | Required | Description                    |
| :---------- | :----- | :------- | :----------------------------- |
| **bill_id** | string | Required | Unique identifier of the bill. |

### Query Parameters

| Parameter           | Type   | Required | Description            |
| :------------------ | :----- | :------- | :--------------------- |
| **organization_id** | string | Required | ID of the organization |

### Request Example
```bash
curl --request DELETE \
  --url 'https://www.zohoapis.com/books/v3/bills/460000000098765/attachment?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken ...'
```

---

## Add comment

Add a comment for a bill.
**OAuth Scope:** `ZohoBooks.bills.CREATE`

### Path Parameters

| Parameter   | Type   | Required | Description                    |
| :---------- | :----- | :------- | :----------------------------- |
| **bill_id** | string | Required | Unique identifier of the bill. |

### Query Parameters

| Parameter           | Type   | Required | Description            |
| :------------------ | :----- | :------- | :--------------------- |
| **organization_id** | string | Required | ID of the organization |

### Arguments

| Argument        | Type   | Required | Description                          |
| :-------------- | :----- | :------- | :----------------------------------- |
| **description** | string | Required | Detailed description of the comment. |

### Request Example
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/bills/460000000098765/comments?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken ...' \
  --header 'content-type: application/json' \
  --data '{"description":"string"}'
```

---

## List bill comments & history

Get the complete history and comments of a bill.
**OAuth Scope:** `ZohoBooks.bills.READ`

### Path Parameters

| Parameter   | Type   | Required | Description                    |
| :---------- | :----- | :------- | :----------------------------- |
| **bill_id** | string | Required | Unique identifier of the bill. |

### Query Parameters

| Parameter           | Type   | Required | Description            |
| :------------------ | :----- | :------- | :--------------------- |
| **organization_id** | string | Required | ID of the organization |

### Request Example
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/bills/460000000098765/comments?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken ...'
```

---

## Delete a comment

Delete a bill comment.
**OAuth Scope:** `ZohoBooks.bills.DELETE`

### Path Parameters

| Parameter      | Type   | Required | Description                       |
| :------------- | :----- | :------- | :-------------------------------- |
| **bill_id**    | string | Required | Unique identifier of the bill.    |
| **comment_id** | string | Required | Unique identifier of the comment. |

### Query Parameters

| Parameter           | Type   | Required | Description            |
| :------------------ | :----- | :------- | :--------------------- |
| **organization_id** | string | Required | ID of the organization |

### Request Example
```bash
curl --request DELETE \
  --url 'https://www.zohoapis.com/books/v3/bills/460000000098765/comments/460000000069037?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken ...'
```

---

## Convert PO to Bill

Create a bill for the selected purchase orders. Use this api to fetch the Bill payload by passing the purchaseorder_ids in the query parameters and then use the create bill api and pass the payload to create a bill.
**OAuth Scope:** `ZohoBooks.bills.READ`

### Query Parameters

| Parameter             | Type   | Required | Description              |
| :-------------------- | :----- | :------- | :----------------------- |
| **purchaseorder_ids** | string | Required | ID of the purchase order |
| **organization_id**   | string | Required | ID of the organization   |

### Request Example
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/bills/editpage/frompurchaseorders?purchaseorder_ids=460000000098765&organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken ...'
```