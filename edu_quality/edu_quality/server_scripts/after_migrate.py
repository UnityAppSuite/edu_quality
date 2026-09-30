import frappe
from frappe.utils import get_url


def after_migrate():
	site_url = get_url()
	if not ("uat" in site_url or "test" in site_url):
		return
	# replace_domain()
	replace_emails()
	replace_account_credentials()
	remove_webhooks()
	disable_incoming_emails()
	remove_mobile_push_tokens()
	# add_guardian_groups()


def replace_domain():
	frappe.db.set_single_value("MGR Settings", "email_domain", "yopmail.com")


def disable_incoming_emails():
	# On non-prod sites, stop all inbound email fetching so ticket/reply
	# automation does not fire against real mailboxes.
	for name in frappe.get_all("Email Account", {"enable_incoming": 1}, pluck="name"):
		frappe.db.set_value("Email Account", name, "enable_incoming", 0)


def add_guardian_groups():
	parents = frappe.db.get_all("Student Guardian", {"parenttype": "Student"}, "guardian")
	for parent in parents:
		email = frappe.db.get_value("Guardian", parent.guardian, "email_address")
		if email and not frappe.db.exists(
			"Email Group Member", {"email_group": "All Parents", "email": email}
		):
			doc = frappe.new_doc("Email Group Member")
			doc.email_group = "All Parents"
			doc.email = email
			doc.save(ignore_permissions=True)


def replace_emails():
	# guardian email/phone
	data = frappe.db.get_all("Guardian", fields=["name", "email_address"])
	for guardian in data:
		if guardian.email_address:
			new_email = guardian.email_address.split("@")[0] + "@yopmail.com"
			frappe.db.set_value(
				"Guardian",
				guardian.name,
				{"email_address": new_email, "mobile_number": None},
			)
		else:
			frappe.db.set_value("Guardian", guardian.name, "mobile_number", None)

	# student email/phone
	student = frappe.db.get_all("Student", fields=["name", "student_email_id"])
	for st in student:
		if st.student_email_id:
			new_email = st.student_email_id.split("@")[0] + "@yopmail.com"
			frappe.db.set_value(
				"Student",
				st.name,
				{
					"student_email_id": new_email,
					"student_mobile_number": "",
					"primary_contact": "",
					"whatsapp_number": "",
				},
			)
		else:
			frappe.db.set_value(
				"Student",
				st.name,
				{
					"student_mobile_number": "",
					"primary_contact": "",
					"whatsapp_number": "",
				},
			)

	# lead email/phone
	leads = frappe.db.get_all(
		"Lead",
		fields=[
			"name",
			"fathers_phone",
			"mothers_phone",
			"fathers_email",
			"mothers_email",
		],
	)
	for lead in leads:
		father_new = ""
		mother_new = ""
		if lead.fathers_email:
			father_new = lead.fathers_email.split("@")[0] + "@yopmail.com"
		if lead.mothers_email:
			mother_new = lead.mothers_email.split("@")[0] + "@yopmail.com"
		frappe.db.set_value(
			"Lead",
			lead.name,
			{
				"fathers_phone": "",
				"mothers_phone": "",
				"fathers_email": father_new,
				"mothers_email": mother_new,
			},
		)

	ease_settings = frappe.get_all("Easebuzz Settings")
	for setting in ease_settings:
		frappe.delete_doc("Easebuzz Settings", setting.name, force=True)


def replace_account_credentials():
	frappe.db.set_single_value(
		"Whatsapp Settings",
		{
			"access_token": "",
			"phone_number_id": "",
			"business_account_id": "",
			"app_id": "",
			"webhook_verify_token": "",
		},
	)
	frappe.db.set_single_value(
		"Google Drive",
		{
			"enable": 0,
			"backup_folder_name": "",
			"frequency": "",
			"email": "",
			"send_email_for_successful_backup": 0,
			"file_backup": 0,
			"backup_folder_id": "",
			"last_backup_on": "",
		},
	)
	frappe.db.set_single_value(
		"Google Settings",
		{"client_id": "", "client_secret": "", "api_key": "", "enable": 0},
	)
	frappe.db.set_single_value(
		"Google Service Account",
		{
			"service_account_credentials_json": "",
			"google_account_prefix": "uat",
			"create_student_workspace": 0,
			"root_folder": "",
			"class_photo_folder": "",
			"products_folder": "",
			"id_card_folder": "",
		},
	)


def remove_webhooks():
	webhooks = frappe.get_all("Webhook")
	for webhook in webhooks:
		frappe.delete_doc("Webhook", webhook.name)


def remove_mobile_push_tokens():
	mobile_push_tokens = frappe.get_all("Mobile Push Token")
	for mobile_push_token in mobile_push_tokens:
		frappe.delete_doc("Mobile Push Token", mobile_push_token.name)
