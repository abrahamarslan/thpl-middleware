Here is the Markdown conversion of the "Recurring Bills" documentation:

# Recurring Bills

Recurring Bills are those bills that repeat itself after a fixed interval of time.

### End Points

| Method     | URL                                                 | Description                                                 |
| :--------- | :-------------------------------------------------- | :---------------------------------------------------------- |
| **POST**   | `/recurringbills`                                   | Create a recurring bill                                     |
| **PUT**    | `/recurringbills`                                   | Update a recurring bill using a custom field's unique value |
| **GET**    | `/recurringbills`                                   | List recurring bills                                        |
| **PUT**    | `/recurringbills/{recurring_bill_id}`               | Update a recurring bill                                     |
| **GET**    | `/recurring_bills/{recurring_bill_id}`              | Get a recurring bill                                        |
| **DELETE** | `/recurring_bills/{recurring_bill_id}`              | Delete a recurring bill                                     |
| **POST**   | `/recurringbills/{recurring_bill_id}/status/stop`   | Stop a recurring bill                                       |
| **POST**   | `/recurringbills/{recurring_bill_id}/status/resume` | Resume a recurring Bill                                     |
| **GET**    | `/recurringbills/{recurring_bill_id}/comments`      | List recurring bill history                                 |

---

## Attributes

| Attribute                         | Data Type | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| :-------------------------------- | :-------- | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **recurring_bill_id**             | string    | The unique identifier of the recurring bill.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| **vendor_id**                     | string    | ID of the vendor the bill has to be created.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| **vendor_name**                   | string    | Name of the Vendor                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| **status**                        | string    | Status of the Recurring Bill                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| **recurrence_name**               | string    | Name of the Recurring Bill. Max-length [100]                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| **currency_id**                   | string    | ID of the Currency                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| **currency_code**                 | string    | Code of the Currency                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| **currency_symbol**               | string    | Symbol of the Currency                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| **start_date**                    | string    | Start date of the recurring bill. Bills will not be generated for dates prior to the current date. Format [yyyy-mm-dd].                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| **end_date**                      | string    | Date on which recurring bill has to expire. Can be left as empty to run forever. Format [yyyy-mm-dd].                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| **source_of_supply**              | string    | Place from where the goods/services are supplied. (If not given, `place of contact` given for the contact will be taken). **[India Only]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| **place_of_supply**               | string    | The place of supply is where a transaction is considered to have occurred for VAT purposes. <br>Supported codes for UAE emirates are : <br>Abu Dhabi - `AB`,<br>Ajman - `AJ`,<br>Dubai - `DU`,<br>Fujairah - `FU`,<br>Ras al-Khaimah - `RA`,<br>Sharjah - `SH`,<br>Umm al-Quwain - `UM`.<br>Supported codes for the GCC countries are : <br>United Arab Emirates - `AE`,<br>Saudi Arabia - `SA`,<br>Bahrain - `BH`,<br>Kuwait - `KW`,<br>Oman - `OM`,<br>Qatar - `QA`. **[GCC Only]**                                                                                                                                                                 |
| **destination_of_supply**         | string    | Place where the goods/services are supplied to. (If not given, organisation's home state will be taken). **[India Only]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| **gst_treatment**                 | string    | Choose whether the contact is GST registered/unregistered/consumer/overseas. Allowed values are `business_gst` , `business_none` , `overseas` , `consumer`. **[India Only]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| **gst_no**                        | string    | 15 digit GST identification number of the vendor. **[India Only]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| **tax_treatment**                 | string    | VAT treatment for the bill. Choose whether the vendor falls under: `vat_registered`,`vat_not_registered`,`gcc_vat_not_registered`,`gcc_vat_registered`,`non_gcc`.<br>`dz_vat_registered` and `dz_vat_not_registered` are supported only for **UAE**.<br>`home_country_mexico`,`border_region_mexico`,`non_mexico` supported only for **MX**.<br>**For Kenya Edition:** `vat_registered` ,`vat_not_registered` ,`non_kenya`(A business that is located outside Kenya).<br>**For SouthAfrica Edition:** `vat_registered`, `vat_not_registered`, `overseas`(A business that is located outside SouthAfrica). **[GCC, Mexico, Kenya, South Africa Only]** |
| **vat_treatment**                 | string    | (Optional) VAT treatment for the bill. VAT treatment denotes the location of the vendor, if the vendor resides in UK then the VAT treatment is `uk`. If the vendor is in an EU country & VAT registered, you are resides in Northen Ireland and purchasing Goods then his VAT treatment is `eu_vat_registered` and if he resides outside the UK then his VAT treatment is `overseas`(For Pre Brexit, this can be split as `eu_vat_registered`, `eu_vat_not_registered` and `non_eu`). **[United Kingdom Only]**                                                                                                                                       |
| **vat_reg_no**                    | string    | **For UK Edition:** VAT Registration number of a contact with length should be between 2 and 12 characters.<br> **For Avalara:** If you are doing sales in the European Union (EU) then provide VAT Registration Number of your customers here. This is used to calculate VAT for B2B sales, from Avalara. **[United Kingdom, Avalara Integration Only]**                                                                                                                                                                                                                                                                                             |
| **is_abn_quoted**                 | string    | **[Australia Only]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| **abn**                           | string    | **[Australia Only]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| **is_reverse_charge_applied**     | boolean   | Applicable for transactions where you pay reverse charge. **[India Only]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| **pricebook_id**                  | string    | Enter ID of the price book.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| **pricebook_name**                | string    | Name of the price book                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| **is_inclusive_tax**              | boolean   | Used to specify whether the line item rates are inclusive or exclusive of tax. **[Not applicable for United States]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| **location_id**                   | string    | Location ID                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| **location_name**                 | string    | Name of the location                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| **line_items**                    | array     | Line items of a recurrence bill.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| **line_item_id**                  | string    | ID of the Line Item                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| **item_id**                       | string    | ID of the Item                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| **sku**                           | string    | SKU of the Item                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| **name**                          | string    |                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| **account_id**                    | string    | ID of the account associated with the line item.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| **account_name**                  | string    | Name of the Account                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| **image_document_id**             | string    | ID of the image document **[India Only]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| **reverse_charge_tax_id**         | string    | Reverse charge tax ID **[India, GCC, South Africa Only]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| **reverse_charge_tax_name**       | string    | Name of the reverse charge tax **[India Only]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| **reverse_charge_tax_percentage** | double    | Enter reverse charge percentage **[India Only]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| **reverse_charge_tax_amount**     | double    | Enter reverse charge amount **[India Only]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| **description**                   | string    | Description of the line item.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| **bcy_rate**                      | integer   | Rate in Base Currency of the Organization                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| **rate**                          | double    | Rate of the line item.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| **tags**                          | array     | Array of Tags                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| **quantity**                      | double    | Quantity of the line item.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| **tax_id**                        | string    | ID of the tax or tax group applied to the line item. **[Not applicable for United States]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| **tds_tax_id**                    | string    | TDS ID of the tax group applied to the line item **[Mexico Only]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| **tax_treatment_code**            | string    | Specify reason for using out of scope.<br>Supported values for **UAE** are `uae_same_tax_group`, `uae_reimbursed_expense` and `uae_others`.<br> Supported values for **Bahrain** are `bahrain_same_tax_group`, `bahrain_transfer_of_concern`, `bahrain_disbursement`, `bahrain_head_to_branch_transaction`, `bahrain_warranty_repair_services` and `bahrain_others`.<br> Supported values for **KSA** are `ksa_reimbursed_expense`. **[GCC Only]**                                                                                                                                                                                                    |
| **tax_exemption_id**              | string    | ID of the Tax Exemption Applied **[India, Australia, Canada Only]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| **tax_exemption_code**            | string    | Code of the Tax Exemption Applied **[India, Australia, Canada, Mexico Only]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| **tax_name**                      | string    | Name of the Tax                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| **tax_type**                      | string    | Type of tax                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| **tax_percentage**                | integer   | Percentage of Tax                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| **item_total**                    | integer   | Total of the Item                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| **item_total_inclusive_of_tax**   | double    | Total of the Item Inclusive of Tax                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| **item_order**                    | integer   |                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| **unit**                          | string    | Unit of the Item                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| **product_type**                  | string    | Type of the bill. This denotes whether the bill line item is to be treated as a goods or service purchase. This only need to be specified in case purchase order is not enabled. Allowed Values: `digital_service`, `goods` and `service`. **[Europe, United Kingdom Only]**                                                                                                                                                                                                                                                                                                                                                                          |
| **hsn_or_sac**                    | string    | Add HSN/SAC code for your goods/services **[India, Kenya, South Africa Only]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| **acquisition_vat_id**            | string    | (Optional) This is the ID of the tax applied in case this is an EU - goods purchase and acquisition VAT needs to be reported. **[United Kingdom, Europe Only]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| **acquisition_vat_name**          | string    | Name of the VAT Acquistion **[United Kingdom, Europe Only]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| **acquisition_vat_percentage**    | string    | Percentage of the VAT Acquistion **[United Kingdom, Europe Only]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| **acquisition_vat_amount**        | string    | Amount of the VAT Acquistion **[United Kingdom, Europe Only]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| **reverse_charge_vat_id**         | string    | (Optional) This is the ID of the tax applied in case this is a non UK - service purchase and reverse charge VAT needs to be reported. **[United Kingdom, Europe Only]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| **reverse_charge_vat_name**       | string    | Name of the Reverse Charge **[United Kingdom, Europe Only]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| **reverse_charge_vat_percentage** | string    | Percentage of the Reverse Charge **[United Kingdom, Europe Only]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| **reverse_charge_vat_amount**     | string    | Percentage of the Reverse Charge **[United Kingdom, Europe Only]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| **is_billable**                   | boolean   | Check if entity is Billable                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| **customer_id**                   | string    | ID of the Customer                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| **customer_name**                 | string    | Name of the Customer                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| **project_id**                    | string    | ID of the Project                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| **project_name**                  | string    | Name of the Project                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| **item_custom_fields**            | array     |                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| **is_tds_applied**                | boolean   | Check if TDS is applied **[India, Global, Australia Only]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| **notes**                         | string    | Notes for the Bill                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| **terms**                         | string    | Terms and Conditions for the Bill                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| **payment_terms**                 | integer   | Number Referring to Payment Terms                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| **payment_terms_label**           | string    | Label of the Payment Terms                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| **custom_fields**                 | array     |                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| **acquisition_vat_summary**       | array     | Summary of the VAT Acquistion **[United Kingdom, Europe Only]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| **reverse_charge_vat_summary**    | array     | Summary of the Reverse Charge **[United Kingdom, Europe Only]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| **acquisition_vat_total**         | double    | Total of the VAT Acquistion **[United Kingdom, Europe Only]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| **reverse_charge_vat_total**      | double    | Total of the Reverse Charge **[United Kingdom, Europe Only]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| **created_time**                  | string    | Created time of the bill                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| **created_by_id**                 | string    | Name of User who created the Bill                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| **last_modified_time**            | string    | Last Modified Time of the Bill                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| **discount**                      | string    | Discount applied to the recurrence. It can be either in % or in amount. E.g: 12.5% or 190.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| **discount_account_id**           | string    | ID of the account associated with the discount account.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| **is_discount_before_tax**        | boolean   | To specify discount applied in before /after tax.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |

---

## Create a recurring bill

Create a recurring bill.
**OAuth Scope :** `ZohoBooks.bills.CREATE`

### Arguments

| Argument                      | Type    | Required | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| :---------------------------- | :------ | :------- | :--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **vendor_id**                 | string  | Required | ID of the vendor the bill has to be created.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| **currency_id**               | string  | Optional | ID of the Currency                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| **recurrence_name**           | string  | Required | Name of the Recurring Bill. Max-length [100]                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| **start_date**                | string  | Required | Start date of the recurring bill. Bills will not be generated for dates prior to the current date. Format [yyyy-mm-dd].                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| **end_date**                  | string  | Optional | Date on which recurring bill has to expire. Can be left as empty to run forever. Format [yyyy-mm-dd].                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| **source_of_supply**          | string  | Optional | Place from where the goods/services are supplied. (If not given, `place of contact` given for the contact will be taken) **[India Only]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| **place_of_supply**           | string  | Optional | The place of supply is where a transaction is considered to have occurred for VAT purposes. For the supply of goods, the place of supply is the location of the goods when the supply occurs. For the supply of services, the place of supply should be where the supplier is established. (If not given, `place of contact` given for the contact will be taken)<br>Supported codes for UAE emirates are : <br>Abu Dhabi - `AB`,<br>Ajman - `AJ`,<br>Dubai - `DU`,<br>Fujairah - `FU`,<br>Ras al-Khaimah - `RA`,<br>Sharjah - `SH`,<br>Umm al-Quwain - `UM`.<br>Supported codes for the GCC countries are : <br>United Arab Emirates - `AE`,<br>Saudi Arabia - `SA`,<br>Bahrain - `BH`,<br>Kuwait - `KW`,<br>Oman - `OM`,<br>Qatar - `QA`. **[GCC Only]** |
| **destination_of_supply**     | string  | Optional | Place where the goods/services are supplied to. (If not given, organisation's home state will be taken) **[India Only]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| **gst_treatment**             | string  | Optional | Choose whether the contact is GST registered/unregistered/consumer/overseas. Allowed values are `business_gst` , `business_none` , `overseas` , `consumer`. **[India Only]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| **gst_no**                    | string  | Optional | 15 digit GST identification number of the vendor. **[India Only]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| **tax_treatment**             | string  | Optional | VAT treatment for the bill. Choose whether the vendor falls under: `vat_registered`,`vat_not_registered`,`gcc_vat_not_registered`,`gcc_vat_registered`,`non_gcc`.<br>`dz_vat_registered` and `dz_vat_not_registered` are supported only for **UAE**.<br>`home_country_mexico`,`border_region_mexico`,`non_mexico` supported only for **MX**.<br>**For Kenya Edition:** `vat_registered` ,`vat_not_registered` ,`non_kenya`(A business that is located outside Kenya).<br>**For SouthAfrica Edition:** `vat_registered`, `vat_not_registered`, `overseas`(A business that is located outside SouthAfrica). **[GCC, Mexico, Kenya, South Africa Only]**                                                                                                      |
| **vat_treatment**             | string  | Optional | (Optional) VAT treatment for the bill. VAT treatment denotes the location of the vendor, if the vendor resides in UK then the VAT treatment is `uk`. If the vendor is in an EU country & VAT registered, you are resides in Northen Ireland and purchasing Goods then his VAT treatment is `eu_vat_registered` and if he resides outside the UK then his VAT treatment is `overseas`(For Pre Brexit, this can be split as `eu_vat_registered`, `eu_vat_not_registered` and `non_eu`). **[United Kingdom Only]**                                                                                                                                                                                                                                            |
| **vat_reg_no**                | string  | Optional | **For UK Edition:** VAT Registration number of a contact with length should be between 2 and 12 characters.<br> **For Avalara:** If you are doing sales in the European Union (EU) then provide VAT Registration Number of your customers here. This is used to calculate VAT for B2B sales, from Avalara. **[United Kingdom, Avalara Integration Only]**                                                                                                                                                                                                                                                                                                                                                                                                  |
| **is_abn_quoted**             | string  | Optional | **[Australia Only]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| **abn**                       | string  | Optional | **[Australia Only]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| **is_reverse_charge_applied** | boolean | Optional | Applicable for transactions where you pay reverse charge **[India Only]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| **pricebook_id**              | string  | Optional | Enter ID of the price book.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| **is_inclusive_tax**          | boolean | Optional | Used to specify whether the line item rates are inclusive or exclusive of tax. **[Not applicable for United States]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| **location_id**               | string  | Optional | Location ID                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| **line_items**                | array   | Optional | Line items of a recurrence bill.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| **is_tds_applied**            | boolean | Optional | Check if TDS is applied **[India, Global, Australia Only]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| **notes**                     | string  | Optional | Notes for the Bill                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| **terms**                     | string  | Optional | Terms and Conditions for the Bill                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| **payment_terms**             | integer | Optional | Number Referring to Payment Terms                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| **payment_terms_label**       | string  | Optional | Label of the Payment Terms                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| **custom_fields**             | array   | Optional |                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| **discount**                  | string  | Optional | Discount applied to the recurrence. It can be either in % or in amount. E.g: 12.5% or 190.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| **discount_account_id**       | string  | Optional | ID of the account associated with the discount account.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| **is_discount_before_tax**    | boolean | Optional | To specify discount applied in before /after tax.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| **repeat_every**              | string  | Required | Description for repeat_every                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| **recurrence_frequency**      | string  | Required | Description for recurrence_frequency                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |

### Query Parameters

| Parameter           | Type   | Required | Description            |
| :------------------ | :----- | :------- | :--------------------- |
| **organization_id** | string | Required | ID of the organization |

### Request Example

```json
{
    "vendor_id": "460000000038029",
    "currency_id": "460000000000099",
    "recurrence_name": "Monthly Rental",
    "start_date": "2013-11-18",
    "end_date": "2013-12-18",
    "source_of_supply": "AP",
    "place_of_supply": "DU",
    "destination_of_supply": "TN",
    "gst_treatment": "business_gst",
    "gst_no": "22AAAAA0000A1Z5",
    "tax_treatment": "vat_registered",
    "vat_treatment": "string",
    "vat_reg_no": "string",
    "is_abn_quoted": "string",
    "abn": "string",
    "is_reverse_charge_applied": true,
    "pricebook_id": 460000000038090,
    "is_inclusive_tax": false,
    "location_id": "460000000038080",
    "line_items": [
        {
            "line_item_id": "460000000067009",
            "item_id": "460000000054135",
            "name": "string",
            "account_id": "460000000000403",
            "description": "string",
            "rate": 10,
            "hsn_or_sac": 80540,
            "reverse_charge_tax_id": 460000000038056,
            "location_id": "460000000038080",
            "quantity": 1,
            "tax_id": "460000000027005",
            "tds_tax_id": "460000000027001",
            "tax_treatment_code": "uae_others",
            "tax_exemption_id": "string",
            "tax_exemption_code": "string",
            "item_order": 1,
            "product_type": "string",
            "acquisition_vat_id": "string",
            "reverse_charge_vat_id": "string",
            "unit": "kgs",
            "tags": [
                {
                    "tag_id": "460000000054178",
                    "tag_option_id": "460000000054180"
                }
            ],
            "is_billable": false,
            "project_id": "string",
            "customer_id": "string",
            "item_custom_fields": [
                {
                    "custom_field_id": 0,
                    "index": 0,
                    "value": "string",
                    "label": "string"
                }
            ],
            "serial_numbers": [
                "string"
            ]
        }
    ],
    "is_tds_applied": true,
    "notes": "Thanks for your business.",
    "terms": "Terms and conditions apply.",
    "payment_terms": 0,
    "payment_terms_label": "Due on Receipt",
    "custom_fields": [
        {
            "index": 0,
            "value": "string"
        }
    ],
    "discount": "30%",
    "discount_account_id": "460000000000403",
    "is_discount_before_tax": true,
    "repeat_every": "",
    "recurrence_frequency": ""
}
```

### Response Example

```json
{
    "code": 0,
    "message": "success",
    "recurring_bill": {
        "recurring_bill_id": 982000000567240,
        "vendor_id": "460000000038029",
        "vendor_name": "string",
        "status": "active",
        "recurrence_name": "Monthly Rental",
        "currency_id": "460000000000099",
        "currency_code": "INR",
        "currency_symbol": "string",
        "start_date": "2013-11-18",
        "end_date": "2013-12-18",
        "source_of_supply": "AP",
        "place_of_supply": "DU",
        "destination_of_supply": "TN",
        "gst_treatment": "business_gst",
        "gst_no": "22AAAAA0000A1Z5",
        "tax_treatment": "vat_registered",
        "vat_treatment": "string",
        "vat_reg_no": "string",
        "is_abn_quoted": "string",
        "abn": "string",
        "is_reverse_charge_applied": true,
        "pricebook_id": 460000000038090,
        "pricebook_name": "string",
        "is_inclusive_tax": false,
        "location_id": "460000000038080",
        "location_name": "string",
        "line_items": [
            {
                "line_item_id": "460000000067009",
                "item_id": "460000000054135",
                "sku": "string",
                "name": "string",
                "account_id": "460000000000403",
                "account_name": "Other Expenses",
                "image_document_id": 460000000038067,
                "location_id": "460000000038080",
                "location_name": "string",
                "reverse_charge_tax_id": 460000000038056,
                "reverse_charge_tax_name": "inter",
                "reverse_charge_tax_percentage": 10,
                "reverse_charge_tax_amount": 100,
                "description": "string",
                "bcy_rate": 40,
                "rate": 10,
                "tags": [
                    {
                        "tag_id": "460000000054178",
                        "tag_option_id": "460000000054180"
                    }
                ],
                "quantity": 1,
                "tax_id": "460000000027005",
                "tds_tax_id": "460000000027001",
                "tax_treatment_code": "uae_others",
                "tax_exemption_id": "string",
                "tax_exemption_code": "string",
                "tax_name": "VAT (12.5%)",
                "tax_type": "tax",
                "tax_percentage": 0,
                "item_total": 40,
                "item_total_inclusive_of_tax": 40,
                "item_order": 1,
                "unit": "kgs",
                "product_type": "string",
                "hsn_or_sac": 80540,
                "acquisition_vat_id": "string",
                "acquisition_vat_name": "string",
                "acquisition_vat_percentage": "string",
                "acquisition_vat_amount": "string",
                "reverse_charge_vat_id": "string",
                "reverse_charge_vat_name": "string",
                "reverse_charge_vat_percentage": "string",
                "reverse_charge_vat_amount": "string",
                "is_billable": false,
                "customer_id": "string",
                "customer_name": "string",
                "project_id": "string",
                "project_name": "string",
                "item_custom_fields": [
                    {
                        "custom_field_id": 0,
                        "index": 0,
                        "value": "string",
                        "label": "string"
                    }
                ]
            }
        ],
        "is_tds_applied": true,
        "notes": "Thanks for your business.",
        "terms": "Terms and conditions apply.",
        "payment_terms": 0,
        "payment_terms_label": "Due on Receipt",
        "custom_fields": [
            {
                "custom_field_id": 0,
                "index": 0,
                "label": "string",
                "value": "string"
            }
        ],
        "acquisition_vat_summary": [
            {
                "tax_name": "VAT (12.5%)",
                "tax_amount": 1.25
            }
        ],
        "reverse_charge_vat_summary": [
            {
                "tax_name": "VAT (12.5%)",
                "tax_amount": 1.25
            }
        ],
        "acquisition_vat_total": 0.1,
        "reverse_charge_vat_total": 0.1,
        "created_time": "2013-09-11T17:18:32+0530",
        "created_by_id": "4600000053001",
        "last_modified_time": "2013-09-11T17:18:32+0530",
        "discount": "30%",
        "discount_account_id": "460000000000403",
        "is_discount_before_tax": true
    }
}
```

---

## Update a recurring bill using a custom field's unique value

A custom field will have unique values if it's configured to not accept duplicate values. Now, you can use that custom field's value to update a recurring bill by providing its API name in the X-Unique-Identifier-Key header and its value in the X-Unique-Identifier-Value header. Based on this value, the corresponding recurring bill will be retrieved and updated. Additionally, there is an optional X-Upsert header. If the X-Upsert header is true and the custom field's unique value is not found in any of the existing recurring bills, a new recurring bill will be created if the necessary payload details are available.
**OAuth Scope :** `ZohoBooks.settings.UPDATE`

### Arguments

| Argument                      | Type    | Required | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| :---------------------------- | :------ | :------- | :--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **recurring_bill_id**         | string  | Optional |                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| **vendor_id**                 | string  | Required | ID of the vendor the bill has to be created.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| **currency_id**               | string  | Optional | ID of the Currency                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| **status**                    | string  | Optional | Status of the Recurring Bill                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| **recurrence_name**           | string  | Required | Name of the Recurring Bill. Max-length [100]                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| **start_date**                | string  | Required | Start date of the recurring bill. Bills will not be generated for dates prior to the current date. Format [yyyy-mm-dd].                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| **end_date**                  | string  | Optional | Date on which recurring bill has to expire. Can be left as empty to run forever. Format [yyyy-mm-dd].                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| **source_of_supply**          | string  | Optional | Place from where the goods/services are supplied. (If not given, `place of contact` given for the contact will be taken) **[India Only]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| **place_of_supply**           | string  | Optional | The place of supply is where a transaction is considered to have occurred for VAT purposes. For the supply of goods, the place of supply is the location of the goods when the supply occurs. For the supply of services, the place of supply should be where the supplier is established. (If not given, `place of contact` given for the contact will be taken)<br>Supported codes for UAE emirates are : <br>Abu Dhabi - `AB`,<br>Ajman - `AJ`,<br>Dubai - `DU`,<br>Fujairah - `FU`,<br>Ras al-Khaimah - `RA`,<br>Sharjah - `SH`,<br>Umm al-Quwain - `UM`.<br>Supported codes for the GCC countries are : <br>United Arab Emirates - `AE`,<br>Saudi Arabia - `SA`,<br>Bahrain - `BH`,<br>Kuwait - `KW`,<br>Oman - `OM`,<br>Qatar - `QA`. **[GCC Only]** |
| **destination_of_supply**     | string  | Optional | Place where the goods/services are supplied to. (If not given, organisation's home state will be taken) **[India Only]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| **gst_treatment**             | string  | Optional | Choose whether the contact is GST registered/unregistered/consumer/overseas. Allowed values are `business_gst` , `business_none` , `overseas` , `consumer`. **[India Only]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| **gst_no**                    | string  | Optional | 15 digit GST identification number of the vendor. **[India Only]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| **tax_treatment**             | string  | Optional | VAT treatment for the bill. Choose whether the vendor falls under: `vat_registered`,`vat_not_registered`,`gcc_vat_not_registered`,`gcc_vat_registered`,`non_gcc`.<br>`dz_vat_registered` and `dz_vat_not_registered` are supported only for **UAE**.<br>`home_country_mexico`,`border_region_mexico`,`non_mexico` supported only for **MX**.<br>**For Kenya Edition:** `vat_registered` ,`vat_not_registered` ,`non_kenya`(A business that is located outside Kenya).<br>**For SouthAfrica Edition:** `vat_registered`, `vat_not_registered`, `overseas`(A business that is located outside SouthAfrica). **[GCC, Mexico, Kenya, South Africa Only]**                                                                                                      |
| **vat_treatment**             | string  | Optional | (Optional) VAT treatment for the bill. VAT treatment denotes the location of the vendor, if the vendor resides in UK then the VAT treatment is `uk`. If the vendor is in an EU country & VAT registered, you are resides in Northen Ireland and purchasing Goods then his VAT treatment is `eu_vat_registered` and if he resides outside the UK then his VAT treatment is `overseas`(For Pre Brexit, this can be split as `eu_vat_registered`, `eu_vat_not_registered` and `non_eu`). **[United Kingdom Only]**                                                                                                                                                                                                                                            |
| **vat_reg_no**                | string  | Optional | **For UK Edition:** VAT Registration number of a contact with length should be between 2 and 12 characters.<br> **For Avalara:** If you are doing sales in the European Union (EU) then provide VAT Registration Number of your customers here. This is used to calculate VAT for B2B sales, from Avalara. **[United Kingdom, Avalara Integration Only]**                                                                                                                                                                                                                                                                                                                                                                                                  |
| **is_abn_quoted**             | string  | Optional | **[Australia Only]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| **abn**                       | string  | Optional | **[Australia Only]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| **is_reverse_charge_applied** | boolean | Optional | Applicable for transactions where you pay reverse charge **[India Only]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| **pricebook_id**              | string  | Optional | Enter ID of the price book.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| **pricebook_name**            | string  | Optional | Name of the price book                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| **is_inclusive_tax**          | boolean | Optional | Used to specify whether the line item rates are inclusive or exclusive of tax. **[Not applicable for United States]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| **location_id**               | string  | Optional | Location ID                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| **line_items**                | array   | Optional | Line items of a recurrence bill.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| **is_tds_applied**            | boolean | Optional | Check if TDS is applied **[India, Global, Australia Only]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| **notes**                     | string  | Optional | Notes for the Bill                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| **terms**                     | string  | Optional | Terms and Conditions for the Bill                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| **payment_terms**             | integer | Optional | Number Referring to Payment Terms                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| **payment_terms_label**       | string  | Optional | Label of the Payment Terms                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| **custom_fields**             | array   | Optional |                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| **discount**                  | string  | Optional | Discount applied to the recurrence. It can be either in % or in amount. E.g: 12.5% or 190.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| **discount_account_id**       | string  | Optional | ID of the account associated with the discount account.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| **is_discount_before_tax**    | boolean | Optional | To specify discount applied in before /after tax.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| **repeat_every**              | string  | Required | Description for repeat_every                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| **recurrence_frequency**      | string  | Required | Description for recurrence_frequency                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |

### Path Parameters

| Parameter             | Type   | Required | Description                              |
| :-------------------- | :----- | :------- | :--------------------------------------- |
| **recurring_bill_id** | string | Required | Unique identifier of the recurring bill. |

### Query Parameters

| Parameter           | Type   | Required | Description            |
| :------------------ | :----- | :------- | :--------------------- |
| **organization_id** | string | Required | ID of the organization |

### Headers

| Header                        | Type    | Required | Description                                                                        |
| :---------------------------- | :------ | :------- | :--------------------------------------------------------------------------------- |
| **X-Unique-Identifier-Key**   | string  | Required | Unique CustomField Api Name                                                        |
| **X-Unique-Identifier-Value** | string  | Required | Unique CustomField Value                                                           |
| **X-Upsert**                  | boolean | Optional | If there is no record is found unique custom field value , will create new invoice |

### Request Example

```bash
curl --request PUT \
  --url 'https://www.zohoapis.com/books/v3/recurringbills?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'X-Unique-Identifier-Key: cf_unique_cf' \
  --header 'X-Unique-Identifier-Value: unique Value' \
  --header 'X-Upsert: true' \
  --header 'content-type: application/json' \
  --data '{"field1":"value1","field2":"value2"}'
```

### Response Example

```json
{
    "code": 0,
    "message": "Recurring Bill information has been updated."
}
```

---

## List recurring bills

List all recurring bills with pagination.
**OAuth Scope :** `ZohoBooks.bills.READ`

### Query Parameters

| Parameter                     | Type    | Required | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| :---------------------------- | :------ | :------- | :--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **organization_id**           | string  | Required | ID of the organization                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| **recurring_bill_id**         | string  | Optional |                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| **vendor_id**                 | long    | Optional | Search recurring bills by Vendor ID                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| **vendor_name**               | string  | Optional | Search recurring bills by vendor name. Variants: `vendor_name_startswith` and `vendor_name_contains`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| **status**                    | string  | Optional | Search recurring bills by recurring bill status. Allowed Values: `active`, `stopped`, `expired`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| **recurrence_name**           | string  | Optional | Search recurring bills by recurrence number. Variants: `recurrence_name_startswith` and `recurrence_name_contains`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| **currency_id**               | string  | Optional | ID of the Currency                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| **currency_code**             | string  | Optional | Code of the Currency                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| **currency_symbol**           | string  | Optional | Symbol of the Currency                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| **start_date**                | string  | Optional | Search recurring bills by recurring bill start date. Variants: `start_date_start`, `start_date_end`, `start_date_before` and `start_date_after`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| **end_date**                  | string  | Optional | Date on which recurring bill has to expire. Can be left as empty to run forever. Format [yyyy-mm-dd].                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| **source_of_supply**          | string  | Optional | Place from where the goods/services are supplied. (If not given, `place of contact` given for the contact will be taken) **[India Only]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| **place_of_supply**           | string  | Optional | The place of supply is where a transaction is considered to have occurred for VAT purposes. For the supply of goods, the place of supply is the location of the goods when the supply occurs. For the supply of services, the place of supply should be where the supplier is established. (If not given, `place of contact` given for the contact will be taken)<br>Supported codes for UAE emirates are : <br>Abu Dhabi - `AB`,<br>Ajman - `AJ`,<br>Dubai - `DU`,<br>Fujairah - `FU`,<br>Ras al-Khaimah - `RA`,<br>Sharjah - `SH`,<br>Umm al-Quwain - `UM`.<br>Supported codes for the GCC countries are : <br>United Arab Emirates - `AE`,<br>Saudi Arabia - `SA`,<br>Bahrain - `BH`,<br>Kuwait - `KW`,<br>Oman - `OM`,<br>Qatar - `QA`. **[GCC Only]** |
| **destination_of_supply**     | string  | Optional | Place where the goods/services are supplied to. (If not given, organisation's home state will be taken) **[India Only]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| **gst_treatment**             | string  | Optional | Choose whether the contact is GST registered/unregistered/consumer/overseas. Allowed values are `business_gst` , `business_none` , `overseas` , `consumer`. **[India Only]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| **gst_no**                    | string  | Optional | 15 digit GST identification number of the vendor. **[India Only]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| **tax_treatment**             | string  | Optional | VAT treatment for the bill. Choose whether the vendor falls under: `vat_registered`,`vat_not_registered`,`gcc_vat_not_registered`,`gcc_vat_registered`,`non_gcc`.<br>`dz_vat_registered` and `dz_vat_not_registered` are supported only for **UAE**.<br>`home_country_mexico`,`border_region_mexico`,`non_mexico` supported only for **MX**.<br>**For Kenya Edition:** `vat_registered` ,`vat_not_registered` ,`non_kenya`(A business that is located outside Kenya).<br>**For SouthAfrica Edition:** `vat_registered`, `vat_not_registered`, `overseas`(A business that is located outside SouthAfrica). **[GCC, Mexico, Kenya, South Africa Only]**                                                                                                      |
| **vat_treatment**             | string  | Optional | (Optional) VAT treatment for the bill. VAT treatment denotes the location of the vendor, if the vendor resides in UK then the VAT treatment is `uk`. If the vendor is in an EU country & VAT registered, you are resides in Northen Ireland and purchasing Goods then his VAT treatment is `eu_vat_registered` and if he resides outside the UK then his VAT treatment is `overseas`(For Pre Brexit, this can be split as `eu_vat_registered`, `eu_vat_not_registered` and `non_eu`). **[United Kingdom Only]**                                                                                                                                                                                                                                            |
| **vat_reg_no**                | string  | Optional | **For UK Edition:** VAT Registration number of a contact with length should be between 2 and 12 characters.<br> **For Avalara:** If you are doing sales in the European Union (EU) then provide VAT Registration Number of your customers here. This is used to calculate VAT for B2B sales, from Avalara. **[United Kingdom, Avalara Integration Only]**                                                                                                                                                                                                                                                                                                                                                                                                  |
| **is_abn_quoted**             | string  | Optional | **[Australia Only]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| **abn**                       | string  | Optional | **[Australia Only]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| **is_reverse_charge_applied** | boolean | Optional | Applicable for transactions where you pay reverse charge **[India Only]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| **pricebook_id**              | string  | Optional | Enter ID of the price book.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| **pricebook_name**            | string  | Optional | Name of the price book                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| **is_inclusive_tax**          | boolean | Optional | Used to specify whether the line item rates are inclusive or exclusive of tax. **[Not applicable for United States]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| **is_tds_applied**            | boolean | Optional | Check if TDS is applied **[India, Global, Australia Only]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| **notes**                     | string  | Optional | Notes for the Bill                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| **terms**                     | string  | Optional | Terms and Conditions for the Bill                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| **payment_terms**             | integer | Optional | Number Referring to Payment Terms                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| **payment_terms_label**       | string  | Optional | Label of the Payment Terms                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| **acquisition_vat_total**     | double  | Optional | Total of the VAT Acquistion **[United Kingdom, Europe Only]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| **reverse_charge_vat_total**  | double  | Optional | Total of the Reverse Charge **[United Kingdom, Europe Only]**                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| **created_time**              | string  | Optional | Created time of the bill                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| **created_by_id**             | string  | Optional | Name of User who created the Bill                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| **last_modified_time**        | string  | Optional | Last Modified Time of the Bill                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| **discount**                  | string  | Optional | Discount applied to the recurrence. It can be either in % or in amount. E.g: 12.5% or 190.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| **discount_account_id**       | string  | Optional | ID of the account associated with the discount account.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| **is_discount_before_tax**    | boolean | Optional | To specify discount applied in before /after tax.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| **page**                      | integer | Optional | Page number to be fetched. Default value is 1.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| **per_page**                  | integer | Optional | Number of records to be fetched per page. Default value is 200.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |

### Request Example

```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/recurringbills?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "success",
    "recurringbills": [
        {
            "recurring_bill_id": 982000000567240,
            "vendor_id": "460000000038029",
            "vendor_name": "string",
            "status": "active",
            "recurrence_name": "Monthly Rental",
            "currency_id": "460000000000099",
            "currency_code": "INR",
            "currency_symbol": "string",
            "start_date": "2013-11-18",
            "end_date": "2013-12-18",
            "source_of_supply": "AP",
            "place_of_supply": "DU",
            "destination_of_supply": "TN",
            "gst_treatment": "business_gst",
            "gst_no": "22AAAAA0000A1Z5",
            "tax_treatment": "vat_registered",
            "vat_treatment": "string",
            "vat_reg_no": "string",
            "is_abn_quoted": "string",
            "abn": "string",
            "is_reverse_charge_applied": true,
            "pricebook_id": 460000000038090,
            "pricebook_name": "string",
            "is_inclusive_tax": false,
            "location_id": "460000000038080",
            "location_name": "string",
            "line_items": [
                {
                    "line_item_id": "460000000067009",
                    "item_id": "460000000054135",
                    "sku": "string",
                    "name": "string",
                    "account_id": "460000000000403",
                    "account_name": "Other Expenses",
                    "image_document_id": 460000000038067,
                    "location_id": "460000000038080",
                    "location_name": "string",
                    "reverse_charge_tax_id": 460000000038056,
                    "reverse_charge_tax_name": "inter",
                    "reverse_charge_tax_percentage": 10,
                    "reverse_charge_tax_amount": 100,
                    "description": "string",
                    "bcy_rate": 40,
                    "rate": 10,
                    "tags": [
                        {
                            "tag_id": "460000000054178",
                            "tag_option_id": "460000000054180"
                        }
                    ],
                    "quantity": 1,
                    "tax_id": "460000000027005",
                    "tds_tax_id": "460000000027001",
                    "tax_treatment_code": "uae_others",
                    "tax_exemption_id": "string",
                    "tax_exemption_code": "string",
                    "tax_name": "VAT (12.5%)",
                    "tax_type": "tax",
                    "tax_percentage": 0,
                    "item_total": 40,
                    "item_total_inclusive_of_tax": 40,
                    "item_order": 1,
                    "unit": "kgs",
                    "product_type": "string",
                    "hsn_or_sac": 80540,
                    "acquisition_vat_id": "string",
                    "acquisition_vat_name": "string",
                    "acquisition_vat_percentage": "string",
                    "acquisition_vat_amount": "string",
                    "reverse_charge_vat_id": "string",
                    "reverse_charge_vat_name": "string",
                    "reverse_charge_vat_percentage": "string",
                    "reverse_charge_vat_amount": "string",
                    "is_billable": false,
                    "customer_id": "string",
                    "customer_name": "string",
                    "project_id": "string",
                    "project_name": "string",
                    "item_custom_fields": [
                        {
                            "custom_field_id": 0,
                            "index": 0,
                            "value": "string",
                            "label": "string"
                        }
                    ],
                    "serial_numbers": [
                        "string"
                    ]
                }
            ],
            "is_tds_applied": true,
            "notes": "Thanks for your business.",
            "terms": "Terms and conditions apply.",
            "payment_terms": 0,
            "payment_terms_label": "Due on Receipt",
            "custom_fields": [
                {
                    "index": 0,
                    "value": "string"
                }
            ],
            "discount": "30%",
            "discount_account_id": "460000000000403",
            "is_discount_before_tax": true,
            "repeat_every": "",
            "recurrence_frequency": ""
        }
    ]
}
```

---

## Update a recurring bill

Update a recurring bill. To delete a line item just remove it from the line_items list.
**OAuth Scope :** `ZohoBooks.bills.UPDATE`

### Path Parameters

| Parameter             | Type   | Required | Description                              |
| :-------------------- | :----- | :------- | :--------------------------------------- |
| **recurring_bill_id** | string | Required | Unique identifier of the recurring bill. |

### Query Parameters

| Parameter           | Type   | Required | Description            |
| :------------------ | :----- | :------- | :--------------------- |
| **organization_id** | string | Required | ID of the organization |

### Arguments
(Same as Create Recurring Bill)

### Request Example

```bash
curl --request PUT \
  --url 'https://www.zohoapis.com/books/v3/recurringbills/982000000567240?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{"field1":"value1","field2":"value2"}'
```

### Response Example

```json
{
    "code": 0,
    "message": "Recurring Bill information has been updated."
}
```

---

## Get a recurring bill

Get the details of a recurring bill.
**OAuth Scope :** `ZohoBooks.bills.READ`

### Path Parameters

| Parameter             | Type   | Required | Description                              |
| :-------------------- | :----- | :------- | :--------------------------------------- |
| **recurring_bill_id** | string | Required | Unique identifier of the recurring bill. |

### Query Parameters

| Parameter           | Type   | Required | Description            |
| :------------------ | :----- | :------- | :--------------------- |
| **organization_id** | string | Required | ID of the organization |

### Request Example

```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/recurring_bills/982000000567240?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "success",
    "recurring_bill": {
        "recurring_bill_id": 982000000567240,
        "vendor_id": "460000000038029",
        "vendor_name": "string",
        "status": "active",
        "recurrence_name": "Monthly Rental",
        "currency_id": "460000000000099",
        "currency_code": "INR",
        "currency_symbol": "string",
        "start_date": "2013-11-18",
        "end_date": "2013-12-18",
        "source_of_supply": "AP",
        "place_of_supply": "DU",
        "destination_of_supply": "TN",
        "gst_treatment": "business_gst",
        "gst_no": "22AAAAA0000A1Z5",
        "tax_treatment": "vat_registered",
        "vat_treatment": "string",
        "vat_reg_no": "string",
        "is_abn_quoted": "string",
        "abn": "string",
        "is_reverse_charge_applied": true,
        "pricebook_id": 460000000038090,
        "pricebook_name": "string",
        "is_inclusive_tax": false,
        "location_id": "460000000038080",
        "location_name": "string",
        "line_items": [
            {
                "line_item_id": "460000000067009",
                "item_id": "460000000054135",
                "sku": "string",
                "name": "string",
                "account_id": "460000000000403",
                "account_name": "Other Expenses",
                "image_document_id": 460000000038067,
                "location_id": "460000000038080",
                "location_name": "string",
                "reverse_charge_tax_id": 460000000038056,
                "reverse_charge_tax_name": "inter",
                "reverse_charge_tax_percentage": 10,
                "reverse_charge_tax_amount": 100,
                "description": "string",
                "bcy_rate": 40,
                "rate": 10,
                "tags": [
                    {
                        "tag_id": "460000000054178",
                        "tag_option_id": "460000000054180"
                    }
                ],
                "quantity": 1,
                "tax_id": "460000000027005",
                "tds_tax_id": "460000000027001",
                "tax_treatment_code": "uae_others",
                "tax_exemption_id": "string",
                "tax_exemption_code": "string",
                "tax_name": "VAT (12.5%)",
                "tax_type": "tax",
                "tax_percentage": 0,
                "item_total": 40,
                "item_total_inclusive_of_tax": 40,
                "item_order": 1,
                "unit": "kgs",
                "product_type": "string",
                "hsn_or_sac": 80540,
                "acquisition_vat_id": "string",
                "acquisition_vat_name": "string",
                "acquisition_vat_percentage": "string",
                "acquisition_vat_amount": "string",
                "reverse_charge_vat_id": "string",
                "reverse_charge_vat_name": "string",
                "reverse_charge_vat_percentage": "string",
                "reverse_charge_vat_amount": "string",
                "is_billable": false,
                "customer_id": "string",
                "customer_name": "string",
                "project_id": "string",
                "project_name": "string",
                "item_custom_fields": [
                    {
                        "custom_field_id": 0,
                        "index": 0,
                        "value": "string",
                        "label": "string"
                    }
                ]
            }
        ],
        "is_tds_applied": true,
        "notes": "Thanks for your business.",
        "terms": "Terms and conditions apply.",
        "payment_terms": 0,
        "payment_terms_label": "Due on Receipt",
        "custom_fields": [
            {
                "custom_field_id": 0,
                "index": 0,
                "label": "string",
                "value": "string"
            }
        ],
        "acquisition_vat_summary": [
            {
                "tax_name": "VAT (12.5%)",
                "tax_amount": 1.25
            }
        ],
        "reverse_charge_vat_summary": [
            {
                "tax_name": "VAT (12.5%)",
                "tax_amount": 1.25
            }
        ],
        "acquisition_vat_total": 0.1,
        "reverse_charge_vat_total": 0.1,
        "created_time": "2013-09-11T17:18:32+0530",
        "created_by_id": "4600000053001",
        "last_modified_time": "2013-09-11T17:18:32+0530",
        "discount": "30%",
        "discount_account_id": "460000000000403",
        "is_discount_before_tax": true
    }
}
```

---

## Delete a recurring bill

Delete an existing recurring bill.
**OAuth Scope :** `ZohoBooks.bills.DELETE`

### Path Parameters

| Parameter             | Type   | Required | Description                              |
| :-------------------- | :----- | :------- | :--------------------------------------- |
| **recurring_bill_id** | string | Required | Unique identifier of the recurring bill. |

### Query Parameters

| Parameter           | Type   | Required | Description            |
| :------------------ | :----- | :------- | :--------------------- |
| **organization_id** | string | Required | ID of the organization |

### Request Example

```bash
curl --request DELETE \
  --url 'https://www.zohoapis.com/books/v3/recurring_bills/982000000567240?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "The recurring bill has been deleted."
}
```

---

## Stop a recurring bill

Stop an active recurring bill.
**OAuth Scope :** `ZohoBooks.bills.CREATE`

### Path Parameters

| Parameter             | Type   | Required | Description                              |
| :-------------------- | :----- | :------- | :--------------------------------------- |
| **recurring_bill_id** | string | Required | Unique identifier of the recurring bill. |

### Query Parameters

| Parameter           | Type   | Required | Description            |
| :------------------ | :----- | :------- | :--------------------- |
| **organization_id** | string | Required | ID of the organization |

### Request Example

```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/recurringbills/982000000567240/status/stop?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "The recurring bill has been stopped."
}
```

---

## Resume a recurring Bill

Resume a stopped recurring bill.
**OAuth Scope :** `ZohoBooks.bills.CREATE`

### Path Parameters

| Parameter             | Type   | Required | Description                              |
| :-------------------- | :----- | :------- | :--------------------------------------- |
| **recurring_bill_id** | string | Required | Unique identifier of the recurring bill. |

### Query Parameters

| Parameter           | Type   | Required | Description            |
| :------------------ | :----- | :------- | :--------------------- |
| **organization_id** | string | Required | ID of the organization |

### Request Example

```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/recurringbills/982000000567240/status/resume?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "The recurring bill has been activated."
}
```

---

## List recurring bill history

Get history and comments of a recurring bill.
**OAuth Scope :** `ZohoBooks.bills.READ`

### Path Parameters

| Parameter             | Type   | Required | Description                              |
| :-------------------- | :----- | :------- | :--------------------------------------- |
| **recurring_bill_id** | string | Required | Unique identifier of the recurring bill. |

### Query Parameters

| Parameter           | Type   | Required | Description            |
| :------------------ | :----- | :------- | :--------------------- |
| **organization_id** | string | Required | ID of the organization |

### Request Example

```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/recurringbills/982000000567240/comments?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "success"
}
```