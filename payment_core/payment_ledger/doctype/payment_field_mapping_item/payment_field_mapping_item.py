# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT. See LICENSE

from frappe.model.document import Document


class PaymentFieldMappingItem(Document):
	"""One purpose → reference field pair inside a Payment Field Mapping."""
