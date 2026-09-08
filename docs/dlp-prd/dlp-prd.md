# DLP PRD

**Version:** 1.0
**Date:** 23rd December of 2024

> This document outlines the complete end-to-end workflows for a logistics platform, covering forward logistics (delivery), reverse logistics (returns), and exceptional scenarios. The design prioritizes scalability, reliability, and customer satisfaction while optimizing operational efficiency.

---

## Business Objectives

* **T+2 to T+3 Days Delivery:** Achieve delivery of goods to end customers within 2-3 days of order receipt from the Sales Team. This requires optimized routing, efficient delivery agent management, and robust exception handling.
* **Real-Time Shipment Visibility:** Provide all stakeholders (internal and external) with up-to-the-minute information on the location and status of shipments. This necessitates seamless integration with tracking systems and clear communication protocols.
* **Quality Check (QC):** Ensure the integrity of packaged goods such as shampoos, honey, diapers, etc., throughout the delivery process. This requires robust quality control protocols and adherence to strict standards.
* **Proof of Delivery Capture:** Secure evidence of successful delivery, including digital signatures, photos, and location timestamps. This minimizes disputes and ensures accountability.
* **Customer Satisfaction Metrics:** Achieve high levels of customer satisfaction through timely delivery, accurate information, and proactive communication. Feedback mechanisms and performance monitoring are crucial.
* **Cost Optimization Targets:** Minimize operational costs associated with last-mile delivery through efficient routing, partner performance management, reduced delivery exceptions, and optimized resource utilization.

---

## Key Stakeholders

* **Sales Team:** Primary point of contact for receiving and processing customer orders. Their efficiency impacts the entire delivery timeline.
* **Delivery Agents:** Personnel responsible for the physical transportation of goods to end customers. Their performance directly impacts delivery speed and cost.
* **Warehouse Operations:** Teams responsible for order fulfillment, packaging, and handover of goods to delivery agents. Efficiency in this stage is crucial for meeting delivery timelines.
* **Quality Control:** Teams responsible for ensuring package condition and product integrity throughout the delivery process. Currently being established at THPL.
* **Customer Service:** Teams responsible for addressing customer inquiries, resolving delivery issues, and managing customer expectations. Currently there is no dedicated CS team at THPL.
* **Fleet Management:** Internal teams responsible for managing the delivery agents and their vehicles used in the delivery process.
* **End Customers/Businesses:** The recipients of the delivered goods. Their experience is paramount and drives many of the business objectives.

---

## Critical Success Factors

* **Delivery Completion Rates:** Percentage of deliveries successfully completed within T+2 to T+3 days.
* **QC Compliance:** Percentage of deliveries passing quality checks for package condition and product integrity.
* **Customer Satisfaction Scores:** Quantifiable metrics reflecting customer happiness with the delivery experience, gathered through surveys or feedback mechanisms.
* **Real-Time Tracking Accuracy:** Accuracy and reliability of the real-time location information provided to stakeholders.
* **Proof of Delivery Compliance:** Percentage of deliveries with valid and complete proof of delivery captured.
* **Cost Per Delivery:** The average cost incurred for each successful delivery, reflecting efficiency and cost optimization efforts.

---

## Technical Architecture Requirements

This section outlines the necessary system architecture and integrations to support the last-mile delivery workflow.

### Core Systems Integration

* **Order Management System (OMS):** The central system for managing customer orders. Integration provides delivery details, customer information, and order specifics. Currently handled through Zoho Books.
* **Delivery and Logistics Platform (DLP):** The system responsible for planning, optimizing, and executing transportation activities. Integration enables efficient route planning and delivery partner assignment. This will be handled through THPL DLP.
* **Delivery Partner Platform:** A platform for onboarding, managing, and communicating with delivery partners. Facilitates seamless handover and data exchange. This will be handled through THPL DLP.
* **Real-time Tracking System:** A system capable of capturing and broadcasting the real-time location of delivery vehicles and packages. This will be handled through THPL DLP.
* **Customer Notification System:** A system for automatically informing customers about their delivery status and estimated arrival times. This will be done through THPL DLP.
* **Monitoring System:** Platform for tracking the QC parameters of delivery products in real-time. This is To-be-decided, but will be dealt with in the future.
* **Mobile Delivery Application:** A mobile application used by delivery partners for route navigation, status updates, and proof of delivery capture.
* **Proof of Delivery System:** A secure repository for storing and managing captured proof of delivery information.
* **Payment System:** UPI based payment system. This will be part of the Core System that will be used by both DLP and Field Service Application.
* **Route Optimization Engine:** Routing of the waypoints in a given zone. This will be part of the Core System that will be used by both DLP and FSA. Multiple constraints will be defined by DLP or FSA backend as required but the constraint solver will be the part of the Core System.
* **Scheduling Platform:** This is to schedule jobs for the Field Service Team, and the Delivery Partners. Part of the core-platform. Constraints will be solved by DLP or FSA as required by specific function.

### Data Flow Requirements

* **Real-time location data:** Continuous stream of location information from delivery vehicles to the Real-time Tracking System. The location will be long-polled by the DLP platform from Delivery Partner’s mobile applications.
* **QC logs:** Periodic QC parameter readings from QC checks to the QC Monitoring System.
* **Delivery status updates:** Updates from the Mobile Delivery Application to the DLP and Customer Notification System (e.g., “Out for Delivery,” “Delivered”).
* **Customer confirmation:** Confirmation of delivery received by the customer, captured through the Proof of Delivery System (PoD System).
* **Partner performance metrics:** Data on delivery times, completion rates, and other relevant metrics flowing from the Delivery Partner Platform to the DLP.
* **Route optimization data:** Optimized routes generated by the DLP and pushed to the Mobile Delivery Application.
* **Proof of delivery data:** Digital signatures, photos, and location/timestamp data from the Mobile Delivery Application to the Proof of Delivery System.

### Integration Points

* **APIs for partner systems:** RESTful APIs for seamless data exchange with Delivery Partner Platforms (e.g., for dispatch, status updates, payment reconciliation).
* **Mobile app interfaces:** Native interfaces for the Mobile Delivery Application to communicate with backend systems, including QC updates.
* **GPS integration:** Integration with GPS services for real-time location tracking.
* **QA sensor integration:** Protocols for receiving data from QA tools/sensors (e.g., MQTT, CoAP).
* **Payment gateway integration:** For handling payments upon delivery.
* **Customer communication channels:** Integration with WhatsApp gateways (MSG91), email services (for later), and potentially push notification services for customer updates.

---

## Workflow Component Requirements

This section provides detailed specifications for the key components of the last-mile delivery workflow.

### Delivery Partner Integration

* **Partner onboarding process:** A streamlined digital process for registering, verifying, and approving new 3PL partners, including background checks (driving license, insurance, registration documents, etc.) and compliance documentation.
* **Performance monitoring:** Tracking key performance indicators (KPIs) like on-time delivery rate, acceptance rate, and customer feedback to evaluate partner performance.
* **Real-time communication:** Secure communication channels via notifications and status updates between dispatchers and delivery partners for immediate issue resolution and instructions.
* **Payment reconciliation:** Automated processes for payments made to delivery partners and the invoice amount.
* **SLA monitoring:** Systematic tracking of Service Level Agreements (SLAs) with delivery partners, including delivery windows and performance targets.
* **Training requirements:** Mandatory training modules and documentation for delivery partners on using the Mobile Delivery Application, handling packages, and adhering to delivery protocols.

### Real-Time Tracking System

* **Location update frequency:** Configurable update frequency (e.g., every 30 seconds while in motion, less frequent when stationary) to balance real-time visibility and battery consumption.
* **Geofencing requirements:** Ability to define virtual boundaries around key locations (e.g., areas, zones, customer addresses) to trigger notifications and automate status updates.
* **Battery optimization:** Implementation of strategies within the Mobile Delivery Application to minimize battery drain while maintaining accurate tracking (e.g., using low-power GPS modes, batching updates).
* **Offline mode handling:** Capability for the Mobile Delivery Application to store location data and delivery updates locally when network connectivity is lost and synchronize upon reconnection, given the rural-first model of the organization.
* **Data accuracy requirements:** Target accuracy for location data (e.g., within 10 meters) to ensure reliable tracking and enforce constraints (for later).
* **Historical data retention:** Defined retention period for historical tracking data for analysis and audit purposes. This data will be later ingested by Apache Spark in our data-pipeline for driving intelligent analytics.
* **Privacy considerations:** Compliance with privacy regulations regarding the collection and use of location data, including clear consent mechanisms for delivery partners.

> **Important Mobile OS Limitation:** There are Android and iOS limitations on background asynchronous location sync - if polling happens too frequently Android / iOS will kill the application. iOS 14 and later straight up disable background location fetch.

### QA Management (Not implemented)

* **QC monitoring frequency:** Regular checks (e.g., at each handover point) for package condition and product integrity.
* **Alert thresholds:** Pre-defined quality standards with automatic alerts triggered when deviations occur, notifying relevant stakeholders (e.g., Quality Control, Delivery Agent).
* **Compliance requirements:** Adherence to industry-specific regulations and standards for packaged goods logistics. Based on data, we can categorize products “To be discarded” if they fail QC checks.
* **Equipment specifications:** Requirements for packaging materials and handling procedures to ensure product integrity.
* **Backup procedures:** Protocols for handling QC equipment failures or other issues to maintain quality standards.
* **Documentation requirements:** Maintaining detailed records of QC checks, deviations, and corrective actions.
* **Quality assurance processes:** Regular checks and calibrations of QC equipment and validation of quality control procedures.

### Proof of Delivery System

* **Digital signature capture:** Secure and legally binding digital signature capture functionality within the Mobile Delivery Application.
* **Photo documentation:** Ability for delivery partners to capture photos of the delivered package at the destination as supplementary proof.
* **GPS location stamping:** Automatic capture of the delivery location coordinates at the time of POD capture.
* **Timestamp requirements:** Accurate timestamping of the POD event, synchronized with a reliable time source.
* **Offline capture capability:** Ability to capture POD data even without network connectivity, with later synchronization (We have already “Sync-when-online” mechanism on all backends).
* **Data synchronization:** Reliable and secure synchronization of POD data from the Mobile Delivery Application to the backend system.
* **Verification processes:** Automated and manual processes for verifying the validity and completeness of captured POD information. Verification to be done by Logistics Team.

### Customer Notification System

* **Notification triggers:** Events that trigger customer notifications (e.g., order confirmation, shipment dispatched, out for delivery, delivery completed, exceptions).
* **Communication channels:** Support for multiple communication channels (e.g., Whatsapp, email, push notifications) based on customer preferences.
* **Message templates:** Customizable and informative message templates providing relevant delivery information.
* **Payment reminders:** Push payment reminders if the payments are made partial or there are due-payments to be made and categorize the frequency based on due window (30 days, 60 days, 90 days).
* **Frequency controls:** Mechanisms to avoid overwhelming customers with excessive notifications.
* **Opt-out management:** Clear and easy options for customers to opt out of receiving notifications.
* **Delivery instructions:** Ability for customers to provide specific delivery instructions (e.g., gate code, leave at back door) during the ordering process.
* **Feedback collection:** Integration with feedback mechanisms (e.g., post-delivery surveys) to gather customer satisfaction data.

---

## Process Flow Requirements

This section details the key process flows within the last-mile delivery workflow.

### Main Delivery Flow

1. **Package Assignment:** The DLP assigns packages to available delivery partners based on optimized routes, capacity, and proximity.
2. **Route Optimization:** The DLP generates the most efficient delivery route for defined waypoints in a zone, considering factors like delivery windows, order priority, delivery partner availability, and store delivery availability window.
3. **Delivery Execution:** The delivery partner uses the Mobile Delivery Application to navigate the route, update delivery status, and manage their deliveries.
4. **Proof of Delivery:** Upon successful delivery, the delivery partner captures proof of delivery (digital signature, photo, GPS timestamp) using the Mobile Delivery Application.
5. **Exception Handling:** If issues arise (e.g., failed delivery attempt), the delivery partner logs the exception in the Mobile Delivery Application, triggering appropriate workflows. (Discussed in later section).
6. **Status Updates:** Real-time delivery status updates are transmitted from the Mobile Delivery Application to the DLP and Customer Notification System.
7. **Completion Verification:** The system verifies the successful completion of the delivery based on the captured proof of delivery.

### Exception Flows

**Failed delivery attempts:** The delivery partner attempts delivery and cannot complete it (e.g., no answer, delivery rejected, incorrect address). The delivery partner logs the reason for failure in the Mobile Delivery Application. Customer Service is notified and attempts to contact the customer. Options include rescheduling delivery, rerouting to a nearby pickup point, or returning to the warehouse.

**QC excursions:** QC checks detect a deviation outside the acceptable quality standards. An alert is triggered, notifying Quality Control and the Delivery Agent. The Delivery Agent may be instructed to take corrective action (e.g., repackage item, move package to a different container). The incident is logged, and the package may be flagged for inspection upon arrival.

**System outages:** Contingency plans are in place for system outages, including offline capabilities for the Mobile Delivery Application. Communication protocols are established to inform relevant stakeholders. The outage is logged in the system with timestamps and delivery window. The warehouse manager and Delivery partner are notified.

**Customer unavailability:** The delivery partner attempts delivery but the customer is unavailable. Options include attempting redelivery or delivering to an alternative location as per customer instructions. Notifications triggered include a “Delivery attempted” Whatsapp template for the customer and notifying the Warehouse Manager.

**Package damage:** The delivery partner identifies damage to the package during transit. Documentation (photos, description) is captured in the Mobile Delivery Application. Notifications are triggered to Customer Service, the Warehouse Manager, and the QA Team. Customers are notified based on status (e.g., “Updated delivery schedule / Order cancelled / Refund initiated, etc.”).

**Access restrictions:** The delivery partner encounters difficulties accessing the delivery location (e.g., shop not found, road closed, any other practical delivery problems). Communication with the customer is initiated to resolve the issue. Notifications triggered include a “Delivery failed due to unforeseen circumstances” WA template for the customer and notifying the Warehouse Manager. Customers are additionally notified based on order status updates.

**Weather disruptions:** Severe weather conditions impact delivery operations. The DLP may automatically adjust routes and delivery timelines. Customer notifications are sent regarding potential delays.

### QA Control Flow

1. **Pre-delivery checks:** Before loading, the delivery partner verifies the QA checks within the container or vehicle and ensures the monitoring system is functioning.
2. **In-transit monitoring:** Temperature sensors / Moisture sensors continuously monitor and log the temperature throughout the delivery journey.
3. **Excursion handling:** If a temperature excursion occurs (as defined by alert thresholds), an alert is triggered, notifying relevant stakeholders.
4. **Documentation:** All temperature readings, alerts, and corrective actions are automatically logged and documented.
5. **Quality assurance:** Upon delivery, Quality Control may review the temperature logs to ensure compliance and investigate any excursions.
6. **Compliance reporting:** Regular reports are generated to demonstrate adherence to cold chain regulations and identify potential areas for improvement.
7. **Corrective actions:** Defined procedures for addressing temperature excursions, including potential spoilage assessment and disposal protocols.

---

## Proof of Payment (PoP) Workflow

This section outlines the detailed process for capturing and validating proof of payment during the delivery process. It covers various payment methods and scenarios, including order edits at the time of delivery.

### Mode of Payment

The Delivery Agent (DA) can collect payment through the following methods:

* **UPI (Unified Payments Interface):** Instant online payment transfer via mobile application.
* **Cash:** Physical currency notes and coins.
* **Cheque:** A written order to a bank to pay a specified sum.
* **Credit:** Allowing the customer to receive the order and pay at a later date.

### Proof of Payment Workflow - Standard Delivery (No Edits)

This workflow describes the process when the delivered order matches the original invoice, and no changes are made.

1. **Delivery Agent Arrives:** The DA arrives at the customer’s location with the package for delivery.
2. **Delivery Completion:** The DA hands over the package to the customer.
3. **Payment Collection:** The DA initiates the payment collection process via the delivery mobile application on the “Payment Collection” page for the specific invoice. The available payment methods will be displayed.
4. **Executing UPI Payment:** On the “Payment Collection” page, the DA selects “UPI” and clicks “Generate QR Code.” The application generates a UPI payment QR code containing the invoice details (payload). The customer scans the QR code using their UPI application and makes the payment. The DA confirms the payment by clicking “Payment Received” in the app, optionally capturing a picture of the payment success screen on the customer’s mobile device, or optionally calling the Accounts Team to confirm payment receipt if there is a delay.
5. **Executing Cash Payment:** On the “Payment Collection” page, the DA selects “Cash.” The DA receives the cash from the customer and enters the details of the cash received (denomination and quantity of each denomination). The DA submits the cash details in the app. Optionally, the DA can click a picture of the cash received to submit and/or print a receipt for the cash payment from the app.
6. **Executing Cheque Payment:** On the “Payment Collection” page, the DA selects “Cheque” and receives the cheque from the customer. The DA captures a clear image of the cheque using the app’s camera functionality and submits the captured image in the “Payments Collection” page.
7. **Executing Credit Payment:** On the “Payment Collection” page, the DA selects “Credit.” The DA confirms with the Accounts Team (via phone or in-app communication) whether allowing delivery on credit is permissible for this customer. The Accounts Team checks the credit history/score and communicates the decision. (Future enhancement: A “Credit Score” feature will display in-app allowing the DA to make informed decisions within limits). If approved, the DA marks the payment as “Credit” in the app.
8. **Executing Partial UPI Payment:** On the “Payment Collection” page, the DA enters the specific partial amount being paid via UPI and clicks “Generate QR Code.” The app generates a QR code pre-populated with this partial amount. The customer scans and completes the transaction. The DA confirms the successful receipt of the partial payment identically to a standard full UPI payment.

### Partial Cash Payment Workflow

This workflow outlines the process when a customer pays a portion of the invoice amount in cash, with the remaining balance settled through another method.

1. **Delivery and Invoice Presentation:** The DA arrives at the customer’s location and presents the invoice.
2. **Customer Indicates Partial Cash Payment:** The customer informs the DA they wish to pay a portion of the total amount in cash.
3. **Initiate Payment Collection:** On the “Payment Collection” page, the DA views the total amount due.
4. **Enter Partial Cash Amount:** The DA enters the specific amount the customer is paying in cash. The app calculates the remaining balance.
5. **Receive Cash:** The DA receives the cash for the entered partial amount.
6. **Record Cash Details:** The DA selects “Cash” for this portion and enters the breakdown (denomination and quantity). The DA submits the details, optionally captures a picture of the cash, and optionally prints a receipt specifically for this partial cash payment.
7. **Determine Remaining Balance Payment Method:** The DA discusses how the remaining balance will be paid (UPI, Cheque, or Credit). Another cash payment for the remainder later is a possibility but discouraged.
8. **Record Remaining Balance Payment:** The DA follows the appropriate workflow based on the agreed-upon payment method for the remaining balance. The app tracks these as separate payment entries against the same invoice.
9. **Submission for Validation:** The DA’s actions are submitted for validation by the Accounts Team.

### Partial Cheque Payment Workflow

This workflow describes the process when a customer pays a portion of the invoice amount with a cheque, with the remaining balance settled through another method.

1. **Delivery and Invoice Presentation:** The DA arrives and presents the invoice.
2. **Customer Indicates Partial Cheque Payment:** The customer informs the DA they wish to pay a portion via cheque.
3. **Initiate Payment Collection:** On the “Payment Collection” page, the DA views the total amount due.
4. **Receive Cheque (Partial Payment):** The DA receives the cheque from the customer.
5. **Record Cheque Details:** The DA selects “Cheque” for this portion, captures a clear image of the cheque, and enters the cheque amount, number, and bank name (if available). The DA submits the image and details.
6. **Verify Cheque Amount:** Ensure the amount on the cheque matches the partial payment amount intended.
7. **Determine Remaining Balance Payment Method:** The DA discusses how the remaining balance will be paid (UPI, Cash, Credit).
8. **Record Remaining Balance Payment:** The DA follows the appropriate workflow for the remaining balance, ensuring the “Payment Collection” page reflects both methods.
9. **Submission for Validation:** The DA’s actions are submitted for validation by the Accounts Team.

### Partial Credit Workflow

This workflow outlines the process when a customer pays a portion upfront and the remaining balance is approved to be paid on credit.

1. **Delivery and Invoice Presentation:** The DA arrives and presents the invoice.
2. **Customer Requests Partial Credit:** The customer informs the DA they wish to pay a portion upfront and the rest on credit.
3. **Initiate Payment Collection:** On the “Payment Collection” page, the DA views the total amount due.
4. **Collect Upfront Partial Payment:** The DA collects the upfront payment using UPI, Cash, or Cheque following the respective partial payment workflows.
5. **Record Upfront Partial Payment:** The DA records the details in the app.
6. **Initiate Credit Request for Remaining Balance:** The DA selects “Credit” for the remaining balance (auto-calculated by the app). The DA confirms permissibility with the Accounts Team.
7. **Credit Approval/Disapproval:** The Accounts Team approves or disapproves the credit request.
8. **Record Credit Details:** If approved, the DA marks the remaining balance as “Credit” (recording approval timestamp and authorizing user). If not approved, the DA discusses alternative methods, reverting to other partial payment scenarios or potentially cancelling the order.
9. **Confirmation and Submission:** The DA confirms the agreed-upon arrangement with the customer and submits all payment details for validation. The actual subsequent payment of the credit amount occurs later via a separate accounts process, outside of the immediate delivery workflow.

### Proof of Payment Workflow - Edited Delivery

This workflow describes the process when the order is edited at the time of delivery (e.g., Item Removal, Quantity Adjustment, Order Decline, Address Change leading to rejection/edit).

1. **Identify the Need for Editing:** The DA identifies the need to edit the invoice based on the customer’s request.
2. **Edit the Invoice:** The DA uses the “Edit Invoice” functionality within the mobile app, making necessary changes. The system creates a new “Delivery Sales Invoice” linked to the original in the database. The app displays the updated total amount due.
3. **Delivery with Edited Items/Handling Declines:** If items were removed/adjusted, the DA delivers the modified order. If the order is fully declined, no items are handed over, and the DA marks the order as “Declined” with a reason.
4. **Payment Collection (Post-Edit):** The DA collects payment based on the new “Delivery Sales Invoice.”
5. **Executing UPI Payment (Edited Order):** The DA selects “UPI,” generates a QR code with the updated amount in the payload, and the customer scans to pay. Confirmation happens as normal. For partial UPI payments, the DA enters the partial amount, generates the QR code, and completes the transaction, handling the balance as standard.
6. **Executing Cash Payment (Edited Order):** The DA selects “Cash,” receives cash for the updated amount, and enters denominations/quantities. For partial cash payments on the edited invoice, the DA enters the specific partial cash amount and records denominations, proceeding to handle the balance standardly.
7. **Executing Cheque Payment (Edited Order):** The DA selects “Cheque,” receives the cheque for the updated amount, captures an image, and submits. For partial cheque payments, the process is identical but handled for the partial amount against the new invoice.
8. **Executing Credit Payment (Edited Order):** The DA selects “Credit,” confirms approval with the Accounts Team for the updated amount, and marks as “Credit” if approved. For partial credit, the upfront portion is collected via chosen method on the new invoice amount, and the remainder goes through the credit approval process.
9. **Order Decline Handling:** If declined, no payment is collected. The order is marked “Declined.”
10. **DA Actions and Submission for Validation:** The DA’s actions, edited invoice details, and payment information are submitted for validation by the Accounts Team.

---

## DA Actions -> Accounts Team Validation Workflow

This workflow elaborates on the actions taken by Delivery Agents (DAs) and the process of submitting payment information for validation. Actions performed in the app are not automatically finalized and require Accounts Team validation.

1. **Payment Collection During Delivery Route:** Throughout the route, the DA collects payments and performs actions in the app for each completed delivery. This includes selecting the payment method, recording payment details (generating QR codes, entering cash denominations, capturing cheque images, or marking credit), handling partial payments, managing edited orders by using the "Edit Invoice" feature, and marking declined orders. No payment collection is recorded for declined orders.
2. **End of Delivery Route or Designated Interval:** The DA prepares for submission and validation.
3. **Physical Preparation of Cash and Cheques:** The DA physically separates/organizes collected cash and gathers all physical cheques.
4. **Return to Accounts Team Location:** The DA returns to the designated location.
5. **Physical Submission of Cash and Cheques:** The DA hands over all physical cash and cheques to the designated Accounts Team member.
6. **Digital Submission Confirmation (Implicit):** The DA’s actions of recording payment information in the app during the route are automatically saved in the THPL backend. This constitutes the digital submission accessed by the Accounts Team on their dashboard.

---

## Accounts Team Validation Process

This workflow provides a detailed step-by-step process for the Accounts Team to validate the payment information submitted by the DAs.

1. **Accessing the Validation Dashboard:** The Accounts Team member logs into the system dashboard designed for validating DA submissions, viewing real-time actions.
2. **Filtering and Reviewing Submissions:** The member filters the dashboard by DA, date, time, etc., and reviews the submissions made by a specific returning DA.
3. **Cash Validation:**
* The member receives the physical cash.
* They compare the physical total with the digital record on the dashboard.
* They verify that denominations and quantities match the DA's entry.
* Optional image verification is performed if the DA submitted a picture.
* Action taken: **Approve (Green)** if perfectly matching (triggers DLP update to Zoho); **Decline/Cancel/Void (Red)** if there is a discrepancy, triggering a notification to the DA; **Unapproved (Orange)** if validation is pending or minor investigation is needed.


4. **Cheque Validation:**
* The member receives the physical cheques.
* They locate the digital submission on the dashboard.
* They match the physical cheque to the digital image.
* The member accurately enters the Cheque Number into the designated field.
* They review the cheque image for clarity.
* Action taken: **Approve (Green)** for valid cheques; **Decline/Cancel/Void (Red)** for invalid or damaged cheques; **Unapproved (Orange)** if awaiting bank confirmation.


5. **UPI Validation:**
* The member accesses bank statements or payment gateway records.
* They compare transaction details (amount, timestamp) with the DA's digital submissions.
* They confirm the UPI payment has been successfully credited.
* Action taken: **Approve (Green)** if confirmed in bank records; **Decline/Cancel/Void (Red)** if not found or discrepancies exist; **Unapproved (Orange)** if there is a delay in bank statement updates.


6. **Handling Credit Transactions:** The primary validation is confirming the DA followed the correct procedure for obtaining credit approval. Actual payment tracking happens via separate accounts receivable processes.
7. **Reviewing Edited Orders:** The Accounts Team cross-references the “Delivery Sales Invoice” details with the original invoice and ensures the Operations Team has approved the corresponding “Return Goods Challan.”
8. **Communication and Resolution:** If discrepancies lead to a decline, the team communicates with the DA to resolve the issue and potentially correct in-app information.

---

## Handling Edited Orders - Operations Team Workflow

This workflow outlines the step-by-step process involving the Operations Team when a Delivery Agent (DA) edits an order during delivery.

1. **DA Edits Order and Submits:** The DA uses the "Edit Invoice" functionality. A new "Delivery Sales Invoice" is generated. The DA completes delivery, collects payment, and submits actions from the app.
2. **Automated Notification to Operations Team:** Submission automatically triggers a dashboard notification to the Operations Team indicating a "Return Goods Challan" is expected against an original invoice, linking to the new invoice.
3. **Operations Team Reviews Notification and Details:** A member reviews the original invoice, new invoice, items removed, DA details, and timestamps.
4. **Goods Return by DA (Physical Process):** The DA returns to the location carrying the removed goods.
5. **Creation of “Return Goods Challan”:** The system automatically generates a challan based on edited details, or warehouse personnel manually creates/confirms one based on the new invoice information.
6. **Physical Receipt and Tallying of Returned Goods:** Personnel receive goods, tally them against the challan, and inspect for damage.
7. **Verification and Reconciliation:** The Operations Team verifies items match the challan and new invoice. Discrepancies are investigated.
8. **Operations Team Action on Dashboard:**
* **Approve (Status: “Goods Returned Verified”):** If matched and in acceptable condition.
* **Reject (Status: “Goods Return Rejected”):** If significant, unresolved discrepancies exist (requires reason).
* **Partial Approval:** In some scenarios, partial approval occurs if only some items match.


9. **Accounts Team Visibility of Operations Approval Status:** The Accounts Team dashboard reflects the Operations Team's verification status (Verified, Rejected, or Awaiting).
10. **Accounts Team Final Review and Approval/Decline:**
* **If Operations Approved:** Accounts Team reviews payment against the new invoice. If it matches, they **Approve (Final)**, triggering the Zoho Backend update. They may still decline for purely financial discrepancies.
* **If Operations Rejected:** Accounts Team likely declines the edited order, investigates, and revisits the payment collected.


11. **Zoho Backend Update:** Upon final approval by Accounts, the DLP updates Zoho to reflect the edited order, new invoice, and payment received.

---

## Proof of Delivery (PoD) Workflow

This workflow outlines the comprehensive process for capturing and managing Proof of Delivery (PoD) to confirm successful delivery of goods.

1. **DA Initiates Delivery Completion in the Mobile App:** After handover, the DA navigates to the specific job in the app and presses “Complete Delivery.”
2. **Accessing the “Delivery Confirmation” Page:** The app navigates to the specific confirmation page.
3. **Capturing Proof of Delivery:**
* **Upload/Take Photos:** The DA can upload gallery images or capture new photos (package at doorstep, handed to recipient, or signed slip). Multiple images are allowed.
* **Capture Customer’s Signature:** The DA hands the device to the customer to sign on-screen. The signature is digitally stored. If the customer is unavailable, the DA indicates a reason (e.g., “Left at Doorstep”).


4. **Submitting Proof of Delivery:** The DA reviews the information and presses “Submit Delivery Confirmation.”
5. **Data Transmission and Storage:** Captured data (images, signature, timestamps, DA ID, job details) is securely transmitted and stored in the THPL backend.
6. **Visibility on Dashboards:**
* **Accounts Team Dashboard:** Views PoD images/signature and color-coded status (Green: Successful, Yellow: Needs review, Red: Missing/Insufficient).
* **Operations Team Dashboard:** Views identical PoD details and color-coded status to identify issues quickly.


7. **Review and Potential Actions:** Dashboards are used for routine review, dispute resolution, performance monitoring, and issue identification. Specific conditions like "No Signature" or "Photo-Only PoD" alter the submission requirements slightly based on delivery type.

---

## Reschedule Workflow

This workflow details the complete process for handling delivery reschedules.

1. **DA Identifies Need for Reschedule:** Encountering issues like customer unavailability, cancellation, requested re-attempt, bad address, or access issues.
2. **DA Initiates Reschedule Request:** The DA selects "Reschedule" or "Report Issue" in the app for the specific job.
3. **DA Records Reschedule Details:** The DA selects a reason from a list, notes the requested reschedule date (default T+7 or customer-requested via calendar), and adds optional notes.
4. **DA Submits Reschedule Request:** The DA presses “Submit Reschedule Request.”
5. **Request Transmission to Operations Team:** Data is sent to the THPL backend, generating a notification and pending status on the Operations Team dashboard.
6. **Operations Team Reviews Reschedule Request:** A team member reviews the request details, original job, DA notes, and requested dates.
7. **Operations Team Evaluates and Makes Decision:** Evaluating validity, customer preference, route optimization, capacity, and SLAs.
8. **Operations Team Approves or Rejects:** Action taken on the dashboard. Approval may adjust the requested date (with reason). Rejection requires a reason.
9. **System Updates Delivery Schedule:**
* **Approval:** Job moved to the new date schedule. WhatsApp notification triggered to customer.
* **Rejection:** Job cancelled. Order marked cancelled in Zoho (Invoice "Void"). WhatsApp notification triggered to customer.


10. **Notification to DA:** The DA receives an in-app notification confirming the new date (if approved) or the rejection reason.
11. **DA Views Updated Schedule:** The DA's job manifest updates to reflect the changes.
12. **Handling Rejected Requests:** Operations Team may contact the customer for alternative arrangements, reassign, or mark for return. The DA receives further instructions as needed.

---

## Order Approved Workflow

This workflow outlines the steps that occur when an invoice is marked as approved.

1. **Invoice Marked as Approved:** The Accounts Team marks the invoice as “Approved” on their dashboard after successful validation.
2. **Payment Status Updated:** The system updates the payment status (e.g., “Paid”), approval status, timestamp, and approving user identity.
3. **Trigger Zoho Update:** The approval triggers the DLP to synchronize this data with the Zoho Backend.
4. **Zoho Backend Update:**
* **DLP Processing:** Extracts, transforms, and maps data for the Zoho API.
* **Zoho Invoice Data Update:** Updates payment status, amount, method, transaction IDs, and timestamps on the Zoho invoice record.
* **Zoho Payment Records Update:** Creates/updates linked payment records in Zoho detailing the transaction ID, amount, method, date, and invoice references.



---

## Order Cancellation Workflow

This workflow details the process for a Delivery Agent (DA) to initiate and record an order cancellation during their delivery route.

1. **DA Identifies Need for Order Cancellation:** Encountering issues like confirmed customer cancellation at doorstep, refusal, confirmed undeliverable address, or safety concerns.
2. **DA Initiates Cancellation in Mobile App:** The DA selects "Cancel Order" on the specific job.
3. **Geofence Verification:** The app checks the DA's location against a predefined geofence. Success records a timestamp and proceeds. Failure displays a warning, requiring justification and recording a failure timestamp.
4. **DA Selects Reason for Cancellation:** Selects from a predefined list, providing free-text explanation if "Other" is chosen.
5. **Timestamp of Cancellation Initiation:** The app automatically records the initiation time.
6. **DA Confirms Order Cancellation:** The DA confirms the decision (e.g., via button or swipe).
7. **Data Submission:** Cancellation data (reason, timestamps, geofence status, DA ID, job details) is transmitted to the THPL backend.
8. **System Updates Order Status:** THPL backend updates the status to "Cancelled" and logs the backend recording timestamp.
9. **Notifications to Relevant Teams:** Automated notifications alert the Operations Team (status updated on dashboard) and Accounts Team (invoice status updated to "Cancelled" to prevent payment processing). The customer may optionally receive a notification.
10. **Visibility on Dashboards:** Both Operations and Accounts dashboards clearly display the cancelled status, reasons, and relevant timestamps.
11. **Inventory Management:** The system triggers an inventory update marking cancelled items as available for restocking.

---

## Order Edition Workflow

This workflow details the process for a Delivery Agent (DA) to edit an order at the time of delivery, creating a new “Delivery Sales Invoice.”

1. **DA Identifies Need for Order Edition:** Customer wants to remove items, adjust quantities, or accept a pre-approved substitution.
2. **DA Initiates Order Edition in Mobile App:** The DA selects "Edit Order."
3. **Geofence Verification:** The app checks the DA's location against the geofence. Success allows progression; failure flags the action for potential justification. Timestamps are recorded for either outcome.
4. **DA Selects Reason for Edition:** Selects from predefined reasons or explains via free-text.
5. **Timestamp of Edition Initiation:** App records the exact time the editing process starts.
6. **DA Edits the Order:** The DA removes items, adjusts quantities, or processes substitutions in the app interface.
7. **System Creates New "Delivery Sales Invoice":** The system calculates the new total and creates a new invoice containing a unique ID, modified items, new total, original invoice link, and DA/timestamp metadata.
8. **DA Confirms Order Edition:** The DA reviews the new invoice, confirms with the customer, and confirms the action in the app.
9. **Data Submission:** Edition data, geofence status, new invoice details, and metadata are transmitted to the THPL backend.
10. **System Updates Order Status and Creates Record:** The original job becomes "Edited," the new invoice is recorded, and the backend timestamp is logged.
11. **Notifications to Relevant Teams:** Operations Team is notified (original job updated to Yellow/Edited). Accounts Team is notified (original invoice marked "Edited," new invoice created with updated amounts).
12. **Payment Collection:** The DA proceeds to collect payment based on the newly generated “Delivery Sales Invoice” amount.
13. **Visibility on Dashboards:** Both teams view full details of the edited status, original invoice linkages, new totals, and exact modification reasons/timestamps.
14. **Inventory Management:** The system triggers an update to mark removed items for restocking and adjust stock levels accordingly.

---

## Delivery Agent (DA) Experience Workflow

This workflow outlines the end-to-end journey of a Delivery Agent.

### Phase 1: Starting the Day at the Warehouse

* **Arrival and Login:** The DA logs into the app at the warehouse.
* **Job Manifest and Route Overview:** The DA views the daily manifest containing On-Route/Off-Route deliveries, On-Route/Off-Route return pick-ups, and custom jobs. Key details (customer name, address, ID, delivery window) and a map overview are displayed.
* **Vehicle and Inventory Check:** The DA completes a pre-trip vehicle inspection checklist and scans/confirms loaded packages against the manifest, flagging discrepancies to the manager.
* **Departure from Warehouse:** The DA marks "Start Journey," recording the departure timestamp and initiating location tracking.

### Phase 2: On the Delivery Route / On the Road (OtR)

* **Navigation to First Stop:** Turn-by-turn navigation guides the DA.
* **Arrival at Delivery Location:** The DA arrives, marks "Arrived at Customer" (timestamp recorded).
* **Delivery Process:** The DA retrieves the package, optionally marks "Delivery Job Started," and hands over the package.
* **Payment Collection:** The DA executes the Proof of Payment Workflow as required.
* **Proof of Delivery (POD):** The DA marks "Delivery Completed," captures the electronic signature, and optionally takes a doorstep photo.
* **Departure from Delivery Location:** The DA marks "Departed from Customer" (timestamp recorded).
* **Navigation to Next Stop:** The app routes the DA to subsequent locations.
* **Handling Issues and Exceptions:** The DA logs delivery exceptions/issues, handles first-attempt failures, and initiates requested reschedules directly via the app, submitting them for Operations Team review.

### Phase 3: Completing the Route and Returning to the Warehouse

* **Completion of Last Job:** The DA marks the final manifest job as complete.
* **Navigation Back to Warehouse:** The app provides return navigation.
* **Arrival at Warehouse:** The DA marks "Arrived at Warehouse" (timestamp recorded).
* **Returns and Undelivered Items:** The DA scans unloaded return items and hands over undelivered packages, reviewing reasons for non-delivery.
* **End-of-Day Procedures:** The DA completes tasks like vehicle inspection and device charging, then logs out.
* **Metrics Calculation:** The system automatically calculates Total Time/Distance of Journey, Driving Time, Time Spent Per Delivery, Average Delivery Time, On-Time Delivery Rate (OTDR), First Attempt Delivery Rate (FADR), Stops Per Hour, Time Spent Traveling vs. Delivering, Idle Time, Delivery Exceptions, POD Rate, Missed Delivery Rate, and Performance Against Targets based on logged timestamps and location data.

---

## Zoho Backend Updates: Triggers and Synchronization Mechanism

The DLP plays a critical role as the intermediary, ensuring data from the THPL backend is accurately transferred to the Zoho Backend once validation processes are complete.

### Invoice Updates (in Zoho Backend)

* **Payments Made:** When full/partial payments are approved (UPI, Cash, Cheque), the Zoho invoice is updated with Payment Status, Amount Paid, Payment Method, Transaction ID, Date/Time, Reference to payment record, and Approving User. Partial payments update the outstanding balance.
* **Editions Made:** When edited orders are approved, the original invoice is marked "Edited/Superseded" and linked to the newly created “Delivery Sales Invoice” containing updated quantities, totals, and reference metadata.
* **Order Cancelled:** When cancelled, the invoice status changes to "Void," recording the date, time, reason, and initiating user.

### Payments Recorded (in Zoho Backend)

* **Payment Receipt (UPI/Cash/Cheque):** A separate payment record is created upon Accounts Team approval, linking to the invoice. It stores Transaction ID, Amount, Method, Date/Time, Reference details (e.g., Cheque Number, UPI Ref), DA details, and Approving User details.
* **Credit Transactions:** No immediate payment record is created. The invoice updates the Payment Method to "Note updated," sets status reflecting outstanding credit, and records the balance and approval date. Actual payment recording occurs later through accounts receivable processes.

### Data Flow and Synchronization Mechanism

* **Triggering Events:** Updates are triggered by Accounts Team approvals on their dashboard (for payments or edited orders) or when an order is marked cancelled.
* **DLP as the Intermediary:** The DLP monitors the THPL backend for these triggers.
* **Data Extraction and Transformation:** The DLP extracts relevant data and transforms it for the Zoho API.
* **Data Mapping and Integrity:** The DLP accurately maps data fields between the THPL and Zoho systems to maintain data integrity.

---

## Technical Specifications

This section provides detailed technical requirements for the key system components.

### Mobile Application

* **Offline functionality:** Essential for handling areas with poor network connectivity, including offline route access, status updates, and POD capture.
* **Battery optimization:** Critical for ensuring the application can run for extended periods without excessive battery drain. Techniques include background processing limitations, efficient GPS usage, and data batching.
* **GPS accuracy:** Requirement for high accuracy GPS readings to ensure reliable tracking and geofencing functionality.
* **Data synchronization:** Robust and secure mechanisms for synchronizing data between the mobile application and backend systems.
* **User interface:** Intuitive and user-friendly interface designed for efficient use by delivery partners, minimizing distractions and training time.
* **Security features:** Secure authentication, authorization, and data encryption to protect sensitive information.
* **Performance metrics:** Fast loading times, smooth navigation, and responsiveness even with large datasets.

### Backend Systems

* **API requirements:** Well-defined RESTful APIs for communication between different systems, with clear request/response formats and error handling.
* **Database design:** Scalable and robust database design to handle large volumes of data, including delivery information, tracking data, and user details.
* **Caching strategy:** Implementation of caching mechanisms to improve performance and reduce database load.
* **Scalability needs:** The system should be designed to handle increasing volumes of deliveries and users without significant performance degradation.
* **Redundancy plans:** Implementing redundancy at various levels (e.g., database, servers) to ensure high availability and minimize downtime.
* **Disaster recovery:** Comprehensive disaster recovery plans to ensure business continuity in case of major incidents.
* **Monitoring tools:** Implementation of monitoring tools to track system health, performance, and identify potential issues proactively.

### Integration Architecture

* **API specifications:** Detailed documentation for all APIs, including endpoints, request/response formats, authentication methods, and error codes.
* **Data formats:** Standardized data formats (e.g., JSON, XML) for seamless data exchange between systems.
* **Security protocols:** Implementation of robust security protocols to protect data in transit and at rest.
* **Error handling:** Well-defined error handling mechanisms to gracefully manage integration failures and provide informative error messages.
* **Rate limiting:** Implementation of rate limiting to protect APIs from abuse and ensure fair usage.
* **Version control:** Proper version control for APIs to manage changes and ensure backward compatibility where possible.
* **Documentation:** Comprehensive documentation for all integration points, including architecture diagrams and data flow diagrams.

---

## Specific Requirements

This section details specific performance, security, and monitoring requirements.

### Performance Requirements

* **System response times:** API calls should respond within acceptable timeframes (e.g., under 200ms for critical operations).
* **Data update frequency:** Real-time data (e.g., location updates) should be processed and reflected in the system with minimal latency.
* **Concurrent user support:** The system should be able to handle a defined number of concurrent users (delivery partners, customer service agents) without performance degradation.
* **Battery consumption:** Mobile application battery consumption should be minimized to allow for full-day usage.
* **Network bandwidth:** The system should be optimized for efficient use of network bandwidth, especially for mobile data usage.
* **Storage requirements:** Adequate storage capacity for historical data, logs, and captured proof of delivery.
* **Processing capacity:** Sufficient processing power to handle the volume of transactions and data processing.

### Security Requirements

* **Authentication methods:** Secure authentication methods for all users (delivery partners, internal staff, API access).
* **Authorization levels:** Granular authorization levels to control access to sensitive data and functionalities based on user roles.
* **Data encryption:** Encryption of sensitive data both in transit and at rest.
* **Privacy controls:** Implementation of privacy controls to comply with relevant data privacy regulations (e.g., GDPR, CCPA).
* **Audit logging:** Comprehensive audit logging of all system activities and user actions for security monitoring and compliance.
* **Compliance needs:** Adherence to relevant security compliance standards and regulations.
* **Access controls:** Strict access controls to prevent unauthorized access to systems and data.

### Monitoring Requirements

* **KPI tracking:** Real-time dashboards and reports to track key performance indicators (e.g., delivery success rate, temperature compliance).
* **Alert thresholds:** Configurable alert thresholds for critical metrics (e.g., temperature excursions, failed deliveries) to enable proactive intervention.
* **Performance metrics:** Monitoring of system performance metrics (e.g., API response times, resource utilization) to identify bottlenecks and optimize performance.
* **System health:** Continuous monitoring of system health and availability of all components.
* **User activity:** Tracking of user activity for security monitoring and identifying potential issues.
* **Error tracking:** Centralized error logging and tracking system to quickly identify and resolve system errors.
* **Audit trails:** Detailed audit trails of all system events and user actions for compliance and security investigations.

---

## Documentation Deliverables

This section outlines the necessary documentation to support the implementation and operation of the last-mile delivery workflow.

### Process Diagrams

* **High-level workflow:** A visual representation of the overall last-mile delivery process.
* **Detailed process flows:** Detailed diagrams for each sub-process (e.g., package assignment, delivery execution, exception handling).
* **System interactions:** Diagrams illustrating the interactions between different systems.
* **Data flow diagrams:** Diagrams showing the flow of data between different components.
* **Exception handling:** Diagrams outlining the workflows for different exception scenarios.
* **Integration architecture:** Visual representation of the system integration points and architecture.
* **Deployment architecture:** Diagram illustrating the deployment environment and infrastructure.

### Technical Specifications

* **API documentation:** Comprehensive documentation for all APIs, including endpoints, request/response formats, and authentication details.
* **Database schema:** Detailed schema diagrams and descriptions for all databases.
* **System requirements:** Hardware and software requirements for all system components.
* **Network architecture:** Diagram of the network infrastructure and communication paths.
* **Security controls:** Documentation of all implemented security controls and measures.
* **Monitoring setup:** Detailed instructions on setting up and configuring monitoring tools.
* **Backup procedures:** Documented procedures for data backup and recovery.

### Operational Procedures

* **Standard operations:** Step-by-step procedures for routine tasks within the last-mile delivery process.
* **Exception handling:** Detailed procedures for handling various exception scenarios.
* **Emergency procedures:** Protocols for handling critical incidents and emergencies.
* **Maintenance tasks:** Scheduled maintenance procedures for system components.
* **Training materials:** Materials for training delivery partners and internal staff on using the system.
* **Support processes:** Defined processes for providing technical support and resolving issues.
* **Escalation paths:** Clear escalation paths for different types of issues.

---

## Quality Assurance Requirements

This section outlines the quality assurance procedures and metrics for the last-mile delivery workflow.

### Testing Procedures

* **Functional testing:** Testing the functionality of each component and the overall workflow.
* **Performance testing:** Evaluating the performance of the system under different load conditions.
* **Integration testing:** Testing the interactions and data flow between different systems.
* **Security testing:** Testing the security vulnerabilities and effectiveness of security controls.
* **User acceptance testing (UAT):** Allowing end-users (delivery partners, customer service) to test the system and provide feedback.
* **Load testing:** Simulating high volumes of transactions to assess system scalability and stability.
* **Failover testing:** Testing the system’s ability to recover from failures and maintain availability.

### Quality Metrics

* **Delivery success rate:** Percentage of deliveries successfully completed without issues.
* **Temperature compliance:** Percentage of temperature-sensitive deliveries maintained within the required range.
* **System uptime:** Percentage of time the system is operational and available.
* **Data accuracy:** Accuracy and integrity of data throughout the system.
* **Customer satisfaction:** Scores reflecting customer happiness with the delivery experience.
* **Partner performance:** Metrics reflecting the efficiency and reliability of delivery partners.
* **Cost efficiency:** Metrics related to the cost of each delivery and overall cost optimization efforts.