"""Explicit seller-held sealed stock; purchase cost is not a consignment payout input."""
from collections.abc import Mapping


def sealed_seller_candidate(item):
    return (item.get('owner_type') == 'CONSIGNOR'
            and item.get('product_type') == 'SEALED'
            and item.get('seal_status') == 'SEALED'
            and item.get('catalogue_identity_status') == 'VERIFIED'
            and bool(item.get('language'))
            and item.get('language') == item.get('catalogue_language')
            and not any(item.get(k) for k in ('condition','grading_company','grade','certificate_number')))


def seller_held_consignment(item):
    record = item.get('source_record') or {}
    approval = record.get('seller_held_approval') if isinstance(record, Mapping) else None
    if not isinstance(approval, Mapping):
        return False
    return (item.get('owner_type') == 'CONSIGNOR' and item.get('product_type') == 'SEALED'
            and item.get('identity_confirmed') is True and item.get('seal_status') == 'SEALED'
            and str(approval.get('owner_id')) == str(item.get('owner_id'))
            and str(approval.get('catalogue_id')) == str(item.get('catalogue_id'))
            and approval.get('language') == (item.get('language') or item.get('catalogue_language'))
            and item.get('language') == item.get('catalogue_language')
            and approval.get('name') == item.get('name')
            and approval.get('set_name') == item.get('set_name')
            and approval.get('variant') == item.get('variant')
            and bool(approval.get('actor_user_id')))
