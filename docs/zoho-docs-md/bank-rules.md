Here is the Zoho Books API documentation for **Bank Rules** converted into Markdown format.

# Bank Rules

In Zoho Books, you can automate the categorization of the bank feeds. The transaction rules feature in banking will help you in automatically identifying the bank transaction and categorizing it under the criteria provided by you.

## Attributes

| Attribute             | Type    | Description                                |
| :-------------------- | :------ | :----------------------------------------- |
| rule_id               | string  | ID of the Rule                             |
| rule_name             | string  | Name of the Rule                           |
| rule_order            | integer | Order of the rule                          |
| apply_to              | string  | Entities to which Rule must be applied     |
| criteria_type         | string  | Type of Criteria                           |
| record_as             | string  | Entity as which it should be recorded      |
| account_id            | string  | Account ID of the Bank                     |
| account_name          | string  | Name of the account                        |
| criterion             | array   | List of criteria associated with the rule. |
| criterion.criteria_id | string  | ID of the Criteria                         |
| criterion.field       | string  | Field involved in the Criteria             |
| criterion.comparator  | string  | Comparator used in Criteria                |
| criterion.value       | string  | Value to be compared with                  |

### Bank Rule Object Example
```json
{
    "rule_id": "460000000048005",
    "rule_name": "Minimum Deposit Rule",
    "rule_order": 0,
    "apply_to": "deposits",
    "criteria_type": "and",
    "record_as": "deposit",
    "account_id": "460000000000361",
    "account_name": "Petty Cash",
    "criterion": [
        {
            "criteria_id": "460000000048009",
            "field": "amount",
            "comparator": "greater_than_or_equals",
            "value": "500.00"
        }
    ]
}
```

---

## Create a rule
Create a rule and apply it on deposit/withdrawal for bank accounts and on refund/charges for credit card accounts.

`OAuth Scope : ZohoBooks.banking.CREATE`

**Endpoint:**
`POST /bankaccounts/rules`

### Arguments
| Argument                  | Type    | Required | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| :------------------------ | :------ | :------- | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| rule_name                 | string  | Required | Name of the Rule                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| target_account_id         | long    | Required | The account on which the rule has to be applied.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| apply_to                  | string  | Required | Rule applies to either deposits or withdrawals for bank accounts and to refunds or charges for credit card account. Allowed Values : `withdrawals`, `deposits`, `refunds` and `charges`.                                                                                                                                                                                                                                                                                                                                                                                |
| criteria_type             | string  | Required | Specifies whether all the criteria have to be satisfied or not. Allowed Values : `and` and `or`                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| criterion                 | array   | Required | List of criteria.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| criterion[].field         | string  | Optional | Field involved in the Criteria                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| criterion[].comparator    | string  | Optional | Comparator used in Criteria                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| criterion[].value         | string  | Optional | Value to be compared with                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| record_as                 | string  | Required | Record transaction based on value specified in apply_to node. <br>For bank accounts: If apply_to is deposits: `sales_without_invoices`, `transfer_fund`, `interest_income`, `other_income`, `expense_refund`, `deposit`. If apply_to is withdrawals: `expense`, `transfer_fund`, `card_payment`, `owner_drawings`. <br>For credit_card accounts: If apply_to is refunds: `card_payment`, `transfer_fund`, `expense_refund`, `refund`. If apply_to is charges: `expense`, `transfer_fund`.                                                                               |
| account_id                | long    | Optional | Account which is involved in the rule with the target account.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| customer_id               | long    | Optional | ID of the customer.(Applicable for sales_without_invoices, deposit, expense)                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| tax_id                    | string  | Optional | Tax ID involved in the transaction.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| reference_number          | string  | Optional | Specifies if Reference number is manual or generated from the statement. Allowed Values: `manual` and `from_statement`                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| vat_treatment             | string  | Optional | **United Kingdom only**. VAT treatment for the bank rules. VAT treatment denotes the location of the customer, if the customer resides in UK then the VAT treatment is `uk`. If the customer is in an EU country & VAT registered, you are resides in Northen Ireland and selling/purchasing Goods then his VAT treatment is `eu_vat_registered`, if he resides outside of the UK then his VAT treatment is `overseas`.                                                                                                                                                 |
| tax_treatment             | string  | Optional | **GCC, Kenya, South Africa only**. VAT treatment for the bank transaction. Choose whether the contact falls under: `vat_registered`, `vat_not_registered`, `gcc_vat_not_registered`, `gcc_vat_registered`, `non_gcc`.<br>`dz_vat_registered` and `dz_vat_not_registered` are supported only for **UAE**.<br>**For Kenya Edition:** `vat_registered`, `vat_not_registered`, `non_kenya` (A business that is located outside Kenya).<br>**For SouthAfrica Edition:** `vat_registered`, `vat_not_registered`, `overseas` (A business that is located outside SouthAfrica). |
| is_reverse_charge_applied | boolean | Optional | **South Africa only**. (Required if customer tax treatment is `vat_registered`)<br>Used to specify whether the transaction is applicable for Domestic Reverse Charge (DRC) or not.                                                                                                                                                                                                                                                                                                                                                                                      |
| product_type              | string  | Optional | **United Kingdom, South Africa, Europe only**. Product Type associated with the Rule. Allowed values:<br>**For UK and Europe:** `digital_service`, `goods` and `service`.<br>**For SouthAfrica Edition:** `service`, `goods`, `capital_service` and `capital_goods`.                                                                                                                                                                                                                                                                                                    |
| tax_authority_id          | string  | Optional | **United States only**. ID of the Tax Authority Associated with the Rule                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| tax_exemption_id          | string  | Optional | **India, United States only**. ID of the Tax Exemption Associated with the Rule                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/bankaccounts/rules?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{
    "rule_name": "Minimum Deposit Rule",
    "target_account_id": 460000000048001,
    "apply_to": "deposits",
    "criteria_type": "and",
    "criterion": [
        {
            "field": "amount",
            "comparator": "greater_than_or_equals",
            "value": "500.00"
        }
    ],
    "record_as": "deposit",
    "account_id": 460000000049001,
    "customer_id": 46000000000111,
    "tax_id": "460000000048238",
    "reference_number": "manual",
    "vat_treatment": "string",
    "tax_treatment": "vat_registered",
    "is_reverse_charge_applied": true,
    "product_type": "string",
    "tax_authority_id": "string",
    "tax_exemption_id": "string"
}'
```

### Response Example
```json
{
    "code": 0,
    "message": "The bank rule has been created.",
    "rule": {
        "rule_id": "460000000048005",
        "rule_name": "Minimum Deposit Rule",
        "rule_order": 0,
        "apply_to": "deposits",
        "criteria_type": "and",
        "criterion": [
            {
                "criteria_id": "460000000048009",
                "field": "amount",
                "comparator": "greater_than_or_equals",
                "value": "500.00"
            }
        ],
        "record_as": "deposit",
        "account_id": "460000000000361",
        "account_name": "Petty Cash",
        "tax_id": "460000000048238",
        "customer_id": "46000000000111",
        "customer_name": "Trendz",
        "reference_number": "from_statement",
        "payment_mode": "Cash",
        "vat_treatment": "string",
        "tax_treatment": "vat_registered",
        "is_reverse_charge_applied": true,
        "product_type": "string",
        "tax_authority_id": "string",
        "tax_authority_name": "string",
        "tax_exemption_code": "string"
    }
}
```

---

## Get Rules List
Fetch all the rules created for a specified bank or credit card account ID.

`OAuth Scope : ZohoBooks.banking.READ`

**Endpoint:**
`GET /bankaccounts/rules`

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |
| account_id      | long   | Required | ID of the Bank Account |

### Request Example
#### cURL
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/bankaccounts/rules?organization_id=10234695&account_id=460000000000361' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "success",
    "rules": [
        {
            "rule_id": "460000000048005",
            "rule_name": "Minimum Deposit Rule",
            "rule_order": 0,
            "apply_to": "deposits",
            "criteria_type": "and",
            "record_as": "deposit",
            "account_id": "460000000000361",
            "account_name": "Petty Cash",
            "criterion": [
                {
                    "criteria_id": "460000000048009",
                    "field": "amount",
                    "comparator": "greater_than_or_equals",
                    "value": "500.00"
                }
            ]
        }
    ]
}
```

---

## Update a rule
Make changes to the rule, add or modify it and update.

`OAuth Scope : ZohoBooks.banking.UPDATE`

**Endpoint:**
`PUT /bankaccounts/rules/{rule_id}`

### Arguments
| Argument                  | Type    | Required | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| :------------------------ | :------ | :------- | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| rule_name                 | string  | Required | Name of the Rule                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| target_account_id         | long    | Required | The account on which the rule has to be applied.                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| apply_to                  | string  | Required | Rule applies to either deposits or withdrawals for bank accounts and to refunds or charges for credit card account. Allowed Values : `withdrawals`, `deposits`, `refunds` and `charges`.                                                                                                                                                                                                                                                                                                  |
| criteria_type             | string  | Required | Specifies whether all the criteria have to be satisfied or not. Allowed Values : `and` and `or`                                                                                                                                                                                                                                                                                                                                                                                           |
| criterion                 | array   | Required | List of criteria.                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| criterion[].criteria_id   | string  | Optional | ID of the Criteria                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| criterion[].field         | string  | Optional | Field involved in the Criteria                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| criterion[].comparator    | string  | Optional | Comparator used in Criteria                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| criterion[].value         | string  | Optional | Value to be compared with                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| record_as                 | string  | Required | Record transaction based on value specified in apply_to node. <br>For bank accounts: If apply_to is deposits: `sales_without_invoices`, `transfer_fund`, `interest_income`, `other_income`, `expense_refund`, `deposit`. If apply_to is withdrawals: `expense`, `transfer_fund`, `card_payment`, `owner_drawings`. <br>For credit_card accounts: If apply_to is refunds: `card_payment`, `transfer_fund`, `expense_refund`, `refund`. If apply_to is charges: `expense`, `transfer_fund`. |
| account_id                | long    | Optional | Account which is involved in the rule with the target account.                                                                                                                                                                                                                                                                                                                                                                                                                            |
| customer_id               | long    | Optional | ID of the customer.(Applicable for sales_without_invoices, deposit, expense)                                                                                                                                                                                                                                                                                                                                                                                                              |
| tax_id                    | string  | Optional | Tax ID involved in the transaction.                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| reference_number          | string  | Optional | Specifies if Reference number is manual or generated from the statement. Allowed Values: `manual` and `from_statement`                                                                                                                                                                                                                                                                                                                                                                    |
| vat_treatment             | string  | Optional | **United Kingdom only**. VAT treatment for the bank rules.                                                                                                                                                                                                                                                                                                                                                                                                                                |
| tax_treatment             | string  | Optional | **GCC, Kenya, South Africa only**. VAT treatment for the bank transaction.                                                                                                                                                                                                                                                                                                                                                                                                                |
| is_reverse_charge_applied | boolean | Optional | **South Africa only**. (Required if customer tax treatment is `vat_registered`)                                                                                                                                                                                                                                                                                                                                                                                                           |
| product_type              | string  | Optional | **United Kingdom, South Africa, Europe only**. Product Type associated with the Rule.                                                                                                                                                                                                                                                                                                                                                                                                     |
| tax_authority_id          | string  | Optional | **United States only**. ID of the Tax Authority Associated with the Rule                                                                                                                                                                                                                                                                                                                                                                                                                  |
| tax_exemption_id          | string  | Optional | **India, United States only**. ID of the Tax Exemption Associated with the Rule                                                                                                                                                                                                                                                                                                                                                                                                           |

### Path Parameters
| Parameter | Type   | Required | Description                                 |
| :-------- | :----- | :------- | :------------------------------------------ |
| rule_id   | string | Required | Unique identifier of the bank account rule. |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request PUT \
  --url 'https://www.zohoapis.com/books/v3/bankaccounts/rules/460000000048005?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{
    "rule_name": "Minimum Deposit Rule",
    "target_account_id": 460000000048001,
    "apply_to": "deposits",
    "criteria_type": "and",
    "criterion": [
        {
            "criteria_id": "460000000048009",
            "field": "amount",
            "comparator": "greater_than_or_equals",
            "value": "500.00"
        }
    ],
    "record_as": "deposit",
    "account_id": 460000000049001,
    "customer_id": 46000000000111,
    "tax_id": "460000000048238",
    "reference_number": "manual",
    "vat_treatment": "string",
    "tax_treatment": "vat_registered",
    "is_reverse_charge_applied": true,
    "product_type": "string",
    "tax_authority_id": "string",
    "tax_exemption_id": "string"
}'
```

### Response Example
```json
{
    "code": 0,
    "message": "The bank rule has been updated.",
    "rule": {
        "rule_id": "460000000048005",
        "rule_name": "Minimum Deposit Rule",
        "rule_order": 0,
        "apply_to": "deposits",
        "criteria_type": "and",
        "criterion": [
            {
                "criteria_id": "460000000048009",
                "field": "amount",
                "comparator": "greater_than_or_equals",
                "value": "500.00"
            }
        ],
        "record_as": "deposit",
        "account_id": "460000000000361",
        "account_name": "Petty Cash",
        "tax_id": "460000000048238",
        "customer_id": "46000000000111",
        "customer_name": "Trendz",
        "reference_number": "from_statement",
        "payment_mode": "Cash",
        "vat_treatment": "string",
        "tax_treatment": "vat_registered",
        "is_reverse_charge_applied": true,
        "product_type": "string",
        "tax_authority_id": "string",
        "tax_authority_name": "string",
        "tax_exemption_code": "string"
    }
}
```

---

## Get a rule
Get details of a specific rule.

`OAuth Scope : ZohoBooks.banking.READ`

**Endpoint:**
`GET /bankaccounts/rules/{rule_id}`

### Path Parameters
| Parameter | Type   | Required | Description                                 |
| :-------- | :----- | :------- | :------------------------------------------ |
| rule_id   | string | Required | Unique identifier of the bank account rule. |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/bankaccounts/rules/460000000048005?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "success",
    "rule_id": "460000000048005",
    "rule_name": "Minimum Deposit Rule",
    "rule_order": 0,
    "apply_to": "deposits",
    "criteria_type": "and",
    "criterion": [
        {
            "criteria_id": "460000000048009",
            "field": "amount",
            "comparator": "greater_than_or_equals",
            "value": "500.00"
        }
    ],
    "record_as": "deposit",
    "account_id": "460000000000361",
    "account_name": "Petty Cash",
    "tax_id": "460000000048238",
    "customer_id": "46000000000111",
    "customer_name": "Trendz",
    "reference_number": "from_statement",
    "payment_mode": "Cash",
    "vat_treatment": "string",
    "tax_treatment": "vat_registered",
    "is_reverse_charge_applied": true,
    "product_type": "string",
    "tax_authority_id": "string",
    "tax_authority_name": "string",
    "tax_exemption_code": "string"
}
```

---

## Delete a rule
Delete a rule from your account and make it no longer applicable on the transactions.

`OAuth Scope : ZohoBooks.banking.DELETE`

**Endpoint:**
`DELETE /bankaccounts/rules/{rule_id}`

### Path Parameters
| Parameter | Type   | Required | Description                                 |
| :-------- | :----- | :------- | :------------------------------------------ |
| rule_id   | string | Required | Unique identifier of the bank account rule. |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request DELETE \
  --url 'https://www.zohoapis.com/books/v3/bankaccounts/rules/460000000048005?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "The rule has been deleted."
}
```