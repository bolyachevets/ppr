# Copyright © 2019 Province of British Columbia
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""This module holds common statement registration data."""
# pylint: disable=too-many-statements, too-many-branches

from http import HTTPStatus

from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM

import mhr_api.models.registration_change_utils as change_utils
import mhr_api.models.registration_json_utils as reg_json_utils
import mhr_api.models.registration_utils as reg_utils
from mhr_api.exceptions import BusinessException, DatabaseException, ResourceErrorCodes
from mhr_api.models import utils as model_utils
from mhr_api.models.mhr_extra_registration import MhrExtraRegistration
from mhr_api.services.authz import STAFF_ROLE
from mhr_api.utils.logging import logger

from .db import db
from .mhr_description import MhrDescription
from .mhr_document import MhrDocument
from .mhr_draft import MhrDraft
from .mhr_location import MhrLocation
from .mhr_note import MhrNote
from .mhr_owner_group import MhrOwnerGroup
from .mhr_party import MhrParty
from .mhr_section import MhrSection
from .type_tables import (
    MhrDocumentTypes,
    MhrNoteStatusTypes,
    MhrOwnerStatusTypes,
    MhrPartyTypes,
    MhrRegistrationStatusTypes,
    MhrRegistrationTypes,
    MhrTenancyTypes,
)

REG_TO_DOC_TYPE = {
    "DECAL_REPLACE": "REG_102",
    "EXEMPTION_NON_RES": "EXNR",
    "EXEMPTION_RES": "EXRS",
    "MHREG": "REG_101",
    "PERMIT": "REG_103",
    "PERMIT_EXTENSION": "REG_103E",
    "TRAND": "DEAT",
    "TRANS": "TRAN",
    "TRANS_AFFIDAVIT": "AFFE",
    "TRANS_ADMIN": "LETA",
    "TRANS_WILL": "WILL",
    "REG_STAFF_ADMIN": "CAU",
}
REG_TYPE = MhrRegistrationTypes.MHREG
CONV_TYPE = MhrRegistrationTypes.MHREG_CONVERSION


class MhrRegistration(db.Model):  # pylint: disable=too-many-instance-attributes, too-many-public-methods
    """This class manages all MHR registration model information."""

    __tablename__ = "mhr_registrations"
    __allow_unmapped__ = True

    # Always use get_generated_values() to generate PK.
    id = db.mapped_column("id", db.Integer, primary_key=True)
    registration_ts = db.mapped_column("registration_ts", db.DateTime, nullable=False, index=True)
    mhr_number = db.mapped_column("mhr_number", db.String(7), nullable=False, index=True)
    account_id = db.mapped_column("account_id", db.String(20), nullable=True, index=True)
    client_reference_id = db.mapped_column("client_reference_id", db.String(50), nullable=True)
    pay_invoice_id = db.mapped_column("pay_invoice_id", db.Integer, nullable=True)
    pay_path = db.mapped_column("pay_path", db.String(256), nullable=True)
    user_id = db.mapped_column("user_id", db.String(1000), nullable=True)

    # parent keys
    draft_id = db.mapped_column("draft_id", db.Integer, db.ForeignKey("mhr_drafts.id"), nullable=False, index=True)
    registration_type = db.mapped_column(
        "registration_type",
        PG_ENUM(MhrRegistrationTypes, name="mhr_registration_type"),
        db.ForeignKey("mhr_registration_types.registration_type"),
        nullable=False,
    )
    status_type = db.mapped_column(
        "status_type",
        PG_ENUM(MhrRegistrationStatusTypes, name="mhr_registration_status_type"),
        db.ForeignKey("mhr_registration_status_types.status_type"),
        nullable=False,
    )

    # relationships
    reg_type = db.relationship(
        "MhrRegistrationType",
        foreign_keys=[registration_type],
        back_populates="registration",
        cascade="all, delete",
        uselist=False,
    )
    draft = db.relationship("MhrDraft", foreign_keys=[draft_id], uselist=False)
    parties = db.relationship("MhrParty", order_by="asc(MhrParty.id)", back_populates="registration")
    locations = db.relationship("MhrLocation", order_by="asc(MhrLocation.id)", back_populates="registration")
    documents = db.relationship("MhrDocument", order_by="asc(MhrDocument.id)", back_populates="registration")
    notes = db.relationship("MhrNote", order_by="asc(MhrNote.id)", back_populates="registration")
    owner_groups = db.relationship(
        "MhrOwnerGroup", order_by="asc(MhrOwnerGroup.group_id)", back_populates="registration"
    )
    descriptions = db.relationship("MhrDescription", order_by="asc(MhrDescription.id)", back_populates="registration")
    sections = db.relationship("MhrSection", order_by="asc(MhrSection.id)", back_populates="registration")

    draft_number: str = None
    doc_reg_number: str = None
    doc_pkey: int = None
    mail_version: bool = False
    reg_json: dict = None
    current_view: bool = False
    change_registrations = []
    staff: bool = False
    report_view: bool = False
    doc_id: str = None

    @property
    def json(self) -> dict:
        """Return the registration as a json object."""
        if self.id and self.id > 0:
            doc_json = self.documents[0].json
            reg_json = {
                "mhrNumber": self.mhr_number,
                "createDateTime": model_utils.format_ts(self.registration_ts),
                "registrationType": self.registration_type,
                "status": self.status_type,
                "declaredValue": doc_json.get("declaredValue", 0),
                "documentDescription": reg_utils.get_document_description(doc_json.get("documentType")),
                "documentId": doc_json.get("documentId"),
                "documentRegistrationNumber": doc_json.get("documentRegistrationNumber"),
                "ownLand": doc_json.get("ownLand"),
                "affirmByName": doc_json.get("affirmByName", ""),
                "attentionReference": doc_json.get("attentionReference", ""),
                "clientReferenceId": self.client_reference_id if self.client_reference_id else "",
            }
            # Set location for all registration types.
            reg_json = reg_json_utils.set_location_json(self, reg_json, False)
            # Set description for all registration types.
            reg_json = reg_json_utils.set_description_json(self, reg_json, False, doc_json.get("documentType"))
            # Set owner groups for all registration types.
            if self.registration_type in (MhrRegistrationTypes.MHREG, MhrRegistrationTypes.MHREG_CONVERSION):
                reg_json = reg_json_utils.set_group_json(self, reg_json, False, True)
            else:
                reg_json = reg_json_utils.set_transfer_group_json(self, reg_json, doc_json.get("documentType"))
            if (
                self.registration_type == MhrRegistrationTypes.TRANS
                and doc_json.get("documentType") != MhrDocumentTypes.TRAN
            ):
                reg_json["transferDocumentType"] = doc_json.get("documentType")
            reg_json = reg_json_utils.set_submitting_json(self, reg_json)
            if (
                self.registration_type in (MhrRegistrationTypes.PERMIT, MhrRegistrationTypes.PERMIT_EXTENSION)
                or doc_json.get("documentType") == MhrDocumentTypes.AMEND_PERMIT
            ):
                reg_json = reg_json_utils.set_note_json(self, reg_json)
                if doc_json.get("documentType") == MhrDocumentTypes.AMEND_PERMIT:
                    reg_json["amendment"] = True
                elif doc_json.get("documentType") == MhrDocumentTypes.REG_103E:
                    reg_json["extension"] = True
            elif self.is_transfer():
                if doc_json.get("transferDate"):
                    reg_json["transferDate"] = doc_json.get("transferDate")
                if doc_json.get("consideration"):
                    reg_json["consideration"] = doc_json.get("consideration")
                reg_json["affirmByName"] = doc_json.get("affirmByName")
            elif self.registration_type in (MhrRegistrationTypes.EXEMPTION_NON_RES, MhrRegistrationTypes.EXEMPTION_RES):
                reg_json = reg_json_utils.set_note_json(self, reg_json)
                if reg_json["note"].get("documentType") == MhrDocumentTypes.EXNR:
                    reg_json["nonResidential"] = True
            elif self.registration_type == MhrRegistrationTypes.REG_STAFF_ADMIN and doc_json.get("documentType") in (
                MhrDocumentTypes.STAT,
                MhrDocumentTypes.REGC,
                MhrDocumentTypes.REGC_CLIENT,
                MhrDocumentTypes.REGC_STAFF,
                MhrDocumentTypes.PUBA,
                MhrDocumentTypes.AMEND_PERMIT,
                MhrDocumentTypes.CANCEL_PERMIT,
                MhrDocumentTypes.EXRE,
            ):
                reg_json["documentType"] = doc_json.get("documentType")
                del reg_json["declaredValue"]
                reg_json = reg_json_utils.set_note_json(self, reg_json)
            elif self.registration_type == MhrRegistrationTypes.REG_STAFF_ADMIN and (
                not self.notes or doc_json.get("documentType") in (MhrDocumentTypes.NCAN, MhrDocumentTypes.NRED)
            ):
                reg_json["documentType"] = doc_json.get("documentType")
                del reg_json["declaredValue"]
                reg_json = reg_json_utils.set_note_json(self, reg_json)
            elif self.registration_type == MhrRegistrationTypes.REG_NOTE:
                reg_json = reg_json_utils.set_note_json(self, reg_json)
                del reg_json["documentId"]
                del reg_json["documentDescription"]
                del reg_json["documentRegistrationNumber"]
            reg_json["hasCaution"] = self.set_caution()
            logger.debug(f"Built registration JSON for type={self.registration_type}.")
            return reg_json_utils.set_payment_json(self, reg_json)
        return {}

    @property
    def registration_json(self) -> dict:
        """Return the search version of the registration as a json object."""
        self.current_view = True
        self.report_view = True
        doc_json = self.documents[0].json
        reg_json = {
            "mhrNumber": self.mhr_number,
            "createDateTime": model_utils.format_ts(self.registration_ts),
            "status": self.status_type,
            "documentId": doc_json.get("documentId"),
            "attentionReference": doc_json.get("attentionReference", ""),
            "clientReferenceId": self.client_reference_id if self.client_reference_id else "",
        }
        reg_json = reg_json_utils.set_submitting_json(self, reg_json)
        reg_json = reg_json_utils.set_location_json(self, reg_json, self.current_view)
        reg_json = reg_json_utils.set_description_json(self, reg_json, self.current_view)
        reg_json = reg_json_utils.set_group_json(self, reg_json, self.current_view, True)
        notes = reg_json_utils.get_notes_json(self, True, self.staff)
        if notes:
            reg_json["notes"] = notes
        # reg_json = model_utils.update_reg_status(reg_json, self.current_view)
        logger.debug(f"Built new search registration JSON for mhr {self.mhr_number}")
        return reg_json_utils.set_current_misc_json(self, reg_json, True)

    @property
    def new_registration_json(self) -> dict:
        """Return the new registration or current/composite version of the registration as a json object."""
        if self.id and self.id > 0:
            doc_json = self.documents[0].json
            reg_json = {
                "mhrNumber": self.mhr_number,
                "createDateTime": model_utils.format_ts(self.registration_ts),
                "registrationType": self.registration_type,
                "status": self.status_type,
                "declaredValue": doc_json.get("declaredValue", 0),
                "documentDescription": reg_utils.get_document_description(doc_json.get("documentType")),
                "documentId": doc_json.get("documentId"),
                "documentRegistrationNumber": doc_json.get("documentRegistrationNumber"),
                "ownLand": doc_json.get("ownLand"),
                "affirmByName": doc_json.get("affirmByName", ""),
                "attentionReference": doc_json.get("attentionReference", ""),
                "clientReferenceId": self.client_reference_id if self.client_reference_id else "",
            }
            if not self.current_view:
                reg_json = reg_json_utils.set_submitting_json(self, reg_json)
            reg_json = reg_json_utils.set_location_json(self, reg_json, self.current_view)
            reg_json = reg_json_utils.set_description_json(self, reg_json, self.current_view)
            reg_json = reg_json_utils.set_group_json(self, reg_json, self.current_view)
            if self.current_view and self.staff:
                reg_json["notes"] = reg_json_utils.get_notes_json(self, False, self.staff)
            elif self.current_view:
                reg_json["notes"] = reg_json_utils.get_non_staff_notes_json(self, False)
            reg_json["hasCaution"] = self.set_caution()
            if self.change_registrations:
                last_reg: MhrRegistration = self.change_registrations[-1]
                if last_reg.registration_type == MhrRegistrationTypes.TRANS_AFFIDAVIT:
                    reg_json["status"] = model_utils.STATUS_FROZEN
                    reg_json["frozenDocumentType"] = MhrDocumentTypes.AFFE
            reg_json = model_utils.update_reg_status(reg_json, self.current_view)
            logger.debug("Built new registration JSON")
            if self.current_view:
                return reg_json_utils.set_current_misc_json(self, reg_json, False)
            return reg_json_utils.set_payment_json(self, reg_json)
        return self.json

    def set_caution(self) -> bool:
        """Check if an active caution exists on the MH registration: exists and not cancelled or expired."""
        has_caution: bool = False
        if not self.change_registrations:
            return has_caution
        for reg in self.change_registrations:
            if (
                reg.notes
                and reg.notes[0].document_type in (MhrDocumentTypes.CAU, MhrDocumentTypes.CAUC, MhrDocumentTypes.CAUE)
                and reg.notes[0].status_type == MhrNoteStatusTypes.ACTIVE.value
            ):
                if not reg.notes[0].expiry_date and reg.notes[0].document_type == MhrDocumentTypes.CAUC:
                    has_caution = True
                elif reg.notes[0].expiry_date:
                    now_ts = model_utils.now_ts()
                    has_caution = reg.notes[0].expiry_date.timestamp() > now_ts.timestamp()
                    break
        return has_caution

    def save(self):
        """Render a registration to the local cache."""
        db.session.add(self)
        db.session.commit()

    def save_exemption(self, new_reg_id: int):
        """Set the state of the original MH registration to exempt."""
        self.status_type = MhrRegistrationStatusTypes.EXEMPT
        if self.change_registrations:  # Close out active transport permit without reverting location.
            for reg in self.change_registrations:
                if (
                    reg.notes
                    and reg.notes[0].document_type
                    in (MhrDocumentTypes.REG_103, MhrDocumentTypes.REG_103E, MhrDocumentTypes.AMEND_PERMIT)
                    and reg.notes[0].status_type == MhrNoteStatusTypes.ACTIVE
                ):
                    note: MhrNote = reg.notes[0]
                    note.status_type = MhrNoteStatusTypes.CANCELLED
                    note.change_registration_id = new_reg_id
        db.session.commit()

    def save_transfer(self, json_data, new_reg_id):
        """Update the original MH removed owner groups."""
        self.remove_groups(json_data, new_reg_id)
        db.session.commit()

    def is_transfer(self) -> bool:
        """Determine if the registration is one of the transfer types."""
        return self.registration_type in (
            MhrRegistrationTypes.TRANS,
            MhrRegistrationTypes.TRAND,
            MhrRegistrationTypes.TRANS_ADMIN,
            MhrRegistrationTypes.TRANS_AFFIDAVIT,
            MhrRegistrationTypes.TRANS_WILL,
        )

    @classmethod
    def find_by_id(cls, registration_id: int, legacy: bool = False, search: bool = False):
        """Return the registration matching the id."""
        registration = None
        if registration_id:
            registration = db.session.query(MhrRegistration).filter(MhrRegistration.id == registration_id).one_or_none()
        if search and registration and registration.mhr_number:
            try:
                registration.change_registrations = (
                    db.session.query(MhrRegistration)
                    .filter(
                        MhrRegistration.mhr_number == registration.mhr_number,
                        ~MhrRegistration.registration_type.in_([REG_TYPE, CONV_TYPE]),
                    )
                    .all()
                )
            except Exception as db_exception:  # noqa: B902; return nicer error
                logger.error("DB find_by_id change registrations exception: " + str(db_exception))
                raise DatabaseException(db_exception) from db_exception

        return registration

    @classmethod
    def find_summary_by_mhr_number(cls, account_id: str, mhr_number: str, staff: bool = False):
        """Return the MHR registration summary information matching the MH registration number."""
        formatted_mhr = model_utils.format_mhr_number(mhr_number)
        logger.debug(f"Account_id={account_id}, mhr_number={formatted_mhr}, staff={staff}")
        return reg_utils.find_summary_by_mhr_number(account_id, formatted_mhr, staff)

    @classmethod
    def find_summary_by_doc_reg_number(cls, account_id: str, doc_reg_number: str, staff: bool = False):
        """Return the MHR registration summary information matching the document registration number."""
        formatted_reg_num = model_utils.format_doc_reg_number(doc_reg_number)
        logger.debug(f"Account_id={account_id}, doc_reg_number={formatted_reg_num}")
        return reg_utils.find_summary_by_doc_reg_number(account_id, formatted_reg_num, staff)

    @classmethod
    def find_all_by_account_id(cls, params: reg_utils.AccountRegistrationParams):
        """Return a summary list of recent MHR registrations belonging to an account."""
        logger.debug(f"Account_id={params.account_id}")
        return reg_utils.find_all_by_account_id(params)

    @classmethod
    def get_doc_id_count(cls, doc_id: str):
        """Execute a query to count existing document id (must not exist check)."""
        return reg_utils.get_doc_id_count(doc_id)

    @classmethod
    def find_by_mhr_number(cls, mhr_number: str, account_id: str, staff: bool = False, reg_type=None):
        """Return the registration matching the MHR number."""
        logger.debug(f"Account={account_id}, mhr_number={mhr_number}")
        registration = None
        formatted_mhr = model_utils.format_mhr_number(mhr_number)
        registration_type = REG_TYPE
        if reg_type and reg_type in MhrRegistrationTypes:
            registration_type = reg_type
        if formatted_mhr:
            try:
                if registration_type == MhrRegistrationTypes.MHREG:
                    registration = (
                        db.session.query(MhrRegistration)
                        .filter(
                            MhrRegistration.mhr_number == formatted_mhr,
                            MhrRegistration.registration_type.in_([registration_type, CONV_TYPE]),
                        )
                        .one_or_none()
                    )
                else:
                    registration = (
                        db.session.query(MhrRegistration)
                        .filter(
                            MhrRegistration.mhr_number == formatted_mhr,
                            MhrRegistration.registration_type == registration_type,
                        )
                        .one_or_none()
                    )
            except Exception as db_exception:  # noqa: B902; return nicer error
                logger.error("DB find_by_mhr_number exception: " + str(db_exception))
                raise DatabaseException(db_exception) from db_exception

        if not registration:
            raise BusinessException(
                error=model_utils.ERR_MHR_REGISTRATION_NOT_FOUND.format(
                    code=ResourceErrorCodes.NOT_FOUND_ERR.value, mhr_number=formatted_mhr
                ),
                status_code=HTTPStatus.NOT_FOUND,
            )

        if not staff and account_id and (not registration or registration.account_id != account_id):
            # Check extra registrations
            extra_reg = MhrExtraRegistration.find_by_mhr_number(formatted_mhr, account_id)
            if not extra_reg:
                raise BusinessException(
                    error=model_utils.ERR_REGISTRATION_ACCOUNT.format(
                        code=ResourceErrorCodes.UNAUTHORIZED_ERR.value, account_id=account_id, mhr_number=formatted_mhr
                    ),
                    status_code=HTTPStatus.UNAUTHORIZED,
                )
        if registration and registration.documents:
            registration.doc_id = registration.documents[0].id
        return registration

    @classmethod
    def find_all_by_mhr_number(cls, mhr_number: str, account_id: str, staff: bool = False):
        """Return the base registration matching the MHR number with the associated change registrations."""
        logger.debug(f"Account={account_id}, mhr_number={mhr_number}")
        base_reg: MhrRegistration = MhrRegistration.find_by_mhr_number(mhr_number, account_id, staff)
        if not base_reg:
            return base_reg
        formatted_mhr = model_utils.format_mhr_number(mhr_number)
        try:
            base_reg.change_registrations = (
                db.session.query(MhrRegistration)
                .filter(
                    MhrRegistration.mhr_number == formatted_mhr,
                    ~MhrRegistration.registration_type.in_([REG_TYPE, CONV_TYPE]),
                )
                .order_by(MhrRegistration.registration_ts)
                .all()
            )
        except Exception as db_exception:  # noqa: B902; return nicer error
            logger.error("DB find_all_by_mhr_number exception: " + str(db_exception))
            raise DatabaseException(db_exception) from db_exception
        return base_reg

    @classmethod
    def find_original_by_mhr_number(cls, mhr_number: str, account_id: str, staff: bool = False):
        """Return the original MH registration information matching the MHR number."""
        logger.debug(f"Account={account_id}, mhr_number={mhr_number}")
        registration = None
        formatted_mhr = model_utils.format_mhr_number(mhr_number)
        if formatted_mhr:
            try:
                registration = (
                    db.session.query(MhrRegistration)
                    .filter(
                        MhrRegistration.mhr_number == formatted_mhr,
                        MhrRegistration.registration_type.in_([REG_TYPE, CONV_TYPE]),
                    )
                    .one_or_none()
                )
            except Exception as db_exception:  # noqa: B902; return nicer error
                logger.error("DB find_by_mhr_number exception: " + str(db_exception))
                raise DatabaseException(db_exception) from db_exception

        if not registration:
            raise BusinessException(
                error=model_utils.ERR_MHR_REGISTRATION_NOT_FOUND.format(
                    code=ResourceErrorCodes.NOT_FOUND_ERR.value, mhr_number=formatted_mhr
                ),
                status_code=HTTPStatus.NOT_FOUND,
            )

        if not staff and account_id and (not registration or registration.account_id != account_id):
            # Check extra registrations
            extra_reg = MhrExtraRegistration.find_by_mhr_number(formatted_mhr, account_id)
            if not extra_reg:
                raise BusinessException(
                    error=model_utils.ERR_REGISTRATION_ACCOUNT.format(
                        code=ResourceErrorCodes.UNAUTHORIZED_ERR.value, account_id=account_id, mhr_number=formatted_mhr
                    ),
                    status_code=HTTPStatus.UNAUTHORIZED,
                )
        if registration and registration.documents:
            registration.doc_id = registration.documents[0].id
        return registration

    @classmethod
    def find_by_document_id(cls, document_id: str, account_id: str, staff: bool = False):
        """Return the registration matching the MHR document ID."""
        logger.debug(f"Account={account_id}, document_id={document_id}, staff={staff}")
        registration = None
        if document_id:
            try:
                doc: MhrDocument = MhrDocument.find_by_document_id(document_id)
                if doc:
                    registration = MhrRegistration.find_by_id(doc.registration_id)
                    if registration and registration.registration_type not in (REG_TYPE, CONV_TYPE):
                        mhr_num = registration.mhr_number
                        registration.change_registrations = (
                            db.session.query(MhrRegistration)
                            .filter(
                                MhrRegistration.mhr_number == mhr_num,
                                ~MhrRegistration.registration_type.in_([REG_TYPE, CONV_TYPE]),
                            )
                            .all()
                        )
                        logger.error(f"DB find_by_document_id getting changes for MHR# {mhr_num}")
            except Exception as db_exception:  # noqa: B902; return nicer error
                logger.error("DB find_by_document_id exception: " + str(db_exception))
                raise DatabaseException(db_exception) from db_exception
        if not registration:
            raise BusinessException(
                error=model_utils.ERR_DOCUMENT_NOT_FOUND_ID.format(
                    code=ResourceErrorCodes.NOT_FOUND_ERR.value, document_id=document_id
                ),
                status_code=HTTPStatus.NOT_FOUND,
            )
        if not staff and account_id and registration and registration.account_id != account_id:
            # Check extra registrations
            extra_reg = MhrExtraRegistration.find_by_mhr_number(registration.mhr_number, account_id)
            if not extra_reg:
                raise BusinessException(
                    error=model_utils.ERR_REGISTRATION_ACCOUNT.format(
                        code=ResourceErrorCodes.UNAUTHORIZED_ERR.value,
                        account_id=account_id,
                        mhr_number=registration.mhr_number,
                    ),
                    status_code=HTTPStatus.UNAUTHORIZED,
                )
        return registration

    @staticmethod
    def create_new_from_json(
        json_data: dict, draft: MhrDraft, account_id: str = None, user_id: str = None, user_group: str = None
    ):
        """Create a new registration object from dict/json."""
        # Draft always exists.
        registration: MhrRegistration = MhrRegistration(
            registration_type=MhrRegistrationTypes.MHREG,
            registration_ts=model_utils.now_ts(),
            status_type=MhrRegistrationStatusTypes.ACTIVE,
            account_id=account_id,
            user_id=user_id,
            mhr_number=draft.mhr_number,
        )
        logger.info(f"New MH reg for MHR number: {draft.mhr_number}")
        reg_vals: MhrRegistration = reg_utils.get_change_generated_values(
            MhrRegistration(), draft, user_group, json_data.get("documentId")
        )
        registration.id = reg_vals.id  # pylint: disable=invalid-name; allow name of id.
        registration.doc_reg_number = reg_vals.doc_reg_number
        registration.doc_pkey = reg_vals.doc_pkey
        if json_data.get("documentId"):
            registration.doc_id = json_data.get("documentId")
        else:
            registration.doc_id = reg_vals.doc_id
            json_data["documentId"] = registration.doc_id
        registration.reg_json = json_data
        draft.draft = json_data
        registration.draft_id = draft.id
        registration.draft = draft
        if "clientReferenceId" in json_data:
            registration.client_reference_id = json_data["clientReferenceId"]
        registration.create_new_groups(json_data)
        # Other parties
        registration.parties = MhrParty.create_from_registration_json(json_data, registration.id)
        registration.locations = [MhrLocation.create_from_json(json_data["location"], registration.id)]
        doc: MhrDocument = MhrDocument.create_from_json(
            registration, json_data, REG_TO_DOC_TYPE[registration.registration_type]
        )
        doc.registration_id = registration.id
        registration.documents = [doc]
        description: MhrDescription = MhrDescription.create_from_json(json_data.get("description"), registration.id)
        registration.descriptions = [description]
        registration.sections = MhrRegistration.get_sections(json_data, registration.id)
        return registration

    @staticmethod
    def create_change_from_json(
        base_reg, json_data, account_id: str = None, user_id: str = None, user_group: str = None
    ):
        """Create common change registration objects from dict/json."""
        # Create or update draft.
        draft = MhrDraft.find_draft(json_data)
        reg_vals: MhrRegistration = reg_utils.get_change_generated_values(
            MhrRegistration(), draft, user_group, json_data.get("documentId")
        )
        registration: MhrRegistration = MhrRegistration()
        registration.id = reg_vals.id  # pylint: disable=invalid-name; allow name of id.
        registration.mhr_number = base_reg.mhr_number
        registration.doc_reg_number = reg_vals.doc_reg_number
        registration.registration_type = json_data.get("registrationType")
        if json_data.get("documentId"):
            registration.doc_id = json_data.get("documentId")
        else:
            registration.doc_id = reg_vals.doc_id
        registration.doc_pkey = reg_vals.doc_pkey
        registration.registration_ts = model_utils.now_ts()
        registration.status_type = MhrRegistrationStatusTypes.ACTIVE
        registration.account_id = account_id
        registration.user_id = user_id
        registration.reg_json = json_data
        if not draft:
            registration.draft_number = reg_vals.draft_number
            registration.draft_id = reg_vals.draft_id
            draft = MhrDraft.create_from_registration(registration, json_data)
        else:
            draft.draft = json_data
            registration.draft_id = draft.id
        registration.draft = draft
        if "clientReferenceId" in json_data:
            registration.client_reference_id = json_data["clientReferenceId"]
        registration.parties = MhrParty.create_from_registration_json(json_data, registration.id)
        json_data["documentId"] = registration.doc_id
        doc: MhrDocument = MhrDocument.create_from_json(
            registration, json_data, REG_TO_DOC_TYPE[registration.registration_type]
        )
        if registration.registration_type == MhrRegistrationTypes.REG_STAFF_ADMIN and json_data.get("documentType"):
            doc.document_type = json_data.get("documentType")
        elif registration.registration_type == MhrRegistrationTypes.REG_NOTE and json_data.get("note"):
            doc.document_type = json_data["note"].get("documentType")
        elif registration.registration_type == MhrRegistrationTypes.TRANS and json_data.get("transferDocumentType"):
            doc.document_type = json_data.get("transferDocumentType")
        doc.registration_id = base_reg.id
        registration.documents = [doc]
        return registration

    @staticmethod
    def create_transfer_from_json(
        base_reg, json_data, account_id: str = None, user_id: str = None, user_group: str = None
    ):
        """Create transfer registration objects from dict/json."""
        if not json_data.get("registrationType"):
            json_data["registrationType"] = MhrRegistrationTypes.TRANS
        registration: MhrRegistration = MhrRegistration.create_change_from_json(
            base_reg, json_data, account_id, user_id, user_group
        )
        if base_reg.owner_groups:
            registration.add_new_groups(json_data, reg_utils.get_owner_group_count(base_reg))
        return registration

    @staticmethod
    def create_exemption_from_json(
        base_reg, json_data, account_id: str = None, user_id: str = None, user_group: str = None
    ):
        """Create exemption registration objects from dict/json."""
        if json_data.get("nonResidential"):
            json_data["registrationType"] = MhrRegistrationTypes.EXEMPTION_NON_RES
        else:
            json_data["registrationType"] = MhrRegistrationTypes.EXEMPTION_RES
        registration: MhrRegistration = MhrRegistration.create_change_from_json(
            base_reg, json_data, account_id, user_id, user_group
        )
        if json_data["note"].get("givingNoticeParty"):
            notice_json = json_data["note"]["givingNoticeParty"]
            registration.parties.append(MhrParty.create_from_json(notice_json, MhrPartyTypes.CONTACT, registration.id))
        doc: MhrDocument = registration.documents[0]
        if json_data.get("note"):
            registration.notes = [
                MhrNote.create_from_json(
                    json_data.get("note"), base_reg.id, doc.id, registration.registration_ts, registration.id
                )
            ]
        return registration

    @staticmethod
    def create_permit_from_json(
        base_reg, json_data, account_id: str = None, user_id: str = None, user_group: str = None
    ):
        """Create transfer registration objects from dict/json."""
        json_data["registrationType"] = MhrRegistrationTypes.PERMIT
        registration: MhrRegistration = MhrRegistration.create_change_from_json(
            base_reg, json_data, account_id, user_id, user_group
        )
        doc: MhrDocument = registration.documents[0]
        if json_data.get("amendment"):
            json_data["registrationType"] = MhrRegistrationTypes.AMENDMENT
            doc.document_type = MhrDocumentTypes.AMEND_PERMIT
            registration.registration_type = MhrRegistrationTypes.AMENDMENT
        elif json_data.get("extension"):
            doc.document_type = MhrDocumentTypes.REG_103E
            registration.registration_type = MhrRegistrationTypes.PERMIT_EXTENSION
        # Save permit expiry date as a note.
        note: MhrNote = MhrNote(
            registration_id=base_reg.id,
            document_id=doc.id,
            document_type=doc.document_type,
            destroyed="N",
            status_type=MhrNoteStatusTypes.ACTIVE,
            remarks="",
            change_registration_id=registration.id,
            expiry_date=model_utils.compute_permit_expiry(),
        )
        # Amendment use existing expiry timestamp
        if json_data.get("amendment"):
            for reg in base_reg.change_registrations:  # Updating a change registration location.
                if (
                    reg.notes
                    and reg.notes[0]
                    and reg.notes[0].status_type == MhrNoteStatusTypes.ACTIVE
                    and reg.notes[0].expiry_date
                    and reg.notes[0].document_type
                    in (MhrDocumentTypes.REG_103, MhrDocumentTypes.REG_103E, MhrDocumentTypes.AMEND_PERMIT)
                ):
                    note.expiry_date = reg.notes[0].expiry_date
        if doc.document_type == MhrDocumentTypes.REG_103E:  # Same location with optional updated tax info.
            change_utils.setup_permit_extension_location(base_reg, registration, json_data.get("newLocation"))
            if account_id == STAFF_ROLE and json_data.get("note") and json_data["note"].get("remarks"):
                note.remarks = json_data["note"].get("remarks")
        else:  # New location
            registration.locations.append(MhrLocation.create_from_json(json_data.get("newLocation"), registration.id))
        registration.notes = [note]
        return registration

    @staticmethod
    def create_note_from_json(base_reg, json_data, account_id: str = None, user_id: str = None, user_group: str = None):
        """Create unit note registration objects from dict/json."""
        if MhrDocumentTypes.NCAN == json_data["note"].get("documentType"):
            json_data["documentType"] = json_data["note"].get("documentType")
            json_data["updateDocumentId"] = json_data.get("cancelDocumentId")
            return MhrRegistration.create_admin_from_json(base_reg, json_data, account_id, user_id, user_group)
        json_data["registrationType"] = MhrRegistrationTypes.REG_NOTE
        json_data["documentId"] = json_data["note"].get("documentId", "")
        registration: MhrRegistration = MhrRegistration.create_change_from_json(
            base_reg, json_data, account_id, user_id, user_group
        )
        if json_data["note"].get("givingNoticeParty"):
            notice_json = json_data["note"]["givingNoticeParty"]
            registration.parties.append(MhrParty.create_from_json(notice_json, MhrPartyTypes.CONTACT, registration.id))
        doc: MhrDocument = registration.documents[0]
        registration.notes = [
            MhrNote.create_from_json(
                json_data.get("note"), registration.id, doc.id, registration.registration_ts, registration.id
            )
        ]
        return registration

    @staticmethod
    def create_admin_from_json(
        base_reg, json_data, account_id: str = None, user_id: str = None, user_group: str = None
    ):
        """Create admin registration objects from dict/json."""
        json_data["registrationType"] = MhrRegistrationTypes.REG_STAFF_ADMIN
        registration: MhrRegistration = MhrRegistration.create_change_from_json(
            base_reg, json_data, account_id, user_id, user_group
        )
        if json_data.get("note") and json_data["note"].get("givingNoticeParty"):
            notice_json = json_data["note"]["givingNoticeParty"]
            registration.parties.append(MhrParty.create_from_json(notice_json, MhrPartyTypes.CONTACT, registration.id))
        doc: MhrDocument = registration.documents[0]
        if json_data.get("note"):
            registration.notes = [
                MhrNote.create_from_json(
                    json_data.get("note"), registration.id, doc.id, registration.registration_ts, registration.id
                )
            ]
        if json_data.get("location") and doc.document_type in (
            MhrDocumentTypes.REGC_CLIENT,
            MhrDocumentTypes.EXRE,
            MhrDocumentTypes.REGC_STAFF,
            MhrDocumentTypes.STAT,
            MhrDocumentTypes.PUBA,
            MhrDocumentTypes.CANCEL_PERMIT,
        ):
            registration.locations.append(MhrLocation.create_from_json(json_data.get("location"), registration.id))
        if json_data.get("description") and doc.document_type in (
            MhrDocumentTypes.REGC_CLIENT,
            MhrDocumentTypes.EXRE,
            MhrDocumentTypes.REGC_STAFF,
            MhrDocumentTypes.PUBA,
        ):
            description: MhrDescription = MhrDescription.create_from_json(json_data.get("description"), registration.id)
            registration.descriptions = [description]
            registration.sections = MhrRegistration.get_sections(json_data, registration.id)
        if (
            json_data.get("addOwnerGroups")
            and json_data.get("deleteOwnerGroups")
            and doc.document_type
            in (MhrDocumentTypes.REGC_CLIENT, MhrDocumentTypes.REGC_STAFF, MhrDocumentTypes.PUBA, MhrDocumentTypes.EXRE)
        ):
            registration.add_new_groups(json_data, reg_utils.get_owner_group_count(base_reg))
        return registration

    def adjust_group_interest(self, new: bool):
        """For tenants in common groups adjust group interest to a common denominator."""
        tc_count: int = 0
        common_denominator: int = 0
        for group in self.owner_groups:
            if group.tenancy_type == MhrTenancyTypes.COMMON and group.status_type == MhrOwnerStatusTypes.ACTIVE:
                tc_count += 1
                if common_denominator == 0:
                    common_denominator = group.interest_denominator
                elif group.interest_denominator > common_denominator:
                    common_denominator = group.interest_denominator
        if tc_count > 0:
            for group in self.owner_groups:
                if new or (group.modified and group.status_type == MhrOwnerStatusTypes.ACTIVE):
                    num = group.interest_numerator
                    den = group.interest_denominator
                    if num > 0 and den > 0:
                        if den != common_denominator:
                            group.interest_denominator = common_denominator
                            group.interest_numerator = common_denominator / den * num

    def create_new_groups(self, json_data):
        """Create owner groups and owners for a new MH registration."""
        self.owner_groups = []
        sequence: int = 0
        for group_json in json_data.get("ownerGroups"):
            sequence += 1
            group: MhrOwnerGroup = MhrOwnerGroup.create_from_json(group_json, self.id)
            group.group_id = sequence
            group.group_sequence_number = sequence
            # Add owners
            for owner_json in group_json.get("owners"):
                party_type = owner_json.get("partyType", None)
                if not party_type and owner_json.get("individualName"):
                    party_type = MhrPartyTypes.OWNER_IND
                elif party_type and party_type == MhrPartyTypes.OWNER_BUS and owner_json.get("individualName"):
                    party_type = MhrPartyTypes.OWNER_IND
                elif party_type and party_type == MhrPartyTypes.OWNER_IND and owner_json.get("organizationName"):
                    party_type = MhrPartyTypes.OWNER_BUS
                elif not party_type:
                    party_type = MhrPartyTypes.OWNER_BUS
                group.owners.append(MhrParty.create_from_json(owner_json, party_type, self.id))
            self.owner_groups.append(group)
        # Update interest common denominator
        # self.adjust_group_interest(True)

    def add_new_groups(self, json_data, existing_count: int):
        """Create owner groups and owners for a change (transfer) registration."""
        self.owner_groups = []
        # Update owner groups: group ID increments with each change.
        group_id: int = existing_count + 1
        if json_data.get("addOwnerGroups"):
            for new_json in json_data.get("addOwnerGroups"):
                logger.info(f"Creating owner group id={group_id}")
                new_group: MhrOwnerGroup = MhrOwnerGroup.create_from_change_json(new_json, self.id, self.id, group_id)
                group_id += 1
                if not new_group.interest or not new_group.interest_numerator or new_group.interest_numerator == 0:
                    new_group.group_sequence_number = 1
                else:
                    new_group.group_sequence_number = new_json.get("groupId")
                # Add owners
                for owner_json in new_json.get("owners"):
                    party_type = owner_json.get("partyType", None)
                    if not party_type and owner_json.get("individualName"):
                        party_type = MhrPartyTypes.OWNER_IND
                    elif not party_type:
                        party_type = MhrPartyTypes.OWNER_BUS
                    new_group.owners.append(MhrParty.create_from_json(owner_json, party_type, self.id))
                logger.info(f"Creating owner group id={group_id} reg id={new_group.registration_id}")
                self.owner_groups.append(new_group)
            # self.adjust_group_interest(False)

    @staticmethod
    def remove_group(delete_json: dict, existing: MhrOwnerGroup, new_reg_id: int, reg_type: str):
        """Conditionally set status on owner group and owners."""
        if existing.group_id == delete_json.get("groupId"):
            existing.status_type = MhrOwnerStatusTypes.PREVIOUS
            existing.change_registration_id = new_reg_id
            existing.modified = True
            logger.info(f"Removing exsting owner group id={existing.id}, reg id={existing.registration_id}")
            for owner in existing.owners:
                owner.status_type = MhrOwnerStatusTypes.PREVIOUS
                owner.change_registration_id = new_reg_id
                if reg_utils.is_transfer_due_to_death(reg_type):
                    reg_utils.update_deceased(delete_json.get("owners"), owner)

    def remove_groups(self, json_data, new_reg_id: int):
        """Set change registration id for removed owner groups and owners for a transfer registration."""
        for group in json_data.get("deleteOwnerGroups"):
            for existing in self.owner_groups:  # Updating a base registration owner group.
                MhrRegistration.remove_group(group, existing, new_reg_id, json_data.get("registrationType"))
            for reg in self.change_registrations:  # Updating a change registration (previous transfer) group.
                for existing in reg.owner_groups:
                    MhrRegistration.remove_group(group, existing, new_reg_id, json_data.get("registrationType"))

    @staticmethod
    def get_sections(json_data, registration_id: int):
        """Build sections from the json_data."""
        sections = []
        if not json_data.get("description") or "sections" not in json_data.get("description"):
            return sections
        for section in json_data["description"]["sections"]:
            sections.append(MhrSection.create_from_json(section, registration_id))
        return sections
