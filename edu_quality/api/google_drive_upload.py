import os
import tempfile
from urllib.parse import quote

import frappe
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from requests import get, post

from edu_quality.api.google_service_auth import GoogleServiceAccountAuth


@frappe.whitelist()
def get_google_drive_object():
	"""
	Returns an object of Google Drive.
	"""

	oauth_obj = GoogleServiceAccountAuth("drive")

	google_drive = oauth_obj.get_google_service_object()

	return google_drive


def get_google_folder_name_with_id(folder_id):
	try:
		if not folder_id:
			return False
		folder_exist = (
			get_google_drive_object()
			.files()
			.get(fileId=folder_id, fields="name", supportsAllDrives=True)
			.execute()
		)
		return folder_exist
	except Exception as e:
		frappe.msgprint("Something Went Wrong")
		return False


def check_for_folder_in_google_drive(folder_name=None, root_folder=None):
	"""Checks if folder exists in Google Drive else create it."""
	service_account_doc = frappe.get_single("Google Service Account")
	root_folder_id = root_folder or service_account_doc.get("root_folder")
	frappe.log_error(
		"Checking and creating folder drive",
		str([root_folder, root_folder_id, folder_name, service_account_doc.get("root_folder")]),
	)
	if folder_name is None:
		return root_folder_id

	def _create_folder_in_google_drive(google_drive, folder_name):
		file_metadata = {
			"name": folder_name,
			"mimeType": "application/vnd.google-apps.folder",
			"parents": [root_folder_id],
		}

		try:
			folder = (
				google_drive.files()
				.create(body=file_metadata, fields="id", supportsAllDrives=True)
				.execute()
				.get("id")
			)
			backup_folder_exists = True
			return folder

		except HttpError as e:
			frappe.throw(f"Google Drive - Could not create folder in Google Drive - Error Code {e}")

	google_drive = get_google_drive_object()

	try:
		encoded_folder_name = generate_name_for_drive(folder_name)
		google_drive_folders = (
			google_drive.files()
			.list(
				q=f"mimeType='application/vnd.google-apps.folder' and name='{encoded_folder_name}' and '{root_folder_id}' in parents",
				supportsAllDrives=True,
				includeItemsFromAllDrives=True,
			)
			.execute()
		)

	except HttpError as e:
		frappe.throw(f"Google Drive - Could not find folder in Google Drive - Error Code {e}")
	backup_folder_exists = False

	for f in google_drive_folders.get("files"):
		if f.get("name") == folder_name:
			backup_folder_exists = True
			return f.get("id")
	if not backup_folder_exists:
		return _create_folder_in_google_drive(google_drive, folder_name)


def get_absolute_path(file_url):
	site_path = frappe.get_site_path()
	if "private" in file_url:
		file_path = site_path + file_url
	else:
		file_path = site_path + "/public" + file_url
	return file_path


@frappe.whitelist()
def upload_file_to_drive(file_url, folder_name=None, root_folder=None, file_name=None, mimetype="image/jpeg"):
	# Get Google Drive Object
	google_drive = get_google_drive_object()

	# Check if folder exists in Google Drive
	id = check_for_folder_in_google_drive(folder_name, root_folder)

	file_metadata = {"name": file_name or os.path.basename(file_url), "parents": [id]}

	try:
		media = MediaFileUpload(get_absolute_path(file_url), mimetype, resumable=True)
		return (
			google_drive.files()
			.create(body=file_metadata, media_body=media, fields="id", supportsAllDrives=True)
			.execute()
		)
	except OSError as e:
		frappe.throw(f"Google Drive - Could not locate - {e}")

	return "Google Drive Backup Successful."


@frappe.whitelist()
def update_file_on_drive(file_url, file_id, file_name=None, mimetype="image/jpeg"):
	# Get Google Drive Object
	google_drive = get_google_drive_object()
	if file_name:
		file_metadata = {"name": file_name}

	try:
		media = MediaFileUpload(get_absolute_path(file_url), mimetype, resumable=True)
		result = (
			google_drive.files()
			.update(fileId=file_id, body=file_metadata, media_body=media, fields="id", supportsAllDrives=True)
			.execute()
		)
		return result
	except OSError as e:
		frappe.throw(f"Google Drive - Could not locate - {e}")

	return "Google Drive Backup Successful."


def upload_file_stream_to_drive(
	file_content,
	root_folder,
	file_name,
	mimetype,
	publish_progress=None,
	publish_doctype=None,
	publish_doc_name=None,
):
	# Get Google Drive Object

	google_drive = get_google_drive_object()
	id = check_for_folder_in_google_drive(None, root_folder)
	file_metadata = {"name": file_name, "parents": [id]}

	temp_file = tempfile.NamedTemporaryFile(delete=False)
	temp_file.write(file_content)
	temp_file.close()

	try:
		media = MediaFileUpload(temp_file.name, mimetype=mimetype, resumable=True)
		if not publish_progress:
			result = (
				google_drive.files()
				.create(body=file_metadata, media_body=media, fields="id", supportsAllDrives=True)
				.execute()
			)
			return result

		result = google_drive.files().create(
			body=file_metadata, media_body=media, fields="id", supportsAllDrives=True
		)
		response = None
		while response is None:
			status, response = result.next_chunk()

			if status:
				frappe.publish_progress(
					int(status.progress() * 100),
					title="Uploading to Drive",
					doctype=publish_doctype,
					docname=publish_doc_name,
				)

		return response

	except Exception as e:
		frappe.throw(f"Google Drive - Could not locate - {e}")
	finally:
		if os and temp_file and temp_file.name:
			os.remove(temp_file.name)
	return "Google Drive File Upload Successful"


def find_file_by_name_and_folder(file_name, root_folder_id):
	try:
		if not root_folder_id or not file_name:
			return False
		google_drive = get_google_drive_object()
		encoded_file_name = generate_name_for_drive(file_name)
		query = f"name='{encoded_file_name}' and '{root_folder_id}' in parents"

		results = (
			google_drive.files()
			.list(
				q=query,
				fields="files(id, name)",
				supportsAllDrives=True,
				includeItemsFromAllDrives=True,
			)
			.execute()
		)
		files = results.get("files", [])

		if files:
			return files[0]
		else:
			print("No files found with that name.")
			return False
	except Exception as e:
		return False


def update_file_stream_on_drive(
	file_content,
	file_id,
	mimetype,
	new_name=None,
	publish_progress=None,
	publish_doctype=None,
	publish_doc_name=None,
):
	# Get Google Drive Object

	google_drive = get_google_drive_object()
	temp_file = tempfile.NamedTemporaryFile(delete=False)
	temp_file.write(file_content)
	temp_file.close()
	file_metadata = None
	if new_name:
		file_metadata = {"name": new_name}
	try:
		media = MediaFileUpload(temp_file.name, mimetype=mimetype, resumable=True)
		if not publish_progress:
			result = (
				google_drive.files()
				.update(
					fileId=file_id,
					body=file_metadata,
					media_body=media,
					fields="id",
					supportsAllDrives=True,
				)
				.execute()
			)
			return result

		result = google_drive.files().update(
			fileId=file_id, body=file_metadata, media_body=media, fields="id", supportsAllDrives=True
		)

		response = None

		while response is None:
			status, response = result.next_chunk()

			if status:
				frappe.publish_progress(
					int(status.progress() * 100),
					"Updating File on Drive",
					publish_doctype,
					publish_doc_name,
				)

		return response

	except Exception as e:
		frappe.throw(f"Google Drive - Could not locate - {e}")
	finally:
		os.remove(temp_file.name)
	return "Google Drive File Update Successful"


# edu_quality.edu_quality.api.google_drive_upload.upload_file
@frappe.whitelist()
def upload_file(file_url, folder_name, root_folder=None):
	frappe.enqueue(
		"edu_quality.api.google_drive_upload.upload_file_to_drive",
		queue="long",
		timeout=1800,
		file_url=file_url,
		folder_name=folder_name,
		root_folder=root_folder,
	)
	return "Queued Successfully"


def schedule_delete_file_from_drive(file_id):
	frappe.enqueue(
		"edu_quality.edu_quality.api.google_drive_upload.delete_file_from_drive",
		queue="long",
		timeout=1800,
		file_id=file_id,
	)


@frappe.whitelist()
def delete_file_from_drive(file_id):
	try:
		google_drive = get_google_drive_object()
		google_drive.files().delete(fileId=file_id, supportsAllDrives=True).execute()
	except Exception as e:
		frappe.log_error("Error deleting folder ", str([e, "with id ", file_id]))
		frappe.throw(f"Google Drive - Could not Delete - {e}")


def progress_callback(request_id, response, exception):
	if exception:
		print("Error:", exception)
	else:
		print(
			"Upload Progress:",
			round(
				(int(response["bytes_uploaded"]) / int(response["total_bytes"])) * 100,
				2,
			),
			"%",
		)


def generate_name_for_drive(file_name):
	if not file_name:
		return ""
	return file_name.replace("\\", "\\\\").replace("'", r"\'")
