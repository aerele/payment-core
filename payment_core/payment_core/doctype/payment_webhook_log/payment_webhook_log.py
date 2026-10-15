# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT. See LICENSE

from frappe.model.document import Document


class PaymentWebhookLog(Document):
	"""One provider webhook delivery, provider-neutral and deduped by event id."""
