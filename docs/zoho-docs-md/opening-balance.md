# Opening Balance

While migrating from existing accounting software to Zoho Books, you need to ensure that the transition is flawless, that all prevailing data such as journal entries, records, expense and income statements etc, has been recorded and continuity in financial statements is maintained. To ensure this, an opening balance needs to be calculated.

### Attribute

| Attribute                | Data Type | Description                                                                                      |
| :----------------------- | :-------- | :----------------------------------------------------------------------------------------------- |
| opening_balance_id       | string    | ID of opening balance.                                                                           |
| date                     | string    | Date on which the opening balance needs to be recorded. [yyyy-MM-dd]                             |
| price_precision          | integer   | Price Precision of the Values                                                                    |
| accounts                 | array     | List of accounts involved in the opening balance.                                                |
| accounts.acount_split_id | string    | ID of split account that you want to update.                                                     |
| accounts.account_id      | string    | ID of account for which you need to record opening balance.                                      |
| accounts.account_name    | string    | Name of the account.                                                                             |
| accounts.debit_or_credit | string    | Debit or Credit for which the amount needs to be recorded. Allowed Values: `debit` and `credit`. |
| accounts.exchange_rate   | double    | Exchange rate for the foreign currencies if involved.                                            |
| accounts.currency_id     | string    | ID of account currency.                                                                          |
| accounts.currency_code   | string    | Currency code of the account.                                                                    |
| accounts.bcy_amount      | double    | Amount in Base Currency of the Organisation                                                      |
| accounts.amount          | double    | Amount in the currency of the account.                                                           |
| accounts.location_id     | string    | Location ID                                                                                      |
| accounts.location_name   | string    | Name of the location.                                                                            |
| total                    | integer   | Total Amount from the Opening Balance                                                            |

### Example

```json
{
    "opening_balance_id": "460000000050041",
    "date": "2013-10-01",
    "price_precision": 2,
    "accounts": [
        {
            "acount_split_id": "460000000050045",
            "account_id": "460000000000358",
            "account_name": "Undeposited Funds",
            "debit_or_credit": "debit",
            "exchange_rate": 1,
            "currency_id": "460000000000097",
            "currency_code": "USD",
            "bcy_amount": 2000,
            "amount": 2000,
            "location_id": "460000000038080",
            "location_name": "string"
        }
    ],
    "total": 10000
}
```

---

## Create opening balance

Creates opening balance with the given information.

`OAuth Scope : ZohoBooks.settings.CREATE`

### Arguments

| Attribute                | Data Type | Description                                                                                                     |
| :----------------------- | :-------- | :-------------------------------------------------------------------------------------------------------------- |
| date                     | string    | **(Required)** Date on which the opening balance needs to be recorded. [yyyy-MM-dd]                             |
| accounts                 | array     |                                                                                                                 |
| accounts.account_id      | string    | ID of account for which you need to record opening balance.                                                     |
| accounts.debit_or_credit | string    | **(Required)** Debit or Credit for which the amount needs to be recorded. Allowed Values: `debit` and `credit`. |
| accounts.exchange_rate   | double    | Exchange rate for the foreign currencies if involved.                                                           |
| accounts.currency_id     | string    | ID of account currency.                                                                                         |
| accounts.amount          | double    | Amount involved.                                                                                                |
| accounts.location_id     | string    | Location ID                                                                                                     |

### Query Parameters

| Attribute       | Data Type | Description                           |
| :-------------- | :-------- | :------------------------------------ |
| organization_id | string    | **(Required)** ID of the organization |

### Request Example

```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/settings/openingbalances?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{
    "date": "2013-10-01",
    "accounts": [
        {
            "account_id": "460000000000358",
            "debit_or_credit": "debit",
            "exchange_rate": 1,
            "currency_id": "460000000000097",
            "amount": 2000,
            "location_id": "460000000038080"
        }
    ]
}'
```

### Response Example

```json
{
    "code": 0,
    "message": "The opening balances are saved!",
    "opening_balance": {
        "opening_balance_id": "460000000050041",
        "date": "2013-10-01",
        "price_precision": 2,
        "accounts": [
            {
                "acount_split_id": "460000000050045",
                "account_id": "460000000000358",
                "account_name": "Undeposited Funds",
                "debit_or_credit": "debit",
                "exchange_rate": 1,
                "currency_id": "460000000000097",
                "currency_code": "USD",
                "bcy_amount": 2000,
                "amount": 2000,
                "location_id": "460000000038080",
                "location_name": "string"
            }
        ],
        "total": 10000
    }
}
```

---

## Update opening balance

Updates the existing opening balance information.

`OAuth Scope : ZohoBooks.settings.UPDATE`

### Arguments

| Attribute                | Data Type | Description                                                                                      |
| :----------------------- | :-------- | :----------------------------------------------------------------------------------------------- |
| date                     | string    | Date on which the opening balance needs to be recorded. [yyyy-MM-dd]                             |
| accounts                 | array     |                                                                                                  |
| accounts.acount_split_id | string    | ID of split account that you want to update.                                                     |
| accounts.account_id      | string    | ID of account for which you need to record opening balance.                                      |
| accounts.account_name    | string    | Name of the account.                                                                             |
| accounts.debit_or_credit | string    | Debit or Credit for which the amount needs to be recorded. Allowed Values: `debit` and `credit`. |
| accounts.exchange_rate   | double    | Exchange rate for the foreign currencies if involved.                                            |
| accounts.currency_id     | string    | ID of account currency.                                                                          |
| accounts.currency_code   | string    | Currency Code.                                                                                   |
| accounts.bcy_amount      | double    | Amount in Base Currency of the Organisation                                                      |
| accounts.amount          | double    | Amount involved.                                                                                 |
| accounts.location_id     | string    | Location ID                                                                                      |
| accounts.location_name   | string    | Name of the location.                                                                            |
| opening_balance_id       | string    | **(Required)** ID of opening balance.                                                            |

### Query Parameters

| Attribute       | Data Type | Description                           |
| :-------------- | :-------- | :------------------------------------ |
| organization_id | string    | **(Required)** ID of the organization |

### Request Example

```bash
curl --request PUT \
  --url 'https://www.zohoapis.com/books/v3/settings/openingbalances?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{
    "date": "2013-10-01",
    "accounts": [
        {
            "acount_split_id": "460000000050045",
            "account_id": "460000000000358",
            "account_name": "Undeposited Funds",
            "debit_or_credit": "debit",
            "exchange_rate": 1,
            "currency_id": "460000000000097",
            "currency_code": "USD",
            "bcy_amount": 2000,
            "amount": 2000,
            "location_id": "460000000038080",
            "location_name": "string"
        }
    ],
    "opening_balance_id": "460000000050041"
}'
```

### Response Example

```json
{
    "code": 0,
    "message": "The opening balances are saved!",
    "opening_balance": {
        "opening_balance_id": "460000000050041",
        "date": "2013-10-01",
        "price_precision": 2,
        "accounts": [
            {
                "acount_split_id": "460000000050045",
                "account_id": "460000000000358",
                "account_name": "Undeposited Funds",
                "debit_or_credit": "debit",
                "exchange_rate": 1,
                "currency_id": "460000000000097",
                "currency_code": "USD",
                "bcy_amount": 2000,
                "amount": 2000,
                "location_id": "460000000038080",
                "location_name": "string"
            }
        ],
        "total": 10000
    }
}
```

---

## Get opening balance

Get opening balance.

`OAuth Scope : ZohoBooks.settings.READ`

### Query Parameters

| Attribute       | Data Type | Description                           |
| :-------------- | :-------- | :------------------------------------ |
| organization_id | string    | **(Required)** ID of the organization |

### Request Example

```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/settings/openingbalances?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "success",
    "opening_balance": {
        "opening_balance_id": "460000000050041",
        "date": "2013-10-01",
        "price_precision": 2,
        "accounts": [
            {
                "acount_split_id": "460000000050045",
                "account_id": "460000000000358",
                "account_name": "Undeposited Funds",
                "debit_or_credit": "debit",
                "exchange_rate": 1,
                "currency_id": "460000000000097",
                "currency_code": "USD",
                "bcy_amount": 2000,
                "amount": 2000,
                "location_id": "460000000038080",
                "location_name": "string"
            }
        ],
        "total": 10000
    }
}
```

---

## Delete opening balance

Delete the entered opening balance.

`OAuth Scope : ZohoBooks.settings.DELETE`

### Query Parameters

| Attribute       | Data Type | Description                           |
| :-------------- | :-------- | :------------------------------------ |
| organization_id | string    | **(Required)** ID of the organization |

### Request Example

```bash
curl --request DELETE \
  --url 'https://www.zohoapis.com/books/v3/settings/openingbalances?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "The entered opening balance has been deleted."
}
```