# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT. See LICENSE

from frappe.model.document import Document


class PaymentWebhookLog(Document):
	"""One provider webhook delivery, deduped per (source, event_id)."""

	def validate(self):
		# event ids are only unique per gateway: two providers may collide
		self.dedupe_key = f"{self.source}:{self.event_id}"
