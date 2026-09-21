# Estimates

An estimate is a quote or a proposal for the products you sell or the services you render to your clients to take your business forward.

### Attributes

| Attribute                         | Datatype | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| :-------------------------------- | :------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **estimate_id**                   | string   | The unique id of a particular estimate.                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| **estimate_number**               | string   | Search estimates by estimate number. Variants: `estimate_number_startswith` and `estimate_number_contains`.                                                                                                                                                                                                                                                                                                                                                                     |
| **date**                          | string   | Search estimates by estimate date. Variants: `date_start`, `date_end`, `date_before` and `date_after`.                                                                                                                                                                                                                                                                                                                                                                          |
| **reference_number**              | string   | Optional external identifier used to associate the estimate with other systems or workflows.                                                                                                                                                                                                                                                                                                                                                                                    |
| **is_pre_gst**                    | boolean  | **India Only:** Applicable for transactions that fall before july 1, 2017.                                                                                                                                                                                                                                                                                                                                                                                                      |
| **place_of_supply**               | string   | **India/GCC Only:** Place where the goods/services are supplied to. (If not given, `place of contact` given for the contact will be taken).                                                                                                                                                                                                                                                                                                                                     |
| **gst_no**                        | string   | **India Only:** 15 digit GST identification number of the customer.                                                                                                                                                                                                                                                                                                                                                                                                             |
| **gst_treatment**                 | string   | **India Only:** Choose whether the contact is GST registered/unregistered/consumer/overseas. Allowed values are `business_gst`, `business_none`, `overseas`, `consumer`.                                                                                                                                                                                                                                                                                                        |
| **tax_treatment**                 | string   | **GCC/Mexico/Kenya/South Africa:** VAT treatment for the Estimate. <br>Allowed Values: `vat_registered`, `vat_not_registered`, `gcc_vat_not_registered`, `gcc_vat_registered`, `non_gcc`. <br> **UAE:** `dz_vat_registered`, `dz_vat_not_registered`. <br> **MX:** `home_country_mexico`, `border_region_mexico`, `non_mexico`. <br> **Kenya:** `vat_registered`, `vat_not_registered`, `non_kenya`. <br> **South Africa:** `vat_registered`, `vat_not_registered`, `overseas`. |
| **is_reverse_charge_applied**     | boolean  | **South Africa Only:** (Required if customer tax treatment is `vat_registered`) Used to specify whether the transaction is applicable for Domestic Reverse Charge (DRC) or not.                                                                                                                                                                                                                                                                                                 |
| **status**                        | string   | Search estimates by status. Allowed Values: `draft`, `sent`, `invoiced`, `accepted`, `declined` and `expired`.                                                                                                                                                                                                                                                                                                                                                                  |
| **customer_id**                   | string   | The ID of the customer (contact) for whom the estimate is created.                                                                                                                                                                                                                                                                                                                                                                                                              |
| **customer_name**                 | string   | Search estimates by customer name. Variants: `customer_name_startswith` and `customer_name_contains`.                                                                                                                                                                                                                                                                                                                                                                           |
| **contact_persons_associated**    | array    | Contact Persons associated with the estimate. Contains `contact_person_id`, `contact_person_name`, `first_name`, `last_name`, `contact_person_email`, `phone`, `mobile`, and `communication_preference`.                                                                                                                                                                                                                                                                        |
| **currency_id**                   | string   | The ID of the currency in which the estimate will be created.                                                                                                                                                                                                                                                                                                                                                                                                                   |
| **currency_code**                 | string   | Currency code of the currency in which the customer wants to pay.                                                                                                                                                                                                                                                                                                                                                                                                               |
| **exchange_rate**                 | double   | Exchange rate of the currency.                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| **expiry_date**                   | string   | The date of expiration of the estimates.                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| **discount**                      | double   | Discount applied to the estimate. It can be either in % or in amount.                                                                                                                                                                                                                                                                                                                                                                                                           |
| **is_discount_before_tax**        | boolean  | Used to specify how the discount has to applied. Either before or after the calculation of tax.                                                                                                                                                                                                                                                                                                                                                                                 |
| **discount_type**                 | string   | How the discount is specified. Allowed values are `entity_level` or `item_level`.                                                                                                                                                                                                                                                                                                                                                                                               |
| **is_inclusive_tax**              | boolean  | **Not applicable for US/Canada:** Used to specify whether the line item rates are inclusive or exclusive of tax.                                                                                                                                                                                                                                                                                                                                                                |
| **line_items**                    | array    | Array of line items included in the estimate. See details below.                                                                                                                                                                                                                                                                                                                                                                                                                |
| **line_items.item_id**            | string   | Unique identifier of the item.                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| **line_items.line_item_id**       | string   | Unique identifier of the line item within the estimate.                                                                                                                                                                                                                                                                                                                                                                                                                         |
| **line_items.name**               | string   | Name of the product or service.                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| **line_items.description**        | string   | Detailed description of the product or service.                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| **line_items.item_order**         | integer  | Sequential order number for this line item.                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| **line_items.product_type**       | string   | Type of product (`goods`, `services`).                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| **line_items.sat_item_key_code**  | string   | **Mexico Only:** SAT Item Key Code.                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| **line_items.unitkey_code**       | string   | **Mexico Only:** SAT Unit Key Code.                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| **line_items.bcy_rate**           | float    | Exchange rate between base currency and transaction currency.                                                                                                                                                                                                                                                                                                                                                                                                                   |
| **line_items.rate**               | double   | Unit price or rate.                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| **line_items.quantity**           | double   | Number of units.                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| **line_items.unit**               | string   | Unit of measurement.                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| **line_items.discount_amount**    | float    | Discount amount applied to this line item.                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| **line_items.discount**           | double   | Discount applied (percentage or amount).                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| **line_items.tax_id**             | string   | Unique identifier of the tax applied.                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| **line_items.tds_tax_id**         | string   | **Mexico Only:** ID of the TDS tax.                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| **line_items.tax_name**           | string   | The name of the tax.                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| **line_items.tax_type**           | string   | The type of the tax.                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| **line_items.tax_percentage**     | float    | The percentage of tax levied.                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| **line_items.tax_treatment_code** | string   | **GCC Only:** Specify reason for using out of scope.                                                                                                                                                                                                                                                                                                                                                                                                                            |
| **line_items.item_total**         | float    | Total amount for this line item.                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| **line_items.location_id**        | string   | Unique identifier of the business location associated with the line item.                                                                                                                                                                                                                                                                                                                                                                                                       |
| **line_items.location_name**      | string   | Name of the location.                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| **location_id**                   | string   | Unique identifier of the business location associated with the estimate.                                                                                                                                                                                                                                                                                                                                                                                                        |
| **location_name**                 | string   | Name of the location.                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| **shipping_charge**               | string   | Additional shipping or delivery charges.                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| **adjustment**                    | double   | Additional charge or credit amount.                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| **adjustment_description**        | string   | Text description explaining the reason for the adjustment.                                                                                                                                                                                                                                                                                                                                                                                                                      |
| **sub_total**                     | float    | The sub total of the all items.                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| **total**                         | double   | Estimate total. Variants: `total_less_than`, `total_less_equals`, `total_greater_than`, `total_greater_equals`.                                                                                                                                                                                                                                                                                                                                                                 |
| **tax_total**                     | double   | The total amount of the tax levied.                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| **price_precision**               | integer  | The precision value on the price.                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| **taxes**                         | array    | List of taxes levied.                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| **billing_address**               | object   | The billing address. Contains `address`, `city`, `state`, `zip`, `country`, `fax`.                                                                                                                                                                                                                                                                                                                                                                                              |
| **shipping_address**              | object   | The shipping address. Contains `address`, `city`, `state`, `zip`, `country`, `fax`.                                                                                                                                                                                                                                                                                                                                                                                             |
| **notes**                         | string   | Additional information or comments.                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| **terms**                         | string   | Terms and conditions.                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| **custom_fields**                 | array    | Custom fields for an estimate.                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| **template_id**                   | string   | The ID of the template used for generating the estimate PDF.                                                                                                                                                                                                                                                                                                                                                                                                                    |
| **template_name**                 | string   | Name of the template.                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| **created_time**                  | string   | The time of creation.                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| **last_modified_time**            | string   | The time of last modification.                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| **salesperson_id**                | string   | ID of the salesperson.                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| **salesperson_name**              | string   | Name of the salesperson.                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| **project**                       | object   | Project details associated with the estimate.                                                                                                                                                                                                                                                                                                                                                                                                                                   |

---

## Create an Estimate

Create an estimate for your customer.
`OAuth Scope : ZohoBooks.estimates.CREATE`

**Method:** `POST`
**Endpoint:** `/estimates`

### Arguments

| Parameter                      | Datatype | Description                                                                                                               |
| :----------------------------- | :------- | :------------------------------------------------------------------------------------------------------------------------ |
| **customer_id**                | string   | **(Required)** The ID of the customer (contact) for whom the estimate is created.                                         |
| **currency_id**                | string   | The ID of the currency in which the estimate will be created.                                                             |
| **contact_persons_associated** | array    | Contact Persons associated with the estimate.                                                                             |
| **template_id**                | string   | The ID of the template used for generating the estimate PDF.                                                              |
| **place_of_supply**            | string   | **India/GCC Only:** Place where the goods/services are supplied to.                                                       |
| **gst_treatment**              | string   | **India Only:** Choose whether the contact is GST registered/unregistered/consumer/overseas.                              |
| **gst_no**                     | string   | **India Only:** 15 digit GST identification number of the customer.                                                       |
| **estimate_number**            | string   | Unique identifier for the estimate. If not provided, the system auto-generates one.                                       |
| **reference_number**           | string   | External reference associated with the estimate.                                                                          |
| **date**                       | string   | Date the estimate is created. Format: YYYY-MM-DD.                                                                         |
| **expiry_date**                | string   | Date when the estimate expires. Format: YYYY-MM-DD.                                                                       |
| **exchange_rate**              | double   | Exchange rate used to convert the estimate amount to the base currency.                                                   |
| **discount**                   | double   | Discount applied to the estimate.                                                                                         |
| **is_discount_before_tax**     | boolean  | Indicates whether the discount is applied before or after tax calculation.                                                |
| **discount_type**              | string   | Specifies how the discount is applied: `entity_level` or `item_level`.                                                    |
| **is_inclusive_tax**           | boolean  | **Not applicable for US/Canada:** Used to specify whether the line item rates are inclusive or exclusive of tax.          |
| **custom_body**                | string   | Custom email body.                                                                                                        |
| **custom_subject**             | string   | Custom email subject.                                                                                                     |
| **salesperson_name**           | string   | Name of the sales person.                                                                                                 |
| **custom_fields**              | array    | Custom fields for an estimate.                                                                                            |
| **line_items**                 | array    | **(Required)** Line items of an estimate.                                                                                 |
| **location_id**                | string   | Unique identifier of the business location.                                                                               |
| **notes**                      | string   | Additional information or comments.                                                                                       |
| **terms**                      | string   | Terms and conditions.                                                                                                     |
| **shipping_charge**            | string   | Additional shipping or delivery charges.                                                                                  |
| **adjustment**                 | double   | Additional charge or credit amount.                                                                                       |
| **adjustment_description**     | string   | Text description explaining the reason for the adjustment.                                                                |
| **tax_id**                     | string   | Unique identifier of the tax to be applied.                                                                               |
| **tax_exemption_id**           | string   | **India/US Only:** ID of the tax exemption.                                                                               |
| **tax_authority_id**           | string   | **US Only:** ID of the tax authority.                                                                                     |
| **avatax_use_code**            | string   | **Avalara Integration:** Used to group like customers for exemption purposes.                                             |
| **avatax_exempt_no**           | string   | **Avalara Integration:** Exemption certificate number.                                                                    |
| **vat_treatment**              | string   | **UK Only:** VAT treatment for the estimates.                                                                             |
| **tax_treatment**              | string   | **GCC/Mexico/Kenya/South Africa:** VAT treatment for the Estimate.                                                        |
| **is_reverse_charge_applied**  | boolean  | **South Africa Only:** Used to specify whether the transaction is applicable for Domestic Reverse Charge (DRC).           |
| **project_id**                 | string   | Unique identifier of the project associated with this estimate.                                                           |
| **accept_retainer**            | boolean  | Boolean flag indicating whether a retainer invoice should be automatically created if the customer accepts this estimate. |
| **retainer_percentage**        | integer  | Percentage of the estimate amount to be collected as a retainer.                                                          |

### Query Parameters

| Parameter                         | Datatype | Description                                                                                  |
| :-------------------------------- | :------- | :------------------------------------------------------------------------------------------- |
| **organization_id**               | string   | **(Required)** ID of the organization.                                                       |
| **send**                          | boolean  | Send the estimate to the contact person(s) associated with the estimate.                     |
| **ignore_auto_number_generation** | boolean  | Ignore auto estimate number generation for this estimate. This mandates the estimate number. |

---

## update an Estimate using a custom field's unique value

Update an estimate by providing its API name in the X-Unique-Identifier-Key header and its value in the X-Unique-Identifier-Value header.
`OAuth Scope : ZohoBooks.estimates.UPDATE`

**Method:** `PUT`
**Endpoint:** `/estimates`

### Headers

| Header                        | Datatype | Description                                                                               |
| :---------------------------- | :------- | :---------------------------------------------------------------------------------------- |
| **X-Unique-Identifier-Key**   | string   | **(Required)** Unique CustomField Api Name.                                               |
| **X-Unique-Identifier-Value** | string   | **(Required)** Unique CustomField Value.                                                  |
| **X-Upsert**                  | boolean  | If true and the custom field's unique value is not found, a new estimate will be created. |

### Arguments
*Same as Create an Estimate*

### Query Parameters

| Parameter           | Datatype | Description                            |
| :------------------ | :------- | :------------------------------------- |
| **organization_id** | string   | **(Required)** ID of the organization. |

---

## List estimates

List all estimates with pagination.
`OAuth Scope : ZohoBooks.estimates.READ`

**Method:** `GET`
**Endpoint:** `/estimates`

### Query Parameters

| Parameter             | Datatype | Description                                                                                                                                               |
| :-------------------- | :------- | :-------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **organization_id**   | string   | **(Required)** ID of the organization.                                                                                                                    |
| **estimate_number**   | string   | Filter or search by unique estimate number. Variants: `estimate_number_startswith`, `estimate_number_contains`.                                           |
| **reference_number**  | string   | Filter or search by reference number. Variants: `reference_number_startswith`, `reference_number_contains`.                                               |
| **customer_name**     | string   | Filter or search by customer's name. Variants: `customer_name_startswith`, `customer_name_contains`.                                                      |
| **total**             | double   | Filter or search by total amount. Variants: `total_less_than`, `total_less_equals`, `total_greater_than`, `total_greater_equals`.                         |
| **customer_id**       | string   | Filter by unique customer ID.                                                                                                                             |
| **item_id**           | string   | Filter by unique item ID.                                                                                                                                 |
| **item_name**         | string   | Search by item name. Variants: `item_name_startswith`, `item_name_contains`.                                                                              |
| **item_description**  | string   | Search by item description. Variants: `item_description_startswith`, `item_description_contains`.                                                         |
| **custom_field**      | string   | Search by custom field. Variants: `custom_field_startswith`, `custom_field_contains`.                                                                     |
| **expiry_date**       | string   | The date of expiration of the estimates.                                                                                                                  |
| **date**              | string   | Search by estimate date. Variants: `date_start`, `date_end`, `date_before`, `date_after`.                                                                 |
| **status**            | string   | Search by status. Allowed Values: `draft`, `sent`, `invoiced`, `accepted`, `declined`, `expired`.                                                         |
| **filter_by**         | string   | Filter by status. Allowed Values: `Status.All`, `Status.Sent`, `Status.Draft`, `Status.Invoiced`, `Status.Accepted`, `Status.Declined`, `Status.Expired`. |
| **search_text**       | string   | Perform a keyword search across estimate number, reference number, or customer name.                                                                      |
| **sort_column**       | string   | Sort estimates. Allowed Values: `customer_name`, `estimate_number`, `date`, `total`, `created_time`.                                                      |
| **zcrm_potential_id** | long     | Potential ID of a Deal in CRM.                                                                                                                            |
| **page**              | integer  | Page number to be fetched. Default value is 1.                                                                                                            |
| **per_page**          | integer  | Number of records to be fetched per page. Default value is 200.                                                                                           |

---

## Update an Estimate

Update an existing estimate.
`OAuth Scope : ZohoBooks.estimates.UPDATE`

**Method:** `PUT`
**Endpoint:** `/estimates/{estimate_id}`

### Path Parameters

| Parameter       | Datatype | Description                                       |
| :-------------- | :------- | :------------------------------------------------ |
| **estimate_id** | string   | **(Required)** Unique identifier of the estimate. |

### Arguments
*Same as Create an Estimate*

### Query Parameters

| Parameter                         | Datatype | Description                                               |
| :-------------------------------- | :------- | :-------------------------------------------------------- |
| **organization_id**               | string   | **(Required)** ID of the organization.                    |
| **ignore_auto_number_generation** | boolean  | Ignore auto estimate number generation for this estimate. |

---

## Get an estimate

Get the details of an estimate.
`OAuth Scope : ZohoBooks.estimates.READ`

**Method:** `GET`
**Endpoint:** `/estimates/{estimate_id}`

### Path Parameters

| Parameter       | Datatype | Description                                       |
| :-------------- | :------- | :------------------------------------------------ |
| **estimate_id** | string   | **(Required)** Unique identifier of the estimate. |

### Query Parameters

| Parameter           | Datatype | Description                                                                                  |
| :------------------ | :------- | :------------------------------------------------------------------------------------------- |
| **organization_id** | string   | **(Required)** ID of the organization.                                                       |
| **print**           | boolean  | Print the exported pdf.                                                                      |
| **accept**          | string   | Get the details in specific formats. Allowed Values: `json`, `pdf`, `html`. Default: `json`. |

---

## Delete an Estimate

Delete an existing estimate.
`OAuth Scope : ZohoBooks.estimates.DELETE`

**Method:** `DELETE`
**Endpoint:** `/estimates/{estimate_id}`

### Path Parameters

| Parameter       | Datatype | Description                                       |
| :-------------- | :------- | :------------------------------------------------ |
| **estimate_id** | string   | **(Required)** Unique identifier of the estimate. |

### Query Parameters

| Parameter           | Datatype | Description                            |
| :------------------ | :------- | :------------------------------------- |
| **organization_id** | string   | **(Required)** ID of the organization. |

---

## Update custom field in existing estimates

Update the value of the custom field in existing estimates.
`OAuth Scope : ZohoBooks.estimates.UPDATE`

**Method:** `PUT`
**Endpoint:** `/estimate/{estimate_id}/customfields`

### Path Parameters

| Parameter       | Datatype | Description                                       |
| :-------------- | :------- | :------------------------------------------------ |
| **estimate_id** | string   | **(Required)** Unique identifier of the estimate. |

### Arguments

| Parameter          | Datatype | Description                |
| :----------------- | :------- | :------------------------- |
| **customfield_id** | long     | ID of the custom field.    |
| **value**          | string   | Value of the custom field. |

### Query Parameters

| Parameter           | Datatype | Description                            |
| :------------------ | :------- | :------------------------------------- |
| **organization_id** | string   | **(Required)** ID of the organization. |

---

## Mark an estimate as sent

Mark a draft estimate as sent.
`OAuth Scope : ZohoBooks.estimates.CREATE`

**Method:** `POST`
**Endpoint:** `/estimates/{estimate_id}/status/sent`

### Path Parameters

| Parameter       | Datatype | Description                                       |
| :-------------- | :------- | :------------------------------------------------ |
| **estimate_id** | string   | **(Required)** Unique identifier of the estimate. |

### Query Parameters

| Parameter           | Datatype | Description                            |
| :------------------ | :------- | :------------------------------------- |
| **organization_id** | string   | **(Required)** ID of the organization. |

---

## Mark an estimate as accepted

Mark a sent estimate as accepted if the customer has accepted it.
`OAuth Scope : ZohoBooks.estimates.CREATE`

**Method:** `POST`
**Endpoint:** `/estimates/{estimate_id}/status/accepted`

### Path Parameters

| Parameter       | Datatype | Description                                       |
| :-------------- | :------- | :------------------------------------------------ |
| **estimate_id** | string   | **(Required)** Unique identifier of the estimate. |

### Query Parameters

| Parameter           | Datatype | Description                            |
| :------------------ | :------- | :------------------------------------- |
| **organization_id** | string   | **(Required)** ID of the organization. |

---

## Mark an estimate as declined

Mark a sent estimate as declined if the customer has rejected it.
`OAuth Scope : ZohoBooks.estimates.CREATE`

**Method:** `POST`
**Endpoint:** `/estimates/{estimate_id}/status/declined`

### Path Parameters

| Parameter       | Datatype | Description                                       |
| :-------------- | :------- | :------------------------------------------------ |
| **estimate_id** | string   | **(Required)** Unique identifier of the estimate. |

### Query Parameters

| Parameter           | Datatype | Description                            |
| :------------------ | :------- | :------------------------------------- |
| **organization_id** | string   | **(Required)** ID of the organization. |

---

## Submit an estimate for approval

Submit an estimate for approval.
`OAuth Scope : ZohoBooks.estimates.CREATE`

**Method:** `POST`
**Endpoint:** `/estimates/{estimate_id}/submit`

### Path Parameters

| Parameter       | Datatype | Description                                       |
| :-------------- | :------- | :------------------------------------------------ |
| **estimate_id** | string   | **(Required)** Unique identifier of the estimate. |

### Query Parameters

| Parameter           | Datatype | Description                            |
| :------------------ | :------- | :------------------------------------- |
| **organization_id** | string   | **(Required)** ID of the organization. |

---

## Approve an estimate

Approve an estimate.
`OAuth Scope : ZohoBooks.estimates.CREATE`

**Method:** `POST`
**Endpoint:** `/estimates/{estimate_id}/approve`

### Path Parameters

| Parameter       | Datatype | Description                                       |
| :-------------- | :------- | :------------------------------------------------ |
| **estimate_id** | string   | **(Required)** Unique identifier of the estimate. |

### Query Parameters

| Parameter           | Datatype | Description                            |
| :------------------ | :------- | :------------------------------------- |
| **organization_id** | string   | **(Required)** ID of the organization. |

---

## Email an estimate

Email an estimate to the customer.
`OAuth Scope : ZohoBooks.estimates.CREATE`

**Method:** `POST`
**Endpoint:** `/estimates/{estimate_id}/email`

### Path Parameters

| Parameter       | Datatype | Description                                       |
| :-------------- | :------- | :------------------------------------------------ |
| **estimate_id** | string   | **(Required)** Unique identifier of the estimate. |

### Arguments

| Parameter                  | Datatype | Description                                                         |
| :------------------------- | :------- | :------------------------------------------------------------------ |
| **send_from_org_email_id** | boolean  | Boolean to trigger the email from the organization's email address. |
| **to_mail_ids**            | array    | **(Required)** Array of email address of the recipients.            |
| **cc_mail_ids**            | array    | Array of email address of the recipients to be cced.                |
| **subject**                | string   | Subject of an email has to be sent.                                 |
| **body**                   | string   | Body of an email has to be sent.                                    |
| **mail_documents**         | array    | Array of Documents ids, which is attached into email.               |

### Query Parameters

| Parameter           | Datatype | Description                            |
| :------------------ | :------- | :------------------------------------- |
| **organization_id** | string   | **(Required)** ID of the organization. |
| **attachments**     | binary   | Files to be attached to the email.     |

---

## Get estimate email content

Get the email content of an estimate.
`OAuth Scope : ZohoBooks.estimates.READ`

**Method:** `GET`
**Endpoint:** `/estimates/{estimate_id}/email`

### Path Parameters

| Parameter       | Datatype | Description                                       |
| :-------------- | :------- | :------------------------------------------------ |
| **estimate_id** | string   | **(Required)** Unique identifier of the estimate. |

### Query Parameters

| Parameter             | Datatype | Description                                                              |
| :-------------------- | :------- | :----------------------------------------------------------------------- |
| **organization_id**   | string   | **(Required)** ID of the organization.                                   |
| **email_template_id** | string   | **(Required)** Get the email content based on a specific email template. |

---

## Email multiple estimates

Send estimates to your customers by email. Maximum of 10 estimates can be sent at once.
`OAuth Scope : ZohoBooks.estimates.CREATE`

**Method:** `POST`
**Endpoint:** `/estimates/email`

### Query Parameters

| Parameter           | Datatype | Description                                                          |
| :------------------ | :------- | :------------------------------------------------------------------- |
| **organization_id** | string   | **(Required)** ID of the organization.                               |
| **estimate_ids**    | string   | **(Required)** Comma separated estimate ids which are to be emailed. |

---

## Bulk export estimates

Maximum of 25 estimates can be exported in a single pdf.
`OAuth Scope : ZohoBooks.estimates.READ`

**Method:** `GET`
**Endpoint:** `/estimates/pdf`

### Query Parameters

| Parameter           | Datatype | Description                                                           |
| :------------------ | :------- | :-------------------------------------------------------------------- |
| **organization_id** | string   | **(Required)** ID of the organization.                                |
| **estimate_ids**    | string   | **(Required)** Comma separated estimate ids which are to be exported. |

---

## Bulk print estimates

Export estimates as pdf and print them. Maximum of 25 estimates can be printed.
`OAuth Scope : ZohoBooks.estimates.READ`

**Method:** `GET`
**Endpoint:** `/estimates/print`

### Query Parameters

| Parameter           | Datatype | Description                                                          |
| :------------------ | :------- | :------------------------------------------------------------------- |
| **organization_id** | string   | **(Required)** ID of the organization.                               |
| **estimate_ids**    | string   | **(Required)** Comma separated estimate ids which are to be printed. |

---

## Update billing address

Updates the billing address for this estimate alone.
`OAuth Scope : ZohoBooks.estimates.UPDATE`

**Method:** `PUT`
**Endpoint:** `/estimates/{estimate_id}/address/billing`

### Path Parameters

| Parameter       | Datatype | Description                                       |
| :-------------- | :------- | :------------------------------------------------ |
| **estimate_id** | string   | **(Required)** Unique identifier of the estimate. |

### Arguments

| Parameter   | Datatype | Description      |
| :---------- | :------- | :--------------- |
| **address** | string   | Billing address. |
| **city**    | string   | City.            |
| **state**   | string   | State.           |
| **zip**     | string   | Zip code.        |
| **country** | string   | Country.         |
| **fax**     | string   | Fax number.      |

### Query Parameters

| Parameter           | Datatype | Description                            |
| :------------------ | :------- | :------------------------------------- |
| **organization_id** | string   | **(Required)** ID of the organization. |

---

## Update shipping address

Updates the shipping address for an existing estimate alone.
`OAuth Scope : ZohoBooks.estimates.UPDATE`

**Method:** `PUT`
**Endpoint:** `/estimates/{estimate_id}/address/shipping`

### Path Parameters

| Parameter       | Datatype | Description                                       |
| :-------------- | :------- | :------------------------------------------------ |
| **estimate_id** | string   | **(Required)** Unique identifier of the estimate. |

### Arguments

| Parameter   | Datatype | Description       |
| :---------- | :------- | :---------------- |
| **address** | string   | Shipping address. |
| **city**    | string   | City.             |
| **state**   | string   | State.            |
| **zip**     | string   | Zip code.         |
| **country** | string   | Country.          |
| **fax**     | string   | Fax number.       |

### Query Parameters

| Parameter           | Datatype | Description                            |
| :------------------ | :------- | :------------------------------------- |
| **organization_id** | string   | **(Required)** ID of the organization. |

---

## List estimate template

Get all estimate pdf templates.
`OAuth Scope : ZohoBooks.estimates.READ`

**Method:** `GET`
**Endpoint:** `/estimates/templates`

### Query Parameters

| Parameter           | Datatype | Description                            |
| :------------------ | :------- | :------------------------------------- |
| **organization_id** | string   | **(Required)** ID of the organization. |

---

## Update estimate template

Update the pdf template associated with the estimate.
`OAuth Scope : ZohoBooks.estimates.UPDATE`

**Method:** `PUT`
**Endpoint:** `/estimates/{estimate_id}/templates/{template_id}`

### Path Parameters

| Parameter       | Datatype | Description                                                |
| :-------------- | :------- | :--------------------------------------------------------- |
| **estimate_id** | string   | **(Required)** Unique identifier of the estimate.          |
| **template_id** | string   | **(Required)** Unique identifier of the estimate template. |

### Query Parameters

| Parameter           | Datatype | Description                            |
| :------------------ | :------- | :------------------------------------- |
| **organization_id** | string   | **(Required)** ID of the organization. |

---

## Add Comments

Add a comment for an estimate.
`OAuth Scope : ZohoBooks.estimates.CREATE`

**Method:** `POST`
**Endpoint:** `/estimates/{estimate_id}/comments`

### Path Parameters

| Parameter       | Datatype | Description                                       |
| :-------------- | :------- | :------------------------------------------------ |
| **estimate_id** | string   | **(Required)** Unique identifier of the estimate. |

### Arguments

| Parameter                   | Datatype | Description                                         |
| :-------------------------- | :------- | :-------------------------------------------------- |
| **description**             | string   | The description of the comment.                     |
| **show_comment_to_clients** | boolean  | Boolean to show the comments to contacts in portal. |

### Query Parameters

| Parameter           | Datatype | Description                            |
| :------------------ | :------- | :------------------------------------- |
| **organization_id** | string   | **(Required)** ID of the organization. |

---

## List estimate comments & history

Get the complete history and comments of an estimate.
`OAuth Scope : ZohoBooks.estimates.READ`

**Method:** `GET`
**Endpoint:** `/estimates/{estimate_id}/comments`

### Path Parameters

| Parameter       | Datatype | Description                                       |
| :-------------- | :------- | :------------------------------------------------ |
| **estimate_id** | string   | **(Required)** Unique identifier of the estimate. |

### Query Parameters

| Parameter           | Datatype | Description                            |
| :------------------ | :------- | :------------------------------------- |
| **organization_id** | string   | **(Required)** ID of the organization. |

---

## Update comment

Update an existing comment of an estimate.
`OAuth Scope : ZohoBooks.estimates.UPDATE`

**Method:** `PUT`
**Endpoint:** `/estimates/{estimate_id}/comments/{comment_id}`

### Path Parameters

| Parameter       | Datatype | Description                                       |
| :-------------- | :------- | :------------------------------------------------ |
| **estimate_id** | string   | **(Required)** Unique identifier of the estimate. |
| **comment_id**  | string   | **(Required)** Unique identifier of the comment.  |

### Arguments

| Parameter                   | Datatype | Description                                         |
| :-------------------------- | :------- | :-------------------------------------------------- |
| **description**             | string   | The description of the comment.                     |
| **show_comment_to_clients** | boolean  | Boolean to show the comments to contacts in portal. |

### Query Parameters

| Parameter           | Datatype | Description                            |
| :------------------ | :------- | :------------------------------------- |
| **organization_id** | string   | **(Required)** ID of the organization. |

---

## Delete a comment

Delete an estimate comment.
`OAuth Scope : ZohoBooks.estimates.DELETE`

**Method:** `DELETE`
**Endpoint:** `/estimates/{estimate_id}/comments/{comment_id}`

### Path Parameters

| Parameter       | Datatype | Description                                       |
| :-------------- | :------- | :------------------------------------------------ |
| **estimate_id** | string   | **(Required)** Unique identifier of the estimate. |
| **comment_id**  | string   | **(Required)** Unique identifier of the comment.  |

### Query Parameters

| Parameter           | Datatype | Description                            |
| :------------------ | :------- | :------------------------------------- |
| **organization_id** | string   | **(Required)** ID of the organization. |