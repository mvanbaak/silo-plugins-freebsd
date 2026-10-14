#!/bin/sh
# Incrementally build FreeBSD binaries only for plugins whose upstream version is
# new (or that lack a FreeBSD build), and refresh manifest.json.
#
#   Usage: ./scripts/build-catalog.sh <asset-base-url> [existing-manifest]
#
#     asset-base-url     URL prefix the binaries built THIS run are published
#                        under, e.g.
#                        https://github.com/OWNER/REPO/releases/download/catalog-20261015T0417Z
#     existing-manifest  our current catalog (default: <repo>/manifest.json)
#
#   Environment:
#     GO         go binary            (default: go)
#     ARCHES     GOARCH list          (default: amd64)
#     UPSTREAM   upstream catalog URL (default: Silo-Server/silo-plugins main)
#     ALLOWLIST  optional file of plugin IDs to consider (one per line)
#     FORCE=1    rebuild every plugin, not only changed ones
#
#   Outputs (under <repo>):
#     manifest.json   rewritten only when something was built
#     dist/*          the newly built binaries
#     built.txt       "<plugin_id> <version> <arch>" per built binary; empty when
#                     nothing changed
#
#   Requires: git, go >= 1.26, curl, jq, sha256sum or shasum, network.
set -eu

GO=${GO:-go}
ARCHES=${ARCHES:-amd64}
UPSTREAM=${UPSTREAM:-https://raw.githubusercontent.com/Silo-Server/silo-plugins/main/manifest.json}
ASSET_BASE=${1:?usage: $0 <asset-base-url> [existing-manifest]}
ASSET_BASE=${ASSET_BASE%/}

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
existing=${2:-$root/manifest.json}
dist="$root/dist"
built="$root/built.txt"
mkdir -p "$dist"
: > "$built"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT INT TERM
mkdir -p "$tmp/upd"

# Prints "yes" when the existing catalog already ships this plugin version with
# a FreeBSD binary for arch.
have() { # id version arch
	jq -r --arg id "$1" --arg v "$2" --arg a "$3" '
		.plugins[]?
		| select(.manifest.plugin_id == $id and .manifest.version == $v)
		| .binaries["freebsd/" + $a]
		| if . == null then empty else "yes" end
	' "$existing" 2>/dev/null | head -1
}

echo "==> fetching upstream catalog"
curl -fsSL "$UPSTREAM" -o "$tmp/upstream.json"
count=$(jq '.plugins | length' "$tmp/upstream.json")
echo "==> upstream lists $count plugins"

i=0
while [ "$i" -lt "$count" ]; do
	manifest=$(jq -c ".plugins[$i].manifest" "$tmp/upstream.json")
	id=$(printf '%s' "$manifest" | jq -r '.plugin_id')
	version=$(printf '%s' "$manifest" | jq -r '.version')
	repo=$(jq -r ".plugins[$i].repo_url // empty" "$tmp/upstream.json")
	i=$((i + 1))

	if [ -z "$repo" ]; then
		echo "skip $id (no repo_url)"
		continue
	fi
	if [ -n "${ALLOWLIST:-}" ] && [ -f "$ALLOWLIST" ] && ! grep -qxF "$id" "$ALLOWLIST"; then
		echo "skip $id (not in $ALLOWLIST)"
		continue
	fi

	need=0
	for arch in $ARCHES; do
		[ -n "$(have "$id" "$version" "$arch")" ] || need=1
	done
	if [ "$need" = 0 ] && [ "${FORCE:-0}" != 1 ]; then
		echo "up-to-date $id $version"
		continue
	fi

	slug=$(printf '%s' "$id" | tr '/.' '--')
	echo "==> building $id $version"
	src="$tmp/src-$slug"
	if ! git clone --quiet --depth 1 --branch "v$version" "$repo.git" "$src" 2>/dev/null; then
		if ! git clone --quiet --depth 1 "$repo.git" "$src" 2>/dev/null; then
			echo "  !! clone failed, skipping"
			continue
		fi
	fi

	sp="$manifest"
	for arch in $ARCHES; do
		if ! printf '%s' "$sp" | jq -e --arg a "$arch" \
			'[.supported_platforms[]? | select(.os=="freebsd" and .arch==$a)] | length > 0' >/dev/null; then
			sp=$(printf '%s' "$sp" | jq -c --arg a "$arch" \
				'.supported_platforms += [{"os":"freebsd","arch":$a}]')
		fi
	done

	binaries='{}'
	for arch in $ARCHES; do
		out="$dist/${slug}-freebsd-${arch}"
		if ( cd "$src" && CGO_ENABLED=0 GOOS=freebsd GOARCH="$arch" "$GO" build -trimpath -o "$out" . ); then
			sum=$( (sha256sum "$out" 2>/dev/null || shasum -a 256 "$out") | awk '{print $1}')
			binaries=$(printf '%s' "$binaries" | jq -c \
				--arg k "freebsd/$arch" \
				--arg u "$ASSET_BASE/$(basename "$out")" \
				--arg c "$sum" \
				'. + {($k): {"url":$u, "checksum":$c}}')
			printf '%s %s %s\n' "$id" "$version" "$arch" >> "$built"
			echo "  built $out"
		else
			echo "  !! build failed for $id on $arch"
		fi
	done
	rm -rf "$src"

	if [ "$binaries" = '{}' ]; then
		echo "skip $id (no binaries built)"
		continue
	fi

	jq -cn --argjson m "$sp" --arg r "$repo" --argjson b "$binaries" \
		'{manifest:$m, repo_url:$r, binaries:$b}' > "$tmp/upd/$slug.json"
done

if ls "$tmp/upd"/*.json >/dev/null 2>&1; then
	jq -s '.' "$tmp"/upd/*.json > "$tmp/updates.json"
	[ -f "$existing" ] || printf '{"plugins":[]}' > "$existing"
	jq --slurpfile up "$tmp/updates.json" '
		.plugins = (
			((.plugins // [])
				| map(select(.manifest.plugin_id as $id
					| ($up[0] | map(.manifest.plugin_id) | index($id)) | not)))
			+ $up[0]
		)
	' "$existing" > "$tmp/manifest.new.json"
	mv "$tmp/manifest.new.json" "$root/manifest.json"
	echo "==> wrote $root/manifest.json ($(wc -l < "$built" | tr -d ' ') binaries)"
else
	echo "==> no changes; manifest.json left untouched"
fi
