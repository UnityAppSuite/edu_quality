# Copyright (c) 2023, Hybrowlabs Technologies and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document

from edu_quality.api.google_service_auth import GoogleServiceAccountAuth


class GoogleServiceAccount(Document):
	pass


# edu_quality.edu_quality.doctype.google_service_account.google_service_account.get_folder_list
@frappe.whitelist()
def get_folder_list():
	oauth_obj = GoogleServiceAccountAuth("drive")
	google_drive_obj = oauth_obj.get_google_service_object()
	folders = (
		google_drive_obj.files()
		.list(
			q="mimeType='application/vnd.google-apps.folder' and trashed=false",
			supportsAllDrives=True,
			includeItemsFromAllDrives=True,
			pageSize=1000,
		)
		.execute()
	)
	return [f'{folder.get("name")}  id:  {folder.get("id")}' for folder in folders.get("files")]
