# Sales Order

A sales order is a financial document that confirms an impending sale. It is raised when an initial estimate is approved and the transaction is underway, and details the exact quantity, price and delivery details of the products or services being sold.

### Attributes

| Attribute                                                                   | Datatype | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| :-------------------------------------------------------------------------- | :------- | :-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **salesorder_id**                                                           | string   | ID of the Sales Order                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| **documents**                                                               | array    | Array of attached documents' IDs and names.                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| **is_pre_gst**                                                              | boolean  | **India Only**: Applicable for transactions that fall before july 1, 2017                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| **gst_no**                                                                  | string   | **India Only**: 15 digit GST identification number of the customer.                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| **gst_treatment**                                                           | string   | **India Only**: Choose whether the contact is GST registered/unregistered/consumer/overseas. Allowed values are `business_gst`, `business_none`, `overseas`, `consumer`.                                                                                                                                                                                                                                                                                                                                        |
| **place_of_supply**                                                         | string   | **India/GCC Only**: Place where the goods/services are supplied to. (If not given, `place of contact` given for the contact will be taken).                                                                                                                                                                                                                                                                                                                                                                     |
| **vat_treatment**                                                           | string   | **UK Only**: (Optional) VAT treatment for the sales order. VAT treatment denotes the location of the customer, if the customer resides in UK then the VAT treatment is `uk`. If the customer is in an EU country & VAT registered, you are resides in Northen Ireland and purchasing Goods then his VAT treatment is `eu_vat_registered` and if he resides outside the UK then his VAT treatment is `overseas`(For Pre Brexit, this can be split as `eu_vat_registered`, `eu_vat_not_registered` and `non_eu`). |
| **tax_treatment**                                                           | string   | **GCC/Mexico/Kenya/South Africa**: VAT treatment for the sales order.                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| **zcrm_potential_id**                                                       | string   | Unique identifier linking the sales order to a Zoho CRM potential record.                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| **zcrm_potential_name**                                                     | string   | Descriptive name of the Zoho CRM potential record associated with this sales order.                                                                                                                                                                                                                                                                                                                                                                                                                             |
| **salesorder_number**                                                       | string   | Unique alphanumeric identifier for the sales order entity. Required when automatic numbering is disabled in organization settings. Must be unique within the organization and follows the configured numbering sequence pattern for sales order identification and tracking.                                                                                                                                                                                                                                    |
| **date**                                                                    | string   | Date when the sales order was created in YYYY-MM-DD format. This date affects order processing timelines, delivery schedules, payment terms calculation, and appears on customer-facing documents and internal reports.                                                                                                                                                                                                                                                                                         |
| **status**                                                                  | string   | Status of the Sales Order                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| **shipment_date**                                                           | string   | Expected or actual date when goods will be shipped to the customer in YYYY-MM-DD format. Used for delivery planning, customer communication, inventory management, and tracking order fulfillment timelines.                                                                                                                                                                                                                                                                                                    |
| **reference_number**                                                        | string   | External reference identifier for cross-referencing with customer purchase orders, internal tracking systems, or third-party applications. Used for order reconciliation, customer communication, and integration with external business systems and workflows.                                                                                                                                                                                                                                                 |
| **customer_id**                                                             | string   | Unique identifier for the customer receiving the sales order. This ID links the order to a specific customer account and determines billing information, payment terms, pricing rules, and tax calculations based on customer settings. Can be fetched from the Get Contacts API or retrieved from existing customer records in your organization.                                                                                                                                                              |
| **customer_name**                                                           | string   | Name of the customer associated with the Sales Order                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| **contact_persons_associated**                                              | array    | Contact Persons associated with the transaction.                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| **contact_persons_associated.contact_person_id**                            | long     | Unique ID of the Contact Person.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| **contact_persons_associated.contact_person_name**                          | string   | Name of the Contact Person                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| **contact_persons_associated.first_name**                                   | string   | First Name of the Contact Person.                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| **contact_persons_associated.last_name**                                    | string   | Last name of the Contact Person.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| **contact_persons_associated.contact_person_email**                         | string   | Email ID of the Contact Person.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| **contact_persons_associated.phone**                                        | string   | Phone Number of the Contact Person.                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| **contact_persons_associated.mobile**                                       | string   | Mobile Number of the Contact Person.                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| **contact_persons_associated.communication_preference**                     | object   | Preferred modes of communication for the contact person at transaction level.                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| **contact_persons_associated.communication_preference.is_email_enabled**    | boolean  | Used to check if Email communication preference is enabled for the contact person at transaction level.                                                                                                                                                                                                                                                                                                                                                                                                         |
| **contact_persons_associated.communication_preference.is_sms_enabled**      | boolean  | **SMS integration only**: Used to check if SMS communication preference is enabled for the contact person at transaction level.                                                                                                                                                                                                                                                                                                                                                                                 |
| **contact_persons_associated.communication_preference.is_whatsapp_enabled** | boolean  | **WhatsApp integration only**: Used to check if WhatsApp communication preference is enabled for the contact person at transaction level.                                                                                                                                                                                                                                                                                                                                                                       |
| **currency_id**                                                             | string   | Unique identifier for the currency used in the sales order transaction. Determines pricing display, exchange rate calculations, and affects financial reporting. If not specified, the organization default currency will be used automatically. Can be fetched from the Get Currencies API or retrieved from your organization currency settings.                                                                                                                                                              |
| **currency_code**                                                           | string   | Code of the Currency involved in the Sales Order                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| **currency_symbol**                                                         | string   | Currency symbol of the currency involved in the Sales Order.                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| **exchange_rate**                                                           | double   | Currency conversion rate from the transaction currency to the organization base currency. Required for multi-currency transactions to ensure accurate financial reporting, profit calculations, and tax computations in the base currency denomination.                                                                                                                                                                                                                                                         |
| **discount_amount**                                                         | double   | Discount amount of the Sales Order.                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| **discount**                                                                | string   | Discount value applied to the sales order total, specified as either percentage or absolute amount. Supports decimal precision and affects final pricing calculations, tax computations, and financial reporting. Format: percentage (e.g., "12.5%") or amount (e.g., "190").                                                                                                                                                                                                                                   |
| **discount_applied_on_amount**                                              | integer  | Amount on which discount is applied.                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| **is_discount_before_tax**                                                  | boolean  | Boolean flag determining the sequence of discount application in tax calculations. When true, discount is applied before tax computation; when false, discount is applied after tax calculation. Affects final pricing accuracy and tax compliance reporting.                                                                                                                                                                                                                                                   |
| **discount_type**                                                           | string   | Classification of discount application scope within the sales order. `entity_level` applies discount to the entire order total, while `item_level` applies discount to individual line items. Determines discount calculation methodology and affects pricing structure.                                                                                                                                                                                                                                        |
| **estimate_id**                                                             | string   | Unique identifier linking this sales order to its originating estimate document. Establishes audit trail continuity, enables estimate-to-order conversion tracking, and maintains historical reference for customer approval workflows and business process documentation.                                                                                                                                                                                                                                      |
| **delivery_method**                                                         | string   | Specification of the transportation and delivery mechanism for order fulfillment. Determines shipping costs, delivery timelines, carrier selection, and customer communication regarding order status and tracking information.                                                                                                                                                                                                                                                                                 |
| **delivery_method_id**                                                      | string   | ID of the delivery method.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| **is_inclusive_tax**                                                        | boolean  | **Not applicable for US/Canada**: Used to specify whether the line item rates are inclusive or exclusive of tax.                                                                                                                                                                                                                                                                                                                                                                                                |
| **location_id**                                                             | string   | Unique identifier for the business location entity. Specifies the organizational location where the sales order transaction is processed, affecting tax jurisdiction calculations, inventory allocation, reporting segmentation, and location-specific business rules enforcement. Can be retrieved from the Locations API.                                                                                                                                                                                     |
| **location_name**                                                           | string   | Name of the location.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| **line_items**                                                              | array    | Line items of a sales order.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| **line_items.item_order**                                                   | integer  | Order of the item in the list.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| **line_items.item_id**                                                      | string   | ID of the item.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| **line_items.rate**                                                         | double   | Rate of the line item.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| **line_items.name**                                                         | string   | Name of the line item.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| **line_items.description**                                                  | string   | Description of the line item.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| **line_items.quantity**                                                     | double   | Quantity of the line item.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| **line_items.product_type**                                                 | string   | Enter `goods` or `services`. **For SouthAfrica Edition**: `service`, `goods`, `capital_service` and `capital_goods`.                                                                                                                                                                                                                                                                                                                                                                                            |
| **line_items.hsn_or_sac**                                                   | string   | **India/South Africa/Kenya**: Add HSN/SAC code for your goods/services                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| **line_items.sat_item_key_code**                                            | string   | **Mexico Only**: Add SAT Item Key Code for your goods/services. Download the CFDI Catalogs.                                                                                                                                                                                                                                                                                                                                                                                                                     |
| **line_items.unitkey_code**                                                 | string   | **Mexico Only**: Add SAT Unit Key Code for your goods/services. Download the CFDI Catalogs.                                                                                                                                                                                                                                                                                                                                                                                                                     |
| **line_items.location_id**                                                  | string   | Unique identifier for the business location entity associated with the line item.                                                                                                                                                                                                                                                                                                                                                                                                                               |
| **line_items.location_name**                                                | string   | Name of the location associated with the line item.                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| **line_items.discount**                                                     | string   | Discount value applied to the sales order total, specified as either percentage or absolute amount. Supports decimal precision and affects final pricing calculations, tax computations, and financial reporting. Format: percentage (e.g., "12.5%") or amount (e.g., "190").                                                                                                                                                                                                                                   |
| **line_items.tax_id**                                                       | string   | ID of the tax or tax group applied                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| **line_items.tds_tax_id**                                                   | string   | **Mexico Only**: ID of the TDS tax or TDS tax group applied                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| **line_items.tags**                                                         | array    | Filter all your reports based on the tag                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| **line_items.tags.is_tag_mandatory**                                        | boolean  | Boolean to check if the tag is mandatory                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| **line_items.tags.tag_id**                                                  | string   | ID of the reporting tag                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| **line_items.tags.tag_name**                                                | string   | Name of the reporting tag                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| **line_items.tags.tag_option_id**                                           | string   | ID of the reporting tag's option                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| **line_items.tags.tag_option_name**                                         | string   | Name of the reporting tag's option                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| **line_items.unit**                                                         | string   | Unit of the line item e.g. kgs, Nos.                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| **line_items.item_custom_fields**                                           | array    | Custom fields for a sales order items.                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| **line_items.item_custom_fields.customfield_id**                            | long     | ID of the Custom Field                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| **line_items.item_custom_fields.index**                                     | integer  | Index of the Custom Field                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| **line_items.item_custom_fields.value**                                     | string   | Value of the Custom Field                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| **line_items.item_custom_fields.label**                                     | string   | Label of the Custom Field                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| **line_items.tax_exemption_id**                                             | string   | **India/US Only**: ID of the tax exemption applied                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| **line_items.tax_exemption_code**                                           | string   | **India/US/Mexico**: Code of Tax Exemption that is applied                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| **line_items.tax_treatment_code**                                           | string   | **GCC Only**: Specify reason for using out of scope.                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| **line_items.avatax_exempt_no**                                             | string   | **Avalara Integration Only**: Exemption certificate number of the customer.                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| **line_items.avatax_use_code**                                              | string   | **Avalara Integration Only**: Used to group like customers for exemption purposes. It is a custom value that links customers to a tax rule.                                                                                                                                                                                                                                                                                                                                                                     |
| **line_items.project_id**                                                   | string   | ID of the project                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| **shipping_charge**                                                         | double   | Additional cost associated with product delivery and logistics services. Applied to the sales order total and affects final pricing calculations, profit margins, and customer billing. Supports decimal precision for accurate cost allocation.                                                                                                                                                                                                                                                                |
| **adjustment**                                                              | double   | Manual modification amount applied to the sales order total for rounding corrections, special pricing arrangements, or other business-specific adjustments. Supports positive and negative values for additions or deductions from the order total.                                                                                                                                                                                                                                                             |
| **adjustment_description**                                                  | string   | Textual explanation for the adjustment amount applied to the sales order. Provides audit trail documentation, justification for pricing modifications, and contextual information for financial reporting and compliance verification purposes.                                                                                                                                                                                                                                                                 |
| **sub_total**                                                               | double   | Sub Total of the Sales Order                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| **tax_total**                                                               | double   | Tax Total of the Sales Order                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| **total**                                                                   | double   | Total of the Sales Order                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| **taxes**                                                                   | array    | List of taxes applied                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| **taxes.tax_id**                                                            | string   | ID of the tax or tax group applied                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| **taxes.tax_name**                                                          | string   | Name of the tax                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| **taxes.tax_amount**                                                        | double   | Amount of the tax                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| **price_precision**                                                         | integer  | Precision of the price                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| **is_emailed**                                                              | boolean  | Check if the Sales Order is emailed to the customer                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| **billing_address**                                                         | object   | Billing address of the customer. Contains address, street2, city, state, zip, country, fax, attention.                                                                                                                                                                                                                                                                                                                                                                                                          |
| **shipping_address**                                                        | object   | Shipping address of the customer. Contains address, street2, city, state, zip, country, fax, attention.                                                                                                                                                                                                                                                                                                                                                                                                         |
| **notes**                                                                   | string   | Free-form text field containing additional information, instructions, or comments related to the sales order. This field supports internal documentation, customer-specific requirements, special handling instructions, and inter-departmental communication for order processing workflows.                                                                                                                                                                                                                   |
| **terms**                                                                   | string   | Contractual terms and conditions governing the sales order transaction. Defines payment obligations, delivery specifications, warranty provisions, liability limitations, and other legal stipulations that establish the binding agreement between the organization and customer for this specific transaction.                                                                                                                                                                                                |
| **custom_fields**                                                           | array    | Custom fields for a sales order.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| **custom_fields.customfield_id**                                            | long     | ID of the Custom Field                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| **custom_fields.index**                                                     | integer  | Index of the Custom Field                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| **custom_fields.value**                                                     | string   | Value of the Custom Field                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| **custom_fields.label**                                                     | string   | Label of the Custom Field                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| **template_id**                                                             | string   | Unique identifier for the PDF document template used for sales order presentation. Determines document layout, branding elements, formatting specifications, and visual presentation standards for customer-facing documents and printed materials.                                                                                                                                                                                                                                                             |
| **template_name**                                                           | string   | Name of the template                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| **page_width**                                                              | string   | Page width of the template                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| **page_height**                                                             | string   | Page height of the template                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| **orientation**                                                             | string   | Orientation of the template                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| **template_type**                                                           | string   | Type of the template                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| **created_time**                                                            | string   | Creation Time of the Sales Order                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| **last_modified_time**                                                      | string   | Last Modified time of the Sales Order                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| **created_by_id**                                                           | string   | ID of the user who created the sales order                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| **attachment_name**                                                         | string   | Name of the attachment                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| **can_send_in_mail**                                                        | boolean  | Can the file be sent in mail.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| **salesperson_id**                                                          | string   | Unique identifier for the salesperson responsible for this sales order. Links the order to a specific sales representative customer relationship management, and sales reporting purposes.                                                                                                                                                                                                                                                                                                                      |
| **salesperson_name**                                                        | string   | Full name of the sales representative assigned to this sales order. Automatically populated when salesperson_id is specified.                                                                                                                                                                                                                                                                                                                                                                                   |
| **merchant_id**                                                             | string   | ID of the merchant                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| **merchant_name**                                                           | string   | Name of the merchant                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |

---

## Create a sales order

Create a sales order for your customer.
`OAuth Scope : ZohoBooks.salesorders.CREATE`

**Method**: POST
**Endpoint**: `/salesorders`

### Arguments

| Parameter                      | Datatype | Description                                                                                                                        |
| :----------------------------- | :------- | :--------------------------------------------------------------------------------------------------------------------------------- |
| **customer_id**                | string   | **(Required)** Unique identifier for the customer receiving the sales order.                                                       |
| **currency_id**                | string   | Unique identifier for the currency used in the sales order transaction.                                                            |
| **contact_persons_associated** | array    | Contact Persons associated with the transaction.                                                                                   |
| **date**                       | string   | Date when the sales order was created in YYYY-MM-DD format.                                                                        |
| **shipment_date**              | string   | Expected or actual date when goods will be shipped to the customer in YYYY-MM-DD format.                                           |
| **custom_fields**              | array    | Custom fields for a sales order.                                                                                                   |
| **place_of_supply**            | string   | **India/GCC Only:** Place where the goods/services are supplied to.                                                                |
| **salesperson_id**             | string   | Unique identifier for the salesperson responsible for this sales order.                                                            |
| **merchant_id**                | string   | ID of the merchant                                                                                                                 |
| **gst_treatment**              | string   | **India Only:** Choose whether the contact is GST registered/unregistered/consumer/overseas.                                       |
| **gst_no**                     | string   | **India Only:** 15 digit GST identification number of the customer.                                                                |
| **is_inclusive_tax**           | boolean  | **Not applicable for US/Canada:** Used to specify whether the line item rates are inclusive or exclusive of tax.                   |
| **location_id**                | string   | Unique identifier for the business location entity.                                                                                |
| **line_items**                 | array    | Line items of a sales order.                                                                                                       |
| **notes**                      | string   | Free-form text field containing additional information, instructions, or comments related to the sales order.                      |
| **terms**                      | string   | Contractual terms and conditions governing the sales order transaction.                                                            |
| **billing_address_id**         | string   | Unique identifier referencing the customer billing address entity.                                                                 |
| **shipping_address_id**        | string   | Unique identifier referencing the customer shipping address entity.                                                                |
| **crm_owner_id**               | string   | CRM Owner ID                                                                                                                       |
| **crm_custom_reference_id**    | string   | CRM Custom Reference ID                                                                                                            |
| **vat_treatment**              | string   | **UK Only:** VAT treatment for the sales order.                                                                                    |
| **tax_treatment**              | string   | **GCC/Mexico/Kenya/South Africa:** VAT treatment for the sales order.                                                              |
| **is_reverse_charge_applied**  | boolean  | **South Africa Only:** Used to specify whether the transaction is applicable for Domestic Reverse Charge (DRC) or not.             |
| **salesorder_number**          | string   | Unique alphanumeric identifier for the sales order entity. Required when automatic numbering is disabled in organization settings. |
| **reference_number**           | string   | External reference identifier for cross-referencing.                                                                               |
| **is_update_customer**         | boolean  | Boolean flag indicating whether customer billing address information should be synchronized with the sales order data.             |
| **discount**                   | string   | Discount value applied to the sales order total, specified as either percentage or absolute amount.                                |
| **exchange_rate**              | double   | Currency conversion rate from the transaction currency to the organization base currency.                                          |
| **salesperson_name**           | string   | Full name of the sales representative assigned to this sales order.                                                                |
| **notes_default**              | string   | Default Notes for the Sales Order                                                                                                  |
| **terms_default**              | string   | Default Terms of the Sales Order                                                                                                   |
| **tax_id**                     | string   | Tax ID for the Sales Order.                                                                                                        |
| **tax_authority_id**           | string   | **US Only:** ID of the tax authority.                                                                                              |
| **tax_exemption_id**           | string   | **India/US Only:** ID of the tax exemption applied                                                                                 |
| **tax_authority_name**         | string   | **US/Mexico Only:** Tax Authority's name.                                                                                          |
| **tax_exemption_code**         | string   | **India/US/Mexico:** Code of Tax Exemption that is applied                                                                         |
| **avatax_exempt_no**           | string   | **Avalara Integration:** Exemption certificate number of the customer.                                                             |
| **avatax_use_code**            | string   | **Avalara Integration:** Used to group like customers for exemption purposes.                                                      |
| **shipping_charge**            | double   | Additional cost associated with product delivery and logistics services.                                                           |
| **adjustment**                 | double   | Manual modification amount applied to the sales order total.                                                                       |
| **delivery_method**            | string   | Specification of the transportation and delivery mechanism for order fulfillment.                                                  |
| **estimate_id**                | string   | ID of the estimate associated with the Sales Order                                                                                 |
| **is_discount_before_tax**     | boolean  | Boolean flag determining the sequence of discount application in tax calculations.                                                 |
| **discount_type**              | string   | Classification of discount application scope within the sales order.                                                               |
| **adjustment_description**     | string   | Textual explanation for the adjustment amount applied to the sales order.                                                          |
| **pricebook_id**               | string   | Unique identifier for the pricing structure applied to the sales order.                                                            |
| **template_id**                | string   | Unique identifier for the PDF document template used for sales order presentation.                                                 |
| **documents**                  | array    | Array of documents                                                                                                                 |
| **zcrm_potential_id**          | string   | Unique identifier linking the sales order to a Zoho CRM potential record.                                                          |
| **zcrm_potential_name**        | string   | Descriptive name of the Zoho CRM potential record associated with this sales order.                                                |

### Query Parameters

| Parameter                         | Datatype | Description                                                                                           |
| :-------------------------------- | :------- | :---------------------------------------------------------------------------------------------------- |
| **organization_id**               | string   | **(Required)** ID of the organization                                                                 |
| **ignore_auto_number_generation** | boolean  | Ignore auto sales order number generation for this sales order. This mandates the sales order number. |
| **can_send_in_mail**              | boolean  | Can the file be sent in mail.                                                                         |
| **totalFiles**                    | integer  | Total number of files.                                                                                |
| **doc**                           | binary   | Document that is to be attached                                                                       |

---

## Update a sales order using a custom field's unique value

Update a sales order by providing its API name in the `X-Unique-Identifier-Key` header and its value in the `X-Unique-Identifier-Value` header.
`OAuth Scope : ZohoBooks.salesorders.UPDATE`

**Method**: PUT
**Endpoint**: `/salesorders`

### Headers

| Header                        | Datatype | Description                                                                        |
| :---------------------------- | :------- | :--------------------------------------------------------------------------------- |
| **X-Unique-Identifier-Key**   | string   | **(Required)** Unique CustomField Api Name                                         |
| **X-Unique-Identifier-Value** | string   | **(Required)** Unique CustomField Value                                            |
| **X-Upsert**                  | boolean  | If there is no record is found unique custom field value , will create new invoice |

### Arguments
*Same as Create a sales order arguments.*

### Query Parameters

| Parameter           | Datatype | Description                           |
| :------------------ | :------- | :------------------------------------ |
| **organization_id** | string   | **(Required)** ID of the organization |

---

## List sales orders

List all sales orders.
`OAuth Scope : ZohoBooks.salesorders.READ`

**Method**: GET
**Endpoint**: `/salesorders`

### Query Parameters

| Parameter              | Datatype | Description                                                                                                                                                                                              |
| :--------------------- | :------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **organization_id**    | string   | **(Required)** ID of the organization                                                                                                                                                                    |
| **sort_column**        | string   | Specify the column field for sorting sales order results. Options: `customer_name`, `salesorder_number`, `shipment_date`, `last_modified_time`, `reference_number`, `total`, `date`, and `created_time`. |
| **search_text**        | string   | General search parameter for cross-field text matching across sales order number, reference number, and customer name fields.                                                                            |
| **filter_by**          | string   | Filter sales order by status. Allowed Values: `Status.All`, `Status.Open`, `Status.Draft`, `Status.OverDue`, `Status.PartiallyInvoiced`, `Status.Invoiced`, `Status.Void` and `Status.Closed`.           |
| **salesorder_number**  | string   | Filter sales orders by sales order number. Variants: `startswith`, `not_in`, `in`, `contains`.                                                                                                           |
| **item_name**          | string   | Filter sales orders by line item name. Variants: `startswith`, `not_in`, `in`, `contains`.                                                                                                               |
| **item_id**            | string   | Filter sales orders by specific line item identifier.                                                                                                                                                    |
| **item_description**   | string   | Filter sales orders by line item description text. Variants: `startswith`, `not_in`, `in`, `contains`.                                                                                                   |
| **reference_number**   | string   | Filter sales orders by external reference number. Variants: `startswith`, `not_in`, `in`, `contains`.                                                                                                    |
| **customer_name**      | string   | Filter sales orders by customer name. Variants: `startswith`, `not_in`, `in`, `contains`.                                                                                                                |
| **total**              | double   | Filter sales orders by total amount. Variants: `start`, `end`, `less_than`, `less_equals`, `greater_than`, `greater_equals`.                                                                             |
| **date**               | string   | Filter sales orders by creation date. Variants: `start`, `end`, `before`, `after`. Format: `yyyy-mm-dd`.                                                                                                 |
| **shipment_date**      | string   | Search sales order by sales order shipment date. Variants: `start`, `end`, `before`, `after`. Format: `yyyy-mm-dd`.                                                                                      |
| **status**             | string   | Search sales order by sales order status. Allowed Values: `draft`, `open`, `invoiced`, `partially_invoiced`, `void` and `overdue`.                                                                       |
| **customer_id**        | string   | Filter sales orders by specific customer identifier.                                                                                                                                                     |
| **salesperson_id**     | string   | Filter sales orders by specific sales representative identifier.                                                                                                                                         |
| **salesorder_ids**     | string   | ID's of the salesorder [Comma seperated values].                                                                                                                                                         |
| **zcrm_potential_id**  | long     | Potential ID of a Deal in CRM.                                                                                                                                                                           |
| **last_modified_time** | string   | Last Modified time of the Sales Order                                                                                                                                                                    |
| **accept**             | string   | Get the details of a particular sales order in formats such as json/ pdf/ html. Allowed Values: `json`, `csv`, `xml`, `xls`, `xlsx`, `pdf`, `jhtml`, `html`.                                             |
| **print**              | boolean  | Print the exported pdf. It will be used when accept = pdf and atleast one value in salesorder_ids.                                                                                                       |
| **customview_id**      | string   | ID of the customview                                                                                                                                                                                     |
| **page**               | integer  | Specify the page number for paginated results retrieval. Default value is 1.                                                                                                                             |
| **per_page**           | integer  | Specify the maximum number of sales order records to return per page. Default value is 200.                                                                                                              |

---

## Update a sales order

Update an existing sales order.
`OAuth Scope : ZohoBooks.salesorders.UPDATE`

**Method**: PUT
**Endpoint**: `/salesorders/{salesorder_id}`

### Path Parameters

| Parameter         | Datatype | Description                                          |
| :---------------- | :------- | :--------------------------------------------------- |
| **salesorder_id** | string   | **(Required)** Unique identifier of the sales order. |

### Arguments
*Same as Create a sales order arguments.*

### Query Parameters

| Parameter                         | Datatype | Description                                                                                           |
| :-------------------------------- | :------- | :---------------------------------------------------------------------------------------------------- |
| **organization_id**               | string   | **(Required)** ID of the organization                                                                 |
| **ignore_auto_number_generation** | boolean  | Ignore auto sales order number generation for this sales order. This mandates the sales order number. |
| **can_send_in_mail**              | boolean  | Can the file be sent in mail.                                                                         |
| **totalFiles**                    | integer  | Total number of files.                                                                                |
| **doc**                           | binary   | Document that is to be attached                                                                       |

---

## Get a sales order

Get the details of a sales order.
`OAuth Scope : ZohoBooks.salesorders.READ`

**Method**: GET
**Endpoint**: `/salesorders/{salesorder_id}`

### Path Parameters

| Parameter         | Datatype | Description                                          |
| :---------------- | :------- | :--------------------------------------------------- |
| **salesorder_id** | string   | **(Required)** Unique identifier of the sales order. |

### Query Parameters

| Parameter           | Datatype | Description                                                                     |
| :------------------ | :------- | :------------------------------------------------------------------------------ |
| **organization_id** | string   | **(Required)** ID of the organization                                           |
| **print**           | boolean  | Print the exported pdf.                                                         |
| **accept**          | string   | Get the details of a particular sales order in formats such as json/ pdf/ html. |

---

## Delete a sales order

Delete an existing sales order. Invoiced sales order cannot be deleted.
`OAuth Scope : ZohoBooks.salesorders.DELETE`

**Method**: DELETE
**Endpoint**: `/salesorders/{salesorder_id}`

### Path Parameters

| Parameter         | Datatype | Description                                          |
| :---------------- | :------- | :--------------------------------------------------- |
| **salesorder_id** | string   | **(Required)** Unique identifier of the sales order. |

### Query Parameters

| Parameter           | Datatype | Description                           |
| :------------------ | :------- | :------------------------------------ |
| **organization_id** | string   | **(Required)** ID of the organization |

---

## Update custom field in existing salesorders

Update the value of the custom field in existing salesorders.
`OAuth Scope : ZohoBooks.salesorders.UPDATE`

**Method**: PUT
**Endpoint**: `/salesorder/{salesorder_id}/customfields`

### Arguments

| Parameter          | Datatype | Description               |
| :----------------- | :------- | :------------------------ |
| **customfield_id** | long     | ID of the Custom Field    |
| **index**          | integer  | Index of the Custom Field |
| **value**          | string   | Value of the Custom Field |
| **label**          | string   | Label of the Custom Field |

### Path Parameters

| Parameter         | Datatype | Description                                          |
| :---------------- | :------- | :--------------------------------------------------- |
| **salesorder_id** | string   | **(Required)** Unique identifier of the sales order. |

### Query Parameters

| Parameter           | Datatype | Description                           |
| :------------------ | :------- | :------------------------------------ |
| **organization_id** | string   | **(Required)** ID of the organization |

---

## Mark a sales order as open

Mark a draft sales order as open.
`OAuth Scope : ZohoBooks.salesorders.CREATE`

**Method**: POST
**Endpoint**: `/salesorders/{salesorder_id}/status/open`

### Path Parameters

| Parameter         | Datatype | Description                                          |
| :---------------- | :------- | :--------------------------------------------------- |
| **salesorder_id** | string   | **(Required)** Unique identifier of the sales order. |

### Query Parameters

| Parameter           | Datatype | Description                           |
| :------------------ | :------- | :------------------------------------ |
| **organization_id** | string   | **(Required)** ID of the organization |

---

## Mark a sales order as void

Mark a sales order as void.
`OAuth Scope : ZohoBooks.salesorders.CREATE`

**Method**: POST
**Endpoint**: `/salesorders/{salesorder_id}/status/void`

### Arguments

| Parameter  | Datatype | Description                                                   |
| :--------- | :------- | :------------------------------------------------------------ |
| **reason** | string   | Reason to convert sales order as void . `Maximum Length: 500` |

### Path Parameters

| Parameter         | Datatype | Description                                          |
| :---------------- | :------- | :--------------------------------------------------- |
| **salesorder_id** | string   | **(Required)** Unique identifier of the sales order. |

### Query Parameters

| Parameter           | Datatype | Description                           |
| :------------------ | :------- | :------------------------------------ |
| **organization_id** | string   | **(Required)** ID of the organization |

---

## Update a sales order sub status

Update a sales order sub status.
`OAuth Scope : ZohoBooks.salesorders.CREATE`

**Method**: POST
**Endpoint**: `/salesorders/{salesorder_id}/substatus/{status_code}`

### Path Parameters

| Parameter         | Datatype | Description                                                |
| :---------------- | :------- | :--------------------------------------------------------- |
| **salesorder_id** | string   | **(Required)** Unique identifier of the sales order.       |
| **status_code**   | string   | **(Required)** Unique code of the status of a sales order. |

### Query Parameters

| Parameter           | Datatype | Description                           |
| :------------------ | :------- | :------------------------------------ |
| **organization_id** | string   | **(Required)** ID of the organization |

---

## Email a sales order

Email a sales order to the customer.
`OAuth Scope : ZohoBooks.salesorders.CREATE`

**Method**: POST
**Endpoint**: `/salesorders/{salesorder_id}/email`

### Arguments

| Parameter                  | Datatype | Description                                                         |
| :------------------------- | :------- | :------------------------------------------------------------------ |
| **from_address_id**        | string   | From Address of the Email Address                                   |
| **send_from_org_email_id** | boolean  | Boolean to trigger the email from the organization's email address. |
| **to_mail_ids**            | array    | **(Required)** Array of email address of the recipients.            |
| **cc_mail_ids**            | array    | Array of email address of the recipients to be CC ed.               |
| **bcc_mail_ids**           | array    | Array of email address of the recipients to be BCC ed.              |
| **subject**                | string   | **(Required)** Subject of the mail.                                 |
| **documents**              | binary   | Documents of the Sales Order                                        |
| **invoice_id**             | string   | ID of the invoice                                                   |
| **body**                   | string   | **(Required)** Body of the mail.                                    |

### Path Parameters

| Parameter         | Datatype | Description                                          |
| :---------------- | :------- | :--------------------------------------------------- |
| **salesorder_id** | string   | **(Required)** Unique identifier of the sales order. |

### Query Parameters

| Parameter           | Datatype | Description                                       |
| :------------------ | :------- | :------------------------------------------------ |
| **organization_id** | string   | **(Required)** ID of the organization             |
| **salesorder_id**   | string   | ID of the Sales Order                             |
| **attachments**     | binary   | Attachments of the Sales Order                    |
| **send_attachment** | boolean  | Send the sales order attachment a with the email. |
| **file_name**       | string   | Name of the file.                                 |

---

## Get sales order email content

Get the email content of a sales order.
`OAuth Scope : ZohoBooks.salesorders.READ`

**Method**: GET
**Endpoint**: `/salesorders/{salesorder_id}/email`

### Path Parameters

| Parameter         | Datatype | Description                                          |
| :---------------- | :------- | :--------------------------------------------------- |
| **salesorder_id** | string   | **(Required)** Unique identifier of the sales order. |

### Query Parameters

| Parameter             | Datatype | Description                                               |
| :-------------------- | :------- | :-------------------------------------------------------- |
| **organization_id**   | string   | **(Required)** ID of the organization                     |
| **email_template_id** | string   | Get the email content based on a specific email template. |

---

## Submit a sales order for approval

Submit a sales order for approval.
`OAuth Scope : ZohoBooks.salesorders.CREATE`

**Method**: POST
**Endpoint**: `/salesorders/{salesorder_id}/submit`

### Path Parameters

| Parameter         | Datatype | Description                                          |
| :---------------- | :------- | :--------------------------------------------------- |
| **salesorder_id** | string   | **(Required)** Unique identifier of the sales order. |

### Query Parameters

| Parameter           | Datatype | Description                           |
| :------------------ | :------- | :------------------------------------ |
| **organization_id** | string   | **(Required)** ID of the organization |

---

## Approve a sales order.

Approve a sales order.
`OAuth Scope : ZohoBooks.salesorders.CREATE`

**Method**: POST
**Endpoint**: `/salesorders/{salesorder_id}/approve`

### Path Parameters

| Parameter         | Datatype | Description                                          |
| :---------------- | :------- | :--------------------------------------------------- |
| **salesorder_id** | string   | **(Required)** Unique identifier of the sales order. |

### Query Parameters

| Parameter           | Datatype | Description                           |
| :------------------ | :------- | :------------------------------------ |
| **organization_id** | string   | **(Required)** ID of the organization |

---

## Bulk export sales orders

Maximum of 25 sales orders can be exported in a single pdf.
`OAuth Scope : ZohoBooks.salesorders.READ`

**Method**: GET
**Endpoint**: `/salesorders/pdf`

### Query Parameters

| Parameter           | Datatype | Description                                                          |
| :------------------ | :------- | :------------------------------------------------------------------- |
| **organization_id** | string   | **(Required)** ID of the organization                                |
| **estimate_ids**    | string   | **(Required)** Comma separated estimate ids which are to be emailed. |

---

## Bulk print sales orders

Export sales orders as pdf and print them. Maximum of 25 sales orders can be printed.
`OAuth Scope : ZohoBooks.salesorders.READ`

**Method**: GET
**Endpoint**: `/salesorders/print`

### Query Parameters

| Parameter           | Datatype | Description                                                          |
| :------------------ | :------- | :------------------------------------------------------------------- |
| **organization_id** | string   | **(Required)** ID of the organization                                |
| **estimate_ids**    | string   | **(Required)** Comma separated estimate ids which are to be emailed. |

---

## Update billing address

Updates the billing address for this sales order alone.
`OAuth Scope : ZohoBooks.salesorders.UPDATE`

**Method**: PUT
**Endpoint**: `/salesorders/{salesorder_id}/address/billing`

### Arguments

| Parameter              | Datatype | Description                                                                                                            |
| :--------------------- | :------- | :--------------------------------------------------------------------------------------------------------------------- |
| **address**            | string   | Address                                                                                                                |
| **city**               | string   | City of the address                                                                                                    |
| **state**              | string   | State of the Address                                                                                                   |
| **zip**                | string   | ZIP Code of the Address                                                                                                |
| **country**            | string   | Country of the Address                                                                                                 |
| **phone**              | string   | Phone Number of the Contact Person.                                                                                    |
| **fax**                | string   | Fax Number                                                                                                             |
| **attention**          | string   | Attention                                                                                                              |
| **is_one_off_address** | boolean  | Is one off address                                                                                                     |
| **is_update_customer** | boolean  | Boolean flag indicating whether customer billing address information should be synchronized with the sales order data. |
| **is_verified**        | boolean  | **Avalara Integration Only**: Check if the Address is verified                                                         |

### Path Parameters

| Parameter         | Datatype | Description                                          |
| :---------------- | :------- | :--------------------------------------------------- |
| **salesorder_id** | string   | **(Required)** Unique identifier of the sales order. |

### Query Parameters

| Parameter           | Datatype | Description                           |
| :------------------ | :------- | :------------------------------------ |
| **organization_id** | string   | **(Required)** ID of the organization |

---

## Update shipping address

Updates the shipping address for this sales order alone.
`OAuth Scope : ZohoBooks.salesorders.UPDATE`

**Method**: PUT
**Endpoint**: `/salesorders/{salesorder_id}/address/shipping`

### Arguments

| Parameter              | Datatype | Description                                                                                                            |
| :--------------------- | :------- | :--------------------------------------------------------------------------------------------------------------------- |
| **address**            | string   | Address                                                                                                                |
| **city**               | string   | City of the address                                                                                                    |
| **state**              | string   | State of the Address                                                                                                   |
| **zip**                | string   | ZIP Code of the Address                                                                                                |
| **country**            | string   | Country of the Address                                                                                                 |
| **fax**                | string   | Fax Number                                                                                                             |
| **attention**          | string   | Attention                                                                                                              |
| **is_one_off_address** | boolean  | Is one off address                                                                                                     |
| **is_update_customer** | boolean  | Boolean flag indicating whether customer billing address information should be synchronized with the sales order data. |
| **is_verified**        | boolean  | **Avalara Integration Only**: Check if the Address is verified                                                         |

### Path Parameters

| Parameter         | Datatype | Description                                          |
| :---------------- | :------- | :--------------------------------------------------- |
| **salesorder_id** | string   | **(Required)** Unique identifier of the sales order. |

### Query Parameters

| Parameter           | Datatype | Description                           |
| :------------------ | :------- | :------------------------------------ |
| **organization_id** | string   | **(Required)** ID of the organization |

---

## List sales order templates

Get all sales order pdf templates.
`OAuth Scope : ZohoBooks.salesorders.READ`

**Method**: GET
**Endpoint**: `/salesorders/templates`

### Query Parameters

| Parameter           | Datatype | Description                           |
| :------------------ | :------- | :------------------------------------ |
| **organization_id** | string   | **(Required)** ID of the organization |

---

## Update sales order template

Update the pdf template associated with the sales order.
`OAuth Scope : ZohoBooks.salesorders.UPDATE`

**Method**: PUT
**Endpoint**: `/salesorders/{salesorder_id}/templates/{template_id}`

### Path Parameters

| Parameter         | Datatype | Description                                                   |
| :---------------- | :------- | :------------------------------------------------------------ |
| **salesorder_id** | string   | **(Required)** Unique identifier of the sales order.          |
| **template_id**   | string   | **(Required)** Unique identifier of the sales order template. |

### Query Parameters

| Parameter           | Datatype | Description                           |
| :------------------ | :------- | :------------------------------------ |
| **organization_id** | string   | **(Required)** ID of the organization |

---

## Add attachment to a sales order

Attach a file to a sales order.
`OAuth Scope : ZohoBooks.salesorders.CREATE`

**Method**: POST
**Endpoint**: `/salesorders/{salesorder_id}/attachment`

### Path Parameters

| Parameter         | Datatype | Description                                          |
| :---------------- | :------- | :--------------------------------------------------- |
| **salesorder_id** | string   | **(Required)** Unique identifier of the sales order. |

### Query Parameters

| Parameter            | Datatype | Description                                                      |
| :------------------- | :------- | :--------------------------------------------------------------- |
| **organization_id**  | string   | **(Required)** ID of the organization                            |
| **attachment**       | binary   | The file that is to be added as an Attachment in the Sales Order |
| **can_send_in_mail** | boolean  | Can the file be sent in mail.                                    |
| **doc**              | binary   | Document that is to be attached                                  |
| **totalFiles**       | integer  | Total number of files.                                           |
| **document_ids**     | string   | ID's of the document                                             |

---

## Update attachment preference

Set whether you want to send the attached file while emailing the sales order.
`OAuth Scope : ZohoBooks.salesorders.UPDATE`

**Method**: PUT
**Endpoint**: `/salesorders/{salesorder_id}/attachment`

### Path Parameters

| Parameter         | Datatype | Description                                          |
| :---------------- | :------- | :--------------------------------------------------- |
| **salesorder_id** | string   | **(Required)** Unique identifier of the sales order. |

### Query Parameters

| Parameter            | Datatype | Description                                  |
| :------------------- | :------- | :------------------------------------------- |
| **organization_id**  | string   | **(Required)** ID of the organization        |
| **can_send_in_mail** | boolean  | **(Required)** Can the file be sent in mail. |

---

## Get a sales order attachment

Returns the file attached to the sales order.
`OAuth Scope : ZohoBooks.salesorders.READ`

**Method**: GET
**Endpoint**: `/salesorders/{salesorder_id}/attachment`

### Path Parameters

| Parameter         | Datatype | Description                                          |
| :---------------- | :------- | :--------------------------------------------------- |
| **salesorder_id** | string   | **(Required)** Unique identifier of the sales order. |

### Query Parameters

| Parameter           | Datatype | Description                                     |
| :------------------ | :------- | :---------------------------------------------- |
| **organization_id** | string   | **(Required)** ID of the organization           |
| **preview**         | boolean  | Check if preview of the Sales Order is required |
| **inline**          | boolean  | Check if inline response is required            |

---

## Delete an attachment

Delete the file attached to the sales order.
`OAuth Scope : ZohoBooks.salesorders.DELETE`

**Method**: DELETE
**Endpoint**: `/salesorders/{salesorder_id}/attachment`

### Path Parameters

| Parameter         | Datatype | Description                                          |
| :---------------- | :------- | :--------------------------------------------------- |
| **salesorder_id** | string   | **(Required)** Unique identifier of the sales order. |

### Query Parameters

| Parameter           | Datatype | Description                           |
| :------------------ | :------- | :------------------------------------ |
| **organization_id** | string   | **(Required)** ID of the organization |

---

## Add comment

Add a comment for a sales order.
`OAuth Scope : ZohoBooks.salesorders.CREATE`

**Method**: POST
**Endpoint**: `/salesorders/{salesorder_id}/comments`

### Arguments

| Parameter       | Datatype | Description                     |
| :-------------- | :------- | :------------------------------ |
| **description** | string   | The description of the comment. |

### Path Parameters

| Parameter         | Datatype | Description                                          |
| :---------------- | :------- | :--------------------------------------------------- |
| **salesorder_id** | string   | **(Required)** Unique identifier of the sales order. |

### Query Parameters

| Parameter           | Datatype | Description                           |
| :------------------ | :------- | :------------------------------------ |
| **organization_id** | string   | **(Required)** ID of the organization |

---

## List sales order comments & history

Get the complete history and comments of sales order.
`OAuth Scope : ZohoBooks.salesorders.READ`

**Method**: GET
**Endpoint**: `/salesorders/{salesorder_id}/comments`

### Path Parameters

| Parameter         | Datatype | Description                                          |
| :---------------- | :------- | :--------------------------------------------------- |
| **salesorder_id** | string   | **(Required)** Unique identifier of the sales order. |

### Query Parameters

| Parameter           | Datatype | Description                           |
| :------------------ | :------- | :------------------------------------ |
| **organization_id** | string   | **(Required)** ID of the organization |

---

## Update comment

Update existing comment of a sales order.
`OAuth Scope : ZohoBooks.salesorders.UPDATE`

**Method**: PUT
**Endpoint**: `/salesorders/{salesorder_id}/comments/{comment_id}`

### Arguments

| Parameter       | Datatype | Description                     |
| :-------------- | :------- | :------------------------------ |
| **description** | string   | The description of the comment. |

### Path Parameters

| Parameter         | Datatype | Description                                          |
| :---------------- | :------- | :--------------------------------------------------- |
| **salesorder_id** | string   | **(Required)** Unique identifier of the sales order. |
| **comment_id**    | string   | **(Required)** Unique identifier of the comment.     |

### Query Parameters

| Parameter           | Datatype | Description                           |
| :------------------ | :------- | :------------------------------------ |
| **organization_id** | string   | **(Required)** ID of the organization |

---

## Delete a comment

Delete a sales order comment.
`OAuth Scope : ZohoBooks.salesorders.DELETE`

**Method**: DELETE
**Endpoint**: `/salesorders/{salesorder_id}/comments/{comment_id}`

### Path Parameters

| Parameter         | Datatype | Description                                          |
| :---------------- | :------- | :--------------------------------------------------- |
| **salesorder_id** | string   | **(Required)** Unique identifier of the sales order. |
| **comment_id**    | string   | **(Required)** Unique identifier of the comment.     |

### Query Parameters

| Parameter           | Datatype | Description                           |
| :------------------ | :------- | :------------------------------------ |
| **organization_id** | string   | **(Required)** ID of the organization |