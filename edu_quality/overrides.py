import json

import frappe
from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
	get_accounting_dimensions,
)
from erpnext.accounts.doctype.bank_account.bank_account import get_party_bank_account
from erpnext.accounts.doctype.payment_entry.payment_entry import (
	get_company_defaults,
)
from erpnext.accounts.doctype.payment_request.payment_request import (
	PaymentRequest,
	_get_payment_gateway_controller,
	get_dummy_message,
	get_existing_payment_request_amount,
	get_gateway_details,
)
from frappe import _
from frappe.utils import nowdate
from frappe.utils.data import cint, flt


class CustomPaymentRequest(PaymentRequest):
	def set_as_paid(self):
		if self.payment_channel == "Phone":
			self.db_set("status", "Paid")

		else:
			if self.status != "Paid":
				payment_entry = self.create_payment_entry()
				# self.make_invoice()
				return payment_entry

	def refund_request(self):
		frappe.set_user("Administrator")
		doc = frappe.get_doc(self.reference_doctype, self.reference_name)
		paid_to = self.bank_account.split()[0]
		paid_to = frappe.db.get_value("Account", {"account_name": paid_to})
		company = doc.get("company") or frappe.db.get_default("company")
		cost_center = frappe.get_cached_value("Company", company, "cost_center")
		paid_from = frappe.db.get_single_value("Fees Settings", "refund_paid_from_account")
		payment_entry = frappe.get_doc(
			{
				"doctype": "Payment Entry",
				"payment_type": "Pay",
				"company": company,
				"cost_center": cost_center,
				"posting_date": nowdate(),
				"reference_date": nowdate(),
				"mode_of_payment": "Bank Draft",
				"party_type": "Student",
				"party": self.party,
				"party_name": frappe.get_value("Student", self.party, "first_name"),
				"paid_from": paid_from,
				"paid_to": paid_to,
				"paid_amount": self.grand_total,
				"received_amount": self.grand_total,
				"remarks": "Deposit Refund",
				"source_exchange_rate": 1,
				"target_exchange_rate": 1,
			}
		)

		for dimension in get_accounting_dimensions():
			payment_entry.update({dimension: doc.get(dimension)})

		payment_entry.insert(ignore_permissions=True)
		payment_entry.submit()
		return payment_entry

	def create_payment_entry(self, submit=False):
		if self.payment_request_type == "Outward":
			return self.refund_request()
		fees = frappe.get_doc(self.reference_doctype, self.reference_name)
		paid_amount = 0
		if self.payment_term:
			company_split = json.loads(fees.company_split)[self.payment_term]
			for company in company_split:
				paid_amount += company_split[company]["amount"]
				if company_split[company]["amount"] > 0:
					payment_entry(
						self,
						fees,
						company_split[company]["amount"],
						company_split[company]["paid_from"],
						company_split[company]["paid_to"],
						company,
						company_split[company]["cost_center"],
						company_split[company].get("fee_categories"),
					)
			mark_payment_term_paid(fees, self.payment_term, self.grand_total)
		else:
			company_split = json.loads(fees.company_split).get("Deposit")
			if company_split:
				for company in company_split:
					paid_amount += company_split[company]["amount"]
					payment_entry(
						self,
						fees,
						company_split[company]["amount"],
						company_split[company]["paid_from"],
						company_split[company]["paid_to"],
						company,
						company_split[company]["cost_center"],
						company_split[company].get("fee_categories"),
					)

		outstanding_amount = flt(fees.outstanding_amount) - paid_amount
		frappe.db.set_value(fees.doctype, fees.name, "outstanding_amount", outstanding_amount)
		self.db_set("status", "Paid")

		try:
			from nextai.funnel.custom_trigger import trigger_event

			trigger_event(doc=self, event_name="fee_receipt")
		except Exception as e:
			print("Chatnext is not installed")
		return payment_entry

	def set_payment_request_url(self):
		hash = frappe.utils.generate_hash(self.name, length=20)
		self.db_set("payment_hash", hash)
		url = frappe.utils.get_url() + "/payment?payment_request=" + hash
		self.db_set("payment_url", url)
		self.db_set("status", "Initiated")

	def get_payment_url(self, **kwargs):
		if self.reference_doctype == "Fees":
			data = frappe.db.get_value(
				self.reference_doctype, self.reference_name, ["student_name"], as_dict=1
			)
			data.update({"company": frappe.defaults.get_defaults().company})
		elif self.reference_doctype == "Fee Advance":
			data = frappe.db.get_value(self.reference_doctype, self.reference_name, ["student"], as_dict=1)
			data.update({"company": frappe.defaults.get_defaults().company})
		else:
			data = frappe.db.get_value(
				self.reference_doctype, self.reference_name, ["company", "customer_name"], as_dict=1
			)
		controller = self.get_payment_gateway_controller()

		controller.validate_transaction_currency(self.currency)

		if hasattr(controller, "validate_minimum_transaction_amount"):
			controller.validate_minimum_transaction_amount(self.currency, self.grand_total)

		return controller.get_payment_url(
			**{
				"amount": flt(self.grand_total, self.precision("grand_total")),
				"title": data.company.encode("utf-8"),
				"description": self.subject.encode("utf-8"),
				"reference_doctype": "Payment Request",
				"reference_docname": self.name,
				"payer_email": self.email_to or frappe.session.user,
				"payer_name": frappe.safe_encode(data.customer_name),
				"order_id": self.name,
				"currency": self.currency,
				"payment_method": kwargs.get("payment_method"),
			}
		)

	def on_payment_authorized(self, status=None):
		if not status:
			return
		if status in ["Authorized", "Completed"]:
			self.set_as_paid()

	def on_submit(self):
		if self.payment_request_type == "Outward":
			self.db_set("status", "Initiated")
			return
		elif self.payment_request_type == "Inward":
			self.db_set("status", "Requested")

		if self.payment_channel != "Phone":
			self.set_payment_request_url()
			self.make_communication_entry()

		elif self.payment_channel == "Phone":
			self.request_phone_payment()

	def make_communication_entry(self):
		"""Make communication entry"""
		comm = frappe.get_doc(
			{
				"doctype": "Communication",
				"subject": self.subject,
				"content": self.get_message(),
				"sent_or_received": "Sent",
				"communication_type": "Communication",
				"reference_doctype": self.reference_doctype,
				"reference_name": self.reference_name,
			}
		)
		comm.insert(ignore_permissions=True)

	def validate(self):
		if self.get("__islocal"):
			self.status = "Draft"

	def get_payment_gateway_controller(self):
		"""Return payment gateway controller"""
		enable_payment_mapping = frappe.get_value("Fees Settings", None, "enable_payment_mapping")
		if cint(enable_payment_mapping):
			program = None
			if self.reference_doctype == "Fees":
				program = frappe.get_value("Fees", self.reference_name, "program")
			elif self.reference_doctype == "Fee Advance":
				program = frappe.get_value("Fee Advance", self.reference_name, "next_program")

			payment_gateway, gateway_account = frappe.db.get_value(
				"Payment Mapping",
				{"parent": "Fees Settings", "grade": program},
				["payment_gateway", "gateway_account"],
			)
			try:
				return frappe.get_doc(payment_gateway, gateway_account)
			except Exception:
				frappe.throw(_("{0} not found").format(payment_gateway))

		gateway = frappe.get_doc("Payment Gateway", self.payment_gateway)

		if gateway.gateway_controller is None:
			try:
				return frappe.get_doc(f"{self.payment_gateway} Settings")
			except Exception:
				frappe.throw(_("{0} Settings not found").format(self.payment_gateway))
		else:
			try:
				return frappe.get_doc(gateway.gateway_settings, gateway.gateway_controller)
			except Exception:
				frappe.throw(_("{0} Settings not found").format(self.payment_gateway))


def payment_entry(doc, ref_doc, party_amount, paid_from, paid_to, company, cost_center, fee_categories=None):
	frappe.set_user("Administrator")

	payment_entry = frappe.get_doc(
		{
			"doctype": "Payment Entry",
			"payment_type": "Receive",
			"company": company,
			"cost_center": cost_center,
			"posting_date": nowdate(),
			"reference_date": nowdate(),
			"mode_of_payment": doc.get("mode_of_payment"),
			"party_type": "Student",
			"party": ref_doc.student,
			"party_name": frappe.get_value("Student", ref_doc.student, "first_name"),
			"paid_from": paid_from,
			"paid_to": paid_to,
			"paid_amount": party_amount,
			"received_amount": party_amount,
			"payment_term": doc.payment_term,
			"source_exchange_rate": 1,
			"target_exchange_rate": 1,
		}
	)

	payment_entry.update(
		{
			"mode_of_payment": doc.mode_of_payment,
			"reference_no": doc.name,
			"reference_date": nowdate(),
			"remarks": f"Payment Entry against {doc.reference_doctype} {doc.reference_name} via Payment Request {doc.name}",
		}
	)

	# Update dimensions
	payment_entry.update(
		{
			"cost_center": cost_center,
			"project": doc.get("project"),
		}
	)

	for dimension in get_accounting_dimensions():
		payment_entry.update({dimension: doc.get(dimension)})

	if payment_entry.difference_amount:
		company_details = get_company_defaults(company)

		payment_entry.append(
			"deductions",
			{
				"account": company_details.exchange_gain_loss_account,
				"cost_center": company_details.cost_center,
				"amount": payment_entry.difference_amount,
			},
		)

	if fee_categories:
		for fee_category in fee_categories:
			for fee_name, amount in fee_category.items():
				payment_entry.append(
					"fee_category",
					{
						"fee_category": fee_name,
						"amount": amount,
					},
				)

				school = frappe.get_value(
					"Fee Component", {"fees_category": fee_name, "parent": ref_doc.name}, "school"
				)
				payment_entry.update({"school": school})

	if not frappe.db.exists("Mode of Payment", "Online"):
		frappe.get_doc(
			{
				"doctype": "Mode of Payment",
				"name": "Online",
				"mode_of_payment": "Online",
			}
		).insert(ignore_permissions=True)

	payment_entry.update(
		{
			"reference_doctype": ref_doc.doctype,  # 'Fees' or 'Fee Advance'
			"reference_name": ref_doc.name,
			"payment_request": doc.name,
			"mode_of_payment": "Online",
		}
	)

	payment_entry.insert(ignore_permissions=True)
	payment_entry.submit()
	return payment_entry


def get_amount(ref_doc, payment_account=None, is_deposit=False, payment_term=None):
	"""get amount based on doctype"""
	dt = ref_doc.doctype
	if dt in ["Sales Order", "Purchase Order"]:
		grand_total = flt(ref_doc.rounded_total) or flt(ref_doc.grand_total)
	elif dt in ["Sales Invoice", "Purchase Invoice"]:
		if not ref_doc.get("is_pos"):
			if ref_doc.party_account_currency == ref_doc.currency:
				grand_total = flt(ref_doc.outstanding_amount)
			else:
				grand_total = flt(ref_doc.outstanding_amount) / ref_doc.conversion_rate
		elif dt == "Sales Invoice":
			for pay in ref_doc.payments:
				if pay.type == "Phone" and pay.account == payment_account:
					grand_total = pay.amount
					break
	elif dt == "POS Invoice":
		for pay in ref_doc.payments:
			if pay.type == "Phone" and pay.account == payment_account:
				grand_total = pay.amount
				break

	elif dt == "Fees" and is_deposit:
		grand_total = 0
		for f in ref_doc.components:
			if f.fee_type and f.fee_type != "Regular":
				grand_total += f.amount

	elif dt == "Fees" and payment_term:
		grand_total = 0
		for schedule in ref_doc.payment_schedule:
			if schedule.payment_term == payment_term:
				grand_total = frappe.db.get_value("Payment Schedule", schedule.name, "outstanding")

	elif dt == "Fees":
		grand_total = ref_doc.outstanding_amount

	elif dt == "Fee Advance":
		grand_total = ref_doc.amount

	if grand_total > 0:
		return grand_total
	else:
		frappe.throw(_("Payment Entry is already created"))


def create_fee_receipt(fees, payment_term=None, transaction_id=None):
	try:
		if not payment_term:
			categories = get_deposits(fees.components)
			due_date = nowdate()
		else:
			categories, due_date = get_categories(fees, payment_term)
		company_wise_split(fees, categories, due_date, payment_term, transaction_id)
	except Exception as e:
		frappe.log_error(title="FeeReceipt Error", message=frappe.get_traceback())
		return e


def get_deposits(components):
	deposits = [
		component for component in components if component.fees_category in ["deposit", "Application fee"]
	]
	return deposits


def get_categories(fees, payment_term, due_date=None, description="description", invoice_portion=100):
	categories = []
	for schedule in fees.payment_schedule:
		if schedule.payment_term == payment_term:
			invoice_portion, due_date, description = (
				schedule.invoice_portion,
				schedule.due_date,
				schedule.description,
			)
	for component in fees.components:
		if component.fees_category in ["deposit", "Application fee"]:
			if "deposit" in description:
				categories.append(component)
		else:
			component.amount = flt((invoice_portion / 100) * component.amount, 2)
			categories.append(component)
	return categories, due_date


def company_wise_split(fees, categories, due_date, payment_term=None, transaction_id=None):
	fee_categories = {}
	amounts = {}
	fee_amounts = {}

	for component in categories:
		fee_category = component.fees_category
		fee_amounts[fee_category] = component.amount
		company = frappe.get_value("Fee Category", fee_category, "custom_company")
		if fee_categories.get(company) is not None:
			fee_categories[company].append(fee_category)
			amounts[company] += component.amount
		else:
			fee_categories[company] = [fee_category]
			amounts[company] = component.amount

	for company, company_categories in fee_categories.items():
		fee_receipt = frappe.new_doc("Fee Receipt")
		fee_receipt.fees = fees.name
		fee_receipt.due_date = due_date
		fee_receipt.company = company
		fee_receipt.paid_on = nowdate()
		fee_receipt.amount = amounts[company]
		fee_receipt.transaction_id = transaction_id
		fee_receipt.payment_term = payment_term
		fee_receipt.school = fees.custom_school

		for fee_category in company_categories:
			fee_receipt.append(
				"fee_category", {"fee_category": fee_category, "amount": fee_amounts[fee_category]}
			)
		fee_receipt.insert(ignore_permissions=True)


def mark_payment_term_paid(fees, term, paid_amount):
	if fees.doctype == "Fee Advance":
		frappe.db.set_value("Fee Advance", fees.name, "paid_date", nowdate())
		return
	for schedule in fees.payment_schedule:
		if schedule.payment_term == term:
			if schedule.outstanding == paid_amount:
				frappe.db.set_value("Payment Schedule", schedule.name, "outstanding", 0)
				frappe.db.set_value("Payment Schedule", schedule.name, "paid_date", nowdate())


def make_payment_request(**args):
	"""Make payment request (internal helper — not exposed over HTTP)."""

	args = frappe._dict(args)
	ref_doc = frappe.get_doc(args.dt, args.dn)
	gateway_account = get_gateway_details(args) or frappe._dict()
	grand_total = get_amount(
		ref_doc, gateway_account.get("payment_account"), args.is_deposit, args.payment_term
	)
	if args.loyalty_points and args.dt == "Sales Order":
		from erpnext.accounts.doctype.loyalty_program.loyalty_program import validate_loyalty_points

		loyalty_amount = validate_loyalty_points(ref_doc, int(args.loyalty_points))
		frappe.db.set_value(
			"Sales Order", args.dn, "loyalty_points", int(args.loyalty_points), update_modified=False
		)
		frappe.db.set_value("Sales Order", args.dn, "loyalty_amount", loyalty_amount, update_modified=False)
		grand_total = grand_total - loyalty_amount

	bank_account = (
		get_party_bank_account(args.get("party_type"), args.get("party")) if args.get("party_type") else ""
	)

	draft_payment_request = frappe.db.get_value(
		"Payment Request",
		{"reference_doctype": args.dt, "reference_name": args.dn, "docstatus": 0},
	)

	# existing_payment_request_amount = get_existing_payment_request_amount(args.dt, args.dn)

	# if existing_payment_request_amount:
	#     grand_total -= existing_payment_request_amount
	# if draft_payment_request:
	#     frappe.db.set_value(
	#         "Payment Request", draft_payment_request, "grand_total", grand_total, update_modified=False
	#     )
	#     pr = frappe.get_doc("Payment Request", draft_payment_request)
	# else:
	pr = frappe.new_doc("Payment Request")
	pr.update(
		{
			"payment_gateway_account": gateway_account.get("name"),
			"payment_gateway": gateway_account.get("payment_gateway"),
			"payment_account": gateway_account.get("payment_account"),
			"payment_channel": gateway_account.get("payment_channel"),
			"payment_request_type": args.get("payment_request_type"),
			"currency": "INR",
			"grand_total": grand_total,
			"mode_of_payment": args.mode_of_payment,
			"email_to": args.recipient_id or ref_doc.owner,
			"subject": _("Payment Request for {0}").format(args.dn),
			"message": gateway_account.get("message") or get_dummy_message(ref_doc),
			"reference_doctype": args.dt,
			"reference_name": args.dn,
			"party_type": args.get("party_type") or "Customer",
			"party": args.get("party") or ref_doc.get("customer"),
			"bank_account": bank_account,
			"payment_term": args.payment_term,
			"company": ref_doc.get("company"),
		}
	)

	# Update dimensions
	pr.update(
		{
			"cost_center": ref_doc.get("cost_center"),
			"project": ref_doc.get("project"),
		}
	)

	for dimension in get_accounting_dimensions():
		pr.update({dimension: ref_doc.get(dimension)})

	if args.order_type == "Shopping Cart" or args.mute_email:
		pr.flags.mute_email = True

	pr.insert(ignore_permissions=True)
	if args.submit_doc:
		pr.submit()

	if args.order_type == "Shopping Cart":
		frappe.db.commit()
		frappe.local.response["type"] = "redirect"
		frappe.local.response["location"] = pr.get_payment_url()

	if args.return_doc:
		return pr

	return pr.as_dict()
