import datetime
import json
import re
import time
import uuid
from itertools import chain

import frappe
import pytz
import requests
from frappe import _, qb, query_builder
from frappe.query_builder import Criterion, functions
from frappe.utils.file_manager import save_file

from edu_quality.public.py.utils import (
	add_indian_country_code,
	convert_time_string_to_hours,
	remove_indian_country_code,
)


def get_class_without_std(txt):
	if not txt:
		return " "
	if "Std. " in txt:
		return txt.split("Std. ")[1]
	return txt


def separate_name(full_name):
	# Split the full name into words
	if not full_name:
		return {
			"first_name": " ",
			"middle_name": " ",
			"last_name": " ",
		}
	name_parts = full_name.split()

	# Determine the number of name parts
	num_parts = len(name_parts)
	if num_parts == 0:
		return {
			"first_name": " ",
			"middle_name": " ",
			"last_name": " ",
		}
	if num_parts == 1:
		# If only one word is provided, consider it as the first name
		first_name = name_parts[0]
		middle_name = ""
		last_name = ""
	elif num_parts == 2:
		# If two words are provided, consider the first as first name and the second as last name
		first_name = name_parts[0]
		middle_name = ""
		last_name = name_parts[1]
	else:
		# If more than two words are provided, consider the first as first name,
		# the last as last name, and everything in between as middle name(s)
		first_name = name_parts[0]
		last_name = name_parts[-1]
		middle_name = " ".join(name_parts[1:-1])

	return {
		"first_name": first_name,
		"middle_name": middle_name,
		"last_name": last_name,
	}


def is_dob_in_range(lead_application, program_doc):
	start = program_doc.get("custom_date_start")
	dob = lead_application.get("date_of_birth")
	end = program_doc.get("custom_date_end")
	if not dob:
		# DOB is optional on a Lead (Facebook leads arrive without it; the parent
		# gives it in the Long Enquiry Form). With no DOB the age band cannot be
		# checked, so it is skipped rather than refusing conversion.
		return True
	if not start or not end:
		return True

	if dob <= end:
		return True
	else:
		return False


@frappe.whitelist()
def create_student_application(**args):
	try:
		if not args:
			raise frappe.exceptions.MandatoryError("Arguments are required")

		lead_doc_name = args.get("name")
		lead_application = frappe.get_doc("Lead", {"name": lead_doc_name})
		program_doc = frappe.get_doc("Program", lead_application.get("class"))

		if not is_dob_in_range(lead_application, program_doc):
			message = f"Date of Birth for class {lead_application.get('class')} is not less than {program_doc.get('custom_date_end')} "
			# frappe.msgprint(msg=message, title="Error", indicator="red")
			raise frappe.exceptions.MandatoryError(message)

		if not lead_application:
			return None

		student_application = frappe.get_doc(serialize_lead_to_application(lead_application))

		# created_mgr_lead = upload_to_mgr(student_application)
		# student_application.lms_id = created_mgr_lead.get("ID")
		# lead_application.lead_status = "Enrolled"
		frappe.db.set_value("Lead", lead_application.name, "status", "Applied")
		# lead_application.status = "Enrolled"
		# lead_application.flags.ignore_mandatory = True
		# lead_application.save()
		student_application.lead = lead_application.name
		student_application.insert(ignore_permissions=True)
		student_application.fathers_mobile_number = lead_application.fathers_phone
		frappe.msgprint("Created Student Application Successfully!")
		url = frappe.utils.get_url_to_form("Student Applicant", student_application.name)
		return url

	except Exception as e:
		frappe.msgprint(msg=str(e), title="Error", indicator="red")
		raise e


# @frappe.whitelist(allow_guest=True)
# def update_stud_data(**data):
#     try:
#         ref_no = data.get("Student").get("refNo", "")
#         ref_no = None if ref_no == "<REF-NO>" else ref_no
#         school_id = data.get("Student").get("school_id", None)
#         data = data.get("Student").get("StudentInfoChange")
#         isStudent = False if not ref_no or not school_id else True
#         # ref_no = data.get("refNo", None) or data.get("Student", {}).get("refNo", None)
#         # school_id = data.get("school_id", None) or data.get("Student", {}).get(
#         #     "school_id", None
#         # )
#         # applicant
#         existing_student_doc = None

#         if not isStudent:
#             existing_student_doc = frappe.get_list(
#                 "Student Applicant",
#                 {"lms_id": data.get("lms_id"), "school": data.get("school_name")},
#                 ignore_permissions=True,
#             )
#         else:
#             existing_student_doc = frappe.get_list(
#                 "Student",
#                 {
#                     "reference_number": ref_no,
#                     "school": school_id_map.get(str(school_id), ""),
#                 },
#                 ignore_permissions=True,
#             )

#         if not existing_student_doc or len(existing_student_doc) == 0:
#             raise Exception("Student Doesnt exist")
#         name = existing_student_doc[0].get("name")

#         current_user = frappe.session.user

#         frappe.set_user("Administrator")

#         # adhar_card_cert = save_file(
#         #     str(uuid.uuid4()),
#         #     data.get("adhar_card_cert"),
#         #     "Student Applicant",
#         #     name,
#         #     decode=True,
#         # )
#         try:
#             court_order = (
#                 save_file(
#                     str(uuid.uuid4()),
#                     data.get("court_order_doc"),
#                     "Student" if isStudent else "Student Applicant",
#                     name,
#                     decode=True,
#                 )
#                 if data.get("court_order_doc", "")
#                 else {}
#             )
#         except Exception:
#             court_order = {}
#             frappe.log_error(
#                 "Error uploading student data court order", str(frappe.get_traceback())
#             )

#         try:
#             image = (
#                 save_file(
#                     str(uuid.uuid4()),
#                     data.get("student_photo"),
#                     "Student" if isStudent else "Student Applicant",
#                     name,
#                     decode=True,
#                 )
#                 if data.get("student_photo", "")
#                 else {}
#             )
#         except Exception:
#             image = {}
#             frappe.log_error(
#                 "Error uploading student data image", str(frappe.get_traceback())
#             )
#         try:
#             birth_cert = (
#                 save_file(
#                     str(uuid.uuid4()),
#                     data.get("birth_cert"),
#                     "Student" if isStudent else "Student Applicant",
#                     name,
#                     decode=True,
#                 )
#                 if data.get("birth_cert", "")
#                 else {}
#             )
#         except Exception:
#             birth_cert = {}
#             frappe.log_error(
#                 "Error uploading student data birth cert", str(frappe.get_traceback())
#             )

#         try:
#             adhar_card_cert = (
#                 save_file(
#                     str(uuid.uuid4()),
#                     data.get("adhar_card_cert"),
#                     "Student" if isStudent else "Student Applicant",
#                     name,
#                     decode=True,
#                 )
#                 if data.get("adhar_card_cert", "")
#                 else {}
#             )
#         except Exception:
#             adhar_card_cert = {}
#             frappe.log_error(
#                 "Error uploading student aadhaar card cert", str(frappe.get_traceback())
#             )

#         frappe.set_user(current_user)
#         if not isStudent:
#             existing_student_doc = frappe.get_doc("Student Applicant", {"name": name})
#         else:
#             existing_student_doc = frappe.get_doc("Student", {"name": name})
#         father_in_doc = next(
#             (
#                 item
#                 for item in existing_student_doc.get("guardians")
#                 if item.get("relation") == "Father"
#             ),
#             {},
#         )
#         mother_in_doc = next(
#             (
#                 item
#                 for item in existing_student_doc.get("guardians")
#                 if item.get("relation") == "Mother"
#             ),
#             {},
#         )
#         other_in_doc = next(
#             (
#                 item
#                 for item in existing_student_doc.get("guardians")
#                 if item.get("relation") == "Others"
#             ),
#             {},
#         )
#         father = frappe.get_doc({"doctype": "Guardian"})
#         if father_in_doc:
#             father = frappe.get_doc("Guardian", father_in_doc.get("guardian"))
#         # father =frappe.get_doc({"doctype":'Guardian',"name":father_in_doc.get('guardian')})
#         father.first_name = (data.get("father_f_name"),)
#         father.guardian_name = data.get("father_f_name")
#         father.middle_name = data.get("father_m_name")
#         father.last_name = data.get("father_l_name")
#         father.education = data.get("father_education")
#         father.occupation = (
#             data.get("father_profession") or data.get("father_profession_other") or ""
#         )
#         father.mobile_number = data.get("father_mobile_no")
#         father.annual_income = data.get("father_annual_income")
#         father.email_address = data.get("father_email_id")
#         father.company_name = data.get("father_company_name")
#         father.designation = data.get("father_designation")
#         father.work_address = data.get("father_office_address")
#         father_in_doc = bool(father_in_doc)

#         if not father_in_doc:
#             father = father.insert(ignore_permissions=True)
#         else:
#             father.save(ignore_permissions=True)

#         # mother =frappe.get_doc({"doctype":'Guardian',"name":mother_in_doc.get('guardian')})
#         mother = frappe.get_doc({"doctype": "Guardian"})
#         if mother_in_doc:
#             mother = frappe.get_doc("Guardian", mother_in_doc.get("guardian"))
#         mother.first_name = data.get("mother_f_name")
#         mother.middle_name = data.get("mother_m_name")
#         mother.guardian_name = data.get("mother_f_name")
#         mother.last_name = data.get("mother_l_name")
#         mother.education = (data.get("mother_education"),)
#         mother.occupation = (
#             data.get("mother_profession") or data.get("mother_profession_other") or ""
#         )
#         mother.email_address = data.get("mother_email_id")
#         mother.mobile_number = data.get("mother_mobile_no")
#         mother.annual_income = data.get("mother_annual_income")
#         mother.company_name = data.get("mother_company_name")
#         mother.designation = data.get("mother_designation")
#         mother.work_address = data.get("mother_office_address")

#         mother_in_doc = bool(mother_in_doc)

#         if not mother_in_doc:
#             mother = mother.insert(ignore_permissions=True)
#         else:
#             mother.save(ignore_permissions=True)

#         # other = frappe.get_doc({"doctype":'Guardian',"name":other_in_doc.get('guardian')})
#         other = frappe.get_doc({"doctype": "Guardian"})
#         if other_in_doc:
#             other = frappe.get_doc("Guardian", other_in_doc.get("guardian"))
#         other.first_name = data.get("guardian_f_name")
#         other.guardian_name = data.get("guardian_f_name") or "not picked"
#         other.middle_name = data.get("guardian_m_name")
#         other.last_name = data.get("guardian_l_name")
#         other.education = data.get("guardian_education")
#         other.occupation = (
#             data.get("other_profession") or data.get("other_profession_other") or ""
#         )
#         other.mobile_number = data.get("guardian_mobile_no") or ""
#         other.address_line_1 = (data.get("guardian_bld_house"),)
#         other.address_line_2 = (data.get("guardian_sub_area"),)
#         other.city = (data.get("guardian_city"),)
#         other.pincode = (data.get("guardian_pin"),)
#         other.day_care_contact = data.get("day_care_contact")
#         other_in_doc = bool(other_in_doc)

#         if not other_in_doc and data.get("guardian_f_name"):
#             other = other.insert(ignore_permissions=True)

#         else:
#             other.save(ignore_permissions=True)

#         if not mother_in_doc:
#             existing_student_doc.append(
#                 "guardians",
#                 {
#                     "guardian": mother.get("name"),
#                     "guardian_name": mother.get("guardian_name"),
#                     "relation": "Mother",
#                 },
#             )

#         if not father_in_doc:
#             existing_student_doc.append(
#                 "guardians",
#                 {
#                     "guardian": father.get("name"),
#                     "guardian_name": father.get("guardian_name"),
#                     "relation": "Father",
#                 },
#             )

#         if not other_in_doc and data.get("guardian_f_name"):
#             existing_student_doc.append(
#                 "guardians",
#                 {
#                     "guardian": other.get("name"),
#                     "guardian_name": other.get("guardian_name"),
#                     "relation": "Others",
#                 },
#             )

#         existing_student_doc.lms_status = data.get("lms_status")

#         existing_student_doc.first_name = data.get("stud_f_name")
#         existing_student_doc.last_name = data.get("stud_l_name")

#         existing_student_doc.gender = data.get("gender")
#         existing_student_doc.date_of_birth = data.get("b_date")
#         existing_student_doc.address_line_1 = data.get("bld_house")
#         existing_student_doc.address_line_2 = data.get("sub_area")
#         existing_student_doc.landmark = data.get("landmark")
#         existing_student_doc.pincode = data.get("pin")
#         existing_student_doc.city = data.get("city")
#         existing_student_doc.state = data.get("state")
#         existing_student_doc.country = data.get("country")
#         existing_student_doc.bus_service_required = data.get("bus_service_required")
#         existing_student_doc.admission_to = data.get("admission_to")
#         existing_student_doc.academic_year = data.get("academic_year")
#         existing_student_doc.stud_rte = data.get("stud_rte")
#         existing_student_doc.is_rte = data.get("stud_rte")
#         existing_student_doc.caste = data.get("other_caste") or data.get("caste")
#         existing_student_doc.religion = data.get("other_religion") or data.get(
#             "religion"
#         )
#         existing_student_doc.subcaste = data.get("other_subcaste") or data.get(
#             "subcaste"
#         )
#         existing_student_doc.sub_caste = data.get("other_subcaste") or data.get(
#             "subcaste"
#         )
#         existing_student_doc.birth_place = data.get("b_city") or data.get("b_city")
#         existing_student_doc.student_mobile_number = data.get("student_sms_no")
#         existing_student_doc.student_is_existingstudent = int(
#             data.get("student_isexistingstudent") or 0
#         )
#         existing_student_doc.student_existing_ref_number = data.get(
#             "student_existing_ref_number"
#         )
#         existing_student_doc.is_sibling_in_school = int(
#             data.get("student_bro_sis_inschool") or 0
#         )
#         existing_student_doc.school = data.get("school_name")
#         existing_student_doc.blood_group = data.get("blood_group")
#         existing_student_doc.catering = data.get("catering")
#         existing_student_doc.aadhaar_card_number = data.get("adhar_card_no")

#         existing_student_doc.nationality = data.get("nationality")
#         existing_student_doc.allergies = bool(
#             data.get("other_allergies") or data.get("allergies")
#         )
#         existing_student_doc.custom_allergies = data.get("other_allergies") or data.get(
#             "allergies"
#         )
#         existing_student_doc.custom_mother_tongue = data.get(
#             "mother_tongue"
#         ) or data.get("other_mother_tongue")
#         existing_student_doc.mother_tongue = data.get("mother_tongue") or data.get(
#             "other_mother_tongue"
#         )
#         existing_student_doc.custom_mother_tongue = data.get(
#             "mother_tongue"
#         ) or data.get("other_mother_tongue")
#         existing_student_doc.aadhaar_card_certificate = adhar_card_cert.get(
#             "file_url", ""
#         )
#         existing_student_doc.aadhar_card_cert = adhar_card_cert.get("file_url", "")
#         existing_student_doc.birth_cert = birth_cert.get("file_url", "")
#         existing_student_doc.image = image.get("file_url", "")
#         existing_student_doc.custom_court_order = court_order.get("file_url", "")
#         existing_student_doc.save(ignore_permissions=True)
#         # if(mother_in_doc):
#         #     mother.save(ignore_permissions=True)
#         # if(father_in_doc):
#         #     father.save(ignore_permissions=True)
#         # if(other_in_doc):
#         #     other.save(ignore_permissions=True)

#         return existing_student_doc
#     except Exception:
#         frappe.log_error(
#             "Error updating student data", [str(frappe.get_traceback()), str(data)]
#         )


def default(obj):
	if isinstance(obj, datetime.date | datetime.datetime):
		return obj.isoformat()


def upload_to_mgr(doc):
	program = frappe.db.get_value("Program", doc.get("program"), "program_name") or " "
	JSON = {
		"user": frappe.db.get_single_value("MGR Settings", "username"),
		"password": frappe.utils.password.get_decrypted_password("MGR Settings", "MGR Settings", "password"),
		"school_name": doc.get("school"),
		"first_name": doc.get("first_name") + " " + (doc.get("middle_name") or ""),
		"last_name": doc.get("last_name") or " ",
		"mother_name": doc.get("mother_f_name") or " ",
		"father_name": doc.get("father_f_name"),
		"father_mobile_number": remove_indian_country_code(doc.get("father_mobile_no")),
		"father_email_address": doc.get("father_email"),
		"gender": doc.get("gender") or " ",
		"date_of_birth": doc.get("date_of_birth") or " ",
		"address1": doc.get("address_line_1") or " ",
		"address2": doc.get("address_line_2") or " ",
		"pin": doc.get("pincode") or " ",
		"city": doc.get("city") or " ",
		"state": doc.get("state") or " ",
		"bus_service_required": "yes" if doc.get("bus_service_required") else "no",
		"class": program or " ",
		"RTE_student": "yes" if doc.get("rte_student") or doc.get("is_rte") else "no",
		"preferred_batch_time": doc.get("batch_time") or " ",
		"academic_year": doc.get("academic_year") or " ",
	}
	mgr_url = frappe.db.get_single_value("MGR Settings", "url")
	if not mgr_url:
		# External LMS sync is optional; skip when no endpoint is configured.
		return
	response = requests.post(
		url=f"{mgr_url}/student_lms/post_student_lms_data",
		json=json.loads(json.dumps(JSON, default=default)),
	)
	try:
		if "OK" not in response.text:
			message = json.loads(response.text)
			frappe.msgprint(msg=message.get("message"), title="Error", indicator="red")
			raise frappe.exceptions.DuplicateEntryError(response.text)

		return json.loads(response.text)

	except Exception:
		frappe.log_error("MGR Error", response.text)
		raise frappe.exceptions.DuplicateEntryError(response.text)


def serialize_lead_to_application(doc: dict):
	if not doc:
		return {}

	if not doc.get("fathers_name") or not doc.get("fathers_phone"):
		frappe.msgprint(msg="Fathers name/phone is required", title="Error", indicator="red")
		raise frappe.exceptions.MandatoryError("Fathers name/phone is required")

	fees_structure = frappe.db.get_value(
		"Fee Structure",
		{
			"program": doc.get("class"),
			"school": doc.get("center"),
			"academic_year": doc.get("academic_year"),
		},
		"name",
	)
	fathers_name = separate_name(doc.get("fathers_name"))

	guardians = []
	append_father_guardian(doc, guardians, fathers_name)
	append_mother_guardian(doc, guardians)

	siblings = []
	if doc.get("is_sibling_already_in_school"):
		sibling_id = doc.get("custom_if_yes_reference_number_of_child")
		siblings = [{"student": sibling_id}] or []

	return {
		"doctype": "Student Applicant",
		"first_name": doc.get("first_name"),
		"last_name": doc.get("last_name"),
		"school": doc.get("center"),
		"academic_year": doc.get("academic_year"),
		"fee_structure": fees_structure,
		"student_email_id": f"test_only{str(time.time())}@yopmail.com",
		"guardians": guardians,
		"program": doc.get("class"),
		"father_f_name": doc.get("fathers_name"),
		"preferred_batch_time": doc.get("preferred_batch_time"),
		"batch_time": doc.get("preferred_batch_time"),
		"gender": doc.get("gender"),
		"address_line_2": doc.get("address2"),
		"address_line_1": doc.get("address"),
		"country": doc.get("country"),
		"pincode": doc.get("pincode"),
		"state": doc.get("state"),
		"city": doc.get("city"),
		"mother_f_name": doc.get("mothers_name"),
		"date_of_birth": doc.get("date_of_birth"),
		"student_mobile_number": doc.get("fathers_phone") or doc.get("mothers_phone"),
		"father_email": doc.get("fathers_email"),
		"mother_mobile_number": doc.get("mothers_phone"),
		"father_mobile_no": doc.get("fathers_phone"),
		"bus_service_required": doc.get("bus_service_required"),
		"is_sibling_in_school": doc.get("is_sibling_already_in_school"),
		"rte_student": doc.get("stud_rte"),
		"is_rte": doc.get("stud_rte"),
		"stud_rte": doc.get("rte_student"),
		"catering": doc.get("catering"),
		"siblings": siblings or [],
		"custom_referred_to": doc.get("referred_to"),
		"seeking_admission_in_class": doc.get("class"),
		"if_yes_reference_number_of_child": doc.get("if_yes_reference_number_of_child"),
	}


def append_mother_guardian(doc, guardians):
	if doc.get("mothers_name") and doc.get("mothers_name").strip():
		existing_mother = frappe.db.get_value(
			"Guardian",
			filters={"mobile_number": doc.get("mothers_phone")},
			fieldname="name",
		)
		mothers_name = separate_name(doc.get("mothers_name"))
		if not existing_mother:
			mother = frappe.get_doc(
				{
					"doctype": "Guardian",
					"guardian_name": doc.get("mothers_name") or " ",
					"first_name": mothers_name.get("first_name") or " ",
					"middle_name": mothers_name.get("middle_name"),
					"last_name": mothers_name.get("last_name"),
					"mobile_number": doc.get("mothers_phone") or " ",
					"email_address": doc.get("mothers_email"),
				}
			).insert(ignore_permissions=True)
		else:
			mother = frappe.get_doc("Guardian", existing_mother)
		guardians.append(
			{
				"guardian": mother.get("name"),
				"relation": "Mother",
				"guardian_name": mother.get("guardian_name"),
			}
		)


def append_father_guardian(doc, guardians, fathers_name):
	existing_father = frappe.db.get_value(
		"Guardian",
		filters={"mobile_number": doc.get("fathers_phone")},
		fieldname="name",
	)
	if not existing_father:
		father = frappe.get_doc(
			{
				"doctype": "Guardian",
				"guardian_name": doc.get("fathers_name"),
				"first_name": fathers_name.get("first_name") or " ",
				"middle_name": fathers_name.get("middle_name"),
				"last_name": fathers_name.get("last_name"),
				"mobile_number": doc.get("fathers_phone"),
				"email_address": doc.get("fathers_email"),
			}
		).insert(ignore_permissions=True)

	else:
		father = frappe.get_doc("Guardian", existing_father)

	guardians.append(
		{
			"guardian": father.get("name"),
			"relation": "Father",
			"guardian_name": father.get("guardian_name"),
		}
	)


def get_existing_leads(first_name, fathers_phone):
	# to improve condition in one go
	return (
		frappe.db.get_list(
			"Lead",
			filters={
				"first_name": first_name,
				# "fathers_name": kwargs.get("fathers_name"),
				"fathers_phone": remove_indian_country_code(str(fathers_phone)),
			},
			ignore_permissions=True,
		)
		or frappe.db.get_list(
			"Lead",
			filters={
				"first_name": "Partial_Lead",
				"fathers_phone": remove_indian_country_code(str(fathers_phone)),
			},
			ignore_permissions=True,
		)
		or frappe.db.get_list(
			"Lead",
			filters={
				"fathers_phone": remove_indian_country_code(str(fathers_phone)),
				"custom_is_partial": 1,
			},
			ignore_permissions=True,
		)
	)


def get_school(location):
	return location


def get_class(school_name, class_name):
	return frappe.db.get_value(
		"Program",
		{
			"school": school_name,
			"program_name": get_class_without_std(str(class_name)),
		},
		"name",
	)


def get_school_code(location):
	return frappe.db.get_value(
		"School",
		{"name": location},
		"prefix",
	)


def create_lead(kwargs):
	kwargs["fathers_name"] = kwargs.get("fathers_name", "").strip()
	kwargs["first_name"] = kwargs.get("first_name", "").strip()

	kwargs["fathers_name"] = (
		"father of " + kwargs.get("first_name")
		if kwargs.get("fathers_name") == kwargs.get("first_name")
		else kwargs.get("fathers_name") or " "
	)
	if not kwargs.get("first_name") or not kwargs.get("fathers_name") or not kwargs.get("fathers_phone"):
		raise frappe.exceptions.MandatoryError("First Name , Fathers Name or Fathers phone is required")
	student_name = separate_name(kwargs.get("first_name"))
	existing_leads = get_existing_leads(student_name.get("first_name"), kwargs.get("fathers_phone"))

	source = "Website"
	if source:
		source_doc = frappe.db.get_list(
			"Lead Source",
			filters={"source_name": kwargs.get("source", "Website")},
			ignore_permissions=True,
		)
		if len(source_doc):
			source = source_doc[0].get("name", None)
		else:
			frappe.get_doc({"doctype": "Lead Source", "source_name": kwargs.get("source")}).insert(
				ignore_permissions=True
			)
			source = kwargs.get("source")

	if len(existing_leads):
		return process_lead(
			source,
			frappe.get_doc("Lead", existing_leads[0].get("name")),
			kwargs.get("page_location", ""),
			"",
			kwargs,
		)

	school_name = get_school(kwargs.get("school")) or kwargs.get("school", "")
	class_name = get_class(school_name, kwargs.get("class", "")) or kwargs.get("class", "")

	lead_doc = frappe.get_doc(
		{
			"doctype": "Lead",
			"first_name": student_name.get("first_name"),
			"last_name": student_name.get("last_name"),
			"middle_name": student_name.get("middle_name"),
			"fathers_name": kwargs.get("fathers_name"),
			"fathers_email": kwargs.get("father_email_id") or kwargs.get("fathers_email"),
			"fathers_phone": remove_indian_country_code(str(kwargs.get("fathers_phone"))),
			# "mobile_no": remove_indian_country_code(str(kwargs.get("fathers_phone"))),
			"mothers_name": " ",
			"academic_year": kwargs.get("academic_year") or "2024-2025",
			"school_from_lead_source": kwargs.get("school"),
			"center": school_name,
			"class": class_name,
			"status": (
				"Hot"
				if kwargs.get("source", "").lower() == "walkin"
				or kwargs.get("lead_mode", "") == "school_walkin"
				else "Fresh"
			),
			"class_from_lead_source": kwargs.get("class"),
			"custom_previous_school": kwargs.get("current_school", ""),
			"source": source or "Website" or "Others",
			"custom_preferred_communication_mode": (
				"Call"
				if kwargs.get("communication_mode", "").lower() == "yes"
				else ("Chat" if kwargs.get("communication_mode", "").lower() == "no" else "Call")
			),
			"custom_preferred_communication_day": kwargs.get("communication_day", "Monday"),
			"custom_preferred_communication_time": kwargs.get("communication_time"),
			"location": kwargs.get("page_location"),
		}
	)
	if kwargs.get("source", "").lower() == "walkin" or kwargs.get("lead_mode", "") == "school_walkin":
		insert_walk_in_date(lead_doc)

	lead_doc.append(
		"notes",
		{
			"note": f'<div class="ql-editor read-mode"><p>Lead Registered from <b>{kwargs.get("source",source).capitalize()} {("at location " + kwargs.get("page_location")) if kwargs.get("page_location") else ""}</b> at <b>{datetime.datetime.now(pytz.timezone("Asia/Kolkata")).strftime("%d-%m-%Y , %H:%M IST")}</b> </p></div>'
		},
	)
	lead_doc = lead_doc.insert(ignore_permissions=True, ignore_mandatory=True)
	return lead_doc


@frappe.whitelist(allow_guest=True)
def create_student_lead(**kwargs):
	# return kwargs
	return create_lead(kwargs)


# to remove just there for backward compatibility to existing places where it is used
@frappe.whitelist(allow_guest=True)
def create_student_lead_fb(**kwargs):
	return create_lead(kwargs)


def process_lead(source, lead, page_location, detail="", kwargs={}):
	if (
		lead.first_name != "Partial Lead"
		and not lead.custom_is_partial
		and lead.status != "Enrolled"
		and lead.status != "Closed"
	):
		lead.status = "Hot"
		lead.custom_re_enquired_count += 1

	source = source if source else "Not Known"
	if source.lower() == "school" or source.lower() == "walkin" or get_school_code(location=source):
		lead.append("custom_lead_sub_status", {"sub_status": "Hot-School Visit Done"})
		insert_walk_in_date(lead)

	if source == "school_walkin" or source.lower() == "walkin":
		lead.append("custom_lead_sub_status", {"sub_status": "Hot-School Visit Done"})
		if lead.status != "Enrolled" and lead.status != "Closed":
			lead.status = "Hot"
		insert_walk_in_date(lead)
		# if lead 3 there replace it otherwise find first empty and put there

	if lead.first_name == "Partial_Lead" or lead.custom_is_partial:
		school_name = get_school(kwargs.get("school")) or kwargs.get("school", "")
		class_name = get_class(school_name, kwargs.get("class", "")) or kwargs.get("class", "")
		student_name = separate_name(kwargs.get("first_name"))

		lead.first_name = student_name.get("first_name")
		lead.last_name = student_name.get("last_name")
		lead.middle_name = student_name.get("middle_name")
		lead.custom_is_partial = 0
		lead.fathers_name = kwargs.get("fathers_name")
		lead.fathers_email = kwargs.get("father_email_id") or kwargs.get("fathers_email")
		lead.fathers_phone = remove_indian_country_code(kwargs.get("fathers_phone"))
		lead.mothers_name = " "
		lead.academic_year = kwargs.get("academic_year") or "2024-2025"
		lead.school_from_lead_source = kwargs.get("school")
		lead.center = school_name
		setattr(lead, "class", class_name)
		lead.class_from_lead_source = kwargs.get("class")
		lead.custom_previous_school = kwargs.get("current_school", "")
		update_communication(lead, kwargs)

	if source.lower() == "whatsapp":
		update_communication(lead, kwargs)

	lead.append(
		"notes",
		{
			"note": f'<div class="ql-editor read-mode"><p>Lead Re-Registered from <b>{source.capitalize()}  {("at location " + page_location.lower()) if page_location else ""}</b> at <b>{datetime.datetime.now(pytz.timezone("Asia/Kolkata")).strftime("%d-%m-%Y , %H:%M IST")}</b> </p>{ " "+detail if detail else ""}</div>'
		},
	)

	lead.flags.ignore_mandatory = True
	lead.save(ignore_permissions=True)
	frappe.db.commit()
	return lead


def update_communication(lead, kwargs):
	lead.custom_preferred_communication_mode = (
		"Call"
		if kwargs.get("communication_mode", "").lower() == "yes"
		else "Chat"
		if kwargs.get("communication_mode", "").lower() == "no"
		else "Call"
	)
	lead.custom_preferred_communication_day = kwargs.get("communication_day", "Monday")
	lead.custom_preferred_communication_time = kwargs.get("communication_time")


def insert_walk_in_date(lead):
	if (
		lead.get("custom_walk_in_3_action_date")
		and lead.get("custom_walk_in_2_action_date")
		and lead.get("custom_walk_in_1_action_date")
	):
		lead.custom_walk_in_3_action_date = datetime.datetime.now(pytz.timezone("Asia/Kolkata")).strftime(
			"%Y-%m-%d"
		)
	else:
		for i in range(1, 4):
			if not lead.get(f"custom_walk_in_{i}_action_date"):
				setattr(
					lead,
					f"custom_walk_in_{i}_action_date",
					datetime.datetime.now(pytz.timezone("Asia/Kolkata")).strftime("%Y-%m-%d"),
				)
				break


# api for only updating all leads belonging to phone number and processing them
@frappe.whitelist(allow_guest=True)
def handle_school_visit(**kwargs):
	try:
		school_visited = get_school(kwargs.get("location", ""))
		existing_leads = frappe.db.get_list(
			"Lead",
			filters=[
				[
					"fathers_phone",
					"Like",
					f'%{remove_indian_country_code(kwargs.get("phone_number") or kwargs.get("fathers_phone"))}%',
				],
				["status", "NOT IN", ["Closed", "Enrolled"]],
				["center", "Like", school_visited],
			],
			ignore_permissions=True,
		)
		# return len(existing_leads)
		# unoptimized to reduce from n+1 queries to 1

		if len(existing_leads):
			for lead in existing_leads:
				lead_doc = frappe.get_doc("Lead", lead.get("name"))
				# if not lead_doc.custom_lead_scheduled:
				# lead_doc.custom_walked_out_time = frappe.utils.now()
				# lead_doc.custom_lead_scheduled = 1

				process_lead("school_walkin", lead_doc, f"whatsapp {kwargs.get('location')}")

	except Exception as e:
		frappe.errprint(e)
		frappe.log_error(title="HandleSchoolVisit Error", message=frappe.get_traceback())


@frappe.whitelist(allow_guest=True)
def get_and_schedule_pending_walkouts():
	try:
		current = frappe.utils.now()
		current_datetime = datetime.datetime.strptime(current, "%Y-%m-%d %H:%M:%S.%f")
		lead = qb.DocType("Lead")

		timediff = query_builder.CustomFunction("TIMEDIFF", ["cur_date", "due_date"])
		hour = query_builder.CustomFunction("Hour", ["date"])

		query = (
			qb.from_(lead)
			.select(
				lead.fathers_phone,
				lead.name,
				lead.center,
			)
			.distinct()
			.where(
				(
					hour(
						timediff(
							current_datetime,
							lead.custom_walked_out_time,
						)
					)
					>= 4
				)
				& (lead.custom_lead_scheduled == 1)
			)
		)

		leads = query.run(as_dict=True)
		# enqueue only once to same phone number
		if len(leads):
			frappe.enqueue(
				"edu_quality.api.student_application.send_feedback_after_walkout",
				name=leads[0].get("name"),
				school=leads[0].get("center"),
				phone_number=leads[0].get("fathers_phone"),
				queue="long",
				timeout=4000,
			)

		# set to none in all leads
		for i in leads:
			set_walked_out_fields_none(i.get("name"))

		return "Queuing"
	except Exception as e:
		frappe.log_error(title="SchedulingPendingWorkflowForWalkin Error", message=frappe.get_traceback())


@frappe.whitelist(allow_guest=True)
def set_walked_out_fields_none(name):
	lead_doc = frappe.get_doc("Lead", name)
	lead_doc.custom_walked_out_time = None
	lead_doc.custom_lead_scheduled = 0

	lead_doc.flags.ignore_mandatory = True
	lead_doc.save(ignore_permissions=True)


def send_feedback_after_walkout(name, school, phone_number):
	botpress_url = frappe.db.get_single_value("Whatsapp Settings", "botpress_webhook_url")
	business_account_id = frappe.db.get_single_value("Whatsapp Settings", "business_account_id")
	phone_number_id = frappe.db.get_single_value("Whatsapp Settings", "phone_number_id")
	contact = frappe.get_all(
		"Contact",
		filters={"whatsapp_id": add_indian_country_code(str(phone_number))},
		fields=["*"],
		limit_page_length=1,
	)

	if len(contact) == 0:
		frappe.log_error("Error No contact found for phone number " + str(phone_number))
		return "Error contact not found"
	contact = contact[0]
	payload = {
		"object": "whatsapp_business_account",
		"entry": [
			{
				"id": business_account_id,
				"changes": [
					{
						"value": {
							"messaging_product": "whatsapp",
							"metadata": {
								"phone_number_id": phone_number_id,
							},
							"contacts": [
								{
									"profile": {"name": "NAME"},
									"wa_id": contact.get("whatsapp_id"),
								}
							],
							"messages": [
								{
									"from": contact.get("whatsapp_id"),
									"timestamp": datetime.datetime.now(
										pytz.timezone("Asia/Kolkata")
									).isoformat(),
									"id": str(uuid.uuid1()),
									"text": {"body": f"Start walkin feedback flow {school}"},
									"type": "text",
								}
							],
						},
						"field": "messages",
					}
				],
			}
		],
		"contact": contact,
	}

	requests.post(
		botpress_url,
		headers={"Content-Type": "application/json"},
		json=json.loads(json.dumps(payload, default=default)),
	)


@frappe.whitelist()
def handle_feedback(**kwargs):
	school_visited = get_school(kwargs.get("location", ""))

	existing_leads = frappe.db.get_list(
		"Lead",
		filters=[
			[
				"fathers_phone",
				"Like",
				f'%{remove_indian_country_code(kwargs.get("phone_number"))}%',
			],
			["status", "NOT IN", ["Closed", "Enrolled"]],
			["center", "Like", school_visited],
		],
		ignore_permissions=True,
	)
	# return len(existing_leads)
	# unoptimized to reduce from n+1 queries to 1
	if len(existing_leads):
		for lead in existing_leads:
			lead_doc = frappe.get_doc("Lead", lead.get("name"))
			process_lead(
				"feedback from whatsapp",
				lead_doc,
				f"whatsapp {kwargs.get('location')}",
				f"""
<div>
<b>Feedback: {kwargs.get("feedback_choice")}</b>
<p>
{kwargs.get('call_me_time',"No call time specified")},<br/>{kwargs.get("no_admission_reason","Not selected")},<br/>{kwargs.get("visiting_date","No visiting date specified")}
</p>
</div>""",
			)


@frappe.whitelist(allow_guest=True)
def create_partial_whatsapp_lead(**kwargs):
	if not kwargs.get("fathers_phone"):
		return "Error Creating lead"
	lead_doc_name = frappe.db.get_value(
		"Lead",
		{
			"fathers_phone": remove_indian_country_code(kwargs.get("fathers_phone")),
		},
		"name",
	)
	if lead_doc_name:
		return lead_doc_name

	new_lead_doc = frappe.get_doc(
		{
			"doctype": "Lead",
			"first_name": kwargs.get("fathers_phone"),
			"fathers_name": "Partial_Lead_Father_Name_Placeholder",
			"custom_is_partial": 1,
			"fathers_phone": remove_indian_country_code(str(kwargs.get("fathers_phone"))),
			"source": "Whatsapp",
		}
	)
	new_lead_doc.append(
		"notes",
		{
			"note": f'<div class="ql-editor read-mode"><p>Partial Lead Registered from <b>Whatsapp  at <b>{datetime.datetime.now(pytz.timezone("Asia/Kolkata")).strftime("%d-%m-%Y , %H:%M IST")}</b> </p></div>',
		},
	)

	new_lead_doc.insert(ignore_permissions=True, ignore_mandatory=True)
	return new_lead_doc


def rename_partial_lead(lead, school_code):
	try:
		splitted_name = lead.name.split("-")[1::]
		new_name = "-".join([school_code, *splitted_name])
		renamed_lead = frappe.rename_doc("Lead", lead.name, new_name, merge=False)
		print(renamed_lead)
		return lead.reload()

	except Exception as e:
		print(e)
		return lead
