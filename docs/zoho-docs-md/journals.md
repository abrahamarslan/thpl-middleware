Here is the documentation for **Journals** in Markdown format, including attributes, endpoints, and examples.

# Journals

Journals are used by accountants to work directly with the general ledger to create both debit and credit entries for unique financial transactions.

## Attributes

| Attribute                                | Type    | Description                                                                                                                                                        |
| :--------------------------------------- | :------ | :----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| journal_id                               | string  | ID of the Journal                                                                                                                                                  |
| entry_number                             | string  | Entry Number of the Journal                                                                                                                                        |
| reference_number                         | string  | Reference number for the journal.                                                                                                                                  |
| notes                                    | string  | Notes for the journal.                                                                                                                                             |
| currency_id                              | string  | ID of the Currency Associated with the Journal                                                                                                                     |
| currency_code                            | string  | Code of the Currency Associated with the Journal                                                                                                                   |
| currency_symbol                          | string  | Symbol of the Currency Associated with the Journal                                                                                                                 |
| exchange_rate                            | double  | Exchange Rate between the Currencies                                                                                                                               |
| journal_date                             | string  | Date on which the journal to be recorded.                                                                                                                          |
| journal_type                             | string  | Type of the Journal. Allowed values: `Cash` and `Both`.                                                                                                            |
| vat_treatment                            | string  | (Optional) VAT treatment for the journals. **UK & Europe only**.                                                                                                   |
| product_type                             | string  | Type of the journal. This denotes whether the journal is to be treated as goods or service. Allowed Values: `digital_service`, `goods` and `service`. **UK only**. |
| include_in_vat_return                    | boolean | Check if Journal should be included in VAT Return. **UK & Europe only**.                                                                                           |
| is_bas_adjustment                        | boolean | Check if Journal is created for BAS Adjustment. **Australia only**.                                                                                                |
| line_items                               | array   | List of line items in the journal.                                                                                                                                 |
| line_items.line_id                       | string  | ID of the Line                                                                                                                                                     |
| line_items.account_id                    | string  | ID of account for which journals to be recorded.                                                                                                                   |
| line_items.customer_id                   | string  | ID of the Customer/Vendor                                                                                                                                          |
| line_items.customer_name                 | string  | Name of the Customer/Vendor                                                                                                                                        |
| line_items.account_name                  | string  | Name of the Account                                                                                                                                                |
| line_items.description                   | string  | Description that can be given at the line item level.                                                                                                              |
| line_items.debit_or_credit               | string  | Whether the accounts needs to be debited or credited. Allowed Values: `debit` and `credit`.                                                                        |
| line_items.tax_exemption_id              | string  | ID of the Tax Exemption. **India, US, Australia, Canada, Mexico only**.                                                                                            |
| line_items.tax_exemption_type            | string  | Type of the Tax Exemption. Allowed Values : `customer` and `item`. **India, US, Australia, Canada, Mexico only**.                                                  |
| line_items.tax_exemption_code            | string  | Code of the Tax Exemption. **India, US, Australia, Canada only**.                                                                                                  |
| line_items.tax_authority_id              | string  | ID of the Tax Authority. **US, Australia, Canada, Mexico only**.                                                                                                   |
| line_items.tax_authority_name            | string  | Name of the Tax Authority. **US, Australia, Canada only**.                                                                                                         |
| line_items.tax_id                        | string  | ID of the tax.                                                                                                                                                     |
| line_items.tax_name                      | string  | Name of the Tax                                                                                                                                                    |
| line_items.tax_type                      | string  | Type of the Tax                                                                                                                                                    |
| line_items.tax_percentage                | string  | Percentage of the Tax                                                                                                                                              |
| line_items.amount                        | double  | Amount to be recorded for the journal.                                                                                                                             |
| line_items.bcy_amount                    | double  | Amount in Base Currency                                                                                                                                            |
| line_items.acquisition_vat_id            | string  | (Optional) This is the ID of the tax applied in case this is an EU - goods journal and acquisition VAT needs to be reported. **UK only**.                          |
| line_items.acquisition_vat_name          | string  | Name of the VAT Acquistion. **UK & Europe only**.                                                                                                                  |
| line_items.acquisition_vat_percentage    | string  | Percentage of the VAT Acquistion. **UK & Europe only**.                                                                                                            |
| line_items.acquisition_vat_amount        | string  | Amount of the VAT Acquistion. **UK & Europe only**.                                                                                                                |
| line_items.reverse_charge_vat_id         | string  | (Optional) This is the ID of the tax applied in case this is a non UK - service journal and reverse charge VAT needs to be reported. **UK only**.                  |
| line_items.reverse_charge_vat_name       | string  | Name of the Reverse Charge. **UK & Europe only**.                                                                                                                  |
| line_items.reverse_charge_vat_percentage | string  | Percentage of the Reverse Charge. **UK & Europe only**.                                                                                                            |
| line_items.reverse_charge_vat_amount     | string  | Percentage of the Reverse Charge. **UK & Europe only**.                                                                                                            |
| line_items.tags                          | array   | List of tags.                                                                                                                                                      |
| line_items.tags.tag_id                   | long    | ID of the Tag                                                                                                                                                      |
| line_items.tags.tag_option_id            | long    | ID of the Tag Option                                                                                                                                               |
| line_items.location_id                   | string  | Location ID                                                                                                                                                        |
| line_items.location_name                 | string  | Name of the location.                                                                                                                                              |
| line_items.project_id                    | string  | ID of the Project                                                                                                                                                  |
| line_items.project_name                  | string  | Name of the Project                                                                                                                                                |
| location_id                              | string  | Location ID                                                                                                                                                        |
| location_name                            | string  | Name of the location.                                                                                                                                              |
| line_item_total                          | double  | Total of the Line Item                                                                                                                                             |
| total                                    | double  | Total of the Journal                                                                                                                                               |
| bcy_total                                | double  | Total in Base Currency                                                                                                                                             |
| price_precision                          | integer | Price Precision for the Values                                                                                                                                     |
| taxes                                    | array   | Taxes information.                                                                                                                                                 |
| taxes.tax_name                           | string  | Name of the Tax                                                                                                                                                    |
| taxes.tax_amount                         | double  | Amount of Tax                                                                                                                                                      |
| taxes.debit_or_credit                    | string  | Whether the accounts needs to be debited or credited. Allowed Values: `debit` and `credit`.                                                                        |
| taxes.tax_account                        | boolean | Account for recording Tax                                                                                                                                          |
| created_time                             | string  | Created Time of the Journal                                                                                                                                        |
| last_modified_time                       | string  | Last Modified Time of the Journal                                                                                                                                  |
| status                                   | string  | Search Journal by journal status. Allowed Values: `draft` and `published`.                                                                                         |
| custom_fields                            | array   | Custom fields.                                                                                                                                                     |
| custom_fields.customfield_id             | string  | ID of the Custom Field                                                                                                                                             |
| custom_fields.value                      | string  | Value of the Custom Field                                                                                                                                          |

### Journal Object Example
```json
{
    "journal_id": "460000000038001",
    "entry_number": "1",
    "reference_number": "7355",
    "notes": "Loan repayment",
    "currency_id": "460000000000097",
    "currency_code": "USD",
    "currency_symbol": "$",
    "exchange_rate": 1,
    "journal_date": "2013-09-04",
    "journal_type": "both",
    "vat_treatment": "string",
    "product_type": "string",
    "include_in_vat_return": true,
    "is_bas_adjustment": true,
    "line_items": [
        {
            "line_id": "460000000038005",
            "account_id": "460000000000361",
            "customer_id": "string",
            "customer_name": "string",
            "account_name": "Petty Cash",
            "description": "string",
            "debit_or_credit": "credit",
            "tax_exemption_id": "string",
            "tax_exemption_type": "string",
            "tax_exemption_code": "string",
            "tax_authority_id": "string",
            "tax_authority_name": "string",
            "tax_id": "string",
            "tax_name": "string",
            "tax_type": "tax",
            "tax_percentage": "string",
            "amount": 5000,
            "bcy_amount": 100,
            "acquisition_vat_id": "string",
            "acquisition_vat_name": "string",
            "acquisition_vat_percentage": "string",
            "acquisition_vat_amount": "string",
            "reverse_charge_vat_id": "string",
            "reverse_charge_vat_name": "string",
            "reverse_charge_vat_percentage": "string",
            "reverse_charge_vat_amount": "string",
            "tags": [
                {
                    "is_tag_mandatory": false,
                    "tag_id": "460000000094001",
                    "tag_name": "Location",
                    "tag_option_id": "460000000048001",
                    "tag_option_name": "USA"
                }
            ],
            "location_id": "460000000038080",
            "location_name": "string",
            "project_id": "460000000898001",
            "project_name": "Network Distribution"
        }
    ],
    "location_id": "460000000038080",
    "location_name": "string",
    "line_item_total": 5000,
    "total": 5000,
    "bcy_total": 100,
    "price_precision": 2,
    "taxes": [
        {
            "tax_name": "string",
            "tax_amount": 0.1,
            "debit_or_credit": "credit",
            "tax_account": true
        }
    ],
    "created_time": "2013-09-04T09:40:07+0530",
    "last_modified_time": "2013-09-05T17:13:31+0530",
    "status": "draft",
    "custom_fields": [
        {
            "customfield_id": "460000000098001",
            "value": "Normal"
        }
    ]
}
```

---

## Create a journal
Create a journal.

`OAuth Scope : ZohoBooks.accountants.CREATE`

**Endpoint:**
`POST /journals`

### Arguments
| Argument                         | Type    | Required | Description                                                                                                                                                        |
| :------------------------------- | :------ | :------- | :----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| journal_date                     | string  | Required | Date on which the journal to be recorded.                                                                                                                          |
| reference_number                 | string  | Optional | Reference number for the journal.                                                                                                                                  |
| notes                            | string  | Optional | Notes for the journal.                                                                                                                                             |
| journal_type                     | string  | Optional | Type of the Journal. Allowed values: `Cash` and `Both`.                                                                                                            |
| vat_treatment                    | string  | Optional | VAT treatment for the journals. **UK & Europe only**.                                                                                                              |
| include_in_vat_return            | boolean | Optional | Check if Journal should be included in VAT Return. **UK & Europe only**.                                                                                           |
| product_type                     | string  | Optional | Type of the journal. This denotes whether the journal is to be treated as goods or service. Allowed Values: `digital_service`, `goods` and `service`. **UK only**. |
| is_bas_adjustment                | boolean | Optional | Check if Journal is created for BAS Adjustment. **Australia only**.                                                                                                |
| currency_id                      | string  | Optional | ID of the Currency Associated with the Journal.                                                                                                                    |
| exchange_rate                    | double  | Optional | Exchange Rate between the Currencies.                                                                                                                              |
| location_id                      | string  | Optional | Location ID                                                                                                                                                        |
| line_items                       | array   | Optional |                                                                                                                                                                    |
| line_items.account_id            | string  | Optional | ID of account for which journals to be recorded.                                                                                                                   |
| line_items.customer_id           | string  | Optional | ID of the Customer/Vendor                                                                                                                                          |
| line_items.line_id               | string  | Optional | ID of the Line                                                                                                                                                     |
| line_items.description           | string  | Optional | Description that can be given at the line item level.                                                                                                              |
| line_items.tax_exemption_id      | string  | Optional | ID of the Tax Exemption. **India, US, Australia, Canada, Mexico only**.                                                                                            |
| line_items.tax_authority_id      | string  | Optional | ID of the Tax Authority. **US, Australia, Canada, Mexico only**.                                                                                                   |
| line_items.tax_exemption_type    | string  | Optional | Type of the Tax Exemption. Allowed Values : `customer` and `item`. **India, US, Australia, Canada, Mexico only**.                                                  |
| line_items.tax_exemption_code    | string  | Optional | Code of the Tax Exemption. **India, US, Australia, Canada only**.                                                                                                  |
| line_items.tax_authority_name    | string  | Optional | Name of the Tax Authority. **US, Australia, Canada only**.                                                                                                         |
| line_items.tax_id                | string  | Optional | ID of the tax.                                                                                                                                                     |
| line_items.amount                | double  | Required | Amount to be recorded for the journal.                                                                                                                             |
| line_items.debit_or_credit       | string  | Required | Whether the accounts needs to be debited or credited. Allowed Values: `debit` and `credit`.                                                                        |
| line_items.acquisition_vat_id    | string  | Optional | This is the ID of the tax applied in case this is an EU - goods journal and acquisition VAT needs to be reported. **UK only**.                                     |
| line_items.reverse_charge_vat_id | string  | Optional | This is the ID of the tax applied in case this is a non UK - service journal and reverse charge VAT needs to be reported. **UK only**.                             |
| line_items.location_id           | string  | Optional | Location ID                                                                                                                                                        |
| line_items.tags                  | array   | Optional |                                                                                                                                                                    |
| line_items.tags.tag_id           | long    | Optional | ID of the Tag                                                                                                                                                      |
| line_items.tags.tag_option_id    | long    | Optional | ID of the Tag Option                                                                                                                                               |
| line_items.project_id            | string  | Optional | ID of the Project                                                                                                                                                  |
| tax_exemption_code               | string  | Optional | Code of the Tax Exemption. **India, US, Australia, Canada only**.                                                                                                  |
| tax_exemption_type               | string  | Optional | Type of the Tax Exemption. Allowed Values : `customer` and `item`. **India, US, Australia, Canada, Mexico only**.                                                  |
| status                           | string  | Optional | Search Journal by journal status. Allowed Values: `draft` and `published`.                                                                                         |
| custom_fields                    | array   | Optional |                                                                                                                                                                    |
| custom_fields.customfield_id     | string  | Optional | ID of the Custom Field                                                                                                                                             |
| custom_fields.value              | string  | Optional | Value of the Custom Field                                                                                                                                          |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/journals?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{"field1":"value1","field2":"value2"}'
```

### Response Example
```json
{
    "code": 0,
    "message": "The journal entry has been created.",
    "journal": {
        "journal_id": "460000000038001",
        "entry_number": "1",
        "reference_number": "7355",
        "notes": "Loan repayment",
        "currency_id": "460000000000097",
        "currency_code": "USD",
        "currency_symbol": "$",
        "exchange_rate": 1,
        "journal_date": "2013-09-04",
        "journal_type": "both",
        "vat_treatment": "string",
        "product_type": "string",
        "include_in_vat_return": true,
        "is_bas_adjustment": true,
        "line_items": [
            {
                "line_id": "460000000038005",
                "account_id": "460000000000361",
                "customer_id": "string",
                "customer_name": "string",
                "account_name": "Petty Cash",
                "description": "string",
                "debit_or_credit": "credit",
                "tax_exemption_id": "string",
                "tax_exemption_type": "string",
                "tax_exemption_code": "string",
                "tax_authority_id": "string",
                "tax_authority_name": "string",
                "tax_id": "string",
                "tax_name": "string",
                "tax_type": "tax",
                "tax_percentage": "string",
                "amount": 5000,
                "bcy_amount": 100,
                "acquisition_vat_id": "string",
                "acquisition_vat_name": "string",
                "acquisition_vat_percentage": "string",
                "acquisition_vat_amount": "string",
                "reverse_charge_vat_id": "string",
                "reverse_charge_vat_name": "string",
                "reverse_charge_vat_percentage": "string",
                "reverse_charge_vat_amount": "string",
                "tags": [
                    {
                        "is_tag_mandatory": false,
                        "tag_id": "460000000094001",
                        "tag_name": "Location",
                        "tag_option_id": "460000000048001",
                        "tag_option_name": "USA"
                    }
                ],
                "location_id": "460000000038080",
                "location_name": "string",
                "project_id": "460000000898001",
                "project_name": "Network Distribution"
            }
        ],
        "location_id": "460000000038080",
        "location_name": "string",
        "line_item_total": 5000,
        "total": 5000,
        "bcy_total": 100,
        "price_precision": 2,
        "taxes": [
            {
                "tax_name": "string",
                "tax_amount": 0.1,
                "debit_or_credit": "credit",
                "tax_account": true
            }
        ],
        "created_time": "2013-09-04T09:40:07+0530",
        "last_modified_time": "2013-09-05T17:13:31+0530",
        "status": "draft",
        "custom_fields": [
            {
                "customfield_id": "460000000098001",
                "value": "Normal"
            }
        ]
    }
}
```

---

## Get journal list
Get journal list.

`OAuth Scope : ZohoBooks.accountants.READ`

**Endpoint:**
`GET /journals`

### Query Parameters
| Parameter          | Type    | Required | Description                                                                                                                                                                                    |
| :----------------- | :------ | :------- | :--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| organization_id    | string  | Required | ID of the organization                                                                                                                                                                         |
| entry_number       | string  | Optional | Search journals by journal entry number. Variants: `entry_number_startswith` and `entry_number_contains`                                                                                       |
| reference_number   | string  | Optional | Search journals by journal reference number. Variants: `reference_number_startswith` and `reference_number_contains`                                                                           |
| date               | string  | Optional | Search journals by journal date. Variants: `date_start`, `date_end`, `date_before` and `date_after`                                                                                            |
| notes              | string  | Optional | Search journals by journal notes. Variants: `notes_startswith` and `notes_contains`                                                                                                            |
| last_modified_time | string  | Optional | Search the journals using Last Modified Time                                                                                                                                                   |
| total              | double  | Optional | Search journals by journal total. Variants: `total_less_than`, `total_less_equals`, `total_greater_than` and `total_greater_equals`                                                            |
| customer_id        | long    | Optional | Search Journals using Customer ID                                                                                                                                                              |
| vendor_id          | long    | Optional | Search the journals using Vendor ID                                                                                                                                                            |
| filter_by          | string  | Optional | Filter journals by journal date. Allowed Values: `JournalDate.All`, `JournalDate.Today`, `JournalDate.ThisWeek`, `JournalDate.ThisMonth`, `JournalDate.ThisQuarter` and `JournalDate.ThisYear` |
| sort_column        | string  | Optional | Sort journal list. Allowed Values: `journal_date`, `entry_number`, `reference_number` and `total`                                                                                              |
| page               | integer | Optional | Page number to be fetched. Default value is 1.                                                                                                                                                 |
| per_page           | integer | Optional | Number of records to be fetched per page. Default value is 200.                                                                                                                                |

### Request Example
#### cURL
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/journals?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "success",
    "journals": [
        {
            "journal_id": "460000000038001",
            "journal_date": "2013-09-04",
            "entry_number": "1",
            "reference_number": "7355",
            "currency_id": "460000000000097",
            "notes": "Loan repayment",
            "journal_type": "both",
            "entity_type": "journal",
            "total": 5000,
            "bcy_total": 100,
            "custom_field": "string"
        },
        {...},
        {...}
    ]
}
```

---

## Update a journal
Updates the journal with given information.

`OAuth Scope : ZohoBooks.accountants.UPDATE`

**Endpoint:**
`PUT /journals/{journal_id}`

### Arguments
| Argument                         | Type    | Required | Description                                                                                                                                                        |
| :------------------------------- | :------ | :------- | :----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| journal_date                     | string  | Required | Date on which the journal to be recorded.                                                                                                                          |
| reference_number                 | string  | Optional | Reference number for the journal.                                                                                                                                  |
| notes                            | string  | Optional | Notes for the journal.                                                                                                                                             |
| journal_type                     | string  | Optional | Type of the Journal. Allowed values: `Cash` and `Both`.                                                                                                            |
| vat_treatment                    | string  | Optional | VAT treatment for the journals. **UK & Europe only**.                                                                                                              |
| include_in_vat_return            | boolean | Optional | Check if Journal should be included in VAT Return. **UK & Europe only**.                                                                                           |
| product_type                     | string  | Optional | Type of the journal. This denotes whether the journal is to be treated as goods or service. Allowed Values: `digital_service`, `goods` and `service`. **UK only**. |
| is_bas_adjustment                | boolean | Optional | Check if Journal is created for BAS Adjustment. **Australia only**.                                                                                                |
| currency_id                      | string  | Optional | ID of the Currency Associated with the Journal                                                                                                                     |
| exchange_rate                    | double  | Optional | Exchange Rate between the Currencies                                                                                                                               |
| location_id                      | string  | Optional | Location ID                                                                                                                                                        |
| line_items                       | array   | Optional |                                                                                                                                                                    |
| line_items.account_id            | string  | Optional | ID of account for which journals to be recorded.                                                                                                                   |
| line_items.customer_id           | string  | Optional | ID of the Customer/Vendor                                                                                                                                          |
| line_items.line_id               | string  | Optional | ID of the Line                                                                                                                                                     |
| line_items.description           | string  | Optional | Description that can be given at the line item level.                                                                                                              |
| line_items.tax_exemption_id      | string  | Optional | ID of the Tax Exemption. **India, US, Australia, Canada, Mexico only**.                                                                                            |
| line_items.tax_authority_id      | string  | Optional | ID of the Tax Authority. **US, Australia, Canada, Mexico only**.                                                                                                   |
| line_items.tax_exemption_type    | string  | Optional | Type of the Tax Exemption. Allowed Values : `customer` and `item`. **India, US, Australia, Canada, Mexico only**.                                                  |
| line_items.tax_exemption_code    | string  | Optional | Code of the Tax Exemption. **India, US, Australia, Canada only**.                                                                                                  |
| line_items.tax_authority_name    | string  | Optional | Name of the Tax Authority. **US, Australia, Canada only**.                                                                                                         |
| line_items.tax_id                | string  | Optional | ID of the tax.                                                                                                                                                     |
| line_items.amount                | double  | Required | Amount to be recorded for the journal.                                                                                                                             |
| line_items.debit_or_credit       | string  | Required | Whether the accounts needs to be debited or credited. Allowed Values: `debit` and `credit`.                                                                        |
| line_items.acquisition_vat_id    | string  | Optional | This is the ID of the tax applied in case this is an EU - goods journal and acquisition VAT needs to be reported. **UK only**.                                     |
| line_items.reverse_charge_vat_id | string  | Optional | This is the ID of the tax applied in case this is a non UK - service journal and reverse charge VAT needs to be reported. **UK only**.                             |
| line_items.tags                  | array   | Optional |                                                                                                                                                                    |
| line_items.tags.tag_id           | long    | Optional | ID of the Tag                                                                                                                                                      |
| line_items.tags.tag_option_id    | long    | Optional | ID of the Tag Option                                                                                                                                               |
| line_items.location_id           | string  | Optional | Location ID                                                                                                                                                        |
| line_items.project_id            | string  | Optional | ID of the Project                                                                                                                                                  |
| tax_exemption_code               | string  | Optional | Code of the Tax Exemption. **India, US, Australia, Canada only**.                                                                                                  |
| tax_exemption_type               | string  | Optional | Type of the Tax Exemption. Allowed Values : `customer` and `item`. **India, US, Australia, Canada, Mexico only**.                                                  |
| custom_fields                    | array   | Optional |                                                                                                                                                                    |
| custom_fields.customfield_id     | string  | Optional | ID of the Custom Field                                                                                                                                             |
| custom_fields.value              | string  | Optional | Value of the Custom Field                                                                                                                                          |

### Path Parameters
| Parameter  | Type   | Required | Description                       |
| :--------- | :----- | :------- | :-------------------------------- |
| journal_id | string | Required | Unique identifier of the journal. |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request PUT \
  --url 'https://www.zohoapis.com/books/v3/journals/460000000038001?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{"field1":"value1","field2":"value2"}'
```

### Response Example
```json
{
    "code": 0,
    "message": "The journal entry has been updated.",
    "journal": {
        "journal_id": "460000000038001",
        "entry_number": "1",
        "reference_number": "7355",
        "notes": "Loan repayment",
        "currency_id": "460000000000097",
        "currency_code": "USD",
        "currency_symbol": "$",
        "exchange_rate": 1,
        "journal_date": "2013-09-04",
        "journal_type": "both",
        "vat_treatment": "string",
        "product_type": "string",
        "include_in_vat_return": true,
        "is_bas_adjustment": true,
        "line_items": [
            {
                "line_id": "460000000038005",
                "account_id": "460000000000361",
                "customer_id": "string",
                "customer_name": "string",
                "account_name": "Petty Cash",
                "description": "string",
                "debit_or_credit": "credit",
                "tax_exemption_id": "string",
                "tax_exemption_type": "string",
                "tax_exemption_code": "string",
                "tax_authority_id": "string",
                "tax_authority_name": "string",
                "tax_id": "string",
                "tax_name": "string",
                "tax_type": "tax",
                "tax_percentage": "string",
                "amount": 5000,
                "bcy_amount": 100,
                "acquisition_vat_id": "string",
                "acquisition_vat_name": "string",
                "acquisition_vat_percentage": "string",
                "acquisition_vat_amount": "string",
                "reverse_charge_vat_id": "string",
                "reverse_charge_vat_name": "string",
                "reverse_charge_vat_percentage": "string",
                "reverse_charge_vat_amount": "string",
                "tags": [
                    {
                        "is_tag_mandatory": false,
                        "tag_id": "460000000094001",
                        "tag_name": "Location",
                        "tag_option_id": "460000000048001",
                        "tag_option_name": "USA"
                    }
                ],
                "location_id": "460000000038080",
                "location_name": "string",
                "project_id": "460000000898001",
                "project_name": "Network Distribution"
            }
        ],
        "tax_exemption_code": "string",
        "tax_exemption_type": "string",
        "custom_fields": [
            {
                "customfield_id": "460000000098001",
                "value": "Normal"
            }
        ]
    }
}
```

---

## Get journal
Get the details of the journal.

`OAuth Scope : ZohoBooks.accountants.READ`

**Endpoint:**
`GET /journals/{journal_id}`

### Path Parameters
| Parameter  | Type   | Required | Description                       |
| :--------- | :----- | :------- | :-------------------------------- |
| journal_id | string | Required | Unique identifier of the journal. |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/journals/460000000038001?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "success",
    "journal": {
        "journal_id": "460000000038001",
        "entry_number": "1",
        "reference_number": "7355",
        "notes": "Loan repayment",
        "currency_id": "460000000000097",
        "currency_code": "USD",
        "currency_symbol": "$",
        "exchange_rate": 1,
        "journal_date": "2013-09-04",
        "journal_type": "both",
        "vat_treatment": "string",
        "product_type": "string",
        "include_in_vat_return": true,
        "is_bas_adjustment": true,
        "line_items": [
            {
                "line_id": "460000000038005",
                "account_id": "460000000000361",
                "customer_id": "string",
                "customer_name": "string",
                "account_name": "Petty Cash",
                "description": "string",
                "debit_or_credit": "credit",
                "tax_exemption_id": "string",
                "tax_exemption_type": "string",
                "tax_exemption_code": "string",
                "tax_authority_id": "string",
                "tax_authority_name": "string",
                "tax_id": "string",
                "tax_name": "string",
                "tax_type": "tax",
                "tax_percentage": "string",
                "amount": 5000,
                "bcy_amount": 100,
                "acquisition_vat_id": "string",
                "acquisition_vat_name": "string",
                "acquisition_vat_percentage": "string",
                "acquisition_vat_amount": "string",
                "reverse_charge_vat_id": "string",
                "reverse_charge_vat_name": "string",
                "reverse_charge_vat_percentage": "string",
                "reverse_charge_vat_amount": "string",
                "tags": [
                    {
                        "is_tag_mandatory": false,
                        "tag_id": "460000000094001",
                        "tag_name": "Location",
                        "tag_option_id": "460000000048001",
                        "tag_option_name": "USA"
                    }
                ],
                "location_id": "460000000038080",
                "location_name": "string",
                "project_id": "460000000898001",
                "project_name": "Network Distribution"
            }
        ],
        "location_id": "460000000038080",
        "location_name": "string",
        "line_item_total": 5000,
        "total": 5000,
        "bcy_total": 100,
        "price_precision": 2,
        "taxes": [
            {
                "tax_name": "string",
                "tax_amount": 0.1,
                "debit_or_credit": "credit",
                "tax_account": true
            }
        ],
        "created_time": "2013-09-04T09:40:07+0530",
        "last_modified_time": "2013-09-05T17:13:31+0530",
        "status": "draft",
        "custom_fields": [
            {
                "customfield_id": "460000000098001",
                "value": "Normal"
            }
        ]
    }
}
```

---

## Delete a journal
Deletes the given journal.

`OAuth Scope : ZohoBooks.accountants.DELETE`

**Endpoint:**
`DELETE /journals/{journal_id}`

### Path Parameters
| Parameter  | Type   | Required | Description                       |
| :--------- | :----- | :------- | :-------------------------------- |
| journal_id | string | Required | Unique identifier of the journal. |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request DELETE \
  --url 'https://www.zohoapis.com/books/v3/journals/460000000038001?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "The selected journal entry has been deleted."
}
```

---

## Mark a journal as published
Mark a draft journal as published.

`OAuth Scope : ZohoBooks.accountants.CREATE`

**Endpoint:**
`POST /journals/{journal_id}/status/publish`

### Path Parameters
| Parameter  | Type   | Required | Description                       |
| :--------- | :----- | :------- | :-------------------------------- |
| journal_id | string | Required | Unique identifier of the journal. |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/journals/460000000038001/status/publish?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "Journal has been published."
}
```

---

## Add attachment to a journal
Attach a file to a journal.

`OAuth Scope : ZohoBooks.accountants.CREATE`

**Endpoint:**
`POST /journals/{journal_id}/attachment`

### Arguments
| Argument     | Type    | Required | Description                                                  |
| :----------- | :------ | :------- | :----------------------------------------------------------- |
| attachment   | binary  | Optional | The file that is to be added as an Attachment in the Journal |
| doc          | binary  | Optional | Document that is to be attached                              |
| totalFiles   | integer | Optional | Total number of files.                                       |
| document_ids | string  | Optional | ID's of the document                                         |

### Path Parameters
| Parameter  | Type   | Required | Description                       |
| :--------- | :----- | :------- | :-------------------------------- |
| journal_id | string | Required | Unique identifier of the journal. |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/journals/460000000038001/attachment?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "Your file has been successfully attached to the journal."
}
```

---

## Add comment
Add a comment for a journal.

`OAuth Scope : ZohoBooks.accountants.CREATE`

**Endpoint:**
`POST /journals/{journal_id}/comments`

### Arguments
| Argument    | Type   | Required | Description              |
| :---------- | :----- | :------- | :----------------------- |
| description | string | Optional | Description of a comment |

### Path Parameters
| Parameter  | Type   | Required | Description                       |
| :--------- | :----- | :------- | :-------------------------------- |
| journal_id | string | Required | Unique identifier of the journal. |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/journals/460000000038001/comments?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{"description":"Journal Created"}'
```

### Response Example
```json
{
    "code": 0,
    "message": "Journal comment has been added successfully.",
    "comment": [
        {
            "comment_id": "460000000048023",
            "description": "string",
            "commented_by_id": "460000000017003",
            "commented_by": "John",
            "comment_type": "system",
            "date": "string",
            "operation_type": "Added"
        },
        {...},
        {...}
    ]
}
```

---

## Delete a comment
Delete a jounral comment.

`OAuth Scope : ZohoBooks.accountants.DELETE`

**Endpoint:**
`DELETE /journals/{journal_id}/comments/{comment_id}`

### Path Parameters
| Parameter  | Type   | Required | Description                       |
| :--------- | :----- | :------- | :-------------------------------- |
| journal_id | string | Required | Unique identifier of the journal. |
| comment_id | string | Required | Unique identifier of the comment. |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request DELETE \
  --url 'https://www.zohoapis.com/books/v3/journals/460000000038001/comments/460000000048023?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "The selected journal comment entries have been deleted."
}
```