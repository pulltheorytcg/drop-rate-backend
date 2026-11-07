"""Reproduce the dependency-free Xcode project; no Expo or package manager needed."""
import json
import plistlib
from pathlib import Path
root = Path(__file__).resolve().parents[1] / 'ios'
objects = {}
def obj(key, isa, **fields):
    objects[key] = dict(isa=isa, **fields)
    return key
# Stable identifiers keep generated project diffs readable.
def ident(n): return f'{n:024X}'
project, group, products, target, product, sources, resources, frameworks = map(ident, range(1,9))
files = ['AppDelegate.swift', 'HubViewController.swift', 'NavigationPolicy.swift']
refs, builds = [], []
for index, filename in enumerate(files):
    ref, build = ident(20+index), ident(30+index)
    obj(ref, 'PBXFileReference', lastKnownFileType='sourcecode.swift', path='DropRate/'+filename, sourceTree='<group>')
    obj(build, 'PBXBuildFile', fileRef=ref)
    refs.append(ref); builds.append(build)
asset, assetbuild = ident(40), ident(41)
obj(asset, 'PBXFileReference', lastKnownFileType='folder.assetcatalog', path='DropRate/Assets.xcassets', sourceTree='<group>')
obj(assetbuild, 'PBXBuildFile', fileRef=asset)
obj(product, 'PBXFileReference', explicitFileType='wrapper.application', path='DropRate.app', sourceTree='BUILT_PRODUCTS_DIR')
obj(group, 'PBXGroup', children=refs+[asset,products], sourceTree='<group>')
obj(products, 'PBXGroup', children=[product], name='Products', sourceTree='<group>')
obj(sources, 'PBXSourcesBuildPhase', buildActionMask=2147483647, files=builds, runOnlyForDeploymentPostprocessing=0)
obj(resources, 'PBXResourcesBuildPhase', buildActionMask=2147483647, files=[assetbuild], runOnlyForDeploymentPostprocessing=0)
obj(frameworks, 'PBXFrameworksBuildPhase', buildActionMask=2147483647, files=[], runOnlyForDeploymentPostprocessing=0)
pconfigs, tconfigs = [], []
for index, name in enumerate(['Debug','Release']):
    p, t = ident(50+index), ident(60+index)
    obj(p, 'XCBuildConfiguration', name=name, buildSettings=dict(SDKROOT='iphoneos', IPHONEOS_DEPLOYMENT_TARGET='16.0', CLANG_ENABLE_MODULES='YES', SWIFT_VERSION='5.0'))
    settings=dict(PRODUCT_NAME='DropRate', PRODUCT_BUNDLE_IDENTIFIER='com.pulltheory.tcg', INFOPLIST_FILE='DropRate/Info.plist', CODE_SIGN_STYLE='Automatic', TARGETED_DEVICE_FAMILY='1', ASSETCATALOG_COMPILER_APPICON_NAME='AppIcon', CURRENT_PROJECT_VERSION='1', MARKETING_VERSION='0.1.0', SWIFT_OPTIMIZATION_LEVEL='-Onone' if name=='Debug' else '-O', SUPPORTED_PLATFORMS='iphoneos iphonesimulator', SUPPORTS_MACCATALYST='NO')
    obj(t, 'XCBuildConfiguration', name=name, buildSettings=settings)
    pconfigs.append(p); tconfigs.append(t)
plist, tlist = ident(70), ident(71)
obj(plist, 'XCConfigurationList', buildConfigurations=pconfigs, defaultConfigurationIsVisible=0, defaultConfigurationName='Release')
obj(tlist, 'XCConfigurationList', buildConfigurations=tconfigs, defaultConfigurationIsVisible=0, defaultConfigurationName='Release')
obj(target, 'PBXNativeTarget', buildConfigurationList=tlist, buildPhases=[sources,frameworks,resources], buildRules=[], dependencies=[], name='DropRate', productName='DropRate', productReference=product, productType='com.apple.product-type.application')
obj(project, 'PBXProject', attributes=dict(LastUpgradeCheck='1600'), buildConfigurationList=plist, compatibilityVersion='Xcode 14.0', developmentRegion='en', hasScannedForEncodings=0, knownRegions=['en','Base'], mainGroup=group, productRefGroup=products, projectDirPath='', projectRoot='', targets=[target])
def encode(value):
    if isinstance(value, dict): return '{\n'+'\n'.join(f'{json.dumps(k)} = {encode(v)};' for k,v in value.items())+'\n}'
    if isinstance(value, list): return '('+', '.join(encode(v) for v in value)+')'
    return str(value) if isinstance(value,int) else json.dumps(value)
(root/'DropRate.xcodeproj/project.pbxproj').write_text('// !$*UTF8*$!\n'+encode(dict(archiveVersion=1, classes={}, objectVersion=56, objects=objects, rootObject=project))+'\n')
info = dict(CFBundleDevelopmentRegion='en', CFBundleDisplayName='Drop Rate', CFBundleExecutable='$(EXECUTABLE_NAME)', CFBundleIdentifier='$(PRODUCT_BUNDLE_IDENTIFIER)', CFBundleInfoDictionaryVersion='6.0', CFBundleName='Drop Rate', CFBundlePackageType='APPL', CFBundleShortVersionString='$(MARKETING_VERSION)', CFBundleVersion='$(CURRENT_PROJECT_VERSION)', LSRequiresIPhoneOS=True, UILaunchScreen={}, UISupportedInterfaceOrientations=['UIInterfaceOrientationPortrait'], NSCameraUsageDescription='Photograph your cards to identify them in Drop Rate.', NSPhotoLibraryUsageDescription='Choose card photos to identify or add to your inventory.')
(root/'DropRate/Info.plist').write_bytes(plistlib.dumps(info))
assets=root/'DropRate/Assets.xcassets'
(assets/'Contents.json').write_text(json.dumps(dict(info=dict(author='xcode',version=1)),indent=2)+'\n')
(assets/'AppIcon.appiconset/Contents.json').write_text(json.dumps(dict(images=[dict(filename='DropRate.png',idiom='universal',platform='ios',size='1024x1024')],info=dict(author='xcode',version=1)),indent=2)+'\n')
