-- Make founder invite access intent explicit and index its owner references.

drop policy if exists founder_invites_no_direct_access on tcg.founder_invites;
create policy founder_invites_no_direct_access
on tcg.founder_invites
for all
to tcg_api
using (false)
with check (false);

create index if not exists founder_invites_created_by_owner_idx
on tcg.founder_invites(created_by_owner_id);

create index if not exists founder_invites_redeemed_owner_idx
on tcg.founder_invites(redeemed_owner_id)
where redeemed_owner_id is not null;
