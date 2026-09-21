# Bank Accounts

In Zoho Books, you can track your transactions, have manual and automatic feeds imported for your bank and credit card accounts.

### Bank Accounts OpenAPI Document
[Download Bank Accounts OpenAPI Document](bank-accounts.yml)

## Bank Accounts Attributes

| Attribute                         | Type    | Description                                                |
| :-------------------------------- | :------ | :--------------------------------------------------------- |
| account_id                        | string  | ID of the Bank/Credit Card account                         |
| account_name                      | string  | Name of the account                                        |
| account_code                      | string  | Code of the Account                                        |
| currency_id                       | string  | ID of the Currency associated with the Account             |
| currency_code                     | string  | Code of the currency associated with the Bank Account      |
| currency_symbol                   | string  | Symbol of the Currency associated with the Account         |
| price_precision                   | integer | Precision of the Price Values                              |
| account_type                      | string  | Type of the account                                        |
| account_number                    | string  | Number associated with the Bank Account                    |
| uncategorized_transactions        | integer | Number of uncategorized transactions                       |
| total_unprinted_checks            | integer | Number of unprinted checks.                                |
| is_active                         | boolean | Check if Account is Active                                 |
| is_feeds_subscribed               | boolean | Check is feeds are subscribed                              |
| is_feeds_active                   | boolean | Check if feeds are active                                  |
| balance                           | double  | Balance present in the account                             |
| bank_balance                      | integer | Balance present in the Bank                                |
| bcy_balance                       | double  | Balance in Base Currency                                   |
| bank_name                         | string  | Name of the Bank                                           |
| routing_number                    | string  | Routing Number of the Account                              |
| is_primary_account                | boolean | Check if the Account is Primary Account in Zoho Books      |
| is_paypal_account                 | boolean | Check if the Account is Paypal Account                     |
| description                       | string  | Description of the Account                                 |
| refresh_status_code               | string  | Refresh Status Code of the Bank                            |
| feeds_last_refresh_date           | string  | Last Refreshed Date of the Feeds                           |
| service_id                        | string  | Service ID of the Account                                  |
| is_system_account                 | boolean | Check if the account is a system account                   |
| is_show_warning_for_feeds_refresh | boolean | Check if warning should be shown for refreshing Bank Feeds |

### Bank Accounts Object Example
```json
{
    "account_id": "460000000050127",
    "account_name": "Corporate Account",
    "account_code": "string",
    "currency_id": "460000000000097",
    "currency_code": "USD",
    "currency_symbol": "$",
    "price_precision": 2,
    "account_type": "bank",
    "account_number": "80000009823",
    "uncategorized_transactions": 0,
    "total_unprinted_checks": 0,
    "is_active": true,
    "is_feeds_subscribed": false,
    "is_feeds_active": false,
    "balance": 0,
    "bank_balance": 0,
    "bcy_balance": 0,
    "bank_name": "Xavier Bank",
    "routing_number": "123456789",
    "is_primary_account": false,
    "is_paypal_account": true,
    "description": "Salary details.",
    "refresh_status_code": "string",
    "feeds_last_refresh_date": "string",
    "service_id": "string",
    "is_system_account": false,
    "is_show_warning_for_feeds_refresh": false
}
```

---

## Create a bank account
Create a bank account or a credit card account for your organization.

`OAuth Scope : ZohoBooks.banking.CREATE`

### Arguments

| Argument             | Type    | Required     | Description                                                                            |
| :------------------- | :------ | :----------- | :------------------------------------------------------------------------------------- |
| account_name         | string  | **Required** | Name of the account                                                                    |
| account_type         | string  | **Required** | Type of the account                                                                    |
| account_number       | string  | Optional     | Number associated with the Bank Account                                                |
| account_code         | string  | Optional     | Code of the Account                                                                    |
| currency_id          | string  | Optional     | ID of the Currency associated with the Account                                         |
| currency_code        | string  | Optional     | Code of the currency associated with the Bank Account                                  |
| description          | string  | Optional     | Description of the Account                                                             |
| bank_name            | string  | Optional     | Name of the Bank                                                                       |
| routing_number       | string  | Optional     | Routing Number of the Account                                                          |
| is_primary_account   | boolean | Optional     | Check if the Account is Primary Account in Zoho Books                                  |
| is_paypal_account    | boolean | Optional     | Check if the Account is Paypal Account                                                 |
| paypal_type          | string  | Optional     | The type of Payment for the Paypal Account. Allowed Values : `standard` and `adaptive` |
| paypal_email_address | string  | Optional     | Email Address of the Paypal account.                                                   |

### Query Parameters

| Parameter       | Type   | Required     | Description            |
| :-------------- | :----- | :----------- | :--------------------- |
| organization_id | string | **Required** | ID of the organization |

### Request Example
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/bankaccounts?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{
    "account_name": "Corporate Account",
    "account_type": "bank",
    "account_number": "80000009823",
    "account_code": "string",
    "currency_id": "460000000000097",
    "currency_code": "USD",
    "description": "Salary details.",
    "bank_name": "Xavier Bank",
    "routing_number": "123456789",
    "is_primary_account": false,
    "is_paypal_account": true,
    "paypal_type": "string",
    "paypal_email_address": "johnsmith@zilliuminc.com"
}'
```

---

## List view of accounts
List all bank and credit card accounts for your organization.

`OAuth Scope : ZohoBooks.banking.READ`

### Query Parameters

| Parameter       | Type    | Required     | Description                                                                                                    |
| :-------------- | :------ | :----------- | :------------------------------------------------------------------------------------------------------------- |
| organization_id | string  | **Required** | ID of the organization                                                                                         |
| filter_by       | string  | Optional     | Filter the account by their status. Allowed Values: `Status.All`, `Status.Active` and `Status.Inactive`.       |
| sort_column     | string  | Optional     | Sort the values based on the allowed values. Allowed Values: `account_name`,`account_type` and `account_code`. |
| page            | integer | Optional     | Page number to be fetched. Default value is 1.                                                                 |
| per_page        | integer | Optional     | Number of records to be fetched per page. Default value is 200.                                                |

### Request Example
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/bankaccounts?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Update bank account
Modify the account that was created.

`OAuth Scope : ZohoBooks.banking.UPDATE`

### Arguments

| Argument             | Type    | Required     | Description                                                                            |
| :------------------- | :------ | :----------- | :------------------------------------------------------------------------------------- |
| account_name         | string  | **Required** | Name of the account                                                                    |
| account_type         | string  | **Required** | Type of the account                                                                    |
| account_number       | string  | Optional     | Number associated with the Bank Account                                                |
| account_code         | string  | Optional     | Code of the Account                                                                    |
| currency_id          | string  | Optional     | ID of the Currency associated with the Account                                         |
| currency_code        | string  | Optional     | Code of the currency associated with the Bank Account                                  |
| description          | string  | Optional     | Description of the Account                                                             |
| bank_name            | string  | Optional     | Name of the Bank                                                                       |
| routing_number       | string  | Optional     | Routing Number of the Account                                                          |
| is_primary_account   | boolean | Optional     | Check if the Account is Primary Account in Zoho Books                                  |
| is_paypal_account    | boolean | Optional     | Check if the Account is Paypal Account                                                 |
| paypal_type          | string  | Optional     | The type of Payment for the Paypal Account. Allowed Values : `standard` and `adaptive` |
| paypal_email_address | string  | Optional     | Email Address of the Paypal account.                                                   |

### Path Parameters

| Parameter  | Type   | Required     | Description                            |
| :--------- | :----- | :----------- | :------------------------------------- |
| account_id | string | **Required** | Unique identifier of the bank account. |

### Query Parameters

| Parameter       | Type   | Required     | Description            |
| :-------------- | :----- | :----------- | :--------------------- |
| organization_id | string | **Required** | ID of the organization |

### Request Example
```bash
curl --request PUT \
  --url 'https://www.zohoapis.com/books/v3/bankaccounts/460000000050127?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{
    "account_name": "Corporate Account",
    "account_type": "bank",
    "account_number": "80000009823",
    "account_code": "string",
    "currency_id": "460000000000097",
    "currency_code": "USD",
    "description": "Salary details.",
    "bank_name": "Xavier Bank",
    "routing_number": "123456789",
    "is_primary_account": false,
    "is_paypal_account": true,
    "paypal_type": "string",
    "paypal_email_address": "johnsmith@zilliuminc.com"
}'
```

---

## Get account details
Get a detailed look of the account specified.

`OAuth Scope : ZohoBooks.banking.READ`

### Path Parameters

| Parameter  | Type   | Required     | Description                            |
| :--------- | :----- | :----------- | :------------------------------------- |
| account_id | string | **Required** | Unique identifier of the bank account. |

### Query Parameters

| Parameter       | Type   | Required     | Description            |
| :-------------- | :----- | :----------- | :--------------------- |
| organization_id | string | **Required** | ID of the organization |

### Request Example
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/bankaccounts/460000000050127?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Delete an account
Delete a bank account from your organization.

`OAuth Scope : ZohoBooks.banking.DELETE`

### Path Parameters

| Parameter  | Type   | Required     | Description                            |
| :--------- | :----- | :----------- | :------------------------------------- |
| account_id | string | **Required** | Unique identifier of the bank account. |

### Query Parameters

| Parameter       | Type   | Required     | Description            |
| :-------------- | :----- | :----------- | :--------------------- |
| organization_id | string | **Required** | ID of the organization |

### Request Example
```bash
curl --request DELETE \
  --url 'https://www.zohoapis.com/books/v3/bankaccounts/460000000050127?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Deactivate account
Make an account inactive.

`OAuth Scope : ZohoBooks.banking.CREATE`

### Path Parameters

| Parameter  | Type   | Required     | Description                            |
| :--------- | :----- | :----------- | :------------------------------------- |
| account_id | string | **Required** | Unique identifier of the bank account. |

### Query Parameters

| Parameter       | Type   | Required     | Description            |
| :-------------- | :----- | :----------- | :--------------------- |
| organization_id | string | **Required** | ID of the organization |

### Request Example
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/bankaccounts/460000000050127/inactive?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Activate account
Make an account active.

`OAuth Scope : ZohoBooks.banking.CREATE`

### Path Parameters

| Parameter  | Type   | Required     | Description                            |
| :--------- | :----- | :----------- | :------------------------------------- |
| account_id | string | **Required** | Unique identifier of the bank account. |

### Query Parameters

| Parameter       | Type   | Required     | Description            |
| :-------------- | :----- | :----------- | :--------------------- |
| organization_id | string | **Required** | ID of the organization |

### Request Example
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/bankaccounts/460000000050127/active?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Import a Bank/Credit Card Statement
Import your bank/credit card feeds into your account.

`OAuth Scope : ZohoBooks.banking.CREATE`

### Arguments

| Argument                      | Type   | Required     | Description                                   |
| :---------------------------- | :----- | :----------- | :-------------------------------------------- |
| account_id                    | string | **Required** | ID of the Bank/Credit Card account            |
| start_date                    | string | Optional     | Least date in the transaction set             |
| end_date                      | string | Optional     | Greatest date in the transaction set          |
| transactions                  | array  | **Required** | Array of transactions to import               |
| transactions.transaction_id   | string | Optional     | Unique ID that is specific to the transaction |
| transactions.date             | string | **Required** | Date of the transaction                       |
| transactions.debit_or_credit  | string | **Required** | Indicates if transaction is Debit or Credit   |
| transactions.amount           | double | **Required** | Amount involved in the transaction            |
| transactions.payee            | string | Optional     | Payee involved in the transaction             |
| transactions.description      | string | Optional     | Transaction description                       |
| transactions.reference_number | string | Optional     | Reference Number of the transaction           |

### Query Parameters

| Parameter       | Type   | Required     | Description            |
| :-------------- | :----- | :----------- | :--------------------- |
| organization_id | string | **Required** | ID of the organization |

### Request Example
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/bankstatements?organization_id=10234695' \
  --header 'content-type: application/json' \
  --data '{
    "account_id": "460000000050127",
    "start_date": "2019-01-01",
    "end_date": "2019-01-02",
    "transactions": [
        {
            "transaction_id": "XXXXSCD01",
            "date": "2012-01-14",
            "debit_or_credit": "credit",
            "amount": 7500,
            "payee": "Bowman and Co",
            "description": "Electronics purchase",
            "reference_number": "Ref-2134"
        }
    ]
}'
```

---

## Get last imported statement
Get the details of previously imported statement for the account.

`OAuth Scope : ZohoBooks.banking.READ`

### Path Parameters

| Parameter  | Type   | Required     | Description                            |
| :--------- | :----- | :----------- | :------------------------------------- |
| account_id | string | **Required** | Unique identifier of the bank account. |

### Query Parameters

| Parameter       | Type   | Required     | Description            |
| :-------------- | :----- | :----------- | :--------------------- |
| organization_id | string | **Required** | ID of the organization |

### Request Example
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/bankaccounts/460000000050127/statement/lastimported?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Delete last imported statement
Delete the statement that was previously imported.

`OAuth Scope : ZohoBooks.banking.DELETE`

### Path Parameters

| Parameter    | Type   | Required     | Description                              |
| :----------- | :----- | :----------- | :--------------------------------------- |
| account_id   | string | **Required** | Unique identifier of the bank account.   |
| statement_id | string | **Required** | Unique identifier of the bank statement. |

### Query Parameters

| Parameter       | Type   | Required     | Description            |
| :-------------- | :----- | :----------- | :--------------------- |
| organization_id | string | **Required** | ID of the organization |

### Request Example
```bash
curl --request DELETE \
  --url 'https://www.zohoapis.com/books/v3/bankaccounts/460000000050127/statement/460000000049013?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```