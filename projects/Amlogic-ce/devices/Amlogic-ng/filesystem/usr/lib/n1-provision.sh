#!/bin/sh
#
# First-boot provisioning for the N1 image.
#
# Runs once, before Kodi starts, and only on a fresh install:
#   1. installs the bundled Chinese language pack
#   2. defaults CoreELEC to manual updates (the custom build must not be
#      replaced by an upstream release)
#
# The language pack is only made available: the UI language, region and font
# stay at the image defaults, and the user picks Chinese in the GUI if wanted.
# Preselecting it here used to leave the skin without CJK glyphs, so the whole
# interface rendered as empty boxes.
#
# Nothing is touched if /storage/.n1-provisioned already exists, so user
# settings survive later boots and image upgrades.

MARKER=/storage/.n1-provisioned
[ -e "$MARKER" ] && exit 0

USERDATA=/storage/.kodi/userdata
ADDONS=/storage/.kodi/addons
PACK=/usr/share/n1-provision/resource.language.zh_cn-11.0.104.zip

mkdir -p "$USERDATA" "$ADDONS"

# 1) Chinese language pack (omega branch, matches Kodi 21)
if [ -f "$PACK" ]; then
	rm -rf "$ADDONS/resource.language.zh_cn"
	unzip -q -o "$PACK" -d "$ADDONS" ||
		echo "n1-provision: could not unpack the language pack"
else
	echo "n1-provision: language pack missing"
fi

# 2) never auto-update this build: an upstream release would replace the
#    Dolby Vision patched SYSTEM/kernel
SETTINGS_DIR="$USERDATA/addon_data/service.coreelec.settings"
SETTINGS="$SETTINGS_DIR/oe_settings.xml"
mkdir -p "$SETTINGS_DIR"
if [ ! -f "$SETTINGS" ]; then
	cat > "$SETTINGS" <<'XML'
<coreelec>
	<addon_config/>
	<settings>
		<updates>
			<AutoUpdate>manual</AutoUpdate>
			<UpdateNotify>0</UpdateNotify>
			<SubmitStats>0</SubmitStats>
		</updates>
	</settings>
</coreelec>
XML
fi

touch "$MARKER"
exit 0
