# HTTP Methods 

Zoho Books API uses appropriate HTTP verbs for every action.

Method

Description

GET

Used for retrieving resources.

POST

Used for creating resources and performing resource actions.

PUT

Used for updating resources.

DELETE

Used for deleting resources.

Using GET method, you can get the list of resources or details of a particular instance of a resource. To get a list of customers

**Request Example**
```curl
$ curl https://www.zohoapis.com/books/v3/contacts?organization_id=10234695 -H 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

To get the details of a customer referred to by a specified customer\_id

**Request Example**
```curl
$ curl https://www.zohoapis.com/books/v3/contacts/903000000000099?organization_id=10234695 -H 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---------------------


# Responses 

Responses will be in the JSON format.

Node Name

Description

code

Zoho Books error code. This will be zero for a success response and non-zero in case of an error.

message

Message for the invoked API.

resource name

Comprises the invoked API’s Data.

  

### Other Formats

Certain APIs also support CSV and PDF formats. The required response format needs to be specified in the respective request’s `Accept` header or `accept` query parameter.

  
  
  
  
  
  
  
  
  
  
  
  
  
  
  
  
  
  

### Date

All timestamps are returned in the ISO 8601 format - YYYY-MM-DDThh:mm:ssTZD.

Example: `2016-06-11T17:38:06-0700`

**Request Example**
```curl
$ curl https://www.zohoapis.com/books/v3/invoices/7000000079426?organization_id=10234695 -H 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' -H 'Accept: application/pdf'
```

OR

**Request Example**
```curl
$ curl https://www.zohoapis.com/books/v3/invoices/7000000079426?accept=pdf \'&organization_id=10234695' -H 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

Response Structure

```json
{ "code" : 0, "message" : "success", "invoice" : { "invoice_id" : "..." } }
```

Response Example

```json
HTTP/1.1 200 OK Content-Disposition: attachment; filename="INV-384.pdf" Content-Type: application/pdf;charset=UTF-8
```

----------------------

# Errors 

Zoho Books uses HTTP status codes to display the result of an API call. Generally, 2xx class codes are success codes, 4xx class codes occur when the information provided by the client is incorrect, and 5xx class codes indicate server side errors. The HTTP status codes that are commonly used are listed below.

### HTTP Status Codes

Status Code

Description

200

OK

201

Created

400

Bad Request

401

Unauthorized (Invalid AuthToken)

404

URL Not Found

405

Method Not Allowed (Method you have called is not supported for the invoked API)

429

Rate Limit Exceeded (API usage limit exceeded)

500

Internal Error

**Request Example**
```curl
$ curl https://www.zohoapis.com/books/v3/invoices/700000007942?organization_id=10234695 -H 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

Response Example

```json
{ "code": 0, "message": "Successfully created." }
```

Response Example

```json
{ "code": 1002, "message": "Invoice does not exist." }
```

Response Example

```json
{ "code": 1000, "message": "Internal error" }
```

------------------------


# Pagination 

Zoho Books provides APIs to retrieve lists of contacts, plans and other resources - paginated to 200 items by default. The pagination information will be included in the list API response under the node name `page_context`.

-   By default first page will be listed. For navigating through pages, use the `page` parameter.
-   The `per_page` parameter can be used to set the number of records that you want to receive in response.

**Request Example**
```curl
$ curl https://www.zohoapis.com/books/v3/contacts?page=2&per_page=25
```

Response Example

```json
{ "code": 0, "message": "success", "contacts": [ {...}, {...} ], "page_context": { "page": 2, "per_page": 25, "has_more_page": false } }
```