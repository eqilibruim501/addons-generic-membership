from datetime import timedelta

from dateutil.relativedelta import relativedelta

from odoo import Command, _, api, fields, models
from odoo.exceptions import ValidationError


class Subscription(models.Model):
    _inherit = "sale.subscription"

    application_ids = fields.One2many(
        comodel_name="argocd.application", inverse_name="subscription_id"
    )

    free_trial_end_date = fields.Date()

    def create_invoice(self):
        res = super().create_invoice()
        if (
            self.sale_subscription_line_ids.filtered(
                lambda l: l.product_id.application_template_id
            )
            and len(self.invoice_ids) == 1
        ):
            # Set price of the first invoice to 1.00
            free_period = self._get_free_period()
            if free_period:
                self.invoice_ids.invoice_line_ids.filtered(
                    lambda l: l.product_id.application_template_id
                ).price_unit = 1.0
        return res

    def _get_grace_period(self):
        return int(
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("argocd_sale.grace_period", "0")
        )

    @api.constrains("sale_subscription_line_ids")
    def _check_multiple_application_products(self):
        app_lines = self.sale_subscription_line_ids.filtered(
            lambda l: l.product_id.application_template_id
        )
        if len(app_lines) > 1:
            raise ValidationError(
                _("Subscription can only have one application, please remove one")
            )

    def _customer_name_to_application_name(self):
        self.ensure_one()
        replacements = {" ": "-", ".": "", "&": "-"}
        partner = self.partner_id.commercial_partner_id
        name = partner.display_name
        name = name.strip().lower()
        for replace in replacements:
            name = name.replace(replace, replacements[replace])
        return "".join(c for c in name if c.isalnum() or c == "-")

    def _invoice_paid_hook(self):
        application_sudo = self.env["argocd.application"].sudo()

        for subscription in self.filtered(
            lambda i: len(i.invoice_ids) == 1
            and i.sale_subscription_line_ids.filtered(
                lambda l: l.product_id.application_template_id
            )
        ):  # Create the application after the first invoice has been paid
            free_period = subscription._get_free_period()
            if free_period:
                today = fields.Datetime.today()
                subscription.recurring_next_date = today + free_period
                subscription.free_trial_end_date = today + free_period
            subscription.action_start_subscription()
            lines = subscription.sale_subscription_line_ids.filtered(
                lambda l: l.product_id.application_template_id
            )
            for line in lines:
                name = application_sudo.find_next_available_name(
                    self._customer_name_to_application_name()
                )
                tags = subscription.sale_subscription_line_ids.filtered(
                    lambda l: l.product_id.application_tag_ids
                    and not l.product_id.application_filter_ids  # All lines with modules linked to them
                    or line.product_id.application_template_id  # If there's no filter
                    in l.product_id.application_filter_ids  # If there's a filter
                ).mapped("product_id.application_tag_ids")

                application = application_sudo.create(
                    {
                        "name": name,
                        "subscription_id": subscription.id,
                        "tag_ids": tags.ids,
                        "template_id": line.product_id.application_template_id.id,
                        "application_set_id": line.product_id.application_set_id.id,
                    }
                )
                application.render_config()
                application.deploy()

    def _do_grace_period_action(self):
        """
        Executes the grace period action on self.

        @return: False if nothing has been done, True if the action has been done
        """
        grace_period_action = self.env["ir.config_parameter"].get_param(
            "argocd_sale.grace_period_action"
        )
        if not grace_period_action:
            return False  # Do nothing
        if grace_period_action == "add_tag":
            grace_period_tag_id = int(
                self.env["ir.config_parameter"].get_param(
                    "argocd_sale.grace_period_tag_id", "0"
                )
            )
            if not grace_period_tag_id:
                return False
            tag = self.env["argocd.application.tag"].browse(grace_period_tag_id)
            if not tag:
                return False
            self.mapped("application_ids").write({"tag_ids": [Command.link(tag.id)]})
        elif grace_period_action == "destroy_app":
            self.mapped("application_ids").destroy()
        return True

    def cron_update_payment_provider_subscriptions(self):
        # Process last payments first because in here paid_for_date can be updated
        res = super().cron_update_payment_provider_subscriptions()
        period = self._get_grace_period()
        if not period:
            return res
        today = fields.Date.today()
        late_date = today - timedelta(days=period)
        late_subs = self.search(
            [
                ("paid_for_date", "<", late_date),
                ("in_progress", "=", True),
                "|",
                ("free_trial_end_date", "<", today),
                ("free_trial_end_date", "=", False),
            ]
        )
        if late_subs.filtered(
            lambda s: not s.free_trial_end_date
            or s.free_trial_end_date + timedelta(days=period) < today
        ):
            late_subs.close_subscription()
            late_subs._do_grace_period_action()
        return res

    def _get_free_period(self):
        self.ensure_one()
        if (
            self.partner_id.is_reseller
            or self.partner_id.parent_id
            and self.partner_id.parent_id.is_reseller
        ):
            return None
        existing_subs = self.partner_id.subscription_ids
        if self.partner_id.parent_id:
            existing_subs += self.partner_id.parent_id.subscription_ids
        existing_subs -= self
        if existing_subs:
            return None
        sudo_config = self.env["ir.config_parameter"].sudo()
        free_period = int(
            sudo_config.get_param("argocd_sale.subscription_free_period", "0")
        )
        if not free_period:
            return None
        free_period_type = sudo_config.get_param(
            "argocd_sale.subscription_free_period_type"
        )
        valid_period_types = (
            "years",
            "months",
            "days",
            "leapdays",
            "weeks",
            "hours",
            "minutes",
            "seconds",
            "microseconds",
        )
        if free_period_type not in valid_period_types:
            return None
        return relativedelta(**{free_period_type: free_period})
