import { UnitNoteDocTypes, UnitNoteStatusTypes } from '@/enums'
import { UnitNoteIF } from '@/interfaces/unit-note-interfaces/unit-note-interface'

export const mockUnitNotes: Array<UnitNoteIF> = [
  {
    documentType: UnitNoteDocTypes.NOTICE_OF_CAUTION,
    documentId: '1',
    documentRegistrationNumber: '123456',
    documentDescription: 'Notice of Caution',
    createDateTime: '2023-12-30T09:00:00Z',
    effectiveDateTime: '2023-13-01T12:00:00Z',
    expiryDateTime: '2023-13-30T23:59:59Z',
    remarks: 'This is a notice of caution.',
    givingNoticeParty: {
      businessName: 'HALSTON MODULAR HOMES LTD.',
      address: {
        street: 'PO BOX 266',
        city: 'KNUTSFORD',
        region: 'BC',
        country: 'CA',
        postalCode: 'V0E 2A0'
      },
      phoneNumber: '2508289998',
      emailAddress: 'testing@email.com'
    },
    status: UnitNoteStatusTypes.ACTIVE,
    destroyed: false
  },
  {
    documentType: UnitNoteDocTypes.EXTENSION_TO_NOTICE_OF_CAUTION,
    documentId: '2',
    documentRegistrationNumber: '789012',
    documentDescription: 'Extension to Notice of Caution',
    createDateTime: '2023-11-31T10:00:00Z',
    effectiveDateTime: '2023-12-01T00:00:00Z',
    expiryDateTime: '2023-12-31T23:59:59Z',
    remarks: 'This is an extension to the notice of caution.',
    givingNoticeParty: {
      personName: {
        first: 'Bob',
        middle: 'L',
        last: 'Brown'
      },
      address: {
        street: 'PO BOX 266',
        city: 'KNUTSFORD',
        region: 'BC',
        country: 'CA',
        postalCode: 'V0E 2A0'
      },
      phoneNumber: '2508289998',
      emailAddress: 'testing@email.com'
    },
    status: UnitNoteStatusTypes.CANCELLED,
    destroyed: false
  },
  {
    documentType: UnitNoteDocTypes.RESTRAINING_ORDER,
    documentId: '1',
    documentRegistrationNumber: '123456',
    documentDescription: 'Notice of Caution',
    createDateTime: '2023-10-30T09:00:00Z',
    effectiveDateTime: '2023-11-01T12:00:00Z',
    expiryDateTime: '2023-11-30T23:59:59Z',
    remarks: 'This is a notice of caution.',
    givingNoticeParty: {
      businessName: 'HALSTON MODULAR HOMES LTD.',
      address: {
        street: 'PO BOX 266',
        city: 'KNUTSFORD',
        region: 'BC',
        country: 'CA',
        postalCode: 'V0E 2A0'
      },
      phoneNumber: '2508289998',
      emailAddress: 'testing@email.com'
    },
    status: UnitNoteStatusTypes.ACTIVE,
    destroyed: false
  },
  {
    documentType: UnitNoteDocTypes.EXTENSION_TO_NOTICE_OF_CAUTION,
    documentId: '2',
    documentRegistrationNumber: '789012',
    documentDescription: 'Extension to Notice of Caution',
    createDateTime: '2023-09-31T10:00:00Z',
    effectiveDateTime: '2023-10-01T00:00:00Z',
    expiryDateTime: '2023-10-31T23:59:59Z',
    remarks: 'This is an extension to the notice of caution.',
    givingNoticeParty: {
      personName: {
        first: 'Bob',
        middle: 'L',
        last: 'Brown'
      },
      address: {
        street: 'PO BOX 266',
        city: 'KNUTSFORD',
        region: 'BC',
        country: 'CA',
        postalCode: 'V0E 2A0'
      },
      phoneNumber: '2508289998',
      emailAddress: 'testing@email.com'
    },
    status: UnitNoteStatusTypes.EXPIRED,
    destroyed: false
  },
  {
    documentType: UnitNoteDocTypes.PUBLIC_NOTE,
    documentId: '2',
    documentRegistrationNumber: '789012',
    documentDescription: 'Extension to Notice of Caution',
    createDateTime: '2023-08-31T10:00:00Z',
    effectiveDateTime: '2023-09-01T00:00:00Z',
    expiryDateTime: '2023-09-31T23:59:59Z',
    remarks: 'This is an extension to the notice of caution.',
    givingNoticeParty: {
      personName: {
        first: 'Bob',
        middle: 'L',
        last: 'Brown'
      },
      address: {
        street: 'PO BOX 266',
        city: 'KNUTSFORD',
        region: 'BC',
        country: 'CA',
        postalCode: 'V0E 2A0'
      },
      phoneNumber: '2508289998',
      emailAddress: 'testing@email.com'
    },
    status: UnitNoteStatusTypes.CANCELLED,
    destroyed: false
  },
  {
    documentType: UnitNoteDocTypes.EXTENSION_TO_NOTICE_OF_CAUTION,
    documentId: '2',
    documentRegistrationNumber: '789012',
    documentDescription: 'Extension to Notice of Caution',
    createDateTime: '2023-07-31T10:00:00Z',
    effectiveDateTime: '2023-08-01T00:00:00Z',
    expiryDateTime: '2023-08-31T23:59:59Z',
    remarks: 'This is an extension to the notice of caution.',
    givingNoticeParty: {
      personName: {
        first: 'Bob',
        middle: 'L',
        last: 'Brown'
      },
      address: {
        street: 'PO BOX 266',
        city: 'KNUTSFORD',
        region: 'BC',
        country: 'CA',
        postalCode: 'V0E 2A0'
      },
      phoneNumber: '2508289998',
      emailAddress: 'testing@email.com'
    },
    status: UnitNoteStatusTypes.CANCELLED,
    destroyed: false
  },
  {
    documentType: UnitNoteDocTypes.NOTICE_OF_CAUTION,
    documentId: '1',
    documentRegistrationNumber: '123456',
    documentDescription: 'Notice of Caution',
    createDateTime: '2023-06-30T09:00:00Z',
    effectiveDateTime: '2023-07-01T12:00:00Z',
    expiryDateTime: '2023-07-30T23:59:59Z',
    remarks: 'This is a notice of caution.',
    givingNoticeParty: {
      businessName: 'HALSTON MODULAR HOMES LTD.',
      address: {
        street: 'PO BOX 266',
        city: 'KNUTSFORD',
        region: 'BC',
        country: 'CA',
        postalCode: 'V0E 2A0'
      },
      phoneNumber: '2508289998',
      emailAddress: 'testing@email.com'
    },
    status: UnitNoteStatusTypes.ACTIVE,
    destroyed: false
  }
]
