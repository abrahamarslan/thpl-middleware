# Categories 

Categories are hierarchical groupings used to organize items in your organization.

Download Categories OpenAPI Document

[Download](categories.yml)

[Download Zoho Books OpenAPI Document](/books/api/v3/openapi-all.zip)

| Method | Endpoint |
| ------ | -------- |
| `POST` | `/categories` |
| `GET` | `/categories` |
| `PUT` | `/categories/{category_id}` |
| `GET` | `/categories/{category_id}` |
| `DELETE` | `/categories/{category_id}` |

### Attribute

- **category_id** _(string)_  
  Unique identifier of the category.
- **name** _(string)_  
  Name of the category. Max-length [100].
- **description** _(string)_  
  Description of the category. Max-length [12000].
- **url** _(string)_  
  URL slug for the category. Max-length [100].
- **parent_category_id** _(string)_  
  ID of the parent category. Use -1 for a root-level category.
- **visibility** _(boolean)_  
  Whether the category is visible.
- **show_in_menu** _(boolean)_  
  Whether the category is shown in the menu.
- **seo_title** _(string)_  
  SEO title for the category. Max-length [100].
- **seo_keyword** _(string)_  
  SEO keywords for the category. Max-length [700].
- **seo_description** _(string)_  
  SEO description for the category. Max-length [700].
- **category_tax_preferences** _(array)_  
  Tax preferences associated with the category.
  - **tax_specification** _(string)_  
    Tax specification for the category tax preference.
  - **tax_id** _(string)_  
    Tax ID for the category tax preference.
- **ondc_category_type** _(string)_  
  ONDC category type.
- **custom_fields** _(array)_  
  Custom fields for the category.
  - **index** _(integer)_  
    Index of the custom field.
  - **value** _(string)_  
    Value of the custom field.
- **ancestors** _(array)_  
  Ancestor categories of this category.
  - **category_id** _(string)_  
    Unique identifier of the category.
  - **name** _(string)_  
    Name of the category. Max-length [100].
  - **url** _(string)_  
    URL slug for the category. Max-length [100].
  - **parent_category_id** _(string)_  
    ID of the parent category. Use -1 for a root-level category.
  - **visibility** _(boolean)_  
    Whether the category is visible.
  - **show_in_menu** _(boolean)_  
    Whether the category is shown in the menu.
- **children** _(array)_  
  Child categories of this category.
  - **category_id** _(string)_  
    Unique identifier of the category.
  - **name** _(string)_  
    Name of the category. Max-length [100].
  - **url** _(string)_  
    URL slug for the category. Max-length [100].
  - **parent_category_id** _(string)_  
    ID of the parent category. Use -1 for a root-level category.
  - **visibility** _(boolean)_  
    Whether the category is visible.
  - **show_in_menu** _(boolean)_  
    Whether the category is shown in the menu.
- **products** _(object)_  
  Items associated with the category.

**Example**

```json
{ "category_id": "4815000000044001", "name": "Electronics", "description": "Electronic gadgets and accessories", "url": "electronics", "parent_category_id": "-1", "parent_category_name": "Root", "visibility": true, "show_in_menu": true, "seo_title": "Electronics", "seo_keyword": "electronics", "seo_description": "Shop electronics and accessories", "category_tax_preferences": [ { "tax_specification": "inter", "tax_id": "4815000000001234" } ], "created_time": "2019-12-12T00:00:00+0530", "last_modified_time": "2019-12-12T00:00:00+0530", "ondc_category_type": "", "is_deprecated_ondc_category": false, "custom_fields": [ { "index": 1, "value": "Priority" } ], "ancestors": [ { "category_id": "4815000000044001", "name": "Electronics", "url": "electronics", "parent_category_id": "-1", "visibility": true, "show_in_menu": true, "created_time": "2019-12-12T00:00:00+0530", "last_modified_time": "2019-12-12T00:00:00+0530" } ], "children": [ { "category_id": "4815000000044001", "name": "Electronics", "url": "electronics", "parent_category_id": "-1", "visibility": true, "show_in_menu": true, "created_time": "2019-12-12T00:00:00+0530", "last_modified_time": "2019-12-12T00:00:00+0530" } ], "products": {} }
```

## Create a category 

Create a new category.  
`OAuth Scope : ZohoBooks.categories.CREATE`

### Arguments

- **name** _(string)_ — (Required)  
  Name of the category. Max-length [100].
- **url** _(string)_ — (Required)  
  URL slug for the category. Max-length [100].
- **description** _(string)_  
  Description of the category. Max-length [12000].
- **sibling_order** _(integer)_  
  Display order of the category among its siblings.
- **parent_category_id** _(string)_  
  ID of the parent category. Use -1 for a root-level category.
- **parent_category_name** _(string)_  
  Name of the parent category.
- **visibility** _(boolean)_  
  Whether the category is visible.
- **show_in_menu** _(boolean)_  
  Whether the category is shown in the menu.
- **category_tax_preferences** _(array)_  
  Tax preferences associated with the category.
  - **tax_specification** _(string)_  
    Tax specification for the category tax preference.
  - **tax_id** _(string)_  
    Tax ID for the category tax preference.
- **custom_fields** _(array)_  
  Custom fields for the category.
  - **index** _(integer)_  
    Index of the custom field.
  - **value** _(string)_  
    Value of the custom field.

### Query Parameters

- **organization_id** _(string)_ — (Required)  
  ID of the organization. Note: This value is a set of numeric characters.

**Request Example**
```deluge
parameters_data='{"field1":"value1","field2":"value2"}'; headers_data = Map(); headers_data.put("Authorization", "Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f"); response = invokeUrl [ url: "https://www.zohoapis.com/books/v3/categories?organization_id=10234695" type: POST headers: headers_data content-type: application/json parameters: parameters_data connection: <connection_name> ]; info response;
```

```java
OkHttpClient client = new OkHttpClient(); MediaType mediaType = MediaType.parse("application/json"); RequestBody body = RequestBody.create(mediaType, "{\"field1\":\"value1\",\"field2\":\"value2\"}"); Request request = new Request.Builder() .url("https://www.zohoapis.com/books/v3/categories?organization_id=10234695") .post(body) .addHeader("Authorization", "Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f") .addHeader("content-type", "application/json") .build(); Response response = client.newCall(request).execute();
```

```javascript
const options = { method: 'POST', headers: { Authorization: 'Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f', 'content-type': 'application/json' }, body: '{"field1":"value1","field2":"value2"}' }; fetch('https://www.zohoapis.com/books/v3/categories?organization_id=10234695', options) .then(response => response.json()) .then(response => console.log(response)) .catch(err => console.error(err));
```

```python
import http.client conn = http.client.HTTPSConnection("www.zohoapis.com") payload = "{\"field1\":\"value1\",\"field2\":\"value2\"}" headers = { 'Authorization': "Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f", 'content-type': "application/json" } conn.request("POST", "/books/v3/categories?organization_id=10234695", payload, headers) res = conn.getresponse() data = res.read() print(data.decode("utf-8"))
```

```node
const http = require("https"); const options = { "method": "POST", "hostname": "www.zohoapis.com", "port": null, "path": "/books/v3/categories?organization_id=10234695", "headers": { "Authorization": "Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f", "content-type": "application/json" } }; const req = http.request(options, function (res) { const chunks = []; res.on("data", function (chunk) { chunks.push(chunk); }); res.on("end", function () { const body = Buffer.concat(chunks); console.log(body.toString()); }); }); req.write(JSON.stringify({field1: 'value1', field2: 'value2'})); req.end();
```

```curl
curl --request POST \ --url 'https://www.zohoapis.com/books/v3/categories?organization_id=10234695' \ --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \ --header 'content-type: application/json' \ --data '{"field1":"value1","field2":"value2"}'
```
**Body Parameters**
```json
{ "name": "Electronics", "url": "electronics", "description": "Electronic gadgets and accessories", "sibling_order": 1, "parent_category_id": "-1", "parent_category_name": "Root", "visibility": true, "show_in_menu": true, "category_tax_preferences": [ { "tax_specification": "inter", "tax_id": "4815000000001234" } ], "custom_fields": [ { "index": 1, "value": "Priority" } ] }
```
**Response Example**
```json
{ "code": 0, "message": "Category created successfully.", "category": { "category_id": "4815000000044001", "name": "Electronics", "description": "Electronic gadgets and accessories", "url": "electronics", "parent_category_id": "-1", "parent_category_name": "Root", "visibility": true, "show_in_menu": true, "seo_title": "Electronics", "seo_keyword": "electronics", "seo_description": "Shop electronics and accessories", "category_tax_preferences": [ { "tax_specification": "inter", "tax_id": "4815000000001234" } ], "created_time": "2019-12-12T00:00:00+0530", "last_modified_time": "2019-12-12T00:00:00+0530", "ondc_category_type": "", "is_deprecated_ondc_category": false, "custom_fields": [ { "index": 1, "value": "Priority" } ], "ancestors": [ { "category_id": "4815000000044001", "name": "Electronics", "url": "electronics", "parent_category_id": "-1", "visibility": true, "show_in_menu": true, "created_time": "2019-12-12T00:00:00+0530", "last_modified_time": "2019-12-12T00:00:00+0530" } ], "children": [ { "category_id": "4815000000044001", "name": "Electronics", "url": "electronics", "parent_category_id": "-1", "visibility": true, "show_in_menu": true, "created_time": "2019-12-12T00:00:00+0530", "last_modified_time": "2019-12-12T00:00:00+0530" } ], "products": {...} } }
```


## List categories 

List all categories with filters and pagination. Results are returned in hierarchical order when not filtered by specific category IDs.  
`OAuth Scope : ZohoBooks.categories.READ`

### Query Parameters

- **organization_id** _(string)_ — (Required)  
  ID of the organization. Note: This value is a set of numeric characters.
- **parent_category_id** _(string)_  
  Filter categories by parent category ID. Use -1 for root-level categories.
- **include_parent_category** _(boolean)_  
  If true, the parent category is included in the results when filtering by parent_category_id. Default value is true.
- **include_root_category** _(boolean)_  
  If true, the root category is included in hierarchical list results. Default value is true.
- **last_modified_time** _(string)_  
  Return categories modified on or after this timestamp (UTC). Format: yyyy-MM-ddTHH:mm:ssZ.
- **search_text** _(string)_  
  Search categories by text.
- **category_ids** _(string)_  
  Comma-separated list of category IDs. Maximum 50 IDs.
- **name** _(string)_  
  Filter by category name. Variants: name_startswith, name_contains, name_in, and name_not_in.
- **name_startswith** _(string)_  
  Filter categories whose name starts with the specified text.
- **name_contains** _(string)_  
  Filter categories whose name contains the specified text.
- **name_in** _(string)_  
  Filter categories whose name is in the specified comma-separated list.
- **name_not_in** _(string)_  
  Filter categories whose name is not in the specified comma-separated list.
- **created_time** _(string)_  
  Filter by creation time. Variants: created_time_less_than, created_time_less_equals, created_time_greater_than, and created_time_greater_equals. Format: yyyy-MM-ddTHH:mm:ssZ.
- **filter_by** _(string)_  
  Filter categories. Allowed Values: All, ShowInMenu, and ActiveItems.
- **page** _(integer)_  
  Page number to be fetched. Default value is 1.
- **per_page** _(integer)_  
  Number of records to be fetched per page. Default value is 5000.
- **sort_column** _(string)_  
  Column to sort by. Default value is sibling_order.
- **sort_order** _(string)_  
  Sort order. Allowed Values: A and D. Default value is A.

**Request Example**
```deluge
headers_data = Map(); headers_data.put("Authorization", "Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f"); response = invokeUrl [ url: "https://www.zohoapis.com/books/v3/categories?organization_id=10234695" type: GET headers: headers_data connection: <connection_name> ]; info response;
```

```java
OkHttpClient client = new OkHttpClient(); Request request = new Request.Builder() .url("https://www.zohoapis.com/books/v3/categories?organization_id=10234695") .get() .addHeader("Authorization", "Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f") .build(); Response response = client.newCall(request).execute();
```

```javascript
const options = { method: 'GET', headers: { Authorization: 'Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' } }; fetch('https://www.zohoapis.com/books/v3/categories?organization_id=10234695', options) .then(response => response.json()) .then(response => console.log(response)) .catch(err => console.error(err));
```

```python
import http.client conn = http.client.HTTPSConnection("www.zohoapis.com") headers = { 'Authorization': "Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f" } conn.request("GET", "/books/v3/categories?organization_id=10234695", headers=headers) res = conn.getresponse() data = res.read() print(data.decode("utf-8"))
```

```node
const http = require("https"); const options = { "method": "GET", "hostname": "www.zohoapis.com", "port": null, "path": "/books/v3/categories?organization_id=10234695", "headers": { "Authorization": "Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f" } }; const req = http.request(options, function (res) { const chunks = []; res.on("data", function (chunk) { chunks.push(chunk); }); res.on("end", function () { const body = Buffer.concat(chunks); console.log(body.toString()); }); }); req.end();
```

```curl
curl --request GET \ --url 'https://www.zohoapis.com/books/v3/categories?organization_id=10234695' \ --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```
**Response Example**
```json
{ "code": 0, "message": "success", "categories": [ { "category_id": "4815000000044001", "name": "Electronics", "description": "Electronic gadgets and accessories", "url": "electronics", "parent_category_id": "-1", "visibility": true, "show_in_menu": true, "sibling_order": 1, "depth": 0, "has_active_items": true, "created_time": "2019-12-12T00:00:00+0530", "last_modified_time": "2019-12-12T00:00:00+0530", "ondc_category_type": "", "ondc_category_type_formatted": "", "is_deprecated_ondc_category": false }, {...}, {...} ], "page_context": { "page": 1, "per_page": 5000, "has_more_page": false, "report_name": "Categories", "applied_filter": "All", "sort_column": "sibling_order", "sort_order": "A" } }
```

## Update a category 

Update an existing category.  
`OAuth Scope : ZohoBooks.categories.UPDATE`

### Path Parameters

- **category_id** _(string)_ — (Required)  
  Unique identifier of the category.

### Query Parameters

- **organization_id** _(string)_ — (Required)  
  ID of the organization. Note: This value is a set of numeric characters.
- **update_all_items** _(boolean)_  
  If true, updates POS preferences of all items associated with this category.

**Request Example**
```deluge
parameters_data='{"field1":"value1","field2":"value2"}'; headers_data = Map(); headers_data.put("Authorization", "Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f"); response = invokeUrl [ url: "https://www.zohoapis.com/books/v3/categories/4815000000044001?organization_id=10234695" type: PUT headers: headers_data content-type: application/json parameters: parameters_data connection: <connection_name> ]; info response;
```

```java
OkHttpClient client = new OkHttpClient(); MediaType mediaType = MediaType.parse("application/json"); RequestBody body = RequestBody.create(mediaType, "{\"field1\":\"value1\",\"field2\":\"value2\"}"); Request request = new Request.Builder() .url("https://www.zohoapis.com/books/v3/categories/4815000000044001?organization_id=10234695") .put(body) .addHeader("Authorization", "Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f") .addHeader("content-type", "application/json") .build(); Response response = client.newCall(request).execute();
```

```javascript
const options = { method: 'PUT', headers: { Authorization: 'Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f', 'content-type': 'application/json' }, body: '{"field1":"value1","field2":"value2"}' }; fetch('https://www.zohoapis.com/books/v3/categories/4815000000044001?organization_id=10234695', options) .then(response => response.json()) .then(response => console.log(response)) .catch(err => console.error(err));
```

```python
import http.client conn = http.client.HTTPSConnection("www.zohoapis.com") payload = "{\"field1\":\"value1\",\"field2\":\"value2\"}" headers = { 'Authorization': "Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f", 'content-type': "application/json" } conn.request("PUT", "/books/v3/categories/4815000000044001?organization_id=10234695", payload, headers) res = conn.getresponse() data = res.read() print(data.decode("utf-8"))
```

```node
const http = require("https"); const options = { "method": "PUT", "hostname": "www.zohoapis.com", "port": null, "path": "/books/v3/categories/4815000000044001?organization_id=10234695", "headers": { "Authorization": "Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f", "content-type": "application/json" } }; const req = http.request(options, function (res) { const chunks = []; res.on("data", function (chunk) { chunks.push(chunk); }); res.on("end", function () { const body = Buffer.concat(chunks); console.log(body.toString()); }); }); req.write(JSON.stringify({field1: 'value1', field2: 'value2'})); req.end();
```

```curl
curl --request PUT \ --url 'https://www.zohoapis.com/books/v3/categories/4815000000044001?organization_id=10234695' \ --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \ --header 'content-type: application/json' \ --data '{"field1":"value1","field2":"value2"}'
```
**Body Parameters**
```json
{ "name": "Electronics", "url": "electronics", "description": "Electronic gadgets and accessories", "sibling_order": 1, "parent_category_id": "-1", "parent_category_name": "Root", "visibility": true, "show_in_menu": true, "category_tax_preferences": [ { "tax_specification": "inter", "tax_id": "4815000000001234" } ], "custom_fields": [ { "index": 1, "value": "Priority" } ] }
```
**Response Example**
```json
{ "code": 0, "message": "Category updated successfully.", "category": { "category_id": "4815000000044001", "name": "Electronics", "description": "Electronic gadgets and accessories", "url": "electronics", "parent_category_id": "-1", "parent_category_name": "Root", "visibility": true, "show_in_menu": true, "seo_title": "Electronics", "seo_keyword": "electronics", "seo_description": "Shop electronics and accessories", "category_tax_preferences": [ { "tax_specification": "inter", "tax_id": "4815000000001234" } ], "created_time": "2019-12-12T00:00:00+0530", "last_modified_time": "2019-12-12T00:00:00+0530", "ondc_category_type": "", "is_deprecated_ondc_category": false, "custom_fields": [ { "index": 1, "value": "Priority" } ], "ancestors": [ { "category_id": "4815000000044001", "name": "Electronics", "url": "electronics", "parent_category_id": "-1", "visibility": true, "show_in_menu": true, "created_time": "2019-12-12T00:00:00+0530", "last_modified_time": "2019-12-12T00:00:00+0530" } ], "children": [ { "category_id": "4815000000044001", "name": "Electronics", "url": "electronics", "parent_category_id": "-1", "visibility": true, "show_in_menu": true, "created_time": "2019-12-12T00:00:00+0530", "last_modified_time": "2019-12-12T00:00:00+0530" } ], "products": {...} } }
```

## Get a category 

Retrieve details of a category, including ancestors and children.  
`OAuth Scope : ZohoBooks.categories.READ`

### Path Parameters

- **category_id** _(string)_ — (Required)  
  Unique identifier of the category.

### Query Parameters

- **organization_id** _(string)_ — (Required)  
  ID of the organization. Note: This value is a set of numeric characters.

**Request Example**
```deluge
headers_data = Map(); headers_data.put("Authorization", "Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f"); response = invokeUrl [ url: "https://www.zohoapis.com/books/v3/categories/4815000000044001?organization_id=10234695" type: GET headers: headers_data connection: <connection_name> ]; info response;
```

```java
OkHttpClient client = new OkHttpClient(); Request request = new Request.Builder() .url("https://www.zohoapis.com/books/v3/categories/4815000000044001?organization_id=10234695") .get() .addHeader("Authorization", "Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f") .build(); Response response = client.newCall(request).execute();
```

```javascript
const options = { method: 'GET', headers: { Authorization: 'Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' } }; fetch('https://www.zohoapis.com/books/v3/categories/4815000000044001?organization_id=10234695', options) .then(response => response.json()) .then(response => console.log(response)) .catch(err => console.error(err));
```

```python
import http.client conn = http.client.HTTPSConnection("www.zohoapis.com") headers = { 'Authorization': "Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f" } conn.request("GET", "/books/v3/categories/4815000000044001?organization_id=10234695", headers=headers) res = conn.getresponse() data = res.read() print(data.decode("utf-8"))
```

```node
const http = require("https"); const options = { "method": "GET", "hostname": "www.zohoapis.com", "port": null, "path": "/books/v3/categories/4815000000044001?organization_id=10234695", "headers": { "Authorization": "Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f" } }; const req = http.request(options, function (res) { const chunks = []; res.on("data", function (chunk) { chunks.push(chunk); }); res.on("end", function () { const body = Buffer.concat(chunks); console.log(body.toString()); }); }); req.end();
```

```curl
curl --request GET \ --url 'https://www.zohoapis.com/books/v3/categories/4815000000044001?organization_id=10234695' \ --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```
**Response Example**
```json
{ "code": 0, "message": "success", "category": { "category_id": "4815000000044001", "name": "Electronics", "description": "Electronic gadgets and accessories", "url": "electronics", "parent_category_id": "-1", "parent_category_name": "Root", "visibility": true, "show_in_menu": true, "seo_title": "Electronics", "seo_keyword": "electronics", "seo_description": "Shop electronics and accessories", "category_tax_preferences": [ { "tax_specification": "inter", "tax_id": "4815000000001234" } ], "created_time": "2019-12-12T00:00:00+0530", "last_modified_time": "2019-12-12T00:00:00+0530", "ondc_category_type": "", "is_deprecated_ondc_category": false, "custom_fields": [ { "index": 1, "value": "Priority" } ], "ancestors": [ { "category_id": "4815000000044001", "name": "Electronics", "url": "electronics", "parent_category_id": "-1", "visibility": true, "show_in_menu": true, "created_time": "2019-12-12T00:00:00+0530", "last_modified_time": "2019-12-12T00:00:00+0530" } ], "children": [ { "category_id": "4815000000044001", "name": "Electronics", "url": "electronics", "parent_category_id": "-1", "visibility": true, "show_in_menu": true, "created_time": "2019-12-12T00:00:00+0530", "last_modified_time": "2019-12-12T00:00:00+0530" } ], "products": {...} } }
```

## Delete a category 

Delete a category. Optionally delete its subcategories.  
`OAuth Scope : ZohoBooks.categories.DELETE`

### Path Parameters

- **category_id** _(string)_ — (Required)  
  Unique identifier of the category.

### Query Parameters

- **organization_id** _(string)_ — (Required)  
  ID of the organization. Note: This value is a set of numeric characters.
- **delete_sub_categories** _(string)_  
  If true, deletes subcategories of the category. Allowed Values: true and false.

**Request Example**
```deluge
headers_data = Map(); headers_data.put("Authorization", "Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f"); response = invokeUrl [ url: "https://www.zohoapis.com/books/v3/categories/4815000000044001?organization_id=10234695" type: DELETE headers: headers_data connection: <connection_name> ]; info response;
```

```java
OkHttpClient client = new OkHttpClient(); Request request = new Request.Builder() .url("https://www.zohoapis.com/books/v3/categories/4815000000044001?organization_id=10234695") .delete(null) .addHeader("Authorization", "Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f") .build(); Response response = client.newCall(request).execute();
```

```javascript
const options = { method: 'DELETE', headers: { Authorization: 'Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' } }; fetch('https://www.zohoapis.com/books/v3/categories/4815000000044001?organization_id=10234695', options) .then(response => response.json()) .then(response => console.log(response)) .catch(err => console.error(err));
```

```python
import http.client conn = http.client.HTTPSConnection("www.zohoapis.com") headers = { 'Authorization': "Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f" } conn.request("DELETE", "/books/v3/categories/4815000000044001?organization_id=10234695", headers=headers) res = conn.getresponse() data = res.read() print(data.decode("utf-8"))
```

```node
const http = require("https"); const options = { "method": "DELETE", "hostname": "www.zohoapis.com", "port": null, "path": "/books/v3/categories/4815000000044001?organization_id=10234695", "headers": { "Authorization": "Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f" } }; const req = http.request(options, function (res) { const chunks = []; res.on("data", function (chunk) { chunks.push(chunk); }); res.on("end", function () { const body = Buffer.concat(chunks); console.log(body.toString()); }); }); req.end();
```

```curl
curl --request DELETE \ --url 'https://www.zohoapis.com/books/v3/categories/4815000000044001?organization_id=10234695' \ --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```
**Response Example**
```json
{ "code": 0, "message": "Category deleted successfully." }
```