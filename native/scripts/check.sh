#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
check_tmp=$(mktemp -d "${TMPDIR:-/tmp}/drop-rate-check.XXXXXX")
trap 'rm -rf "$check_tmp"' EXIT
swiftc -module-cache-path "$check_tmp/cache" ios/DropRate/NavigationPolicy.swift tests/main.swift -o "$check_tmp/navigation-tests"
"$check_tmp/navigation-tests"
plutil -lint ios/DropRate/Info.plist ios/DropRate.xcodeproj/project.pbxproj
# Syntax-only; an iOS SDK is required for full type checking and linking.
swiftc -frontend -parse ios/DropRate/*.swift
if xcodebuild -version >/dev/null 2>&1; then
    xcodebuild -project ios/DropRate.xcodeproj -scheme DropRate -sdk iphonesimulator -configuration Debug -derivedDataPath "$check_tmp/build" CODE_SIGNING_ALLOWED=NO build
else
    echo 'Full iOS build NOT RUN: install and open Xcode first.'
fi
