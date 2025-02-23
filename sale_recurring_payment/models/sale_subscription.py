import logging
from datetime import datetime
from html import escape

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class SaleSubscription(models.Model):
    _inherit = "sale.subscription"

    payment_provider_subscription_id = fields.Many2one(
        "payment.provider.subscription",
        string="Payment Provider Subscription",
        readonly=True,
    )
    is_payment_provider_subscription_terminated = fields.Boolean()
    last_date_invoiced = fields.Date(
        help="Date when last invoice was generated for the subscription",
    )
    paid_for_date = fields.Date(
        help="The date until the subscription is paid for (invoice date + recurring rule)",
        compute="_compute_paid_for_date",
        store=True,
    )

    @api.depends("invoice_ids", "invoice_ids.payment_state", "invoice_ids.invoice_date")
    def _compute_paid_for_date(self):
        for sub in self:
            paid_for_date = False
            paid_invoices = sub.invoice_ids.filtered(
                lambda s: s.payment_state == "paid"
            )
            if paid_invoices:
                last_paid_invoice = paid_invoices.sorted("invoice_date")[-1]
                type_interval = sub.template_id.recurring_rule_type
                interval = int(sub.template_id.recurring_interval)
                paid_for_date = last_paid_invoice.invoice_date + relativedelta(
                    **{type_interval: interval}
                )
            sub.paid_for_date = paid_for_date

    @api.model
    def cron_update_payment_provider_subscriptions(self):
        date_ref = fields.Date.context_today(self)
        sale_subscriptions = self.search(
            [
                ("template_id.invoicing_mode", "!=", "sale_and_invoice"),
                ("payment_provider_subscription_id", "!=", False),
                ("is_payment_provider_subscription_terminated", "=", False),
                "|",
                ("recurring_next_date", "<=", date_ref),
                ("last_date_invoiced", "=", date_ref),
            ]
        )
        companies = set(sale_subscriptions.mapped("company_id"))
        for company in companies:
            sale_subscriptions_to_update = sale_subscriptions.filtered(
                lambda s: s.company_id == company
                and (not s.date or s.recurring_next_date <= s.date)
            ).with_company(company)
            for sale_subscription in sale_subscriptions_to_update:
                try:
                    sale_subscription.update_sale_subscription_payments_and_subscription_status(
                        date_ref
                    )
                except Exception as exception:
                    sale_subscription._log_provider_exception(
                        exception, "updating subscription"
                    )
        return True

    def update_sale_subscription_payments_and_subscription_status(self, date_ref):
        # This method needs to be extended in each provider module.
        # This method updates the payments, their status and subscription status for sale subscriptions
        return True

    @api.model
    def cron_terminate_payment_provider_subscriptions(self):
        date_ref = fields.Date.context_today(self)
        sale_subscriptions = self.search(
            [
                ("payment_provider_subscription_id", "!=", False),
                ("is_payment_provider_subscription_terminated", "=", False),
                ("date", "<=", date_ref),
            ]
        )
        for sale_subscription in sale_subscriptions:
            try:
                sale_subscription.terminate_payment_provider_subscription()
            except Exception as exception:
                sale_subscription._log_provider_exception(
                    exception, "terminating subscription"
                )
        return True

    def generate_invoice(self):
        res = super().generate_invoice()
        self.last_date_invoiced = fields.Date.context_today(self)
        return res

    def write(self, values):
        if "stage_id" in values:
            for record in self:
                if (
                    record.stage_id
                    and record.stage_id.type == "post"
                    and record.payment_provider_subscription_id
                    and record.is_payment_provider_subscription_terminated
                ):
                    raise UserError(
                        _(
                            "Terminated subscriptions with payment provider subscription also terminated cannot be "
                            "updated. Please generate a new subscription"
                        )
                    )
        if "sale_subscription_line_ids" in values:
            # Don't allow changes on in-progress subs because atm it will not be reflected in the payment provider (e.g. Mollie)
            if self.filtered(
                lambda sub: sub.payment_provider_subscription_id and sub.in_progress
            ):
                raise UserError(
                    _(
                        "Cannot change in-progress subscriptions. Please close this one and create a new one."
                    )
                )

        res = super().write(values)
        if "stage_id" in values:
            for record in self:
                if (
                    record.stage_id
                    and record.stage_id.type == "post"
                    and record.payment_provider_subscription_id
                    and not record.is_payment_provider_subscription_terminated
                ):
                    record.terminate_payment_provider_subscription()
        return res

    @api.model
    def terminate_payment_provider_subscription(self):
        # This method cancels/terminates the subscription
        # This method needs to be extended in each provider module to end the subscriptions on provider end.
        vals = {"date": datetime.today(), "recurring_next_date": False}
        stage = self.stage_id
        closed_stage = self.env["sale.subscription.stage"].search(
            [("type", "=", "post")], limit=1
        )
        if stage != closed_stage:
            vals["stage_id"]: closed_stage.id
        return vals

    def _log_provider_exception(self, exception, process):
        """Both log error, and post a message on the subscription record."""
        self.ensure_one()
        _logger.warning(
            _("Payment Provider %(name)s: Error " "while %(process)s"),
            dict(
                name=self.payment_provider_subscription_id.provider_id.name,
                process=process,
            ),
            exc_info=True,
        )
        self.message_post(
            body=_(
                "Payment Provider {name}: Error"
                " while {process} - {exception}. See server logs for "
                "more details."
            ).format(
                name=self.payment_provider_subscription_id.provider_id.name,
                process=process,
                exception=escape(str(exception)) or _("N/A"),
            ),
            subject=_("Issue with Payment Provider"),
        )
