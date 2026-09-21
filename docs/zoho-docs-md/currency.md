# Currency

In case your organization sells products or provides services to customer from different countries, you can add those currencies and exchange rates you deal with, to your Zoho Books account.

### End Points

| Method     | URL                                                                   | Description             |
| :--------- | :-------------------------------------------------------------------- | :---------------------- |
| **POST**   | `/settings/currencies`                                                | Create a Currency       |
| **GET**    | `/settings/currencies`                                                | List Currencies         |
| **PUT**    | `/settings/currencies/{currency_id}`                                  | Update a Currency       |
| **GET**    | `/settings/currencies/{currency_id}`                                  | Get a Currency          |
| **DELETE** | `/settings/currencies/{currency_id}`                                  | Delete a currency       |
| **POST**   | `/settings/currencies/{currency_id}/exchangerates`                    | Create an exchange rate |
| **GET**    | `/settings/currencies/{currency_id}/exchangerates`                    | List exchange rates     |
| **PUT**    | `/settings/currencies/{currency_id}/exchangerates/{exchange_rate_id}` | Update an exchange rate |
| **GET**    | `/settings/currencies/{currency_id}/exchangerates/{exchange_rate_id}` | Get an exchange rate.   |
| **DELETE** | `/settings/currencies/{currency_id}/exchangerates/{exchange_rate_id}` | Delete an exchage rate  |

---

## Attributes

| Attribute          | Type    | Description                                                |
| :----------------- | :------ | :--------------------------------------------------------- |
| `currency_id`      | string  | A unique ID for the currency.                              |
| `currency_code`    | string  | A unique standard code for the currency. Max-len [100]     |
| `currency_name`    | string  | The name for the currency.                                 |
| `currency_symbol`  | string  | A unique symbol for the currency. Max-len [4]              |
| `price_precision`  | integer | The precision for the price                                |
| `currency_format`  | string  | The format for the currency to be displayed. Max-len [100] |
| `is_base_currency` | boolean | Is it the base currency of the organization.               |

---

## Create a Currency

Create a currency for transaction.

`OAuth Scope : ZohoBooks.settings.CREATE`

### Arguments

| Argument          | Type    | Required | Description                                                |
| :---------------- | :------ | :------- | :--------------------------------------------------------- |
| `currency_code`   | string  | Required | A unique standard code for the currency. Max-len [100]     |
| `currency_symbol` | string  | Optional | A unique symbol for the currency. Max-len [4]              |
| `price_precision` | integer | Optional | The precision for the price                                |
| `currency_format` | string  | Required | The format for the currency to be displayed. Max-len [100] |

### Query Parameters

| Parameter         | Type   | Required | Description            |
| :---------------- | :----- | :------- | :--------------------- |
| `organization_id` | string | Required | ID of the organization |

### Request Example

```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/settings/currencies?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{"currency_code":"AUD","currency_symbol":"$","price_precision":2,"currency_format":"1,234,567.89"}'
```

### Response Example

```json
{
    "code": 0,
    "message": "The currency has been added.",
    "currency": {
        "currency_id": "982000000004012",
        "currency_code": "AUD",
        "currency_name": "AUD- Australian Dollar",
        "currency_symbol": "$",
        "price_precision": 2,
        "currency_format": "1,234,567.89",
        "is_base_currency": false
    }
}
```

---

## List Currencies

Get list of currencies configured.

`OAuth Scope : ZohoBooks.settings.READ`

### Query Parameters

| Parameter         | Type    | Required | Description                                                                                 |
| :---------------- | :------ | :------- | :------------------------------------------------------------------------------------------ |
| `organization_id` | string  | Required | ID of the organization                                                                      |
| `filter_by`       | string  | Optional | Filter currencies excluding base currency. Allowed Values: `Currencies.ExcludeBaseCurrency` |
| `page`            | integer | Optional | Page number to be fetched. Default value is 1.                                              |
| `per_page`        | integer | Optional | Number of records to be fetched per page. Default value is 200.                             |

### Request Example

```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/settings/currencies?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "success",
    "currencies": [
        {
            "currency_id": "982000000004012",
            "currency_code": "AUD",
            "currency_name": "AUD- Australian Dollar",
            "currency_symbol": "$",
            "price_precision": 2,
            "currency_format": "1,234,567.89",
            "is_base_currency": false,
            "exchange_rate": 1,
            "effective_date": "2013-09-04"
        },
        {...},
        {...}
    ]
}
```

---

## Update a Currency

Update the details of a currency.

`OAuth Scope : ZohoBooks.settings.UPDATE`

### Arguments

| Argument          | Type    | Required | Description                                                |
| :---------------- | :------ | :------- | :--------------------------------------------------------- |
| `currency_code`   | string  | Required | A unique standard code for the currency. Max-len [100]     |
| `currency_symbol` | string  | Optional | A unique symbol for the currency. Max-len [4]              |
| `price_precision` | integer | Optional | The precision for the price                                |
| `currency_format` | string  | Required | The format for the currency to be displayed. Max-len [100] |

### Path Parameters

| Parameter     | Type   | Required | Description                        |
| :------------ | :----- | :------- | :--------------------------------- |
| `currency_id` | string | Required | Unique identifier of the currency. |

### Query Parameters

| Parameter         | Type   | Required | Description            |
| :---------------- | :----- | :------- | :--------------------- |
| `organization_id` | string | Required | ID of the organization |

### Request Example

```bash
curl --request PUT \
  --url 'https://www.zohoapis.com/books/v3/settings/currencies/982000000004012?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{"currency_code":"AUD","currency_symbol":"$","price_precision":2,"currency_format":"1,234,567.89"}'
```

### Response Example

```json
{
    "code": 0,
    "message": "Currency information has been saved.",
    "currency": {
        "currency_id": "982000000004012",
        "currency_code": "AUD",
        "currency_name": "AUD- Australian Dollar",
        "currency_symbol": "$",
        "price_precision": 2,
        "currency_format": "1,234,567.89",
        "is_base_currency": false
    }
}
```

---

## Get a Currency

Get the details of a currency.

`OAuth Scope : ZohoBooks.settings.READ`

### Path Parameters

| Parameter     | Type   | Required | Description                        |
| :------------ | :----- | :------- | :--------------------------------- |
| `currency_id` | string | Required | Unique identifier of the currency. |

### Query Parameters

| Parameter         | Type   | Required | Description            |
| :---------------- | :----- | :------- | :--------------------- |
| `organization_id` | string | Required | ID of the organization |

### Request Example

```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/settings/currencies/982000000004012?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "success",
    "currency": {
        "currency_id": "982000000004012",
        "currency_code": "AUD",
        "currency_name": "AUD- Australian Dollar",
        "currency_symbol": "$",
        "price_precision": 2,
        "currency_format": "1,234,567.89",
        "is_base_currency": false
    }
}
```

---

## Delete a currency

Delete a currency. Currency that is associated to transactions cannot be deleted.

`OAuth Scope : ZohoBooks.settings.DELETE`

### Path Parameters

| Parameter     | Type   | Required | Description                        |
| :------------ | :----- | :------- | :--------------------------------- |
| `currency_id` | string | Required | Unique identifier of the currency. |

### Query Parameters

| Parameter         | Type   | Required | Description            |
| :---------------- | :----- | :------- | :--------------------- |
| `organization_id` | string | Required | ID of the organization |

### Request Example

```bash
curl --request DELETE \
  --url 'https://www.zohoapis.com/books/v3/settings/currencies/982000000004012?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "The currency has been deleted."
}
```

---

## Create an exchange rate

Create an exchange rate for the specified currency.

`OAuth Scope : ZohoBooks.settings.CREATE`

### Arguments

| Argument         | Type   | Required | Description                                                      |
| :--------------- | :----- | :------- | :--------------------------------------------------------------- |
| `effective_date` | string | Optional | Date which the exchange rate is applicable for the currency.     |
| `rate`           | double | Optional | Rate of exchange for the currency with respect to base currency. |

### Path Parameters

| Parameter     | Type   | Required | Description                        |
| :------------ | :----- | :------- | :--------------------------------- |
| `currency_id` | string | Required | Unique identifier of the currency. |

### Query Parameters

| Parameter         | Type   | Required | Description            |
| :---------------- | :----- | :------- | :--------------------- |
| `organization_id` | string | Required | ID of the organization |

### Request Example

```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/settings/currencies/982000000004012/exchangerates?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{"effective_date":"2013-09-04","rate":1.23}'
```

### Response Example

```json
{
    "code": 0,
    "message": "The exchange rate has been added.",
    "exchange_rate": 1
}
```

---

## List exchange rates

List of exchange rates configured for the currency.

`OAuth Scope : ZohoBooks.settings.READ`

### Path Parameters

| Parameter     | Type   | Required | Description                        |
| :------------ | :----- | :------- | :--------------------------------- |
| `currency_id` | string | Required | Unique identifier of the currency. |

### Query Parameters

| Parameter         | Type    | Required | Description                                                                                                                                 |
| :---------------- | :------ | :------- | :------------------------------------------------------------------------------------------------------------------------------------------ |
| `organization_id` | string  | Required | ID of the organization                                                                                                                      |
| `from_date`       | string  | Optional | Returns the exchange rate details from the given date or from previous closest match in the absence of the exchange rate on the given date. |
| `is_current_date` | boolean | Optional | To return the exchange rate only if available for current date.                                                                             |
| `sort_column`     | string  | Optional | Sorts the exchange rate according to this column. Allowed Values : `effective_date`                                                         |

### Request Example

```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/settings/currencies/982000000004012/exchangerates?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "success",
    "exchange_rates": [
        {
            "exchange_rate_id": "460000000038035",
            "currency_id": "982000000004012",
            "currency_code": "AUD",
            "effective_date": "2013-09-04",
            "rate": 1.23
        },
        {...},
        {...}
    ]
}
```

---

## Update an exchange rate

Update the details of exchange rate for a currency.

`OAuth Scope : ZohoBooks.settings.UPDATE`

### Arguments

| Argument         | Type   | Required | Description                                                      |
| :--------------- | :----- | :------- | :--------------------------------------------------------------- |
| `effective_date` | string | Optional | Date which the exchange rate is applicable for the currency.     |
| `rate`           | double | Optional | Rate of exchange for the currency with respect to base currency. |

### Path Parameters

| Parameter          | Type   | Required | Description                             |
| :----------------- | :----- | :------- | :-------------------------------------- |
| `currency_id`      | string | Required | Unique identifier of the currency.      |
| `exchange_rate_id` | string | Required | Unique identifier of the exchange rate. |

### Query Parameters

| Parameter         | Type   | Required | Description            |
| :---------------- | :----- | :------- | :--------------------- |
| `organization_id` | string | Required | ID of the organization |

### Request Example

```bash
curl --request PUT \
  --url 'https://www.zohoapis.com/books/v3/settings/currencies/982000000004012/exchangerates/460000000038035?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{"effective_date":"2013-09-04","rate":1.23}'
```

### Response Example

```json
{
    "code": 0,
    "message": "The exchange rate has been updated."
}
```

---

## Get an exchange rate.

Get the details of an exchange rate that has been asscoiated to the currency.

`OAuth Scope : ZohoBooks.settings.READ`

### Path Parameters

| Parameter          | Type   | Required | Description                             |
| :----------------- | :----- | :------- | :-------------------------------------- |
| `currency_id`      | string | Required | Unique identifier of the currency.      |
| `exchange_rate_id` | string | Required | Unique identifier of the exchange rate. |

### Query Parameters

| Parameter         | Type   | Required | Description            |
| :---------------- | :----- | :------- | :--------------------- |
| `organization_id` | string | Required | ID of the organization |

### Request Example

```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/settings/currencies/982000000004012/exchangerates/460000000038035?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "success",
    "exchange_rate": 1
}
```

---

## Delete an exchage rate

Delete an exchange rate for the specified currency.

`OAuth Scope : ZohoBooks.settings.DELETE`

### Path Parameters

| Parameter          | Type   | Required | Description                             |
| :----------------- | :----- | :------- | :-------------------------------------- |
| `currency_id`      | string | Required | Unique identifier of the currency.      |
| `exchange_rate_id` | string | Required | Unique identifier of the exchange rate. |

### Query Parameters

| Parameter         | Type   | Required | Description            |
| :---------------- | :----- | :------- | :--------------------- |
| `organization_id` | string | Required | ID of the organization |

### Request Example

```bash
curl --request DELETE \
  --url 'https://www.zohoapis.com/books/v3/settings/currencies/982000000004012/exchangerates/460000000038035?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "Exchange rate successfully deleted"
}
```