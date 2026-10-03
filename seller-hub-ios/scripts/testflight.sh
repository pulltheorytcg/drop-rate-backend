#!/usr/bin/env bash
set -euo pipefail
# Never enable shell tracing: credentials belong only in the ephemeral keychain.
for required in IOS_CERTIFICATE_BASE64 IOS_CERTIFICATE_PASSWORD IOS_PROFILE_BASE64 APPLE_TEAM_ID ASC_KEY_ID ASC_ISSUER_ID ASC_PRIVATE_KEY_BASE64; do
  if [[ -z "${!required:-}" ]]; then
    echo "Missing signing setup: $required. Follow seller-hub-ios/README.md."
    exit 1
  fi
done
signing_dir="$(mktemp -d "${RUNNER_TEMP:?}/seller-hub-signing.XXXXXX")"
export SELLER_HUB_SIGNING_DIR="$signing_dir"
keychain_path="$signing_dir/signing.keychain-db"
keychain_password="$(openssl rand -hex 32)"
profile_path=""
cleanup() {
  security delete-keychain "$keychain_path" >/dev/null 2>&1 || true
  if [[ -n "$profile_path" ]]; then rm -f "$profile_path"; fi
  rm -rf "$signing_dir"
}
trap cleanup EXIT
python3 - <<'PY'
import base64, os, pathlib
p = pathlib.Path(os.environ['SELLER_HUB_SIGNING_DIR'])
for variable, name in [('IOS_CERTIFICATE_BASE64', 'certificate.p12'), ('IOS_PROFILE_BASE64', 'profile.mobileprovision'), ('ASC_PRIVATE_KEY_BASE64', 'AuthKey_' + os.environ['ASC_KEY_ID'] + '.p8')]:
    path = p / name
    path.write_bytes(base64.b64decode(os.environ[variable], validate=True))
    path.chmod(0o600)
PY
security create-keychain -p "$keychain_password" "$keychain_path"
security set-keychain-settings -lut 3600 "$keychain_path"
security unlock-keychain -p "$keychain_password" "$keychain_path"
security import "$signing_dir/certificate.p12" -P "$IOS_CERTIFICATE_PASSWORD" -A -t cert -f pkcs12 -k "$keychain_path" >/dev/null
security set-key-partition-list -S apple-tool:,apple: -k "$keychain_password" "$keychain_path" >/dev/null
security list-keychains -d user -s "$keychain_path"
security cms -D -i "$signing_dir/profile.mobileprovision" > "$signing_dir/profile.plist"
python3 - <<'PY'
import datetime, os, pathlib, plistlib
p = pathlib.Path(os.environ['SELLER_HUB_SIGNING_DIR'])
profile = plistlib.loads((p / 'profile.plist').read_bytes())
team = os.environ['APPLE_TEAM_ID']
bundle = 'com.pulltheory.sellerhub'
assert team in profile['TeamIdentifier'], 'Provisioning profile belongs to a different Apple team'
assert profile['Entitlements']['application-identifier'].endswith('.' + bundle), 'Profile is not for the Seller Hub app'
assert not profile['Entitlements'].get('get-task-allow'), 'Use an App Store distribution profile'
assert not profile.get('ProvisionedDevices') and not profile.get('ProvisionsAllDevices'), 'Use an App Store profile, not ad hoc or enterprise'
assert profile['ExpirationDate'] > datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None), 'Provisioning profile expired'
(p / 'profile-uuid').write_text(profile['UUID'])
options = {'method': 'app-store-connect', 'teamID': team, 'signingStyle': 'manual',
           'signingCertificate': 'Apple Distribution', 'provisioningProfiles': {bundle: profile['UUID']},
           'uploadSymbols': True, 'manageAppVersionAndBuildNumber': False}
(p / 'ExportOptions.plist').write_bytes(plistlib.dumps(options))
PY
profile_uuid="$(cat "$signing_dir/profile-uuid")"
# Xcode 16+ uses this directory (the workflow selects Xcode 26.3).
profile_directory="$HOME/Library/Developer/Xcode/UserData/Provisioning Profiles"
mkdir -p "$profile_directory"
profile_path="$profile_directory/$profile_uuid.mobileprovision"
cp "$signing_dir/profile.mobileprovision" "$profile_path"
build_number="$(python3 - <<'PY'
import os
n = int(os.environ['GITHUB_RUN_NUMBER']) * 10 + int(os.environ['GITHUB_RUN_ATTEMPT']) - 1
assert n < 99990000, 'Choose a new marketing version before increasing build numbers further'
print(f'{1 + n // 10000}.{n // 100 % 100}.{n % 100}')
PY
)"
xcodebuild archive -project SellerHub.xcodeproj -scheme SellerHub \
  -configuration Release -destination 'generic/platform=iOS' -archivePath build/SellerHub.xcarchive \
  DEVELOPMENT_TEAM="$APPLE_TEAM_ID" CODE_SIGN_IDENTITY='Apple Distribution' \
  PROVISIONING_PROFILE_SPECIFIER="$profile_uuid" CURRENT_PROJECT_VERSION="$build_number" \
  OTHER_CODE_SIGN_FLAGS="--keychain $keychain_path"
xcodebuild -exportArchive -archivePath build/SellerHub.xcarchive \
  -exportOptionsPlist "$signing_dir/ExportOptions.plist" -exportPath build/export
# altool discovers API keys in API_PRIVATE_KEYS_DIR; no Apple password is used.
export API_PRIVATE_KEYS_DIR="$signing_dir"
xcrun altool --upload-app --type ios --file build/export/SellerHub.ipa \
  --apiKey "$ASC_KEY_ID" --apiIssuer "$ASC_ISSUER_ID"
echo 'Upload submitted to App Store Connect. Apple processing and TestFlight access must be verified separately.'
