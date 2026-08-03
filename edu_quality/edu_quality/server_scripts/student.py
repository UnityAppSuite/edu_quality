import datetime

import frappe
from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
	get_accounting_dimensions,
)
from erpnext.accounts.doctype.bank_account.bank_account import get_party_bank_account
from erpnext.accounts.doctype.payment_request.payment_request import get_gateway_details
from frappe.utils import getdate

from edu_quality.api.print_id_card import generate_permanent_id_cards
from edu_quality.edu_quality.server_scripts.utils import get_email_domain


@frappe.whitelist()
def validate_bank_account(student):
	return frappe.db.exists("Bank Account", {"party": student})


@frappe.whitelist()
def cancel_student(student, academic_year, fee_collection):
	try:
		if frappe.db.exists(
			"Program Enrollment", {"student": student, "academic_year": academic_year, "docstatus": 1}
		):
			frappe.db.set_value(
				"Program Enrollment",
				{"student": student, "academic_year": academic_year, "docstatus": 1},
				"docstatus",
				2,
			)
		frappe.db.set_value("Student", student, "enabled", 0)
		frappe.db.set_value("Student", student, "student_status", "Cancelled")
		fees_list = frappe.db.get_all("Fees", filters={"docstatus": 1, "student": student})
		for fee in fees_list:
			if frappe.db.exists(
				"Fee Component", [["parent", "=", fee.name], ["fees_category", "like", "%DEPOSIT%"]]
			):
				deposit = frappe.db.get_value(
					"Fee Component",
					[["parent", "=", fee.name], ["fees_category", "like", "%DEPOSIT%"]],
					"amount",
				)
				refund_deposit(student, fee.name, deposit)
		return 1
	except Exception as e:
		frappe.log_error(title="Cancel Error", message=frappe.get_traceback())
		return 0


def refund_deposit(student, fee, amount):
	gateway_account = get_gateway_details({}) or frappe._dict()
	pr = frappe.new_doc("Payment Request")
	ref_doc = frappe.get_doc("Fees", fee)
	bank_account = get_party_bank_account("Student", student)
	pr.update(
		{
			"payment_gateway_account": gateway_account.get("name"),
			"payment_gateway": gateway_account.get("payment_gateway"),
			"payment_account": gateway_account.get("payment_account"),
			"payment_channel": gateway_account.get("payment_channel"),
			"payment_request_type": "Outward",
			"currency": "INR",
			"grand_total": amount,
			"email_to": f"{student}@{get_email_domain()}",
			"subject": f"Deposit Refund For for {student}",
			"message": "Deposit Refund",
			"reference_doctype": "Fees",
			"reference_name": fee,
			"party_type": "Student",
			"party": student,
			"bank_account": bank_account,
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

	pr.insert(ignore_permissions=True)
	pr.submit()


@frappe.whitelist()
def mark_entry(student, status, reason=None, date=None, time=None):
	current_datetime = frappe.utils.now()
	curr_date, curr_time = current_datetime.split(" ")

	if not date:
		date = curr_date
	if not time:
		time = curr_time

	try:
		if frappe.db.exists("Attendance Entry", {"student": student, "date": date}):
			entry = frappe.get_doc("Attendance Entry", {"student": student, "date": date})
			entry.append(
				"absent_and_delays",
				{
					"reason": reason,
					"status": status,
					"timestamp": date + " " + time,
					"user": frappe.session.user,
				},
			)
			entry.flags.ignore_mandatory = True
			entry.save(ignore_permissions=True)
		else:
			entry = frappe.new_doc("Attendance Entry")
			entry.student = student
			entry.date = date
			entry.append(
				"absent_and_delays",
				{
					"reason": reason,
					"status": status,
					"timestamp": date + " " + time,
					"user": frappe.session.user,
				},
			)
			entry.insert(ignore_permissions=True)
		return True
	except Exception as e:
		frappe.log_error(title="Entry Error", message=frappe.get_traceback())
		return False


@frappe.whitelist()
def swap_division(**kwargs):
	try:
		division = kwargs.get("division")
		student = kwargs.get("student_to_swap")
		pe = kwargs.get("program_enrollment")
		pe_doc = frappe.get_doc("Program Enrollment", pe)

		if division:
			# remove from current division
			remove_from_division(pe_doc)
			# add to new division
			roll_no = add_to_division(pe_doc, division)
			enrollments = frappe.json.dumps([pe_doc.name])
			generate_permanent_id_cards(enrollments=enrollments)
			update_linked_docs(pe_doc, division, pe_doc.student_batch_name, roll_no=roll_no)
			send_email_for_division_swap(pe_doc, is_swap=False)
			# sync division data
			sync_and_sort_division_data(division)
			sync_and_sort_division_data(pe_doc.student_group)
			return True
		elif student:
			# get the program enrollment of the student to swap
			swap_pe = frappe.get_doc(
				"Program Enrollment",
				{"student": student, "academic_year": pe_doc.academic_year, "docstatus": 1},
			)
			# swap the division
			swap_student_division(pe_doc, swap_pe)
			# sync division data
			sync_and_sort_division_data(pe_doc.student_group)
			sync_and_sort_division_data(swap_pe.student_group)
			return True
	except:
		frappe.db.rollback()
		frappe.log_error("Error while swapping division", frappe.get_traceback())
		return False


def remove_from_division(doc):
	"""
	doc: Program Enrollment
	division: Division
	this function removes the student from the division
	"""
	division = frappe.get_doc("Student Group", doc.student_group)
	roll_no = None
	for d in division.students:
		if d.student == doc.student:
			roll_no = d.group_roll_number
			division.remove(d)
			break
	division.save()
	add_comment_in_division(doc, doc.student_group, True)
	add_student_log(doc, doc.student_group, True)
	return roll_no


def add_to_division(doc, division, roll_no=0, add_log=True):
	"""
	doc: Program Enrollment
	division: Division
	this function adds the student to the division
	"""
	sg = frappe.get_doc("Student Group", division)
	if len(sg.students) >= sg.max_strength and sg.max_strength != 0:
		return frappe.throw("Max strength reached")

	next_roll_number = 0
	if not roll_no:
		roll_numbers = frappe.get_all(
			"Program Enrollment",
			filters=[
				["Program Enrollment", "custom_status", "!=", "Cancelled"],
				["Program Enrollment", "student_group", "=", division],
				["Program Enrollment", "docstatus", "=", "1"],
			],
			pluck="roll_no",
		)
		roll_numbers = set(roll_numbers)
		total_students = frappe.db.count(
			"Program Enrollment",
			filters=[
				["Program Enrollment", "custom_status", "!=", "Cancelled"],
				["Program Enrollment", "student_group", "=", division],
				["Program Enrollment", "docstatus", "=", "1"],
			],
		)

		for i in range(1, total_students + 1):
			if str(i) not in roll_numbers:
				next_roll_number = i
				break
		if not next_roll_number:
			next_roll_number = total_students + 1

	sg.append(
		"students",
		{
			"student": doc.student,
			"student_name": doc.student_name,
			"group_roll_number": next_roll_number or roll_no,
			"active": 1,
		},
	)
	sg.save()

	if add_log:
		add_comment_in_division(doc, division)
		add_student_log(doc, division)
	return next_roll_number or roll_no


def sync_and_sort_division_data(division):
	"""
	division: Division
	this function syncs the student data in the division and sorts the students based on roll number
	"""
	div_doc = frappe.get_doc("Student Group", division)
	div_doc.students = []
	students = frappe.get_all(
		"Program Enrollment",
		[
			["Program Enrollment", "student_group", "=", division],
			["Program Enrollment", "docstatus", "=", "1"],
			["Program Enrollment", "custom_status", "!=", "Cancelled"],
		],
		["student", "roll_no"],
	)
	sorted_students = sorted(students, key=lambda x: int(x["roll_no"] if x["roll_no"] is not None else "0"))
	for student in sorted_students:
		roll_no = int(student.roll_no) if student.roll_no else None
		div_doc.append(
			"students",
			{"student": student.student, "group_roll_number": roll_no},
		)
	div_doc.save()


def swap_student_division(pe_doc_1, pe_doc_2):
	"""
	pe_doc_1: Program Enrollment of student 1
	pe_doc_2: Program Enrollment of student 2
	this function swaps the student division
	"""
	division_1 = pe_doc_1.student_group
	division_2 = pe_doc_2.student_group
	batch_1 = pe_doc_1.student_batch_name
	batch_2 = pe_doc_2.student_batch_name
	# remove student 1 from current division
	rno1 = remove_from_division(pe_doc_1)
	# remove student 2 from current division
	rno2 = remove_from_division(pe_doc_2)
	# add student 1 to student 2 division
	add_to_division(pe_doc_1, division_2, roll_no=rno2)
	# update details in program enrollment of student 1
	update_linked_docs(pe_doc_1, division_2, batch_2, roll_no=rno2)
	# add student 2 to student 1 division
	add_to_division(pe_doc_2, division_1, roll_no=rno1)
	# update details in program enrollment of student 2
	update_linked_docs(pe_doc_2, division_1, batch_1, roll_no=rno1)
	# generate permanent id cards
	enrollments = frappe.json.dumps([pe_doc_1.name, pe_doc_2.name])
	generate_permanent_id_cards(enrollments=enrollments)

	# send email to bcc admin of school
	send_email_for_division_swap(pe_doc_1)
	send_email_for_division_swap(pe_doc_2)
	return True


def send_email_for_division_swap(pe_doc_1, is_swap=True):
	"""
	pe_doc_1: Program Enrollment of student 1
	this function sends email to students for division swap
	"""
	try:
		student = frappe.get_doc("Student", pe_doc_1.student)
		school = frappe.get_doc("School", pe_doc_1.custom_school)
		bcc_emails = (
			[
				eg.email
				for eg in frappe.get_all(
					"Email Group Member", filters={"email_group": school.admin_group}, fields=["email"]
				)
			]
			if school.admin_group
			else []
		)

		message = f"Division of Student: {student.student_name}({student.name}) has been {'swapped' if is_swap else 'added to division'} successfully. Please find the details below:\n\nDivision: {pe_doc_1.student_group}"

		frappe.sendmail(
			recipients=[school.bcc_email_address],
			bcc=bcc_emails,
			subject="Division Swap",
			message=message,
		)
	except:
		frappe.log_error("Error in Sending Email While Division Swap", frappe.get_traceback())


def add_comment_in_division(student, division, is_removed=False):
	"""
	Adds a comment in the division for a student.

	Args:
	    student (object): The student object.
	    division (str): The division name.
	    is_removed (bool, optional): Flag to indicate if the student is removed. Defaults to False.
	"""
	if is_removed:
		comment = f"Student: {student.student_name}({student.name}) is Removed from division {division}"
	else:
		comment = f"Student: {student.student_name}({student.name}) is Added to division {division}"
	frappe.get_doc(
		{
			"doctype": "Comment",
			"comment_type": "Info",
			"reference_doctype": "Student Group",
			"reference_name": division,
			"content": comment,
		}
	).insert(ignore_permissions=True)


def add_student_log(doc, division, is_removed=False):
	"""
	doc: Program Enrollment
	division: Division
	this function adds student log
	"""
	student_info = f"Student: {doc.student_name}({doc.name})"
	action = "Removed from" if is_removed else "Added to"
	log = f"{student_info} is {action} division {division}"

	doc_info = {
		"doctype": "Student Log",
		"student": doc.student,
		"type": "General",
		"academic_year": doc.academic_year,
		"academic_term": doc.academic_term,
		"program": doc.program,
		"student_batch": doc.student_batch_name,
		"log": log,
		"date": frappe.utils.now_datetime(),
	}

	frappe.get_doc(doc_info).insert(ignore_permissions=True)


def update_linked_docs(pe_doc, student_group, batch_name, tiffin_rack_no=None, roll_no=None):
	"""
	pe_doc: Program Enrollment
	student_group: Student Group
	batch_name: Batch Name
	this function updates linked documents like student, program enrollment
	"""
	# update student group, tiffin rack no, and batch in program enrollment
	pe_doc.student_group = student_group
	pe_doc.tiffin_rack_no = tiffin_rack_no
	pe_doc.student_batch_name = batch_name
	pe_doc.roll_no = roll_no
	pe_doc.save()
