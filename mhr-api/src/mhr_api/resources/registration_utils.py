# Copyright © 2019 Province of British Columbia
#
# Licensed under the Apache License, Version 2.0 (the 'License');
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an 'AS IS' BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Helper methods for financing statements and updates to financing statements."""
import copy
import json
from http import HTTPStatus

from flask import current_app, g, request

import mhr_api.models.registration_change_utils as change_utils
from mhr_api.exceptions import DatabaseException
from mhr_api.models import (
    EventTracking,
    MhrDraft,
    MhrRegistration,
    MhrRegistrationReport,
    SearchResult,
    batch_utils,
    registration_json_utils,
)
from mhr_api.models import utils as model_utils
from mhr_api.models.registration_utils import (
    get_document_description,
    get_registration_description,
    save_admin,
    save_cancel_note,
)
from mhr_api.models.type_tables import MhrDocumentTypes, MhrRegistrationStatusTypes, MhrRegistrationTypes
from mhr_api.reports import get_pdf
from mhr_api.resources import cc_payment_utils
from mhr_api.resources import utils as resource_utils
from mhr_api.services.authz import STAFF_ROLE, is_reg_staff_account
from mhr_api.services.document_storage.storage_service import DocumentTypes, GoogleStorageService
from mhr_api.services.notify import Notify
from mhr_api.services.payment.exceptions import SBCPaymentException
from mhr_api.services.payment.payment import Payment
from mhr_api.services.queue_service import GoogleQueueService
from mhr_api.services.utils.exceptions import ReportDataException, ReportException, StorageException
from mhr_api.utils.auth import jwt
from mhr_api.utils.logging import logger

VAL_ERROR = "Registration request data validation errors."  # Default validation error prefix
SAVE_ERROR_MESSAGE = "Account {0} create {1} statement db save failed: {2}"
PAY_REFUND_MESSAGE = "Account {0} create {1} statement refunding payment for invoice {2}."
PAY_REFUND_ERROR = "Account {0} create {1} statement payment refund failed for invoice {2}: {3}."
DUPLICATE_REGISTRATION_ERROR = "Registration {0} is already available to the account."
# Payment detail/transaction description by registration.
REG_CLASS_TO_STATEMENT_TYPE = {
    "AMENDMENT": "Register an Amendment Statement",
    "COURTORDER": "Register an Amendment Statement",
    "CHANGE": "Register a Change Statement",
    "RENEWAL": "Register a Renewal Statement",
    "DISCHARGE": "Register a Discharge Statement",
}
TO_DRS_DOC_TYPE = {
    "TRANS_SEVER_GRANT": "TRAN",
    "TRANS_RECEIVERSHIP": "TRAN",
    "TRANS_LAND_TITLE": "TRAN",
    "TRANS_FAMILY_ACT": "TRAN",
    "TRANS_QUIT_CLAIM": "TRAN",
    "TRANS_INFORMAL_SALE": "TRAN",
    "TRANS_WRIT_SEIZURE": "TRAN",
    "REGC_STAFF": "REGC",
    "REGC_CLIENT": "REGC",
}
CALLBACK_MESSAGES = {
    resource_utils.CallbackExceptionCodes.UNKNOWN_ID.value: "01: no registration data found for id={key_id}.",
    resource_utils.CallbackExceptionCodes.MAX_RETRIES.value: "02: maximum retries reached for id={key_id}.",
    resource_utils.CallbackExceptionCodes.INVALID_ID.value: "03: no registration found for id={key_id}.",
    resource_utils.CallbackExceptionCodes.DEFAULT.value: "04: default error for id={key_id}.",
    resource_utils.CallbackExceptionCodes.REPORT_DATA_ERR.value: "05: report data error for id={key_id}.",
    resource_utils.CallbackExceptionCodes.REPORT_ERR.value: "06: generate report failed for id={key_id}.",
    resource_utils.CallbackExceptionCodes.FILE_TRANSFER_ERR.value: "09: SFTP failed for id={key_id}.",
    resource_utils.CallbackExceptionCodes.SETUP_ERR.value: "10: setup failed for id={key_id}.",
}
PAY_DETAILS_LABEL = "MH Registration Type:"
PAY_DETAILS_LABEL_TRANS_ID = "Registration Number {trans_id} Type:"
EMAIL_DOWNLOAD = "\n\nTo access the file,\n\n[[{0}]]({1})"
EMAIL_DOWNLOAD_LOCATION = "\n\n[[{0}]]({1})"
EVENT_KEY_BATCH_MAN_REG: int = 99000000
EVENT_KEY_BATCH_LOCATION: int = 99000001
EVENT_KEY_BATCH_REG: int = 99000002
REQUEST_PARAM_CC_PAY: str = "ccPayment"


def get_pay_details(reg_type: str, trans_id: str = None) -> dict:
    """Build pay api transaction description details."""
    value: str = get_registration_description(reg_type).lower().title()
    label = PAY_DETAILS_LABEL
    if trans_id:
        label = PAY_DETAILS_LABEL_TRANS_ID.format(trans_id=trans_id)
    details = {"label": label, "value": value}
    return details


def get_pay_details_doc(doc_type: str, trans_id: str = None) -> dict:
    """Build pay api transaction description details using the registration document type."""
    value: str = get_document_description(doc_type).lower().title()
    label = PAY_DETAILS_LABEL
    if trans_id:
        label = PAY_DETAILS_LABEL_TRANS_ID.format(trans_id=trans_id)
    details = {"label": label, "value": value}
    return details


def set_cc_payment(req: request, details: dict) -> dict:
    """Set optional cc payment indicator in details from the known request parameter."""
    cc_payment: bool = req.args.get(REQUEST_PARAM_CC_PAY) if request.args.get(REQUEST_PARAM_CC_PAY) else False
    details["ccPayment"] = cc_payment
    return details


def pay(req: request, request_json: dict, account_id: str, trans_type: str, trans_id: str = None):
    """Set up and submit a pay-api request."""
    payment: Payment = None
    pay_ref = None
    client_ref: str = request_json.get("clientReferenceId", "")
    details: dict = get_pay_details(request_json.get("registrationType"))
    if request_json.get("transferDocumentType"):
        details = get_pay_details_doc(request_json.get("transferDocumentType"))
    elif request_json.get("documentType"):
        details = get_pay_details_doc(request_json.get("documentType"))
    elif request_json.get("registrationType") == MhrRegistrationTypes.PERMIT and request_json.get("amendment"):
        details = get_pay_details_doc(MhrDocumentTypes.AMEND_PERMIT)
    details = set_cc_payment(req, details)
    if not is_reg_staff_account(account_id):
        payment = Payment(jwt=jwt.get_token_auth_header(), account_id=account_id, details=details)
        pay_ref = payment.create_payment(trans_type, 1, trans_id, client_ref, False)
    else:
        payment_info = build_staff_payment(req, trans_type, 1, trans_id)
        payment = Payment(jwt=jwt.get_token_auth_header(), account_id=None, details=details)
        pay_ref = payment.create_payment_staff(payment_info, client_ref)
    return payment, pay_ref


def pay_staff(req: request, request_json: dict, trans_type: str, trans_id: str = None):
    """Set up and submit a staff pay-api request for note and admin registrations."""
    payment: Payment = None
    pay_ref = None
    client_ref: str = request_json.get("clientReferenceId", "")
    doc_type: str = request_json.get("documentType")
    if not doc_type:
        doc_type = request_json["note"].get("documentType")
    details: dict = get_pay_details_doc(doc_type)
    details = set_cc_payment(req, details)
    payment_info = build_staff_payment(req, trans_type, 1, trans_id)
    payment = Payment(jwt=jwt.get_token_auth_header(), account_id=None, details=details)
    pay_ref = payment.create_payment_staff(payment_info, client_ref)
    return payment, pay_ref


def pay_and_save_registration(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    req: request, request_json: dict, account_id: str, user_group: str, trans_type: str
):
    """Set up the registration statement, pay, and save the data."""
    # Charge a fee.
    token: dict = g.jwt_oidc_token_info
    request_json["affirmByName"] = get_affirmby(token)
    request_json["registrationType"] = MhrRegistrationTypes.MHREG
    # Create draft with MHR number here to include in the pay api request.
    draft: MhrDraft = MhrDraft.create_from_mhreg_json(request_json, account_id, token.get("username"))
    draft.save()
    request_json["mhrNumber"] = draft.mhr_number
    logger.info(f"New MH registration MHR#={draft.mhr_number}")
    payment, pay_ref = pay(req, request_json, account_id, trans_type, draft.mhr_number)
    if pay_ref.get("ccPayment"):
        logger.info("Payment response CC method.")
        request_json = setup_cc_draft(request_json, pay_ref, account_id, token.get("username", None), user_group)
        return cc_payment_utils.save_new_cc_draft(request_json, draft)
    invoice_id = pay_ref["invoiceId"]
    # Try to save the registration: failure throws an exception.
    try:
        registration: MhrRegistration = MhrRegistration.create_new_from_json(
            request_json, draft, account_id, token.get("username", None), user_group
        )
        registration.pay_invoice_id = int(invoice_id)
        registration.pay_path = pay_ref["receipt"]
        registration.save()
        return registration
    except Exception as db_exception:  # noqa: B902; handle all db related errors.
        logger.error(SAVE_ERROR_MESSAGE.format(account_id, "registration", str(db_exception)))
        if account_id and invoice_id is not None:
            logger.info(PAY_REFUND_MESSAGE.format(account_id, "registration", invoice_id))
            try:
                payment.cancel_payment(invoice_id)
            except SBCPaymentException as cancel_exception:
                logger.error(PAY_REFUND_ERROR.format(account_id, "registration", invoice_id, str(cancel_exception)))
        raise DatabaseException(db_exception) from db_exception


def pay_and_save_transfer(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    req: request, current_reg: MhrRegistration, request_json, account_id: str, user_group: str, trans_type: str
):
    """Set up the registration statement, pay, and save the data."""
    # Charge a fee.
    token: dict = g.jwt_oidc_token_info
    logger.debug(f"user_group={user_group}")
    request_json["affirmByName"] = get_affirmby(token)
    if not request_json.get("registrationType"):
        request_json["registrationType"] = MhrRegistrationTypes.TRANS
    payment, pay_ref = pay(req, request_json, account_id, trans_type, current_reg.mhr_number)
    if pay_ref.get("ccPayment"):
        logger.info("Payment response CC method.")
        request_json = setup_cc_draft(request_json, pay_ref, account_id, token.get("username", None), user_group)
        return cc_payment_utils.save_change_cc_draft(current_reg, request_json)
    invoice_id = pay_ref["invoiceId"]
    # Try to save the registration: failure throws an exception.
    try:
        registration: MhrRegistration = MhrRegistration.create_transfer_from_json(
            current_reg, request_json, account_id, token.get("username", None), user_group
        )
        registration.pay_invoice_id = int(invoice_id)
        registration.pay_path = pay_ref["receipt"]
        registration.save()
        if current_reg.id and current_reg.id > 0 and current_reg.owner_groups:
            current_reg.save_transfer(request_json, registration.id)
        elif MhrRegistration.is_exre_transfer(current_reg, request_json):
            current_reg.save_transfer(request_json, registration.id)
        return registration
    except Exception as db_exception:  # noqa: B902; handle all db related errors.
        logger.error(SAVE_ERROR_MESSAGE.format(account_id, "registration", str(db_exception)))
        if account_id and invoice_id is not None:
            logger.info(PAY_REFUND_MESSAGE.format(account_id, "registration", invoice_id))
            try:
                payment.cancel_payment(invoice_id)
            except SBCPaymentException as cancel_exception:
                logger.error(PAY_REFUND_ERROR.format(account_id, "registration", invoice_id, str(cancel_exception)))
        raise DatabaseException(db_exception) from db_exception


def pay_and_save_exemption(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    req: request, current_reg: MhrRegistration, request_json, account_id: str, user_group: str, trans_type: str
):
    """Set up the registration statement, pay, and save the data."""
    # Charge a fee.
    token: dict = g.jwt_oidc_token_info
    logger.debug(f"user_group={user_group}")
    request_json["affirmByName"] = get_affirmby(token)
    if request_json.get("nonResidential"):
        request_json["registrationType"] = MhrRegistrationTypes.EXEMPTION_NON_RES
    else:
        request_json["registrationType"] = MhrRegistrationTypes.EXEMPTION_RES
    payment, pay_ref = pay(req, request_json, account_id, trans_type, current_reg.mhr_number)
    if pay_ref.get("ccPayment"):
        logger.info("Payment response CC method.")
        request_json = setup_cc_draft(request_json, pay_ref, account_id, token.get("username", None), user_group)
        return cc_payment_utils.save_change_cc_draft(current_reg, request_json)
    invoice_id = pay_ref["invoiceId"]
    # Try to save the registration: failure throws an exception.
    try:
        registration: MhrRegistration = MhrRegistration.create_exemption_from_json(
            current_reg, request_json, account_id, token.get("username", None), user_group
        )
        registration.pay_invoice_id = int(invoice_id)
        registration.pay_path = pay_ref["receipt"]
        registration.save()
        current_reg.save_exemption(registration.id)
        return registration
    except Exception as db_exception:  # noqa: B902; handle all db related errors.
        logger.error(SAVE_ERROR_MESSAGE.format(account_id, "registration", str(db_exception)))
        if account_id and invoice_id is not None:
            logger.info(PAY_REFUND_MESSAGE.format(account_id, "registration", invoice_id))
            try:
                payment.cancel_payment(invoice_id)
            except SBCPaymentException as cancel_exception:
                logger.error(PAY_REFUND_ERROR.format(account_id, "registration", invoice_id, str(cancel_exception)))
        raise DatabaseException(db_exception) from db_exception


def setup_cc_draft(json_data: dict, pay_ref: dict, account_id: str, username: str, usergroup: str) -> dict:
    """Set common draft properties from request information."""
    json_data["payment"] = pay_ref
    json_data["accountId"] = account_id
    json_data["username"] = username if username else ""
    json_data["usergroup"] = usergroup if usergroup else ""
    return json_data


def pay_and_save_permit(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    req: request, current_reg: MhrRegistration, request_json, account_id: str, user_group: str, trans_type: str
):
    """Set up the registration statement, pay, and save the data."""
    # Charge a fee.
    token: dict = g.jwt_oidc_token_info
    logger.debug(f"user_group={user_group}")
    request_json["affirmByName"] = get_affirmby(token)
    if not request_json.get("registrationType"):
        request_json["registrationType"] = MhrRegistrationTypes.PERMIT
    payment, pay_ref = pay(req, request_json, account_id, trans_type, current_reg.mhr_number)
    if pay_ref.get("ccPayment"):
        logger.info("Payment response CC method.")
        request_json = setup_cc_draft(request_json, pay_ref, account_id, token.get("username", None), user_group)
        return cc_payment_utils.save_change_cc_draft(current_reg, request_json)

    invoice_id = pay_ref["invoiceId"]
    # Try to save the registration: failure throws an exception.
    try:
        registration: MhrRegistration = MhrRegistration.create_permit_from_json(
            current_reg, request_json, account_id, token.get("username", None), user_group
        )
        registration.pay_invoice_id = int(invoice_id)
        registration.pay_path = pay_ref["receipt"]
        registration.save()
        if current_reg.id and current_reg.id > 0 and current_reg.locations:
            change_utils.save_permit(current_reg, request_json, registration.id)
        return registration
    except Exception as db_exception:  # noqa: B902; handle all db related errors.
        logger.error(SAVE_ERROR_MESSAGE.format(account_id, "registration", str(db_exception)))
        if account_id and invoice_id is not None:
            logger.info(PAY_REFUND_MESSAGE.format(account_id, "registration", invoice_id))
            try:
                payment.cancel_payment(invoice_id)
            except SBCPaymentException as cancel_exception:
                logger.error(PAY_REFUND_ERROR.format(account_id, "registration", invoice_id, str(cancel_exception)))
        raise DatabaseException(db_exception) from db_exception


def pay_and_save_note(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    req: request, current_reg: MhrRegistration, request_json, account_id: str, user_group: str, trans_type: str
):
    """Set up the registration statement, pay, and save the data."""
    # Charge a fee.
    token: dict = g.jwt_oidc_token_info
    logger.debug(f"user_group={user_group}")
    request_json["affirmByName"] = get_affirmby(token)
    if not request_json.get("registrationType"):
        request_json["registrationType"] = MhrRegistrationTypes.REG_NOTE
    payment, pay_ref = pay_staff(req, request_json, trans_type, current_reg.mhr_number)
    invoice_id = pay_ref["invoiceId"]
    # Try to save the registration: failure throws an exception.
    try:
        registration: MhrRegistration = MhrRegistration.create_note_from_json(
            current_reg, request_json, account_id, token.get("username", None), user_group
        )
        registration.pay_invoice_id = int(invoice_id)
        registration.pay_path = pay_ref["receipt"]
        registration.save()
        if request_json.get("cancelDocumentId") and request_json["note"].get("documentType") == MhrDocumentTypes.NCAN:
            save_cancel_note(current_reg, request_json, registration.id)
        return registration
    except Exception as db_exception:  # noqa: B902; handle all db related errors.
        logger.error(SAVE_ERROR_MESSAGE.format(account_id, "registration", str(db_exception)))
        if account_id and invoice_id is not None:
            logger.info(PAY_REFUND_MESSAGE.format(account_id, "registration", invoice_id))
            try:
                payment.cancel_payment(invoice_id)
            except SBCPaymentException as cancel_exception:
                logger.error(PAY_REFUND_ERROR.format(account_id, "registration", invoice_id, str(cancel_exception)))
        raise DatabaseException(db_exception) from db_exception


def pay_and_save_admin(  # pylint: disable=too-many-arguments,too-many-positional-arguments
    req: request, current_reg: MhrRegistration, request_json, account_id: str, user_group: str, trans_type: str
):
    """Set up the registration statement, pay, and save the data."""
    # Charge a fee.
    token: dict = g.jwt_oidc_token_info
    logger.debug(f"user_group={user_group}")
    request_json["affirmByName"] = get_affirmby(token)
    if not request_json.get("registrationType"):
        request_json["registrationType"] = MhrRegistrationTypes.REG_STAFF_ADMIN
    payment = None
    pay_ref = None
    if is_reg_staff_account(account_id):
        payment, pay_ref = pay_staff(req, request_json, trans_type, current_reg.mhr_number)
    else:
        payment, pay_ref = pay(req, request_json, account_id, trans_type, current_reg.mhr_number)
    invoice_id = pay_ref["invoiceId"]
    # Try to save the registration: failure throws an exception.
    try:
        registration: MhrRegistration = MhrRegistration.create_admin_from_json(
            current_reg, request_json, account_id, token.get("username", None), user_group
        )
        registration.pay_invoice_id = int(invoice_id)
        registration.pay_path = pay_ref["receipt"]
        registration.save()
        if request_json.get("cancelDocumentId") and request_json["note"].get("documentType") == MhrDocumentTypes.NCAN:
            save_cancel_note(current_reg, request_json, registration.id)
        elif request_json.get("updateDocumentId") and request_json.get("documentType") in (
            MhrDocumentTypes.NCAN,
            MhrDocumentTypes.NRED,
            MhrDocumentTypes.EXRE,
        ):
            save_cancel_note(current_reg, request_json, registration.id)
        elif request_json.get("documentType") in (
            MhrDocumentTypes.EXRE,
            MhrDocumentTypes.REGC_CLIENT,
            MhrDocumentTypes.REGC_STAFF,
            MhrDocumentTypes.STAT,
            MhrDocumentTypes.PUBA,
        ):
            save_admin(current_reg, request_json, registration.id)
        elif request_json.get("documentType") == MhrDocumentTypes.CANCEL_PERMIT and current_reg:
            change_utils.save_permit(current_reg, request_json, registration.id)
        return registration
    except Exception as db_exception:  # noqa: B902; handle all db related errors.
        logger.error(SAVE_ERROR_MESSAGE.format(account_id, "registration", str(db_exception)))
        if account_id and invoice_id is not None:
            logger.info(PAY_REFUND_MESSAGE.format(account_id, "registration", invoice_id))
            try:
                payment.cancel_payment(invoice_id)
            except SBCPaymentException as cancel_exception:
                logger.error(PAY_REFUND_ERROR.format(account_id, "registration", invoice_id, str(cancel_exception)))
        raise DatabaseException(db_exception) from db_exception


def build_staff_payment(req: request, trans_type: str, quantity: int = 1, transaction_id: str = None):
    """Extract staff payment information from request parameters."""
    payment_info = {
        "transactionType": trans_type,
        "quantity": quantity,
        "waiveFees": True,
        "accountId": resource_utils.get_staff_account_id(req),
    }
    if transaction_id:
        payment_info["transactionId"] = transaction_id
    account_id = resource_utils.get_account_id(req)
    logger.info(f"Checking account_id={account_id}")
    if account_id and account_id != STAFF_ROLE:
        payment_info["waiveFees"] = False
        payment_info["accountId"] = account_id
    certified = req.args.get(resource_utils.CERTIFIED_PARAM)
    routing_slip = req.args.get(resource_utils.ROUTING_SLIP_PARAM)
    bcol_number = req.args.get(resource_utils.BCOL_NUMBER_PARAM)
    dat_number = req.args.get(resource_utils.DAT_NUMBER_PARAM)
    priority = req.args.get(resource_utils.PRIORITY_PARAM)
    if certified is not None and isinstance(certified, bool) and certified:
        payment_info[resource_utils.CERTIFIED_PARAM] = True
    elif certified is not None and isinstance(certified, str) and certified.lower() in ["true", "1", "y", "yes"]:
        payment_info[resource_utils.CERTIFIED_PARAM] = True
    if routing_slip is not None:
        payment_info[resource_utils.ROUTING_SLIP_PARAM] = str(routing_slip)
    if bcol_number is not None:
        payment_info[resource_utils.BCOL_NUMBER_PARAM] = str(bcol_number)
    if dat_number is not None:
        payment_info[resource_utils.DAT_NUMBER_PARAM] = str(dat_number)
    if priority is not None and isinstance(priority, bool) and priority:
        payment_info[resource_utils.PRIORITY_PARAM] = True
    elif priority is not None and isinstance(priority, str) and priority.lower() in ["true", "1", "y", "yes"]:
        payment_info[resource_utils.PRIORITY_PARAM] = True

    if resource_utils.ROUTING_SLIP_PARAM in payment_info or resource_utils.BCOL_NUMBER_PARAM in payment_info:
        payment_info["waiveFees"] = False
    logger.debug(payment_info)
    return payment_info


def add_payment_json(registration, reg_json):
    """Add registration payment info json if payment exists."""
    if registration.pay_invoice_id and registration.pay_path:
        payment = {"invoiceId": str(registration.pay_invoice_id), "receipt": registration.pay_path}
        reg_json["payment"] = payment
    return reg_json


def enqueue_registration_report(
    registration: MhrRegistration, json_data: dict, report_type: str, current_json: dict = None
):
    """Add the registration report request to the registration queue. Staff conditionally queue  a DRS record."""
    try:
        if json_data and report_type:
            # Signal registration report request is pending: record exists but no doc_storage_url.
            reg_report: MhrRegistrationReport = MhrRegistrationReport(
                create_ts=registration.registration_ts,
                registration_id=registration.id,
                report_data=json_data,
                report_type=report_type,
            )
            reg_report.batch_report_data = get_batch_report_data(registration, json_data, current_json)
            if batch_utils.is_batch_doc_type(registration.documents[0].document_type):
                logger.debug("Setting mhr_registration_reports.batch_registration_data")
                reg_report.batch_registration_data = batch_utils.get_batch_registration_json(
                    registration, json_data, current_json
                )
            reg_report.save()
        payload = {"registrationId": registration.id}
        apikey = current_app.config.get("SUBSCRIPTION_API_KEY")
        if apikey:
            payload["apikey"] = apikey
        GoogleQueueService().publish_registration_report(payload)
        logger.info(f"Enqueue registration report successful for id={registration.id}.")
        if (
            json_data.get("usergroup") == STAFF_ROLE or registration.account_id == STAFF_ROLE
        ) and current_app.config.get("DOC_CREATE_REC_TOPIC"):
            enqueue_doc_record(registration, json_data)
        elif json_data.get("usergroup") == STAFF_ROLE or registration.account_id == STAFF_ROLE:
            logger.info("Staff registration but skipping queuing of DRS record: DOC_CREATE_REC_TOPIC not configured.")
    except DatabaseException as db_err:
        # Just log, do not return an error response.
        msg = f"Enqueue MHR registration report type {report_type} db error for id={registration.id}: " + str(db_err)
        logger.error(msg)
    except Exception as err:  # noqa: B902; do not alter app processing
        msg = f"Enqueue MHR registration report type {report_type} failed for id={registration.id}: " + str(err)
        logger.error(msg)
        EventTracking.create(
            registration.id,
            EventTracking.EventTrackingTypes.MHR_REGISTRATION_REPORT,
            int(HTTPStatus.INTERNAL_SERVER_ERROR),
            msg,
        )


def enqueue_doc_record(registration: MhrRegistration, json_data: dict):
    """Add a new DRS record request to the document record queue."""
    try:
        doc_type: str = registration.documents[0].document_type
        if TO_DRS_DOC_TYPE.get(doc_type):
            doc_type = TO_DRS_DOC_TYPE.get(doc_type)
        payload = {
            "accountId": registration.account_id,
            "author": json_data.get("username", ""),
            "documentClass": "MHR",
            "documentType": doc_type,
            "consumerDocumentId": registration.documents[0].document_id,
            "consumerIdentifier": registration.mhr_number,
            "consumerFilingDate": json_data.get("createDateTime", ""),
        }
        logger.info(f"Staff reg id={registration.id} queuing DRS record payload={payload}")
        GoogleQueueService().publish_create_doc_record(payload)
    except Exception as err:  # noqa: B902; do not alter app processing
        msg = f"Enqueue DRS record failed for id={registration.id}: " + str(err)
        logger.error(msg)


def get_batch_report_data(registration: MhrRegistration, json_data: dict, current_json: dict):
    """Conditionally setup batch report data initially for NOC location registrations."""
    batch_data = None
    try:
        if (
            registration.registration_type == MhrRegistrationTypes.PERMIT
            or (registration.registration_type == MhrRegistrationTypes.AMENDMENT and json_data.get("newLocation"))
            or (registration.registration_type == MhrRegistrationTypes.REG_STAFF_ADMIN and json_data.get("location"))
        ):
            logger.debug(f"batch report setup PPR lien check for reg_type={registration.registration_type}")
            if json_data.get("documentType"):
                logger.debug("doc type=" + json_data.get("documentType"))
            logger.info(f"Searching PPR for MHR num {registration.mhr_number}.")
            ppr_registrations = SearchResult.search_ppr_by_mhr_number(registration.mhr_number)
            if not ppr_registrations:
                logger.debug("No PPR lien found in batch NOC location report setup.")
                return batch_data
            batch_data = copy.deepcopy(json_data)
            batch_data["nocLocation"] = True
            if json_data.get("addOwnerGroups"):
                batch_data["ownerGroups"] = json_data.get("addOwnerGroups")
                del batch_data["addOwnerGroups"]
            if json_data.get("newLocation"):
                batch_data["location"] = json_data.get("newLocation")
                del batch_data["newLocation"]
            if not batch_data.get("ownerGroups") and current_json and current_json.get("ownerGroups"):
                batch_data["ownerGroups"] = current_json.get("ownerGroups")
            batch_ppr = []
            for reg in ppr_registrations:
                report_ppr = {
                    "baseRegistrationNumber": reg["financingStatement"].get("baseRegistrationNumber"),
                    "registrationDescription": reg["financingStatement"].get("registrationDescription"),
                    "securedParties": reg["financingStatement"].get("securedParties"),
                    "debtors": reg["financingStatement"].get("debtors"),
                }
                batch_ppr.append(report_ppr)
            batch_data["pprRegistrations"] = batch_ppr
            logger.debug("batch NOC location report setup complete.")
    except Exception as err:  # noqa: B902; do not alter app processing
        msg = f"Enqueue MHR registration report batch data setup failed for id={registration.id}: " + str(err)
        logger.error(msg)
        EventTracking.create(
            registration.id, EventTracking.EventTrackingTypes.EMAIL_REPORT, int(HTTPStatus.INTERNAL_SERVER_ERROR), msg
        )
    return batch_data


def get_registration_report(  # pylint: disable=too-many-return-statements,too-many-locals
    registration: MhrRegistration,
    report_data: dict,
    report_type: str,
    token=None,
    response_status: int = HTTPStatus.OK,
):
    """Get existing or generate a registration PDF of the provided report type using the provided data."""
    registration_id = registration.id
    try:
        report_info: MhrRegistrationReport = MhrRegistrationReport.find_by_registration_id(registration_id)
        if report_info and report_info.doc_storage_url:
            doc_name = report_info.doc_storage_url
            logger.info(f"{registration_id} fetching doc storage report {doc_name}.")
            raw_data = GoogleStorageService.get_document(doc_name, DocumentTypes.REGISTRATION)
            return raw_data, response_status, {"Content-Type": "application/pdf"}

        if report_info and not report_info.doc_storage_url:
            # Check if report api error: more than 15 minutes has elapsed since the request was queued and no report.
            if not model_utils.report_retry_elapsed(report_info.create_ts):
                logger.info(f"Pending report generation for reg id={registration_id}.")
                return report_data, HTTPStatus.ACCEPTED, {"Content-Type": "application/json"}
            rep_data = report_info.report_data if report_info.report_data else report_data
            logger.info(f"Retrying report generation for reg id={registration_id}.")
            raw_data, status_code, headers = get_pdf(rep_data, registration.account_id, report_type, token)
            logger.debug(f"Retry report api call status={status_code}.")
            if status_code not in (HTTPStatus.OK, HTTPStatus.CREATED):
                logger.error(f"{registration_id} retry report api call failed: " + raw_data.get_data(as_text=True))
            else:
                doc_name = model_utils.get_doc_storage_name(registration)
                logger.info(f"Saving registration report output to doc storage: name={doc_name}.")
                response = GoogleStorageService.save_document(doc_name, raw_data, DocumentTypes.REGISTRATION)
                logger.info(f"Save document storage response: {response}")
                report_info.create_ts = model_utils.now_ts()
                report_info.doc_storage_url = doc_name
                report_info.save()
            return raw_data, response_status, headers

        # Edge case: too large to generate in real time.
        results_length = len(json.dumps(report_data))
        if results_length > current_app.config.get("MAX_SIZE_SEARCH_RT"):
            logger.info(f"Registration {registration_id} queued, size too large: {results_length}.")
            enqueue_registration_report(registration, report_data, report_type)
            return report_data, HTTPStatus.ACCEPTED, {"Content-Type": "application/json"}
        # No report in doc storage: generate, store.
        return new_registration_report(registration, report_data, report_type, token, response_status)
    except ReportException as report_err:
        return resource_utils.service_exception_response("MHR reg report API error: " + str(report_err))
    except ReportDataException as report_data_err:
        return resource_utils.service_exception_response("MHR reg report API data error: " + str(report_data_err))
    except StorageException as storage_err:
        return resource_utils.service_exception_response("MHR reg report storage API error: " + str(storage_err))
    except DatabaseException as db_exception:
        return resource_utils.db_exception_response(db_exception, None, "Generate MHR registration report state.")


def new_registration_report(
    registration: MhrRegistration,  # pylint: disable=too-many-return-statements,too-many-locals
    report_data: dict,
    report_type: str,
    token=None,
    response_status: int = HTTPStatus.OK,
):
    """Generate a registration PDF of the provided report type using the provided data."""
    current_reg: MhrRegistration = MhrRegistration.find_all_by_mhr_number(registration.mhr_number, STAFF_ROLE, True)
    current_reg.current_view = True
    current_json = current_reg.new_registration_json
    report_data["status"] = current_json.get("status")
    reg_type = registration.registration_type
    if reg_type in (MhrRegistrationTypes.EXEMPTION_NON_RES, MhrRegistrationTypes.EXEMPTION_RES):
        report_data["status"] = MhrRegistrationStatusTypes.EXEMPT
        report_data = registration_json_utils.set_reg_location_json(current_reg, report_data, registration.id)
        report_data = registration_json_utils.set_reg_groups_json(current_reg, report_data, registration.id, False)
    elif reg_type in (
        MhrRegistrationTypes.PERMIT,
        MhrRegistrationTypes.PERMIT_EXTENSION,
        MhrRegistrationTypes.AMENDMENT,
    ):
        report_data = registration_json_utils.set_reg_location_json(current_reg, report_data, registration.id)
        report_data = registration_json_utils.set_reg_groups_json(current_reg, report_data, registration.id, False)
        report_data = registration_json_utils.set_reg_description_json(current_reg, report_data, registration.id)

    raw_data, status_code, headers = get_pdf(report_data, registration.account_id, report_type, token)
    logger.debug(f"Report api call status={status_code}.")
    if status_code not in (HTTPStatus.OK, HTTPStatus.CREATED):
        logger.error(f"{registration.id} report api call failed: " + raw_data.get_data(as_text=True))
    else:
        doc_name = model_utils.get_doc_storage_name(registration)
        logger.info(f"Saving registration report output to doc storage: name={doc_name}.")
        response = GoogleStorageService.save_document(doc_name, raw_data, DocumentTypes.REGISTRATION)
        logger.info(f"Save document storage response: {response}")
        reg_report: MhrRegistrationReport = MhrRegistrationReport(
            create_ts=model_utils.now_ts(),
            registration_id=registration.id,
            report_data=report_data,
            report_type=report_type,
            doc_storage_url=doc_name,
        )
        reg_report.save()
    return raw_data, response_status, headers


def get_affirmby(token) -> str:
    """Get the registration affirm by name (user name) from the user token."""
    firstname = token.get("given_name", None)
    if not firstname:
        firstname = token.get("firstname", "")
    lastname = token.get("family_name", None)
    if not lastname:
        lastname = token.get("lastname", "")
    return firstname + " " + lastname


def notify_man_reg_config() -> dict:
    """Build the notify configuration for a staff manufacturer registrations batch job."""
    env_var: str = current_app.config.get("NOTIFY_MAN_REG_CONFIG", None)
    if not env_var:
        return None
    return json.loads(env_var)


def email_batch_man_report_data(config: dict, report_url: str) -> dict:
    """Build email notification to reg staff with report download link."""
    body: str = config.get("body") if report_url else config.get("bodyNone")
    now_local = model_utils.today_local()
    rep_date: str = now_local.strftime("%B %-d, %Y")
    body = body.format(rep_date=rep_date)
    if report_url:
        body += EMAIL_DOWNLOAD.format(config.get("filename"), report_url)
    email_data = {"recipients": config.get("recipients"), "content": {"subject": config.get("subject"), "body": body}}
    return email_data


def email_batch_man_report_staff(report_url: str):
    """Send email notification to reg staff with batch manufacturer reg report download link."""
    config = notify_man_reg_config()
    email_data = email_batch_man_report_data(config, report_url)
    logger.debug(email_data)
    # Send email
    notify_url = config.get("url")
    notify = Notify(**{"url": notify_url})
    status_code = notify.send_email(email_data)
    message: str = f"Email sent to {notify_url}, return code: {status_code}"
    logger.info(message)
    if status_code != HTTPStatus.OK:
        EventTracking.create(
            EVENT_KEY_BATCH_MAN_REG, EventTracking.EventTrackingTypes.MHR_REGISTRATION_REPORT, status_code, message
        )


def notify_location_config() -> dict:
    """Build the notify configuration for a staff noc location batch job."""
    env_var: str = current_app.config.get("NOTIFY_LOCATION_CONFIG", None)
    if not env_var:
        return None
    return json.loads(env_var)


def email_batch_location_data(config: dict, report_url: str) -> dict:
    """Build email notification for location change to reg staff with report download link."""
    body: str = config.get("body") if report_url else config.get("bodyNone")
    now_local = model_utils.today_local()
    rep_date: str = now_local.strftime("%B %-d, %Y")
    rep_filename = config.get("filename")
    rep_filename = rep_filename.format(rep_date=rep_date)
    subject = config.get("subject") if report_url else config.get("subjectNone")
    subject = subject.format(rep_date=rep_date)
    if report_url:
        body += EMAIL_DOWNLOAD_LOCATION.format(rep_filename, report_url)
    else:
        body = body.format(rep_date=rep_date)
    email_data = {"recipients": config.get("recipients"), "content": {"subject": subject, "body": body}}
    return email_data


def email_batch_location_staff(report_url: str):
    """Send email notification to reg staff with batch noc location registrations report download link."""
    config = notify_location_config()
    email_data = email_batch_location_data(config, report_url)
    logger.debug(email_data)
    # Send email
    notify_url = config.get("url")
    notify = Notify(**{"url": notify_url})
    status_code = notify.send_email(email_data)
    message: str = f"Email sent to {notify_url}, return code: {status_code}"
    logger.info(message)
    if status_code != HTTPStatus.OK:
        EventTracking.create(
            EVENT_KEY_BATCH_LOCATION, EventTracking.EventTrackingTypes.MHR_REGISTRATION_REPORT, status_code, message
        )


def get_active_location(registration) -> dict:
    """Get the currently active location as JSON before updating."""
    reg_json = {}
    reg_json = registration_json_utils.set_location_json(registration, reg_json, True)
    return reg_json.get("location")


def get_active_owners(registration) -> dict:
    """Get the currently active owner groups as JSON before updating."""
    reg_json = {}
    reg_json = registration_json_utils.set_group_json(registration, reg_json, True)
    return reg_json.get("ownerGroups")
