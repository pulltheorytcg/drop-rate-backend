"""One-shot checked follow-up, removed before opening the implementation PR."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
p=ROOT/'backend/app/imports.py';s=p.read_text()
old='from .import_inventory import lock_import_owner, create_draft_copies'
assert s.count(old)==1
s=s.replace(old,old+'\nfrom .import_admission import manual_admission_valid',1)
old='''                if previous and catalogue_id is None and previous.get("catalogue_id"):
                    catalogue_id = previous["catalogue_id"]
                    issues = [issue for issue in issues if issue != "catalogue_not_found"]
'''
new=old+'''
                # Reuse a recorded human decision only for the identical source
                # key and an unchanged catalogue identity. This is a mapping,
                # not a fabricated model confidence or a new canonical record.
                if previous and previous.get("catalogue_id"):
                    prior_record = previous.get("normalized_record") or {}
                    prior_confirmation = prior_record.get("import_identity_confirmation") or {}
                    if prior_confirmation.get("method") == "MANUAL":
                        chosen = await connection.fetchrow(
                            "select * from tcg.catalogue_products where id=$1",
                            previous["catalogue_id"],
                        )
                        if manual_admission_valid(prior_record, dict(chosen) if chosen else None):
                            catalogue_id = previous["catalogue_id"]
                            for identity_field in ("game", "name", "set_name", "card_number", "variant", "rarity", "language"):
                                normalized[identity_field] = prior_record.get(identity_field)
                            normalized["import_identity_confirmation"] = prior_confirmation
                            resolved = {"missing_name", "missing_game", "missing_set", "missing_card_number",
                                        "catalogue_not_found", "catalogue_admin_review_required",
                                        "ambiguous_catalogue_match", "manual_identity_confirmation_required"}
                            if normalized.get("language"):
                                resolved.update({"missing_language", "language_conflict"})
                            issues = [issue for issue in issues if issue not in resolved]
'''
assert s.count(old)==1
p.write_text(s.replace(old,new,1))
p=ROOT/'backend/app/owner_auto_imports.py';s=p.read_text()
s=s.replace('        if not result:\n            raise ValueError("Choose a supported card language")','        if result not in {"English", "Japanese", "Chinese", "Korean", "French", "German", "Italian", "Spanish", "Portuguese"}:\n            raise ValueError("Choose a supported card language")',1)
p.write_text(s)
