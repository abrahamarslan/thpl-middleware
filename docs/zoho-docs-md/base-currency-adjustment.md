Here is the documentation for **Base Currency Adjustment** converted to Markdown format.

# Base Currency Adjustment

In Zoho Books you can have an insight on the profit or loss incurred due to the change in exchange rates and also can apply the changes to open transactions.

### End Points

| Method     | URL                                                     | Description                                       |
| :--------- | :------------------------------------------------------ | :------------------------------------------------ |
| **POST**   | `/basecurrencyadjustment`                               | Create a base currency adjustment                 |
| **GET**    | `/basecurrencyadjustment`                               | List base currency adjustment                     |
| **GET**    | `/basecurrencyadjustment/{base_currency_adjustment_id}` | Get a base currency adjustment                    |
| **DELETE** | `/basecurrencyadjustment/{base_currency_adjustment_id}` | Delete a base currency adjustment                 |
| **GET**    | `/basecurrencyadjustment/accounts`                      | List account details for base currency adjustment |

---

## Attributes

| Attribute                     | Type   | Description                                          |
| :---------------------------- | :----- | :--------------------------------------------------- |
| `base_currency_adjustment_id` | string | ID of the Base Currency Adjustment                   |
| `adjustment_date`             | string | Date of adjustment.                                  |
| `exchange_rate`               | double | Exchange rate of the currency.                       |
| `currency_id`                 | string | ID of currency for which we need to post adjustment. |
| `accounts`                    | array  | List of accounts involved. See sub-attributes below. |
| `notes`                       | string | Notes for base currency adjustment.                  |
| `currency_code`               | string | Currency Code involved in the Adjustment.            |

**Sub-Attributes for `accounts`:**

| Attribute          | Type    | Description                                     |
| :----------------- | :------ | :---------------------------------------------- |
| `account_id`       | string  | ID of the Account in Base Currency Adjustment   |
| `account_name`     | string  | Name of the Account in Base Currency Adjustment |
| `bcy_balance`      | double  | Balance in Base Currency of the Organisation    |
| `fcy_balance`      | double  | Balance in Foreign Currency                     |
| `adjusted_balance` | double  | Adjusted Balance                                |
| `gain_or_loss`     | double  | Amount in Total Gain/Loss                       |
| `gl_specific_type` | integer | GL Specific Type of the Account Involved        |

### Attribute Example

```json
{
    "base_currency_adjustment_id": "460000000039001",
    "adjustment_date": "2013-09-05",
    "exchange_rate": 1,
    "currency_id": "460000000000109",
    "accounts": [
        {
            "account_id": "460000000000364",
            "account_name": "Accounts Receivable",
            "bcy_balance": 171.47,
            "fcy_balance": 139.41,
            "adjusted_balance": 209.12,
            "gain_or_loss": 37.65,
            "gl_specific_type": 5
        }
    ],
    "notes": "Base Currency Adjustment against EUR",
    "currency_code": "EUR"
}
```

---

## Create a base currency adjustment

Creates a base currency adjustment for the given information.

`OAuth Scope : ZohoBooks.accountants.CREATE`

### Arguments

| Argument          | Type   | Required | Description                                          |
| :---------------- | :----- | :------- | :--------------------------------------------------- |
| `currency_id`     | string | Required | ID of currency for which we need to post adjustment. |
| `adjustment_date` | string | Required | Date of adjustment.                                  |
| `exchange_rate`   | double | Required | Exchange rate of the currency.                       |
| `notes`           | string | Required | Notes for base currency adjustment.                  |

### Query Parameters

| Parameter         | Type   | Required | Description                                                               |
| :---------------- | :----- | :------- | :------------------------------------------------------------------------ |
| `organization_id` | string | Required | ID of the organization                                                    |
| `account_ids`     | string | Required | ID of the accounts for which base currency adjustments need to be posted. |

### Request Example

```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/basecurrencyadjustment?organization_id=10234695&account_ids=460000000000364' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{"currency_id":"460000000000109","adjustment_date":"2013-09-05","exchange_rate":1,"notes":"Base Currency Adjustment against EUR"}'
```

### Response Example

```json
{
    "code": 0,
    "message": "The adjustment has been made. The account balances will now reflect the adjustment.",
    "data": {
        "base_currency_adjustment_id": "460000000039001",
        "adjustment_date": "2013-09-05",
        "exchange_rate": 1,
        "currency_id": "460000000000109",
        "accounts": [
            {
                "account_id": "460000000000364",
                "account_name": "Accounts Receivable",
                "bcy_balance": 171.47,
                "fcy_balance": 139.41,
                "adjusted_balance": 209.12,
                "gain_or_loss": 37.65,
                "gl_specific_type": 5
            }
        ],
        "notes": "Base Currency Adjustment against EUR",
        "currency_code": "EUR"
    }
}
```

---

## List base currency adjustment

Lists base currency adjustment.

`OAuth Scope : ZohoBooks.accountants.READ`

### Query Parameters

| Parameter            | Type    | Required | Description                                                                                                                                                |
| :------------------- | :------ | :------- | :--------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `organization_id`    | string  | Required | ID of the organization                                                                                                                                     |
| `filter_by`          | string  | Optional | Filter base currency adjustment list. Allowed Values: `Date.All`, `Date.Today`, `Date.ThisWeek`, `Date.ThisMonth`, `Date.ThisQuarter` and `Date.ThisYear`. |
| `sort_column`        | string  | Optional | Sort base currency adjustment list. Allowed Values: `adjustment_date`, `exchange_rate`, `currency_code`, `debit_or_credit` and `gain_or_loss`.             |
| `last_modified_time` | string  | Optional | Search using the Last Modified Time of the Base Currency Adjustment                                                                                        |
| `page`               | integer | Optional | Page number to be fetched. Default value is 1.                                                                                                             |
| `per_page`           | integer | Optional | Number of records to be fetched per page. Default value is 200.                                                                                            |

### Request Example

```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/basecurrencyadjustment?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "success",
    "base_currency_adjustments": [
        {
            "base_currency_adjustment_id": "460000000039001",
            "adjustment_date": "2013-09-05",
            "exchange_rate": 1,
            "currency_id": "460000000000109",
            "currency_code": "EUR",
            "notes": "Base Currency Adjustment against EUR",
            "gain_or_loss": 37.65
        },
        {...},
        {...}
    ]
}
```

---

## Get a base currency adjustment

Get the base currency adjustment details.

`OAuth Scope : ZohoBooks.accountants.READ`

### Path Parameters

| Parameter                     | Type   | Required | Description                                        |
| :---------------------------- | :----- | :------- | :------------------------------------------------- |
| `base_currency_adjustment_id` | string | Required | Unique identifier of the base currency adjustment. |

### Query Parameters

| Parameter         | Type   | Required | Description            |
| :---------------- | :----- | :------- | :--------------------- |
| `organization_id` | string | Required | ID of the organization |

### Request Example

```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/basecurrencyadjustment/460000000039001?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "success",
    "data": {
        "base_currency_adjustment_id": "460000000039001",
        "adjustment_date": "2013-09-05",
        "exchange_rate": 1,
        "currency_id": "460000000000109",
        "accounts": [
            {
                "account_id": "460000000000364",
                "account_name": "Accounts Receivable",
                "bcy_balance": 171.47,
                "fcy_balance": 139.41,
                "adjusted_balance": 209.12,
                "gain_or_loss": 37.65,
                "gl_specific_type": 5
            }
        ],
        "notes": "Base Currency Adjustment against EUR",
        "currency_code": "EUR"
    }
}
```

---

## Delete a base currency adjustment

Deletes the base currency adjustment.

`OAuth Scope : ZohoBooks.accountants.DELETE`

### Path Parameters

| Parameter                     | Type   | Required | Description                                        |
| :---------------------------- | :----- | :------- | :------------------------------------------------- |
| `base_currency_adjustment_id` | string | Required | Unique identifier of the base currency adjustment. |

### Query Parameters

| Parameter         | Type   | Required | Description            |
| :---------------- | :----- | :------- | :--------------------- |
| `organization_id` | string | Required | ID of the organization |

### Request Example

```bash
curl --request DELETE \
  --url 'https://www.zohoapis.com/books/v3/basecurrencyadjustment/460000000039001?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "The selected base currency adjustment has been deleted."
}
```

---

## List account details for base currency adjustment

List of accounts having transaction with effect to the given exchange rate.

`OAuth Scope : ZohoBooks.accountants.READ`

### Query Parameters

| Parameter         | Type   | Required | Description                                          |
| :---------------- | :----- | :------- | :--------------------------------------------------- |
| `organization_id` | string | Required | ID of the organization                               |
| `currency_id`     | string | Required | ID of currency for which we need to post adjustment. |
| `adjustment_date` | string | Required | Date of adjustment.                                  |
| `exchange_rate`   | double | Required | Exchange rate of the currency.                       |
| `notes`           | string | Required | Notes for base currency adjustment.                  |

### Request Example

```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/basecurrencyadjustment/accounts?organization_id=10234695&currency_id=460000000000109&adjustment_date=2013-09-05&exchange_rate=1&notes=Base%20Currency%20Adjustment%20against%20EUR' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "success",
    "data": {
        "adjustment_date": "2013-09-05",
        "exchange_rate": 1,
        "currency_id": "460000000000109",
        "accounts": [
            {
                "account_id": "460000000000364",
                "account_name": "Accounts Receivable",
                "bcy_balance": 171.47,
                "fcy_balance": 139.41,
                "adjusted_balance": 209.12,
                "gain_or_loss": 37.65,
                "gl_specific_type": 5
            }
        ],
        "notes": "Base Currency Adjustment against EUR",
        "currency_code": "EUR"
    }
}
```