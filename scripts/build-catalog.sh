#!/bin/sh
# Incrementally build FreeBSD binaries for plugins whose upstream version is new,
# or that are missing a FreeBSD build for an arch, and refresh manifest.json.
#
#   Usage: ./scripts/build-catalog.sh <asset-base-url>
#
#     asset-base-url  URL prefix the binaries built THIS run are published
#                     under, e.g.
#                     https://github.com/OWNER/REPO/releases/download/catalog-20261015T0417Z
#
#   Environment:
#     GO         go binary            (default: go)
#     MAKE       make binary          (default: make; used by repos whose
#                                     Makefile declares a prepare step)
#     ARCHES     GOARCH list          (default: amd64; e.g. "amd64 arm64")
#     UPSTREAM   upstream catalog URL (default: Silo-Server/silo-plugins main)
#     FORCE=1    rebuild every arch, not only the missing ones
#     BUILT      build list to write        (default: <repo>/built.txt)
#
#   Outputs:
#     <repo>/manifest.json  rewritten only when it changed
#     <repo>/dist/*         the newly built binaries
#     $BUILT                "<plugin_id> <version> <arch>" per built binary; empty
#                           when nothing changed
#
#   Requires: git, go >= 1.26, curl, jq, sha256sum or shasum, network.
set -eu

GO=${GO:-go}
ARCHES=${ARCHES:-amd64}
UPSTREAM=${UPSTREAM:-https://raw.githubusercontent.com/Silo-Server/silo-plugins/main/manifest.json}
ASSET_BASE=${1:?usage: $0 <asset-base-url>}
ASSET_BASE=${ASSET_BASE%/}

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
out_manifest=$root/manifest.json
existing=$out_manifest
dist=$root/dist
built=${BUILT:-$root/built.txt}
mkdir -p "$dist"
mkdir -p "$(dirname -- "$built")"
: > "$built"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT INT TERM
mkdir -p "$tmp/upd"

echo "==> fetching upstream catalog"
curl -fsSL "$UPSTREAM" -o "$tmp/upstream.json"
count=$(jq '.plugins | length' "$tmp/upstream.json")
echo "==> upstream lists $count plugins; arches: $ARCHES"

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

	# Binaries already published for this exact version are reused; only the
	# arches we are missing (all of them when the version changed) get built.
	# Validate untrusted upstream fields before using them in paths/commands.
	case "$id" in
		''|*[!A-Za-z0-9._-]*) echo "skip $id (invalid plugin id)"; continue ;;
	esac
	case "$version" in
		''|*[!0-9A-Za-z._+-]*) echo "skip $id (invalid version)"; continue ;;
	esac
	case "$repo" in
		https://github.com/*) ;;
		*) echo "skip $id (invalid repo_url)"; continue ;;
	esac
	rest=${repo#https://github.com/}
	case "$rest" in
		''|*/*/*|*\?*|*\#*|*' '*) echo "skip $id (invalid repo_url)"; continue ;;
	esac
	case "$rest" in
		*/*) ;;
		*) echo "skip $id (invalid repo_url)"; continue ;;
	esac
	owner=${rest%%/*}
	reponame=${rest#*/}
	case "$owner" in
		''|*[!A-Za-z0-9._-]*) echo "skip $id (invalid repo_url)"; continue ;;
	esac
	case "$reponame" in
		''|*[!A-Za-z0-9._-]*) echo "skip $id (invalid repo_url)"; continue ;;
	esac
	for arch in $ARCHES; do
		case "$arch" in
			amd64|arm64|386|arm) ;;
			*) echo "skip $id (unsupported arch $arch)"; continue 2 ;;
		esac
	done

	existing_entry=$(jq -c --arg id "$id" --arg v "$version" '
		.plugins[]?
		| select(.manifest.plugin_id == $id and .manifest.version == $v)
	' "$existing" 2>/dev/null | head -1)
	existing_bins=$(printf '%s' "$existing_entry" | jq -c '.binaries // {}' 2>/dev/null)
	[ -n "$existing_bins" ] || existing_bins='{}'

	# Binaries already published for this exact version are reused; only the
	# arches we are missing (all of them when the version changed) get built.
	reusable=0
	if [ "${FORCE:-0}" != 1 ] && [ -n "$existing_entry" ]; then
		reusable=1
		for arch in $ARCHES; do
			if ! printf '%s' "$existing_bins" | jq -e --arg a "$arch" 'has("freebsd/" + $a)' >/dev/null 2>&1; then
				reusable=0
				break
			fi
		done
	fi

	build_arches=""
	if [ "$reusable" = 1 ]; then
		build_arches=""
	else
		for arch in $ARCHES; do
			build_arches="$build_arches $arch"
		done
	fi
	if [ -z "$build_arches" ]; then
		echo "up-to-date $id $version"
		continue
	fi

	slug=$id
	echo "==> building $id $version:$build_arches"
	src="$tmp/src-$slug"
	if ! git clone --quiet --depth 1 --branch "v$version" "$repo.git" "$src" 2>/dev/null; then
		echo "  !! clone failed (missing v$version tag?), skipping"
		continue
	fi

	# Advertise every FreeBSD arch we target.
	sp="$manifest"
	for arch in $ARCHES; do
		if ! printf '%s' "$sp" | jq -e --arg a "$arch" \
			'[.supported_platforms[]? | select(.os=="freebsd" and .arch==$a)] | length > 0' >/dev/null; then
			sp=$(printf '%s' "$sp" | jq -c --arg a "$arch" \
				'.supported_platforms += [{"os":"freebsd","arch":$a}]')
		fi
	done

	# Some repos ship no go.sum (and no vendor dir); -mod=mod generates one in
	# the throwaway clone, which is deleted below.
	modflag=""
	[ -f "$src/go.sum" ] || modflag="-mod=mod"

	binaries='{}'
	built_here=0
	failed=0
	expected=0
	for _ in $build_arches; do expected=$((expected + 1)); done

	for arch in $build_arches; do
		out="$dist/${slug}-freebsd-${arch}"
		# Silo refuses an install whose binary reports a different version than the
		# catalog lists, and a plugin reports main.version, which only the linker
		# sets: without -X it keeps the version frozen in its embedded manifest.json.
		# A repo that declares a prepare step needs its own pipeline (it patches a
		# dependency and points GOFLAGS at the patched tree), so use its Makefile,
		# which runs prepare and writes ./plugin with the version ldflags.
		built_ok=0
		if grep -q '^prepare:' "$src/Makefile" 2>/dev/null; then
			( cd "$src" && CGO_ENABLED=0 GOOS=freebsd GOARCH="$arch" \
				"${MAKE:-make}" build VERSION="$version" >/dev/null && mv plugin "$out" ) \
				&& built_ok=1
		elif ( cd "$src" && CGO_ENABLED=0 GOOS=freebsd GOARCH="$arch" "$GO" build $modflag -trimpath \
			-ldflags "-s -w -X main.version=$version" -o "$out" . ); then
			built_ok=1
		fi
		if [ "$built_ok" = 1 ]; then
			# -X is a silent no-op on a symbol that does not exist, so check both
			# ends: the variable is declared, and the binary carries the version.
			if ! grep -q 'var version' "$src/main.go" 2>/dev/null ||
				! strings -a "$out" | grep -qxF "$version"; then
				echo "  !! $id $version does not report its version; not publishing"
				rm -f "$out"
				failed=1
				continue
			fi
			sum=$( (sha256sum "$out" 2>/dev/null || shasum -a 256 "$out") | awk '{print $1}')
			binaries=$(printf '%s' "$binaries" | jq -c \
				--arg k "freebsd/$arch" \
				--arg u "$ASSET_BASE/$(basename "$out")" \
				--arg c "$sum" \
				'. + {($k): {"url":$u, "checksum":$c}}')
			built_here=$((built_here + 1))
			echo "  built $out"
		else
			echo "  !! build failed for $id on $arch"
			rm -f "$out"
			failed=1
		fi
	done
	rm -rf "$src"

	if [ "$failed" = 1 ] || [ "$built_here" -ne "$expected" ]; then
		echo "skip $id (incomplete build)"
		for arch in $build_arches; do rm -f "$dist/${slug}-freebsd-${arch}"; done
		continue
	fi

	for arch in $build_arches; do
		printf '%s %s %s\n' "$id" "$version" "$arch" >> "$built"
	done

	jq -cn --argjson m "$sp" --arg r "$repo" --argjson b "$binaries" \
		'{manifest:$m, repo_url:$r, binaries:$b}' > "$tmp/upd/$slug.json"
done

jq -s '.' "$tmp"/upd/*.json > "$tmp/updates.json" 2>/dev/null || printf '[]' > "$tmp/updates.json"
[ -f "$existing" ] || printf '{"plugins":[]}' > "$existing"
jq --slurpfile up "$tmp/updates.json" --slurpfile src "$tmp/upstream.json" '
	($src[0].plugins | map(.manifest.plugin_id)) as $listed
	| ($up[0] | map(.manifest.plugin_id)) as $updated
	| .plugins = (
		((.plugins // [])
			| map(select(.manifest.plugin_id as $id
				| ($listed | index($id)) != null and ($updated | index($id)) == null)))
		+ $up[0]
	)
' "$existing" > "$tmp/manifest.new.json"
if cmp -s "$tmp/manifest.new.json" "$out_manifest"; then
	echo "==> no changes; $out_manifest left untouched"
else
	mv "$tmp/manifest.new.json" "$out_manifest"
	echo "==> wrote $out_manifest ($(wc -l < "$built" | tr -d ' ') binaries)"
fi
