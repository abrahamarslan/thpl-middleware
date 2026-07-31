# Vendor Payments

Payments to Vendors towards Bills.

### Vendor Payments OpenAPI Document
[Download Vendor Payments OpenAPI Document](vendor-payments.yml)

---

## Create a vendor payment
Create a payment made to your vendor and you can also apply them to bills either partially or fully.

`OAuth Scope : ZohoBooks.vendorpayments.CREATE`

### Arguments

| Argument                  | Type    | Required     | Description                                                                                           |
| :------------------------ | :------ | :----------- | :---------------------------------------------------------------------------------------------------- |
| vendor_id                 | string  | Optional     | ID of the vendor associated with the Vendor Payment.                                                  |
| bills                     | array   | Optional     | Individual bill payment details as array.                                                             |
| bills.bill_payment_id     | string  | Optional     | ID of the Bill Payment                                                                                |
| bills.bill_id             | string  | Optional     | ID of the bill the payment is to be applied.                                                          |
| bills.amount_applied      | double  | Optional     | Amount applied to the bill.                                                                           |
| bills.tax_amount_withheld | double  | Optional     | **🌎 Global, 🇮🇳 India, 🇦🇺 Australia only** Tax Amount Withheld during Bill Payment                       |
| date                      | string  | Optional     | Date the payment is made.                                                                             |
| exchange_rate             | double  | Optional     | Exchange rate of the currency.                                                                        |
| amount                    | double  | **Required** | Total Amount of Vendor Payment                                                                        |
| paid_through_account_id   | string  | Optional     | ID of the cash/ bank account from which the payment is made.                                          |
| payment_mode              | string  | Optional     | Mode of Vendor Payment                                                                                |
| description               | string  | Optional     | Description for the Vendor Payment recorded.                                                          |
| reference_number          | string  | Optional     | Reference number for the Vendor Payment recorded.                                                     |
| check_details             | array   | Optional     | **🇺🇸 United States, 🇨🇦 Canada only**                                                                    |
| is_paid_via_print_check   | boolean | Optional     | **🇺🇸 United States, 🇨🇦 Canada, 🇲🇽 Mexico only** Check if the Bill Payment is paid Via Print Check Option |
| location_id               | string  | Optional     | Location ID                                                                                           |
| custom_fields             | array   | Optional     | Custom fields.                                                                                        |
| custom_fields.index       | integer | Optional     | Index of the Custom Field                                                                             |
| custom_fields.value       | string  | Optional     | Value for the Custom Field                                                                            |

### Query Parameters

| Parameter       | Type   | Required     | Description            |
| :-------------- | :----- | :----------- | :--------------------- |
| organization_id | string | **Required** | ID of the organization |

### Request Example

```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/vendorpayments?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{
    "vendor_id": "460000000026049",
    "bills": [
        {
            "bill_payment_id": "460000000053221",
            "bill_id": "460000000053199",
            "amount_applied": 150,
            "tax_amount_withheld": 0.1
        }
    ],
    "date": "2013-10-07",
    "exchange_rate": 1,
    "amount": 500,
    "paid_through_account_id": "460000000000358",
    "payment_mode": "Stripe",
    "description": "string",
    "reference_number": "REF#912300",
    "check_details": [
        "string"
    ],
    "is_paid_via_print_check": false,
    "location_id": "460000000038080",
    "custom_fields": [
        {
            "index": 0,
            "value": "string"
        }
    ]
}'
```

### Response Example

```json
{
    "code": 0,
    "message": "The payment made to the vendor has been recorded.",
    "ach_payment_status": "string",
    "amount": 500,
    "balance": 300,
    "billing_address": [
        "address",
        "city",
        "state",
        "zip",
        "country",
        "fax",
        "attention"
    ],
    "bills": [
        {
            "bill_payment_id": "460000000053221",
            "bill_id": "460000000053199",
            "amount_applied": 150,
            "tax_amount_withheld": 0.1,
            "balance": 300,
            "bill_number": "B-1000",
            "date": "2013-10-07",
            "due_date": "2013-10-07",
            "price_precision": 2,
            "total": 450
        }
    ],
    "check_details": {
        "amount_in_words": "string",
        "check_id": "string",
        "check_number": "string",
        "check_status": "string",
        "memo": "string"
    },
    "comments": "Payment of amount $150.00 made and applied for b-01",
    "created_time": "2016-12-16T00:18:42-0500",
    "currency_id": "460000000000099",
    "currency_symbol": "$",
    "custom_fields": [
        {
            "custom_field_id": "string",
            "index": 0,
            "label": "string",
            "value": "string"
        }
    ],
    "date": "2013-10-07",
    "description": "string",
    "exchange_rate": 1,
    "imported_transactions": [
        "string"
    ],
    "documents": [
        "string"
    ],
    "is_ach_payment": false,
    "is_paid_via_print_check": false,
    "last_modified_time": "string",
    "paid_through_account_id": "460000000000358",
    "paid_through_account_name": "Undeposited Funds",
    "paid_through_account_type": "cash",
    "payment_id": "460000000053219",
    "payment_mode": "Stripe",
    "payment_number": 4,
    "reference_number": "REF#912300",
    "tax_account_name": "string",
    "tax_amount_withheld": 0.1,
    "location_id": "460000000038080",
    "location_name": "string",
    "vendor_id": "460000000026049",
    "vendor_name": "Bowman and Co",
    "vendorpayment_refunds": [
        {
            "vendorpayment_refund_id": "460000000003017",
            "date": "2017-01-10",
            "refund_mode": "cash",
            "reference_number": "string",
            "description": "Payment Refund",
            "amount_bcy": 4,
            "amount_fcy": 4
        }
    ]
}
```

---

## Update an vendor payment using a custom field's unique value
A custom field will have unique values if it's configured to not accept duplicate values. Now, you can use that custom field's value to update a vendor payment by providing its API name in the X-Unique-Identifier-Key header and its value in the X-Unique-Identifier-Value header. Based on this value, the corresponding vendor payment will be retrieved and updated. Additionally, there is an optional X-Upsert header. If the X-Upsert header is true and the custom field's unique value is not found in any of the existing vendor payments, a new vendor payment will be created if the necessary payload details are available.

`OAuth Scope : ZohoBooks.vendorpayments.UPDATE`

### Arguments

| Argument                | Type    | Required     | Description                                                                                           |
| :---------------------- | :------ | :----------- | :---------------------------------------------------------------------------------------------------- |
| vendor_id               | string  | Optional     | ID of the vendor associated with the Vendor Payment.                                                  |
| bills                   | array   | Optional     | Individual bill payment details as array.                                                             |
| date                    | string  | Optional     | Date the payment is made.                                                                             |
| exchange_rate           | double  | Optional     | Exchange rate of the currency.                                                                        |
| amount                  | double  | **Required** | Total Amount of Vendor Payment                                                                        |
| paid_through_account_id | string  | Optional     | ID of the cash/ bank account from which the payment is made.                                          |
| payment_mode            | string  | Optional     | Mode of Vendor Payment                                                                                |
| description             | string  | Optional     | Description for the Vendor Payment recorded.                                                          |
| reference_number        | string  | Optional     | Reference number for the Vendor Payment recorded.                                                     |
| is_paid_via_print_check | boolean | Optional     | **🇺🇸 United States, 🇨🇦 Canada, 🇲🇽 Mexico only** Check if the Bill Payment is paid Via Print Check Option |
| check_details           | array   | Optional     | **🇺🇸 United States, 🇨🇦 Canada only**                                                                    |
| location_id             | string  | Optional     | Location ID                                                                                           |
| custom_fields           | array   | Optional     | Custom fields details                                                                                 |

### Query Parameters

| Parameter       | Type   | Required     | Description            |
| :-------------- | :----- | :----------- | :--------------------- |
| organization_id | string | **Required** | ID of the organization |

### Headers

| Parameter                 | Type    | Required     | Description                                                                        |
| :------------------------ | :------ | :----------- | :--------------------------------------------------------------------------------- |
| X-Unique-Identifier-Key   | string  | **Required** | Unique CustomField Api Name                                                        |
| X-Unique-Identifier-Value | string  | **Required** | Unique CustomField Value                                                           |
| X-Upsert                  | boolean | Optional     | If there is no record is found unique custom field value , will create new invoice |

### Request Example

```bash
curl --request PUT \
  --url 'https://www.zohoapis.com/books/v3/vendorpayments?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'X-Unique-Identifier-Key: cf_unique_cf' \
  --header 'X-Unique-Identifier-Value: unique Value' \
  --header 'X-Upsert: true' \
  --header 'content-type: application/json' \
  --data '{
    "vendor_id": "460000000026049",
    "bills": [
        {
            "bill_payment_id": "460000000053221",
            "bill_id": "460000000053199",
            "amount_applied": 150,
            "tax_amount_withheld": 0.1
        }
    ],
    "date": "2013-10-07",
    "exchange_rate": 1,
    "amount": 500,
    "paid_through_account_id": "460000000000358",
    "payment_mode": "Stripe",
    "description": "string",
    "reference_number": "REF#912300",
    "is_paid_via_print_check": false,
    "check_details": [
        "string"
    ],
    "location_id": "460000000038080",
    "custom_fields": [
        {
            "index": 0,
            "value": "string"
        }
    ]
}'
```

---

## List vendor payments
List all the payments made to your vendor.

`OAuth Scope : ZohoBooks.vendorpayments.READ`

### Query Parameters

| Parameter          | Type    | Required     | Description                                                                                                                                                                                                                                                                                                                                       |
| :----------------- | :------ | :----------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| organization_id    | string  | **Required** | ID of the organization                                                                                                                                                                                                                                                                                                                            |
| vendor_name        | string  | Optional     | Search payments by vendor name. Variants: `vendor_name_startswith` and `vendor_name_contains`.                                                                                                                                                                                                                                                    |
| reference_number   | string  | Optional     | Search payments by reference number. Variants: `reference_number_startswith` and `reference_number_contains`. In refunds, reference number for the refund recorded.                                                                                                                                                                               |
| payment_number     | string  | Optional     | Search with Payment Number. Variant: `payment_number_startswith`, `payment_number_contains`                                                                                                                                                                                                                                                       |
| date               | string  | Optional     | Date the payment is made. Search payments by payment made date. Variants: `date_start`, `date_end`, `date_before` and `date_after`.                                                                                                                                                                                                               |
| amount             | double  | Optional     | Payment amount made to the vendor. Search payments by payment amount. Variants: `amount_less_than`, `amount_less_equals`, `amount_greater_than` and `amount_greater_equals`. In refunds, Amount refunded from the vendor payment.                                                                                                                 |
| payment_mode       | string  | Optional     | Search payments by payment mode. Variants: `payment_mode_startswith` and `payment_mode_contains`.                                                                                                                                                                                                                                                 |
| notes              | string  | Optional     | Search with Payment Notes. Variant: `notes_startswith`, `notes_contains`                                                                                                                                                                                                                                                                          |
| vendor_id          | string  | Optional     | ID of the vendor. Search payments by vendor id.                                                                                                                                                                                                                                                                                                   |
| last_modified_time | string  | Optional     | Search with the Last Modified Time of the Vendor Payment                                                                                                                                                                                                                                                                                          |
| bill_id            | string  | Optional     | Search payments by Bill ID.                                                                                                                                                                                                                                                                                                                       |
| description        | string  | Optional     | Search payments by description. Variants: `description_startswith` and `description_contains`.                                                                                                                                                                                                                                                    |
| filter_by          | string  | Optional     | Filter payments by mode. Allowed Values: `PaymentMode.All`, `PaymentMode.Check`, `PaymentMode.Cash`, `PaymentMode.BankTransfer`, `PaymentMode.Paypal`, `PaymentMode.CreditCard`, `PaymentMode.GoogleCheckout`, `PaymentMode.Credit`, `PaymentMode.Authorizenet`, `PaymentMode.BankRemittance`, `PaymentMode.Payflowpro` and `PaymentMode.Others`. |
| search_text        | string  | Optional     | Search payments by reference number or vendor name or payment description.                                                                                                                                                                                                                                                                        |
| sort_column        | string  | Optional     | Sort the payment list. Allowed Values: `vendor_name`, `date`, `reference_number`, `amount` and `balance`.                                                                                                                                                                                                                                         |
| page               | integer | Optional     | Page number to be fetched. Default value is 1.                                                                                                                                                                                                                                                                                                    |
| per_page           | integer | Optional     | Number of records to be fetched per page. Default value is 200.                                                                                                                                                                                                                                                                                   |

### Request Example

```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/vendorpayments?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Bulk delete vendor payments
Delete multiple vendor payments.

`OAuth Scope : ZohoBooks.vendorpayments.DELETE`

### Query Parameters

| Parameter        | Type    | Required     | Description                                              |
| :--------------- | :------ | :----------- | :------------------------------------------------------- |
| organization_id  | string  | **Required** | ID of the organization                                   |
| vendorpayment_id | string  | **Required** | Comma-separated list of vendor payment IDs to be deleted |
| bulk_delete      | boolean | **Required** | Flag to indicate bulk delete operation                   |

### Request Example

```bash
curl --request DELETE \
  --url 'https://www.zohoapis.com/books/v3/vendorpayments?organization_id=10234695&vendorpayment_id=460000000053219,460000000053220,460000000053221&bulk_delete=true' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Update a vendor payment
Update an existing vendor payment. You can also modify the amount applied to the bills.

`OAuth Scope : ZohoBooks.vendorpayments.UPDATE`

### Arguments

| Argument                | Type    | Required     | Description                                                                                           |
| :---------------------- | :------ | :----------- | :---------------------------------------------------------------------------------------------------- |
| vendor_id               | string  | Optional     | ID of the vendor associated with the Vendor Payment.                                                  |
| bills                   | array   | Optional     | Individual bill payment details as array.                                                             |
| date                    | string  | Optional     | Date the payment is made.                                                                             |
| exchange_rate           | double  | Optional     | Exchange rate of the currency.                                                                        |
| amount                  | double  | **Required** | Total Amount of Vendor Payment                                                                        |
| paid_through_account_id | string  | Optional     | ID of the cash/ bank account from which the payment is made.                                          |
| payment_mode            | string  | Optional     | Mode of Vendor Payment                                                                                |
| description             | string  | Optional     | Description for the Vendor Payment recorded.                                                          |
| reference_number        | string  | Optional     | Reference number for the Vendor Payment recorded.                                                     |
| is_paid_via_print_check | boolean | Optional     | **🇺🇸 United States, 🇨🇦 Canada, 🇲🇽 Mexico only** Check if the Bill Payment is paid Via Print Check Option |
| check_details           | array   | Optional     | **🇺🇸 United States, 🇨🇦 Canada only**                                                                    |
| location_id             | string  | Optional     | Location ID                                                                                           |
| custom_fields           | array   | Optional     | Custom fields                                                                                         |

### Path Parameters

| Parameter  | Type   | Required     | Description                       |
| :--------- | :----- | :----------- | :-------------------------------- |
| payment_id | string | **Required** | Unique identifier of the payment. |

### Query Parameters

| Parameter       | Type   | Required     | Description            |
| :-------------- | :----- | :----------- | :--------------------- |
| organization_id | string | **Required** | ID of the organization |

### Request Example

```bash
curl --request PUT \
  --url 'https://www.zohoapis.com/books/v3/vendorpayments/460000000053219?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{
    "vendor_id": "460000000026049",
    "bills": [
        {
            "bill_payment_id": "460000000053221",
            "bill_id": "460000000053199",
            "amount_applied": 150,
            "tax_amount_withheld": 0.1
        }
    ],
    "date": "2013-10-07",
    "exchange_rate": 1,
    "amount": 500,
    "paid_through_account_id": "460000000000358",
    "payment_mode": "Stripe",
    "description": "string",
    "reference_number": "REF#912300",
    "is_paid_via_print_check": false,
    "check_details": [
        "string"
    ],
    "location_id": "460000000038080",
    "custom_fields": [
        {
            "index": 0,
            "value": "string"
        }
    ]
}'
```

---

## Get a vendor payment
Get the details of a vendor payment.

`OAuth Scope : ZohoBooks.vendorpayments.READ`

### Path Parameters

| Parameter  | Type   | Required     | Description                       |
| :--------- | :----- | :----------- | :-------------------------------- |
| payment_id | string | **Required** | Unique identifier of the payment. |

### Query Parameters

| Parameter              | Type    | Required     | Description                                                       |
| :--------------------- | :------ | :----------- | :---------------------------------------------------------------- |
| organization_id        | string  | **Required** | ID of the organization                                            |
| fetchTaxInfo           | boolean | Optional     | Check if tax information should be fetched                        |
| fetchstatementlineinfo | boolean | Optional     | Check is Statement Line Information for Vendor Payment be fetched |
| print                  | boolean | Optional     | Check if Vendor Payment must be printed.                          |
| is_bill_payment_id     | boolean | Optional     | Check if the ID is Bill Payment or Vendor Payment                 |

### Request Example

```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/vendorpayments/460000000053219?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Delete a vendor payment
Delete an existing vendor payment.

`OAuth Scope : ZohoBooks.vendorpayments.DELETE`

### Path Parameters

| Parameter  | Type   | Required     | Description                       |
| :--------- | :----- | :----------- | :-------------------------------- |
| payment_id | string | **Required** | Unique identifier of the payment. |

### Query Parameters

| Parameter       | Type   | Required     | Description            |
| :-------------- | :----- | :----------- | :--------------------- |
| organization_id | string | **Required** | ID of the organization |

### Request Example

```bash
curl --request DELETE \
  --url 'https://www.zohoapis.com/books/v3/vendorpayments/460000000053219?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Refund an excess vendor payment
Refund the excess amount paid to the vendor.

`OAuth Scope : ZohoBooks.vendorpayments.CREATE`

### Arguments

| Argument         | Type   | Required     | Description                               |
| :--------------- | :----- | :----------- | :---------------------------------------- |
| date             | string | **Required** | Date of the Vendor Payment Refund.        |
| refund_mode      | string | Optional     | Mode in which refund is made.             |
| reference_number | string | Optional     | Reference Number of the Payment Refund    |
| amount           | double | **Required** | Total Amount of Vendor Payment            |
| exchange_rate    | double | Optional     | Exchange rate of the currency.            |
| to_account_id    | string | **Required** | The account to which payment is refunded. |
| description      | string | Optional     | Description of the Payment Refund         |

### Path Parameters

| Parameter  | Type   | Required     | Description                       |
| :--------- | :----- | :----------- | :-------------------------------- |
| payment_id | string | **Required** | Unique identifier of the payment. |

### Query Parameters

| Parameter       | Type   | Required     | Description            |
| :-------------- | :----- | :----------- | :--------------------- |
| organization_id | string | **Required** | ID of the organization |

### Request Example

```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/vendorpayments/460000000053219/refunds?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{
    "date": "2017-01-10",
    "refund_mode": "cash",
    "reference_number": "string",
    "amount": 500,
    "exchange_rate": 1,
    "to_account_id": "460000000000385",
    "description": "Payment Refund"
}'
```

---

## List refunds of a vendor payment
List all the refunds pertaining to an existing vendor payment.

`OAuth Scope : ZohoBooks.vendorpayments.READ`

### Path Parameters

| Parameter  | Type   | Required     | Description                       |
| :--------- | :----- | :----------- | :-------------------------------- |
| payment_id | string | **Required** | Unique identifier of the payment. |

### Query Parameters

| Parameter       | Type    | Required     | Description                                                     |
| :-------------- | :------ | :----------- | :-------------------------------------------------------------- |
| organization_id | string  | **Required** | ID of the organization                                          |
| page            | integer | Optional     | Page number to be fetched. Default value is 1.                  |
| per_page        | integer | Optional     | Number of records to be fetched per page. Default value is 200. |

### Request Example

```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/vendorpayments/460000000053219/refunds?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Update a refund
Update the refunded transaction.

`OAuth Scope : ZohoBooks.vendorpayments.UPDATE`

### Arguments

| Argument         | Type   | Required     | Description                               |
| :--------------- | :----- | :----------- | :---------------------------------------- |
| date             | string | **Required** | Date of the Vendor Payment Refund.        |
| refund_mode      | string | Optional     | Mode in which refund is made.             |
| reference_number | string | Optional     | Reference Number of the Payment Refund    |
| amount           | double | **Required** | Total Amount of Vendor Payment            |
| exchange_rate    | double | Optional     | Exchange rate of the currency.            |
| to_account_id    | string | **Required** | The account to which payment is refunded. |
| description      | string | Optional     | Description of the Payment Refund         |

### Path Parameters

| Parameter               | Type   | Required     | Description                                     |
| :---------------------- | :----- | :----------- | :---------------------------------------------- |
| payment_id              | string | **Required** | Unique identifier of the payment.               |
| vendorpayment_refund_id | string | **Required** | Unique identifier of the vendor payment refund. |

### Query Parameters

| Parameter       | Type   | Required     | Description            |
| :-------------- | :----- | :----------- | :--------------------- |
| organization_id | string | **Required** | ID of the organization |

### Request Example

```bash
curl --request PUT \
  --url 'https://www.zohoapis.com/books/v3/vendorpayments/460000000053219/refunds/460000000003017?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{
    "date": "2017-01-10",
    "refund_mode": "cash",
    "reference_number": "string",
    "amount": 500,
    "exchange_rate": 1,
    "to_account_id": "460000000000385",
    "description": "Payment Refund"
}'
```

---

## Details of a refund
Obtain details of a particular refund of a vendor payment.

`OAuth Scope : ZohoBooks.vendorpayments.READ`

### Path Parameters

| Parameter               | Type   | Required     | Description                                     |
| :---------------------- | :----- | :----------- | :---------------------------------------------- |
| payment_id              | string | **Required** | Unique identifier of the payment.               |
| vendorpayment_refund_id | string | **Required** | Unique identifier of the vendor payment refund. |

### Query Parameters

| Parameter       | Type   | Required     | Description            |
| :-------------- | :----- | :----------- | :--------------------- |
| organization_id | string | **Required** | ID of the organization |

### Request Example

```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/vendorpayments/460000000053219/refunds/460000000003017?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Delete a refund
Delete refund pertaining to an existing vendor payment.

`OAuth Scope : ZohoBooks.vendorpayments.DELETE`

### Path Parameters

| Parameter               | Type   | Required     | Description                                     |
| :---------------------- | :----- | :----------- | :---------------------------------------------- |
| payment_id              | string | **Required** | Unique identifier of the payment.               |
| vendorpayment_refund_id | string | **Required** | Unique identifier of the vendor payment refund. |

### Query Parameters

| Parameter       | Type   | Required     | Description            |
| :-------------- | :----- | :----------- | :--------------------- |
| organization_id | string | **Required** | ID of the organization |

### Request Example

```bash
curl --request DELETE \
  --url 'https://www.zohoapis.com/books/v3/vendorpayments/460000000053219/refunds/460000000003017?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Email a vendor payment
Send a vendor payment receipt to the vendor via email. You can customize the email content, attach files, and control sender preferences. If the request body is empty, the email will be sent with default content based on the email template associated with the vendor or the default template.

`OAuth Scope : ZohoBooks.vendorpayments.CREATE`

### Arguments

| Argument               | Type    | Required     | Description                                                                                                                                                                                                                                                 |
| :--------------------- | :------ | :----------- | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| send_from_org_email_id | boolean | Optional     | Boolean to trigger the email from the organization's email address                                                                                                                                                                                          |
| from_address_id        | string  | Optional     | From email address id                                                                                                                                                                                                                                       |
| to_mail_ids            | array   | **Required** | Array of email address of the recipients.                                                                                                                                                                                                                   |
| cc_mail_ids            | array   | Optional     | Array of email address of the recipients to be CC'd.                                                                                                                                                                                                        |
| subject                | string  | **Required** | Subject of the email                                                                                                                                                                                                                                        |
| body                   | string  | **Required** | Body of the email                                                                                                                                                                                                                                           |
| email_template_id      | string  | Optional     | Get the email content based on a specific email template. If this param is not inputted, then the content will be based on the email template associated with the vendor. If no template is associated with the vendor, then default template will be used. |

### Path Parameters

| Parameter  | Type   | Required     | Description |
| :--------- | :----- | :----------- | :---------- |
| payment_id | string | **Required** |             |

### Query Parameters

| Parameter       | Type    | Required     | Description                                        |
| :-------------- | :------ | :----------- | :------------------------------------------------- |
| organization_id | string  | **Required** | ID of the organization                             |
| send_attachment | boolean | Optional     | Send the vendor payment attachment with the email. |
| attachments     | binary  | Optional     | Files to be attached to the email                  |
| file_name       | string  | Optional     | Name of the file to be attached                    |

### Request Example

```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/vendorpayments/460000000053219/email?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{
    "send_from_org_email_id": false,
    "from_address_id": "2000000011993",
    "to_mail_ids": [
        "vendor@example.com"
    ],
    "cc_mail_ids": [
        "manager@example.com"
    ],
    "subject": "Vendor Payment Receipt from Your Company (Payment#: VP-00001)",
    "body": "Dear Vendor,<br><br>Thank you for your services.<br><br>Please find attached the payment receipt for Payment#: VP-00001.<br><br>Payment Details:<br>Payment Number: VP-00001<br>Date: 2024-01-15<br>Amount: $1,500.00<br><br>Best regards,<br>Your Company",
    "email_template_id": "string"
}'
```

---

## Get vendor payment email content
Retrieve the pre-populated email content for a vendor payment, including subject, body, recipient contacts, sender options, and attachment details. This endpoint provides all the necessary information to compose and send a vendor payment receipt email.

`OAuth Scope : ZohoBooks.vendorpayments.READ`

### Path Parameters

| Parameter  | Type   | Required     | Description |
| :--------- | :----- | :----------- | :---------- |
| payment_id | string | **Required** |             |

### Query Parameters

| Parameter       | Type   | Required     | Description            |
| :-------------- | :----- | :----------- | :--------------------- |
| organization_id | string | **Required** | ID of the organization |

### Request Example

```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/vendorpayments/460000000053219/email?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```