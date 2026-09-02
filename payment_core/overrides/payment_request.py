# Copyright (c) Frappe Technologies Pvt. Ltd. and contributors
# License: MIT. See LICENSE
#
# Temporary shim: redirects ERPNext's Payment Request gateway resolution from
# the `payments` app to payment_core, until ERPNext changes it upstream.
# Rebinding the two module-level resolver helpers is enough — ERPNext's own
# methods resolve them at call time. Only `create_subscription` needs a class
# override (its payments import is function-local). The class is registered
# via `extend_doctype_class` (see hooks.py) so this module loads with the
# Payment Request controller; ERPNext's controller file stays pristine.

import erpnext.accounts.doctype.payment_request.payment_request as erpnext_payment_request

from payment_core.api.subscriptions import create_gateway_subscription
from payment_core.utils import get_payment_gateway_controller, is_v2_gateway

erpnext_payment_request._get_payment_gateway_controller = get_payment_gateway_controller
erpnext_payment_request._is_v2_gateway = is_v2_gateway


class PaymentRequest(erpnext_payment_request.PaymentRequest):
	"""Payment Request whose gateway resolution is owned by payment_core.

	All methods are inherited from ERPNext as-is; only `create_subscription`
	is overridden (function-local payments import, not redirectable).
	"""

	def create_subscription(self, payment_provider, gateway_controller, data):
		# Dispatch via payment_core's registry, not payments.stripe_integration.
		return create_gateway_subscription(payment_provider, gateway_controller, data)
