# Bank Transactions

In many instances, you would wish to record manual entries for your offline transactions for your bank or credit card accounts. These entries might not be a part of your bank feeds but would make an important entry for your business records.

### Bank Transactions OpenAPI Document
[Download Bank Transactions OpenAPI Document](bank-transactions.yml)

## Bank Transaction Attributes

| Attribute                     | Type    | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| :---------------------------- | :------ | :--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| transaction_id                | string  | ID of the Transaction                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| from_account_id               | string  | The account ID from which money will be transferred (Mandatory for specific type of transactions). These accounts differ with respect to transaction_type. Ex: To a bank account, from-account can be: bank , card, income, refund. To a card account, from account can be: bank, card, refund.                                                                                                                                                                                                            |
| from_account_name             | string  | The account Name from which money will be transferred                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| to_account_id                 | string  | ID of the account to which the money gets transferred (Mandatory for specific type of transactions). Ex: From a bank account, to-account can be: bank, card, drawings, expense, credit notes. From a card account, to-account can be: card, bank, expense.                                                                                                                                                                                                                                                 |
| to_account_name               | string  | Name of the account to which money gets transferred.                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| transaction_type              | string  | Type of the transaction. <br> **Allowed transaction types**: `deposit`, `refund` (*Supported only in Credit Card accounts), `transfer_fund`, `card_payment`, `sales_without_invoices`, `expense_refund`, `owner_contribution`, `interest_income`, `other_income`, `owner_drawings`, `sales_return`. <br> **Note:** You will not be able to create module-specific transaction types under Bank Transaction endpoints (e.g., Expense, Vendor Payment, Customer Payment). Refer to their respective modules. |
| currency_id                   | string  | The currency ID involved in the transaction.                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| currency_code                 | string  | Code of the currency involved in the transaction.                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| payment_mode                  | string  | Mode of payment for the transaction. (not applicable for transfer_fund, card_payment, owner_drawings). Ex: cash, cheque, etc.                                                                                                                                                                                                                                                                                                                                                                              |
| exchange_rate                 | integer | The foreign currency exchange rate value.                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| date                          | string  | Transaction date.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| customer_id                   | string  | ID of the customer or vendor.                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| customer_name                 | string  | Name of the Customer.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| vendor_id                     | string  | ID of the Vendor.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| vendor_name                   | string  | Name of the Vendor.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| reference_number              | string  | Reference Number of the transaction.                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| description                   | string  | A brief description about the transaction.                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| bank_charges                  | double  | Bank Charges applied to the transaction.                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| tax_id                        | string  | **🇺🇸 US only** ID of the tax or tax group applied.                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| documents                     | array   | List of files to be attached to a particular transaction. Contains `file_name` and `document_id`.                                                                                                                                                                                                                                                                                                                                                                                                          |
| is_inclusive_tax              | boolean | Check if transaction is tax Inclusive.                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| tax_name                      | string  | Name of the Tax.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| tax_percentage                | double  | Percentage of the Tax.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| tax_amount                    | double  | Amount of Tax.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| sub_total                     | integer | Sub Total of the transaction.                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| tax_authority_id              | string  | **🇺🇸 US, 🇦🇺 Australia, 🇨🇦 Canada only** ID of the Tax Authority.                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| tax_authority_name            | string  | **🇺🇸 US, 🇦🇺 Australia, 🇨🇦 Canada only** Name of the Tax Authority.                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| tax_exemption_id              | string  | **🇮🇳 India, 🇺🇸 US, 🇦🇺 Australia, 🇨🇦 Canada only** ID of the Tax Exemption.                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| tax_exemption_code            | string  | **🇮🇳 India, 🇺🇸 US, 🇦🇺 Australia, 🇨🇦 Canada only** Code of the Tax Exemption.                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| total                         | integer | Total of the transaction.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| bcy_total                     | integer | Total in Base Currency of the Organisation.                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| amount                        | double  | Amount of the transaction.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| vat_treatment                 | string  | **🇬🇧 UK / Europe only** VAT treatment for the bank transaction. Values: `uk`, `eu_vat_registered`, `overseas`.                                                                                                                                                                                                                                                                                                                                                                                              |
| tax_treatment                 | string  | **GCC, 🇰🇪 Kenya, 🇿🇦 South Africa only** VAT treatment. Values: `vat_registered`, `vat_not_registered`, `gcc_vat_not_registered`, `gcc_vat_registered`, `non_gcc`, `dz_vat_registered` (UAE), `dz_vat_not_registered` (UAE), `non_kenya`, `overseas`.                                                                                                                                                                                                                                                         |
| product_type                  | string  | **🇬🇧 UK / Europe / 🇿🇦 South Africa only** Type of the transaction (goods/service). Values: `digital_service`, `goods`, `service`, `capital_service`, `capital_goods`.                                                                                                                                                                                                                                                                                                                                        |
| acquisition_vat_id            | string  | **🇬🇧 UK / Europe only** ID of the tax applied for EU goods purchase or expense where acquisition VAT applies.                                                                                                                                                                                                                                                                                                                                                                                               |
| acquisition_vat_name          | string  | **🇬🇧 UK / Europe only** Name of the VAT Acquisition.                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| acquisition_vat_percentage    | string  | **🇬🇧 UK / Europe only** Percentage of the VAT Acquisition.                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| acquisition_vat_amount        | string  | **🇬🇧 UK / Europe only** Amount of the VAT Acquisition.                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| reverse_charge_vat_id         | string  | **🇬🇧 UK / Europe only** ID of the tax applied for non-UK service purchase/expense where reverse charge VAT applies.                                                                                                                                                                                                                                                                                                                                                                                         |
| reverse_charge_vat_name       | string  | **🇬🇧 UK / Europe only** Name of the Reverse Charge.                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| reverse_charge_vat_percentage | string  | **🇬🇧 UK / Europe only** Percentage of the Reverse Charge.                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| reverse_charge_vat_amount     | string  | **🇬🇧 UK / Europe only** Percentage of the Reverse Charge.                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| reverse_charge_tax_id         | string  | **🇮🇳 India, GCC, 🇿🇦 South Africa only** Enter reverse charge tax ID.                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| filed_in_vat_return_id        | string  | **🇬🇧 UK only** ID of the VAT Return the Vendor Credit is filed in.                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| filed_in_vat_return_name      | string  | **🇬🇧 UK only** Name of the VAT Return the Vendor Credit is filed in.                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| filed_in_vat_return_type      | string  | **🇬🇧 UK only** Type of the VAT Return the Vendor Credit is filed in.                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| imported_transactions         | array   | List of imported transaction details (ID, date, amount, payee, status, etc.).                                                                                                                                                                                                                                                                                                                                                                                                                              |
| tags                          | array   | Array of tags associated. Contains `tag_id` and `tag_option_id`.                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| line_items                    | array   | Line items details including account IDs, amounts, taxes, and tags.                                                                                                                                                                                                                                                                                                                                                                                                                                        |

---

## Create a transaction for an account
Create a bank transaction based on the allowed transaction types.

`OAuth Scope : ZohoBooks.banking.CREATE`

### Arguments
| Argument          | Type    | Required     | Description                                                                                                                                                                                                                    |
| :---------------- | :------ | :----------- | :----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| transaction_type  | string  | **Required** | Type of the transaction. Allowed: `deposit`, `refund`, `transfer_fund`, `card_payment`, `sales_without_invoices`, `expense_refund`, `owner_contribution`, `interest_income`, `other_income`, `owner_drawings`, `sales_return`. |
| from_account_id   | string  | Optional     | The account ID from which money will be transferred.                                                                                                                                                                           |
| to_account_id     | string  | Optional     | ID of the account to which the money gets transferred.                                                                                                                                                                         |
| amount            | double  | Optional     | Amount of the transaction.                                                                                                                                                                                                     |
| payment_mode      | string  | Optional     | Mode of payment.                                                                                                                                                                                                               |
| exchange_rate     | integer | Optional     | Foreign currency exchange rate.                                                                                                                                                                                                |
| date              | string  | Optional     | Transaction date.                                                                                                                                                                                                              |
| customer_id       | string  | Optional     | ID of the customer or vendor.                                                                                                                                                                                                  |
| reference_number  | string  | Optional     | Reference Number.                                                                                                                                                                                                              |
| description       | string  | Optional     | Brief description.                                                                                                                                                                                                             |
| currency_id       | string  | Optional     | Currency ID.                                                                                                                                                                                                                   |
| tax_id            | string  | Optional     | **🇺🇸 US only** ID of the tax.                                                                                                                                                                                                   |
| is_inclusive_tax  | boolean | Optional     | Check if transaction is tax Inclusive.                                                                                                                                                                                         |
| tags              | array   | Optional     | Tags associated.                                                                                                                                                                                                               |
| from_account_tags | array   | Optional     | Tags for the from account.                                                                                                                                                                                                     |
| to_account_tags   | array   | Optional     | Tags for the to account.                                                                                                                                                                                                       |
| documents         | array   | Optional     | Files to be attached.                                                                                                                                                                                                          |
| bank_charges      | double  | Optional     | Bank Charges applied.                                                                                                                                                                                                          |
| user_id           | long    | Optional     | ID of the User involved.                                                                                                                                                                                                       |
| tax_authority_id  | string  | Optional     | **🇺🇸 US, 🇦🇺 Australia, 🇨🇦 Canada only** ID of the Tax Authority.                                                                                                                                                                  |
| tax_exemption_id  | string  | Optional     | **🇮🇳 India, 🇺🇸 US, 🇦🇺 Australia, 🇨🇦 Canada only** ID of the Tax Exemption.                                                                                                                                                         |
| custom_fields     | array   | Optional     | Custom fields.                                                                                                                                                                                                                 |

### Query Parameters
| Parameter       | Type   | Required     | Description            |
| :-------------- | :----- | :----------- | :--------------------- |
| organization_id | string | **Required** | ID of the organization |

### Request Example
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/banktransactions?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{
    "from_account_id": "460000000070003",
    "to_account_id": "460000000048001",
    "transaction_type": "deposit",
    "amount": 2000,
    "payment_mode": "Cash",
    "exchange_rate": 1,
    "date": "2013-10-01",
    "customer_id": "460000000000111",
    "reference_number": "Ref-121",
    "description": "string",
    "currency_id": "460000000000097",
    "is_inclusive_tax": false,
    "bank_charges": 0
}'
```

---

## Get transactions list
Get all the transaction details involved in an account.

`OAuth Scope : ZohoBooks.banking.READ`

### Query Parameters
| Parameter          | Type    | Required     | Description                                                                                                              |
| :----------------- | :------ | :----------- | :----------------------------------------------------------------------------------------------------------------------- |
| organization_id    | string  | **Required** | ID of the organization                                                                                                   |
| account_id         | long    | Optional     | ID of the account to filter.                                                                                             |
| transaction_type   | string  | Optional     | Type of transaction.                                                                                                     |
| date               | string  | Optional     | Variants: `date_start` and `date_end`.                                                                                   |
| amount             | double  | Optional     | Variants: `amount_start` and `amount_end`.                                                                               |
| status             | string  | Optional     | Status list view: All, uncategorized, manually_added, matched, excluded, categorized.                                    |
| reference_number   | string  | Optional     | Search using Reference Number.                                                                                           |
| filter_by          | string  | Optional     | `Status.All`, `Status.Uncategorized`, `Status.Categorized`, `Status.ManuallyAdded`, `Status.Excluded`, `Status.Matched`. |
| sort_column        | string  | Optional     | Allowed Values: `date`.                                                                                                  |
| transaction_status | string  | Optional     | Transaction status filter.                                                                                               |
| search_text        | string  | Optional     | Search by contact name or description.                                                                                   |
| page               | integer | Optional     | Page number. Default 1.                                                                                                  |
| per_page           | integer | Optional     | Records per page. Default 200.                                                                                           |

### Request Example
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/banktransactions?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Update a transaction
Make changes in the applicable fields of a transaction and update it.

`OAuth Scope : ZohoBooks.banking.UPDATE`

### Path Parameters
| Parameter           | Type   | Required     | Description                                |
| :------------------ | :----- | :----------- | :----------------------------------------- |
| bank_transaction_id | string | **Required** | Unique identifier of the bank transaction. |

### Query Parameters
| Parameter       | Type   | Required     | Description            |
| :-------------- | :----- | :----------- | :--------------------- |
| organization_id | string | **Required** | ID of the organization |

### Arguments
See "Create a transaction for an account" for argument details. This endpoint supports updating fields like `from_account_id`, `to_account_id`, `amount`, `line_items`, etc.

### Request Example
```bash
curl --request PUT \
  --url 'https://www.zohoapis.com/books/v3/banktransactions/460000000048017?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{
    "from_account_id": "460000000070003",
    "to_account_id": "460000000048001",
    "transaction_type": "deposit",
    "amount": 2000,
    "payment_mode": "Cash",
    "exchange_rate": 1,
    "date": "2013-10-01",
    "customer_id": "460000000000111",
    "reference_number": "Ref-121",
    "description": "string",
    "currency_id": "460000000000097",
    "is_inclusive_tax": false,
    "line_items": [
        {
            "line_id": "46000000001234",
            "account_id": "460000000048001",
            "account_name": "Petty Cash",
            "description": "string",
            "item_total": 7500,
            "item_order": 1
        }
    ]
}'
```

---

## Get transaction
Fetch the details of a transaction by specifying the transaction_id.

`OAuth Scope : ZohoBooks.banking.READ`

### Path Parameters
| Parameter           | Type   | Required     | Description                                |
| :------------------ | :----- | :----------- | :----------------------------------------- |
| bank_transaction_id | string | **Required** | Unique identifier of the bank transaction. |

### Query Parameters
| Parameter       | Type   | Required     | Description            |
| :-------------- | :----- | :----------- | :--------------------- |
| organization_id | string | **Required** | ID of the organization |

### Request Example
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/banktransactions/460000000048017?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Delete a transaction
Delete a transaction from an account by specifying the transaction_id.

`OAuth Scope : ZohoBooks.banking.DELETE`

### Path Parameters
| Parameter           | Type   | Required     | Description                                |
| :------------------ | :----- | :----------- | :----------------------------------------- |
| bank_transaction_id | string | **Required** | Unique identifier of the bank transaction. |

### Query Parameters
| Parameter       | Type   | Required     | Description            |
| :-------------- | :----- | :----------- | :--------------------- |
| organization_id | string | **Required** | ID of the organization |

### Request Example
```bash
curl --request DELETE \
  --url 'https://www.zohoapis.com/books/v3/banktransactions/460000000048017?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Match a transaction
Match an uncategorized transaction with an existing transaction in the account.

`OAuth Scope : ZohoBooks.banking.CREATE`

### Arguments
| Argument                   | Type  | Required | Description                                                                       |
| :------------------------- | :---- | :------- | :-------------------------------------------------------------------------------- |
| transactions_to_be_matched | array | Optional | Array of transactions to match. Contains `transaction_id` and `transaction_type`. |

### Path Parameters
| Parameter      | Type   | Required     | Description                                |
| :------------- | :----- | :----------- | :----------------------------------------- |
| transaction_id | string | **Required** | Unique identifier of the bank transaction. |

### Query Parameters
| Parameter       | Type   | Required     | Description                                                   |
| :-------------- | :----- | :----------- | :------------------------------------------------------------ |
| organization_id | string | **Required** | ID of the organization                                        |
| account_id      | string | Optional     | Mandatory Account id for which transactions are to be listed. |

### Request Example
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/banktransactions/uncategorized/460000000048017/match?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{
    "transactions_to_be_matched": [
        {
            "transaction_id": "460000000048017",
            "transaction_type": "deposit"
        }
    ]
}'
```

---

## Get matching transactions
Provide criteria to search for matching uncategorised transactions. The list of transactions can also include invoices/bills/credit-notes which will not be matched directly. Instead, a new (payment/refund) transaction is recorded and matched.

`OAuth Scope : ZohoBooks.banking.READ`

### Path Parameters
| Parameter      | Type   | Required     | Description                                |
| :------------- | :----- | :----------- | :----------------------------------------- |
| transaction_id | string | **Required** | Unique identifier of the bank transaction. |

### Query Parameters
| Parameter             | Type    | Required     | Description                                        |
| :-------------------- | :------ | :----------- | :------------------------------------------------- |
| organization_id       | string  | **Required** | ID of the organization                             |
| transaction_id        | string  | Optional     | ID of the Transaction.                             |
| transaction_type      | string  | Optional     | Type of the transaction.                           |
| date_after            | string  | Optional     | Date after which Transactions are to be filtered.  |
| date_before           | string  | Optional     | Date before which Transactions are to be filtered. |
| amount_start          | double  | Optional     | Starting amount filter.                            |
| amount_end            | double  | Optional     | Ending amount filter.                              |
| contact               | string  | Optional     | Contact person name.                               |
| reference_number      | string  | Optional     | Reference Number.                                  |
| show_all_transactions | boolean | Optional     | Check if all transactions must be shown.           |
| page                  | integer | Optional     | Page number.                                       |
| per_page              | integer | Optional     | Records per page.                                  |

### Request Example
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/banktransactions/uncategorized/460000000048017/match?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Unmatch a matched transaction
Unmatch a transaction that was previously matched and make it uncategorized.

`OAuth Scope : ZohoBooks.banking.CREATE`

### Path Parameters
| Parameter      | Type   | Required     | Description                                |
| :------------- | :----- | :----------- | :----------------------------------------- |
| transaction_id | string | **Required** | Unique identifier of the bank transaction. |

### Query Parameters
| Parameter       | Type   | Required     | Description                                                   |
| :-------------- | :----- | :----------- | :------------------------------------------------------------ |
| organization_id | string | **Required** | ID of the organization                                        |
| account_id      | string | Optional     | Mandatory Account id for which transactions are to be listed. |

### Request Example
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/banktransactions/460000000048017/unmatch?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Exclude a transaction
Exclude a transaction from your bank or credit card account.

`OAuth Scope : ZohoBooks.banking.CREATE`

### Path Parameters
| Parameter      | Type   | Required     | Description                                |
| :------------- | :----- | :----------- | :----------------------------------------- |
| transaction_id | string | **Required** | Unique identifier of the bank transaction. |

### Query Parameters
| Parameter       | Type   | Required     | Description                                                   |
| :-------------- | :----- | :----------- | :------------------------------------------------------------ |
| organization_id | string | **Required** | ID of the organization                                        |
| account_id      | string | Optional     | Mandatory Account id for which transactions are to be listed. |

### Request Example
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/banktransactions/uncategorized/460000000048017/exclude?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Restore a transaction
Restore an excluded transaction in your account.

`OAuth Scope : ZohoBooks.banking.CREATE`

### Path Parameters
| Parameter      | Type   | Required     | Description                                |
| :------------- | :----- | :----------- | :----------------------------------------- |
| transaction_id | string | **Required** | Unique identifier of the bank transaction. |

### Query Parameters
| Parameter       | Type   | Required     | Description                                                   |
| :-------------- | :----- | :----------- | :------------------------------------------------------------ |
| organization_id | string | **Required** | ID of the organization                                        |
| account_id      | string | Optional     | Mandatory Account id for which transactions are to be listed. |

### Request Example
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/banktransactions/uncategorized/460000000048017/restore?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Categorize an uncategorized transaction
Categorize an uncategorized transaction by creating a new transaction.

`OAuth Scope : ZohoBooks.banking.CREATE`

### Arguments
| Argument         | Type   | Required     | Description                                                                                                                                                                                                 |
| :--------------- | :----- | :----------- | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| transaction_type | string | **Required** | Allowed types: `deposit`, `refund`, `transfer_fund`, `card_payment`, `sales_without_invoices`, `expense_refund`, `owner_contribution`, `interest_income`, `other_income`, `owner_drawings`, `sales_return`. |
| from_account_id  | string | Optional     | Source account ID.                                                                                                                                                                                          |
| to_account_id    | string | Optional     | Destination account ID.                                                                                                                                                                                     |
| amount           | double | Optional     | Amount.                                                                                                                                                                                                     |
| date             | string | Optional     | Transaction date.                                                                                                                                                                                           |
| payment_mode     | string | Optional     | Payment mode.                                                                                                                                                                                               |
| customer_id      | string | Optional     | Customer/Vendor ID.                                                                                                                                                                                         |
| ...              |        |              | (Similar arguments to "Create a transaction")                                                                                                                                                               |

### Path Parameters
| Parameter      | Type   | Required     | Description                                |
| :------------- | :----- | :----------- | :----------------------------------------- |
| transaction_id | string | **Required** | Unique identifier of the bank transaction. |

### Query Parameters
| Parameter       | Type   | Required     | Description            |
| :-------------- | :----- | :----------- | :--------------------- |
| organization_id | string | **Required** | ID of the organization |

### Request Example
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/banktransactions/uncategorized/460000000048017/categorize?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{
    "from_account_id": "460000000070003",
    "to_account_id": "460000000048001",
    "transaction_type": "deposit",
    "amount": 2000,
    "payment_mode": "Cash",
    "exchange_rate": 1,
    "date": "2013-10-01",
    "customer_id": "460000000000111",
    "reference_number": "Ref-121",
    "description": "string",
    "line_items": [
        {
            "line_id": "46000000001234",
            "account_id": "460000000048001",
            "account_name": "Petty Cash",
            "item_total": 7500,
            "item_order": 1
        }
    ]
}'
```

---

## Categorize as expense
Categorize an Uncategorized transaction as expense.

`OAuth Scope : ZohoBooks.banking.CREATE`

### Arguments
| Argument                | Type    | Required | Description                       |
| :---------------------- | :------ | :------- | :-------------------------------- |
| account_id              | string  | Optional | Mandatory Account id.             |
| paid_through_account_id | string  | Optional | ID of the credit/bank account.    |
| date                    | string  | Optional | Transaction date.                 |
| amount                  | double  | Optional | Amount.                           |
| tax_id                  | string  | Optional | **🇺🇸 US only** Tax ID.             |
| project_id              | string  | Optional | Project ID.                       |
| is_billable             | boolean | Optional | If the expense is billable.       |
| customer_id             | string  | Optional | Customer ID.                      |
| vendor_id               | string  | Optional | Vendor ID.                        |
| line_items              | array   | Optional | Expense line items.               |
| ...                     |         |          | (Various standard Expense fields) |

### Path Parameters
| Parameter      | Type   | Required     | Description                                |
| :------------- | :----- | :----------- | :----------------------------------------- |
| transaction_id | string | **Required** | Unique identifier of the bank transaction. |

### Query Parameters
| Parameter       | Type   | Required     | Description            |
| :-------------- | :----- | :----------- | :--------------------- |
| organization_id | string | **Required** | ID of the organization |

### Request Example
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/banktransactions/uncategorized/460000000048017/categorize/expenses?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{
    "account_id": "460000000048001",
    "paid_through_account_id": "460000000000358",
    "date": "2013-10-01",
    "amount": 2000,
    "is_billable": true,
    "reference_number": "Ref-121",
    "customer_id": "460000000000111",
    "vendor_id": "460000000026049",
    "line_items": [
        {
            "line_item_id": "460000000012834",
            "account_id": "460000000048001",
            "amount": 2000,
            "item_order": 1
        }
    ]
}'
```

---

## Uncategorize a categorized transaction
Revert a categorized transaction as uncategorized.

`OAuth Scope : ZohoBooks.banking.CREATE`

### Path Parameters
| Parameter      | Type   | Required     | Description                                |
| :------------- | :----- | :----------- | :----------------------------------------- |
| transaction_id | string | **Required** | Unique identifier of the bank transaction. |

### Query Parameters
| Parameter       | Type   | Required     | Description            |
| :-------------- | :----- | :----------- | :--------------------- |
| organization_id | string | **Required** | ID of the organization |
| account_id      | string | Optional     | Mandatory Account id.  |

### Request Example
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/banktransactions/460000000048017/uncategorize?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Categorize a vendor payment
Categorize an uncategorized transaction as Vendor Payment.

`OAuth Scope : ZohoBooks.banking.CREATE`

### Arguments
| Argument                | Type   | Required     | Description                                                      |
| :---------------------- | :----- | :----------- | :--------------------------------------------------------------- |
| vendor_id               | string | Optional     | ID of the Vendor.                                                |
| amount                  | double | **Required** | Amount of the transaction.                                       |
| date                    | string | **Required** | Transaction date.                                                |
| paid_through_account_id | string | Optional     | ID of the credit/bank account.                                   |
| bills                   | array  | Optional     | Array containing `bill_id`, `bill_payment_id`, `amount_applied`. |
| ...                     |        |              | (Standard vendor payment fields)                                 |

### Path Parameters
| Parameter      | Type   | Required     | Description                                |
| :------------- | :----- | :----------- | :----------------------------------------- |
| transaction_id | string | **Required** | Unique identifier of the bank transaction. |

### Query Parameters
| Parameter       | Type   | Required     | Description            |
| :-------------- | :----- | :----------- | :--------------------- |
| organization_id | string | **Required** | ID of the organization |

### Request Example
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/banktransactions/uncategorized/460000000048017/categorize/vendorpayments?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{
    "vendor_id": "460000000026049",
    "bills": [
        {
            "bill_id": "460000000053199",
            "amount_applied": 150,
            "tax_amount_withheld": 0
        }
    ],
    "payment_mode": "Cash",
    "date": "2013-10-01",
    "reference_number": "Ref-121",
    "exchange_rate": 1,
    "paid_through_account_id": "460000000000358",
    "amount": 2000
}'
```

---

## Categorize as customer payment
Categorize an uncategorized transaction as Customer Payment.

`OAuth Scope : ZohoBooks.banking.CREATE`

### Arguments
| Argument    | Type   | Required | Description                                      |
| :---------- | :----- | :------- | :----------------------------------------------- |
| customer_id | string | Optional | ID of the customer.                              |
| amount      | double | Optional | Amount of the transaction.                       |
| account_id  | string | Optional | Mandatory Account id.                            |
| invoices    | array  | Optional | Array containing `invoice_id`, `amount_applied`. |
| date        | string | Optional | Transaction date.                                |
| ...         |        |          | (Standard customer payment fields)               |

### Path Parameters
| Parameter      | Type   | Required     | Description                                |
| :------------- | :----- | :----------- | :----------------------------------------- |
| transaction_id | string | **Required** | Unique identifier of the bank transaction. |

### Query Parameters
| Parameter       | Type   | Required     | Description            |
| :-------------- | :----- | :----------- | :--------------------- |
| organization_id | string | **Required** | ID of the organization |

### Request Example
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/banktransactions/uncategorized/460000000048017/categorize/customerpayments?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{
    "customer_id": "460000000000111",
    "invoices": [
        {
            "invoice_id": "460000000000481",
            "amount_applied": 150,
            "tax_amount_withheld": 0
        }
    ],
    "payment_mode": "Cash",
    "reference_number": "Ref-121",
    "exchange_rate": 1,
    "amount": 2000,
    "account_id": "460000000048001",
    "date": "2013-10-01"
}'
```

---

## Categorize as credit note refunds
Categorize an Uncategorized transaction as a refund from a credit note.

`OAuth Scope : ZohoBooks.banking.CREATE`

### Arguments
| Argument        | Type   | Required     | Description                                          |
| :-------------- | :----- | :----------- | :--------------------------------------------------- |
| creditnote_id   | string | **Required** | ID of the credit note that has to be refunded.       |
| date            | string | **Required** | Transaction date.                                    |
| amount          | double | Optional     | Amount of the transaction.                           |
| from_account_id | string | Optional     | The account ID from which money will be transferred. |
| ...             |        |              | (Standard credit note refund fields)                 |

### Path Parameters
| Parameter      | Type   | Required     | Description                                |
| :------------- | :----- | :----------- | :----------------------------------------- |
| transaction_id | string | **Required** | Unique identifier of the bank transaction. |

### Query Parameters
| Parameter       | Type   | Required     | Description            |
| :-------------- | :----- | :----------- | :--------------------- |
| organization_id | string | **Required** | ID of the organization |

### Request Example
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/banktransactions/uncategorized/460000000048017/categorize/creditnoterefunds?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{
    "creditnote_id": "4000000030049",
    "date": "2013-10-01",
    "refund_mode": "Cash",
    "reference_number": "Ref-121",
    "amount": 2000,
    "exchange_rate": 1,
    "from_account_id": "460000000070003",
    "description": "string"
}'
```

---

## Categorize as vendor credit refunds
Categorize an uncategorized transaction as a refund from a vendor credit.

`OAuth Scope : ZohoBooks.banking.CREATE`

### Arguments
| Argument         | Type   | Required     | Description                                      |
| :--------------- | :----- | :----------- | :----------------------------------------------- |
| vendor_credit_id | string | **Required** | ID of the vendor credit that has to be refunded. |
| date             | string | **Required** | Transaction date.                                |
| amount           | double | Optional     | Amount of the transaction.                       |
| account_id       | string | Optional     | Mandatory Account id.                            |
| ...              |        |              | (Standard vendor credit refund fields)           |

### Path Parameters
| Parameter      | Type   | Required     | Description                                |
| :------------- | :----- | :----------- | :----------------------------------------- |
| transaction_id | string | **Required** | Unique identifier of the bank transaction. |

### Query Parameters
| Parameter       | Type   | Required     | Description            |
| :-------------- | :----- | :----------- | :--------------------- |
| organization_id | string | **Required** | ID of the organization |

### Request Example
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/banktransactions/uncategorized/460000000048017/categorize/vendorcreditrefunds?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{
    "vendor_credit_id": "460000000030049",
    "date": "2013-10-01",
    "refund_mode": "Cash",
    "reference_number": "Ref-121",
    "amount": 2000,
    "exchange_rate": 1,
    "account_id": "460000000048001",
    "description": "string"
}'
```

---

## Categorize as Customer Payment refund
Categorizing bank transactions as Payment Refund.

`OAuth Scope : ZohoBooks.banking.CREATE`

### Arguments
| Argument          | Type   | Required     | Description                                          |
| :---------------- | :----- | :----------- | :--------------------------------------------------- |
| statement_line_id | string | **Required** | Unique identifier of the bank statement line.        |
| date              | string | **Required** | Transaction date.                                    |
| amount            | double | **Required** | Amount of the transaction.                           |
| from_account_id   | string | **Required** | The account ID from which money will be transferred. |
| ...               |        |              | (Other refund fields)                                |

### Path Parameters
| Parameter         | Type   | Required     | Description                                   |
| :---------------- | :----- | :----------- | :-------------------------------------------- |
| statement_line_id | string | **Required** | Unique identifier of the bank statement line. |

### Query Parameters
| Parameter       | Type   | Required     | Description            |
| :-------------- | :----- | :----------- | :--------------------- |
| organization_id | string | **Required** | ID of the organization |

### Request Example
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/banktransactions/uncategorized//categorize/paymentrefunds?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{
    "date": "2013-10-01",
    "refund_mode": "Cash",
    "reference_number": "Ref-121",
    "amount": 2000,
    "exchange_rate": 1,
    "from_account_id": "460000000070003",
    "description": "string"
}'
```

---

## Categorize as Vendor Payment refund
Categorizing bank transactions as Vendor Payment Refund.

`OAuth Scope : ZohoBooks.banking.CREATE`

### Arguments
| Argument         | Type   | Required     | Description                                            |
| :--------------- | :----- | :----------- | :----------------------------------------------------- |
| vendorpayment_id | string | Optional     | Vendor Payment to which you want to record the refund. |
| date             | string | **Required** | Transaction date.                                      |
| amount           | double | **Required** | Amount of the transaction.                             |
| to_account_id    | string | **Required** | ID of the account to which the money gets transferred. |
| ...              |        |              | (Other refund fields)                                  |

### Path Parameters
| Parameter         | Type   | Required     | Description                                   |
| :---------------- | :----- | :----------- | :-------------------------------------------- |
| statement_line_id | string | **Required** | Unique identifier of the bank statement line. |

### Query Parameters
| Parameter       | Type   | Required     | Description            |
| :-------------- | :----- | :----------- | :--------------------- |
| organization_id | string | **Required** | ID of the organization |

### Request Example
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/banktransactions/uncategorized//categorize/vendorpaymentrefunds?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{
    "vendorpayment_id": "460000000012345",
    "date": "2013-10-01",
    "refund_mode": "Cash",
    "reference_number": "Ref-121",
    "amount": 2000,
    "exchange_rate": 1,
    "to_account_id": "460000000048001",
    "description": "string"
}'
```