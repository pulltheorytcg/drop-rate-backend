-- Keep the public seller-invite preview contract aligned with the FastAPI join flow.
-- The raw invite token remains outside PostgreSQL; the function receives only its SHA-256 hash.

begin;

drop function if exists tcg.preview_owner_invite(text);

create function tcg.preview_owner_invite(p_token_hash text)
returns table(
    invited_name text,
    invited_email text,
    commission_bps integer,
    expires_at timestamptz,
    available boolean
)
language sql
security definer
set search_path = pg_catalog, tcg
as $function$
    select
      i.invited_name,
      i.invited_email,
      i.commission_bps,
      i.expires_at,
      (
        i.redeemed_at is null
        and i.revoked_at is null
        and i.expires_at > now()
      ) as available
    from tcg.owner_invites i
    where i.token_hash=btrim(p_token_hash)
    limit 1
$function$;

revoke all on function tcg.preview_owner_invite(text)
from public,anon,authenticated,service_role;

grant execute on function tcg.preview_owner_invite(text) to tcg_api;

commit;
