# Chart Of Accounts

The Chart of Accounts in Zoho Books consists of a wide range of accounts that are generally used with any type of business. The accounts are classified into different types such as Income, Expense, Equity, Liability & Assets.

## Attributes

| Attribute                    | Type    | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| :--------------------------- | :------ | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| account_id                   | string  | ID of the Account                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| account_name                 | string  | Name of the account                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| account_code                 | string  | Code Associated with the Account                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| is_active                    | boolean | Check if account is Active or Inactive                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| account_type                 | string  | Type of the account. Allowed Values: `other_asset`, `other_current_asset`, `intangible_asset`, `right_to_use_asset`, `financial_asset`, `contingent_asset`, `contract_asset`, `cash`, `bank`, `fixed_asset`, `other_current_liability`, `contract_liability`, `refund_liability`, `credit_card`, `long_term_liability`, `loans_and_borrowing`, `lease_liability`, `employee_benefit_liability`, `contingent_liability`, `financial_liability`, `other_liability`, `equity`, `income`, `finance_income`, `other_comprehensive_income`, `other_income`, `expense`, `manufacturing_expense`, `impairment_expense`, `depreciation_expense`, `employee_benefit_expense`, `lease_expense`, `finance_expense`, `tax_expense`, `cost_of_goods_sold`, `other_expense`, `accounts_receivable` and `accounts_payable`. |
| currency_id                  | string  | ID of the account currency.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| currency_code                | string  | Code of the Currency Associated with the Account                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| description                  | string  | Description of the account                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| is_system_account            | boolean | Check if it is an System Account                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| is_involved_in_transaction   | boolean | Check if account is involved in transaction                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| can_show_in_ze               | boolean |                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| include_in_vat_return        | boolean | Boolean to include an account in VAT returns. **United Kingdom only**.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| custom_fields                | array   |                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| custom_fields.customfield_id | string  | ID of the Custom Field                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| custom_fields.value          | string  | Value of the Custom Field                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| parent_account_id            | string  | ID of the Parent Account                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| documents                    | array   |                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| created_time                 | string  | Created Time associated with the Entity                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| last_modified_time           | string  | Last Modified time associated with the entity                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |

### Chart Of Accounts Example
```json
{
    "account_id": "460000000038079",
    "account_name": "Notes Payable",
    "account_code": "string",
    "is_active": true,
    "account_type": "long_term_liability",
    "currency_id": "460000000000097",
    "currency_code": "INR",
    "description": "A Liability account which can be paid off in a time period longer than one year.",
    "is_system_account": true,
    "is_involved_in_transaction": false,
    "can_show_in_ze": false,
    "include_in_vat_return": true,
    "custom_fields": [
        {
            "customfield_id": "460000000080163",
            "value": "Normal"
        }
    ],
    "parent_account_id": "460000000009097",
    "documents": [
        "string"
    ],
    "created_time": "2013-01-17T15:27:23+0530",
    "last_modified_time": "2013-01-17T15:27:23+0530"
}
```

---

## Create an account
Creates an account with the given account type.

`OAuth Scope : ZohoBooks.accountants.CREATE`

**Endpoint:**
`POST /chartofaccounts`

### Arguments
| Argument              | Type    | Required | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| :-------------------- | :------ | :------- | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| account_name          | string  | Optional | Name of the account                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| account_code          | string  | Optional | Code Associated with the Account                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| account_type          | string  | Optional | Type of the account. Allowed Values: `other_asset`, `other_current_asset`, `intangible_asset`, `right_to_use_asset`, `financial_asset`, `contingent_asset`, `contract_asset`, `cash`, `bank`, `fixed_asset`, `other_current_liability`, `contract_liability`, `refund_liability`, `credit_card`, `long_term_liability`, `loans_and_borrowing`, `lease_liability`, `employee_benefit_liability`, `contingent_liability`, `financial_liability`, `other_liability`, `equity`, `income`, `finance_income`, `other_comprehensive_income`, `other_income`, `expense`, `manufacturing_expense`, `impairment_expense`, `depreciation_expense`, `employee_benefit_expense`, `lease_expense`, `finance_expense`, `tax_expense`, `cost_of_goods_sold`, `other_expense`, `accounts_receivable` and `accounts_payable`. |
| currency_id           | string  | Optional | ID of the account currency.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| description           | string  | Optional | Description of the account                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| show_on_dashboard     | boolean | Optional |                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| can_show_in_ze        | boolean | Optional |                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| include_in_vat_return | boolean | Optional | Boolean to include an account in VAT returns. **United Kingdom only**.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| custom_fields         | array   | Optional |                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| parent_account_id     | string  | Optional | ID of the Parent Account                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/chartofaccounts?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{
    "account_name": "Notes Payable",
    "account_code": "string",
    "account_type": "long_term_liability",
    "currency_id": "460000000000097",
    "description": "A Liability account which can be paid off in a time period longer than one year.",
    "show_on_dashboard": false,
    "can_show_in_ze": false,
    "include_in_vat_return": true,
    "custom_fields": [
        {
            "customfield_id": "460000000080163",
            "value": "Normal"
        }
    ],
    "parent_account_id": "460000000009097"
}'
```

### Response Example
```json
{
    "code": 0,
    "message": "The account has been created.",
    "chart_of_account": {
        "account_id": "460000000038079",
        "account_name": "Notes Payable",
        "account_code": "string",
        "is_active": true,
        "account_type": "long_term_liability",
        "currency_id": "460000000000097",
        "currency_code": "INR",
        "description": "A Liability account which can be paid off in a time period longer than one year.",
        "is_system_account": true,
        "is_involved_in_transaction": false,
        "can_show_in_ze": false,
        "include_in_vat_return": true,
        "custom_fields": [
            {
                "customfield_id": "460000000080163",
                "value": "Normal"
            }
        ],
        "parent_account_id": "460000000009097",
        "documents": [
            "string"
        ],
        "created_time": "2013-01-17T15:27:23+0530",
        "last_modified_time": "2013-01-17T15:27:23+0530"
    }
}
```

---

## List chart of accounts
List all chart of accounts along with pagination.

`OAuth Scope : ZohoBooks.accountants.READ`

**Endpoint:**
`GET /chartofaccounts`

### Query Parameters
| Parameter          | Type    | Required | Description                                                                                                                                                                                                                                                |
| :----------------- | :------ | :------- | :--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| organization_id    | string  | Required | ID of the organization                                                                                                                                                                                                                                     |
| showbalance        | boolean | Optional | Boolean to get current balance of accounts.                                                                                                                                                                                                                |
| filter_by          | string  | Optional | Filter accounts based on its account type and status. Allowed Values: `AccountType.All`, `AccountType.Active`, `AccountType.Inactive`, `AccountType.Asset`, `AccountType.Liability`, `AccountType.Equity`, `AccountType.Income` and `AccountType.Expense`. |
| sort_column        | string  | Optional | Sort accounts. Allowed Values: `account_name` and `account_type`.                                                                                                                                                                                          |
| last_modified_time | string  | Optional |                                                                                                                                                                                                                                                            |
| page               | integer | Optional | Page number to be fetched. Default value is 1.                                                                                                                                                                                                             |
| per_page           | integer | Optional | Number of records to be fetched per page. Default value is 200.                                                                                                                                                                                            |

### Request Example
#### cURL
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/chartofaccounts?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "success",
    "chartofaccounts": [
        {
            "account_id": "460000000038079",
            "account_name": "Notes Payable",
            "account_code": "string",
            "account_type": "long_term_liability",
            "is_user_created": true,
            "is_system_account": true,
            "is_standalone_account": false,
            "is_active": true,
            "can_show_in_ze": false,
            "is_involved_in_transaction": false,
            "current_balance": null,
            "parent_account_id": "460000000009097",
            "parent_account_name": " ",
            "depth": "string",
            "has_attachment": false,
            "is_child_present": "string",
            "child_count": "string",
            "documents": [
                "string"
            ],
            "created_time": "2013-01-17T15:27:23+0530",
            "last_modified_time": "2013-01-17T15:27:23+0530"
        },
        {...},
        {...}
    ]
}
```

---

## Update an account
Updates the account information.

`OAuth Scope : ZohoBooks.accountants.UPDATE`

**Endpoint:**
`PUT /chartofaccounts/{account_id}`

### Arguments
| Argument              | Type    | Required | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| :-------------------- | :------ | :------- | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| account_name          | string  | Optional | Name of the account                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| account_code          | string  | Optional | Code Associated with the Account                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| account_type          | string  | Optional | Type of the account. Allowed Values: `other_asset`, `other_current_asset`, `intangible_asset`, `right_to_use_asset`, `financial_asset`, `contingent_asset`, `contract_asset`, `cash`, `bank`, `fixed_asset`, `other_current_liability`, `contract_liability`, `refund_liability`, `credit_card`, `long_term_liability`, `loans_and_borrowing`, `lease_liability`, `employee_benefit_liability`, `contingent_liability`, `financial_liability`, `other_liability`, `equity`, `income`, `finance_income`, `other_comprehensive_income`, `other_income`, `expense`, `manufacturing_expense`, `impairment_expense`, `depreciation_expense`, `employee_benefit_expense`, `lease_expense`, `finance_expense`, `tax_expense`, `cost_of_goods_sold`, `other_expense`, `accounts_receivable` and `accounts_payable`. |
| currency_id           | string  | Optional | ID of the account currency.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| description           | string  | Optional | Description of the account                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| show_on_dashboard     | boolean | Optional |                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| can_show_in_ze        | boolean | Optional |                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| include_in_vat_return | boolean | Optional | Boolean to include an account in VAT returns. **United Kingdom only**.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| custom_fields         | array   | Optional |                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| parent_account_id     | string  | Optional | ID of the Parent Account                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |

### Path Parameters
| Parameter  | Type   | Required | Description                       |
| :--------- | :----- | :------- | :-------------------------------- |
| account_id | string | Required | Unique identifier of the account. |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request PUT \
  --url 'https://www.zohoapis.com/books/v3/chartofaccounts/460000000038079?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{
    "account_name": "Notes Payable",
    "account_code": "string",
    "account_type": "long_term_liability",
    "currency_id": "460000000000097",
    "description": "A Liability account which can be paid off in a time period longer than one year.",
    "show_on_dashboard": false,
    "can_show_in_ze": false,
    "include_in_vat_return": true,
    "custom_fields": [
        {
            "customfield_id": "460000000080163",
            "value": "Normal"
        }
    ],
    "parent_account_id": "460000000009097"
}'
```

### Response Example
```json
{
    "code": 0,
    "message": "The details of the account have been updated.",
    "chart_of_account": {
        "account_id": "460000000038079",
        "account_name": "Notes Payable",
        "account_code": "string",
        "is_active": true,
        "account_type": "long_term_liability",
        "currency_id": "460000000000097",
        "currency_code": "INR",
        "description": "A Liability account which can be paid off in a time period longer than one year.",
        "is_system_account": true,
        "is_involved_in_transaction": false,
        "can_show_in_ze": false,
        "include_in_vat_return": true,
        "custom_fields": [
            {
                "customfield_id": "460000000080163",
                "value": "Normal"
            }
        ],
        "parent_account_id": "460000000009097",
        "documents": [
            "string"
        ],
        "created_time": "2013-01-17T15:27:23+0530",
        "last_modified_time": "2013-01-17T15:27:23+0530"
    }
}
```

---

## Get an account
Gets the details of an account.

`OAuth Scope : ZohoBooks.accountants.READ`

**Endpoint:**
`GET /chartofaccounts/{account_id}`

### Path Parameters
| Parameter  | Type   | Required | Description                       |
| :--------- | :----- | :------- | :-------------------------------- |
| account_id | string | Required | Unique identifier of the account. |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/chartofaccounts/460000000038079?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "success",
    "account_id": "460000000038079",
    "account_name": "Notes Payable",
    "account_code": "string",
    "is_active": true,
    "account_type": "long_term_liability",
    "currency_id": "460000000000097",
    "currency_code": "INR",
    "description": "A Liability account which can be paid off in a time period longer than one year.",
    "is_system_account": true,
    "is_involved_in_transaction": false,
    "can_show_in_ze": false,
    "include_in_vat_return": true,
    "custom_fields": [
        {
            "customfield_id": "460000000080163",
            "value": "Normal"
        }
    ],
    "closing_balance": 0,
    "parent_account_id": "460000000009097",
    "documents": [
        "string"
    ],
    "created_time": "2013-01-17T15:27:23+0530",
    "last_modified_time": "2013-01-17T15:27:23+0530"
}
```

---

## Delete an account
Deletes the given account. Accounts associated in any transaction/products could not be deleted.

`OAuth Scope : ZohoBooks.accountants.DELETE`

**Endpoint:**
`DELETE /chartofaccounts/{account_id}`

### Path Parameters
| Parameter  | Type   | Required | Description                       |
| :--------- | :----- | :------- | :-------------------------------- |
| account_id | string | Required | Unique identifier of the account. |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request DELETE \
  --url 'https://www.zohoapis.com/books/v3/chartofaccounts/460000000038079?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "The account has been deleted."
}
```

---

## Mark an account as active
Updates the account status as active.

`OAuth Scope : ZohoBooks.accountants.CREATE`

**Endpoint:**
`POST /chartofaccounts/{account_id}/active`

### Path Parameters
| Parameter  | Type   | Required | Description                       |
| :--------- | :----- | :------- | :-------------------------------- |
| account_id | string | Required | Unique identifier of the account. |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/chartofaccounts/460000000038079/active?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "The account has been marked as active."
}
```

---

## Mark an account as inactive
Updates the account status as inactive.

`OAuth Scope : ZohoBooks.accountants.CREATE`

**Endpoint:**
`POST /chartofaccounts/{account_id}/inactive`

### Path Parameters
| Parameter  | Type   | Required | Description                       |
| :--------- | :----- | :------- | :-------------------------------- |
| account_id | string | Required | Unique identifier of the account. |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/chartofaccounts/460000000038079/inactive?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "The account has been marked as inactive."
}
```

---

## List of transactions for an account
List all involved transactions for the given account.

`OAuth Scope : ZohoBooks.accountants.READ`

**Endpoint:**
`GET /chartofaccounts/transactions`

### Query Parameters
| Parameter        | Type    | Required | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| :--------------- | :------ | :------- | :-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| organization_id  | string  | Required | ID of the organization                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| account_id       | string  | Required | ID of the Account                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| date             | string  | Optional | Search account transactions with the given date range. Default date format is yyyy-mm-dd. Variants: `date.start`, `date.end`, `date.before` and `date.after`.                                                                                                                                                                                                                                                                                                                                                                     |
| amount           | double  | Optional | Search account transactions with given amount range. Variants: `amount.less_than`, `amount.less_equals`, `amount.greater_than` and `amount.greater_equals`.                                                                                                                                                                                                                                                                                                                                                                       |
| filter_by        | string  | Optional | Filter accounts based on its account type and status. Allowed Values: `AccountType.All`, `AccountType.Active`, `AccountType.Inactive`, `AccountType.Asset`, `AccountType.Liability`, `AccountType.Equity`, `AccountType.Income` and `AccountType.Expense`.                                                                                                                                                                                                                                                                        |
| transaction_type | string  | Optional | Search transactions based on the given transaction type. Allowed Values: `invoice`, `customer_payment`, `bills`, `vendor_payment`, `credit_notes`, `creditnote_refund`, `expense`, `card_payment`, `purchase_or_charges`, `journal`, `deposit`, `refund`, `transfer_fund`, `base_currency_adjustment`, `opening_balance`, `sales_without_invoices`, `expense_refund`, `tax_refund`, `receipt_from_initial_debtors`, `owner_contribution`, `interest_income`, `other_income`, `owner_drawings` and `payment_to_initial_creditors`. |
| sort_column      | string  | Optional | Sort accounts. Allowed Values: `account_name` and `account_type`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| page             | integer | Optional | Page number to be fetched. Default value is 1.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| per_page         | integer | Optional | Number of records to be fetched per page. Default value is 200.                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |

### Request Example
#### cURL
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/chartofaccounts/transactions?organization_id=10234695&account_id=460000000038079' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "success",
    "transactions": [
        {
            "categorized_transaction_id": "460000000052051",
            "transaction_type": "customer_payment",
            "transaction_status": "string",
            "transaction_source": "string",
            "transaction_id": "460000000050163",
            "transaction_date": "2013-10-04",
            "account_id": "460000000038079",
            "customer_id": "460000000044001",
            "payee": "Richards Electric Company",
            "description": "A Liability account which can be paid off in a time period longer than one year.",
            "entry_number": "INV-00004",
            "currency_id": "460000000000097",
            "currency_code": "INR",
            "debit_or_credit": "credit",
            "offset_account_name": "string",
            "reference_number": "string",
            "reconcile_status": "string",
            "debit_amount": "string",
            "credit_amount": 25
        },
        {...},
        {...}
    ]
}
```

---

## Delete a transaction
Deletes the transaction.

`OAuth Scope : ZohoBooks.accountants.DELETE`

**Endpoint:**
`DELETE /chartofaccounts/transactions/{transaction_id}`

### Path Parameters
| Parameter      | Type   | Required | Description                           |
| :------------- | :----- | :------- | :------------------------------------ |
| transaction_id | string | Required | Unique identifier of the transaction. |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request DELETE \
  --url 'https://www.zohoapis.com/books/v3/chartofaccounts/transactions/460000000050163?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "The transaction has been deleted."
}
```