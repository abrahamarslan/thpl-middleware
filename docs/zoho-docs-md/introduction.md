# Introduction 

The Zoho Books API allows you to perform all the operations that you do with our web client.

Zoho Books API is built using REST principles which ensures predictable URLs that makes writing applications easy. This API follows HTTP rules, enabling a wide range of HTTP clients can be used to interact with the API.

Every resource is exposed as a URL. The URL of each resource can be obtained by accessing the API Root Endpoint.

Download Zoho Books OpenAPI Document

[Download](/books/api/v3/openapi-all.zip)

**API Root Endpoint**

`https://www.zohoapis.com/books/v3`

# Organization ID

In Zoho Books, your business is termed as an organization. If you have multiple businesses, you simply set each of those up as an individual organization. Each organization is an independent Zoho Books Organization with it’s own organization ID, base currency, time zone, language, contacts, reports, etc.

The parameter `organization_id` along with the organization ID should be sent in with every API request to identify the organization.

The `organization_id` can be obtained from the `GET /organizations` API’s JSON response.  
`oauthscope : ZohoBooks.settings.READ`  
Alternatively, it can be obtained from the **Manage Organizations** page in the admin console:

Log in to the Zoho Books admin console. Click the drop down with organization’s name as the label and click **Manage Organizations**.

**Request Example**
```curl
$ curl -X GET 'https://www.zohoapis.com/books/v3/organizations' \ -H 'Authorization: Zoho-oauthtoken 6e80xxxxxxxxxxxxxxxxxxxxxxxx8a80'
```

Response Example

```json
{ "code": 0, "message": "success", "organizations": [ { "organization_id": "10234695", "name": "Zillum", "contact_name": "John Smith", "email": "johnsmith@zillum.com", "is_default_org": false, "language_code": "en", "fiscal_year_start_month": 0, "account_created_date": "2016-02-18", "time_zone": "PST", "is_org_active": true, "currency_id": "460000000000097", "currency_code": "USD", "currency_symbol": "$", "currency_format": "###,##0.00", "price_precision": 2 }, {...}, {...} ] }
```

# Multiple Data Centers

Zoho Books is hosted at multiple data centers, and therefore available on different domains.

There are 8 different domains for Zoho Books' APIs, and you will have to use the one that is applicable to you.

Data Center

Domain

Base API URI

United States

.com

https://www.zohoapis.com/books/

Europe

.eu

https://www.zohoapis.eu/books/

India

.in

https://www.zohoapis.in/books/

Australia

.com.au

https://www.zohoapis.com.au/books/

Japan

.jp

https://www.zohoapis.jp/books/

Canada

.ca

https://www.zohoapis.ca/books/

China

.com.cn

https://www.zohoapis.com.cn/books/

Saudi Arabia

.sa

https://www.zohoapis.sa/books/

The APIs on this page are for organizations in Zoho Books that are hosted on the **.com** domain. If your organization is on a different domain, then you **must replace .com with the appropriate domain for API endpoints** on this page before using them.

**Note:** To know the domain you're accessing Zoho Books from, visit the Zoho Books web app and check its URL. If the URL contains books.zoho.**_com_**, then you're accessing it from the **.com** domain. If the URL contains books.zoho.**_in_**, you're accessing it from the **.in** domain. Similarly, you could be accessing Zoho Books from the **.eu** or **.com.au** or **.jp** or **.ca** domain.

  

For example, here's how you would modify the domain in an API endpoint for the .eu domain:

**API endpoint for the .com domain, as available on this page:**

`https://www.zohoapis**_.com_**/books/v3/invoices`

**API endpoint after replacing the .com domain with .eu:**

`https://www.zohoapis.**_eu_**/books/v3/invoices`

# API Call Limit

API calls are limited to provide better quality of service and availability to all the users. You can make 100 requests per minute per organization. The limits on total requests per day are listed below for each plan:

-   Free Plan - 1000 API requests/day
-   Standard Plan- 2000 requests/day
-   Professional Plan- 5000 requests/day
-   Premium Plan- 10000 requests/day
-   Elite Plan- 10000 requests/day
-   Ultimate Plan- 10000 requests/day

An error with HTTP status code 429 will be returned if the number of requests made exceeds the number of requests of a particular plan.

Response Example

```json
{ "code": 45, "message": "The API call for this organization has exceeded the maximum call rate limit of 1000." }
```

An error with HTTP status code 429 will be returned if the number of requests per minute per organization exceeds 100. Users who access the application via the web interface may encounter the following error.

Response Example

```json
{ "code": 44, "message": "For security reasons your account has been blocked as you have exceeded the maximum number of requests per minute that can originate from one account." }
```

An error with HTTP status code 429 will be returned if the number of requests per minute per organization exceeds 100. API customers may encounter the following error.

Response Example

```json
{ "code": 44, "message": "For security reasons your organization has been blocked as it have exceeded the maximum number of requests per minute that can originate from an organization." }
```

# Concurrent Rate Limiter

The concurrent rate limiter is the maximum number of API calls that can be simultaneously active for an organization at any given point in time.

The concurrent rate limit varies based on the plan:

-   Free Plan - 5 concurrent calls
-   Paid Plans - 10 concurrent calls (soft limit)

An error with HTTP status code 429 will be returned if the number of concurrent calls exceeds the specified limits.

Response Example

```json
{ "code": 1070, "message": "You have reached the maximum number of in process requests allowed. Kindly try again after some time." }
```