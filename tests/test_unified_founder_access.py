"""The personal workspace does not turn an owner into a platform administrator."""
import pytest
from fastapi import HTTPException

from app.access_control import require_owner_portal, require_platform_admin, require_business_founder
from test_business_access import Connection


@pytest.mark.asyncio
@pytest.mark.parametrize('slot', [1, 2, 3])
async def test_rostered_founder_can_use_both_workspaces_with_same_owner(slot):
    connection = Connection(slot=slot)
    personal = await require_owner_portal(connection)
    business = await require_business_founder(connection)
    assert personal['owner_id'] == business['owner_id'] == connection.row['owner_id']


@pytest.mark.asyncio
@pytest.mark.parametrize('changes', [dict(authorized=False), dict(slot=4), dict(slot=None), dict(kind='CONSIGNOR')])
async def test_generic_admin_is_not_granted_personal_workspace_as_a_founder(changes):
    with pytest.raises(HTTPException) as error:
        await require_owner_portal(Connection(**changes))
    assert error.value.status_code == 403


@pytest.mark.asyncio
async def test_seller_remains_denied_all_founder_controls():
    connection = Connection(role='OWNER', authorized=False, slot=None, kind='CONSIGNOR')
    assert (await require_owner_portal(connection))['owner_id'] == connection.row['owner_id']
    for guard in (require_platform_admin, require_business_founder):
        with pytest.raises(HTTPException) as error:
            await guard(connection)
        assert error.value.status_code == 403
    assert connection.data_queries == []
