#!/bin/sh
# Build FreeBSD binaries for every plugin in the upstream Silo catalog and emit
# a FreeBSD catalog (manifest.json) plus the binaries under dist/.
#
#   Usage: ./scripts/build-catalog.sh <asset-base-url>
#
#     asset-base-url  base URL the binaries will be published under, e.g.
#                     https://github.com/OWNER/silo-plugins-freebsd/releases/download/catalog
#
#   Environment:
#     GO         go binary            (default: go)
#     ARCHES     GOARCH list          (default: amd64; e.g. "amd64 arm64")
#     UPSTREAM   upstream catalog URL (default: Silo-Server/silo-plugins main)
#     ALLOWLIST  optional file of plugin IDs to include (one per line)
#
#   Requires: git, go >= 1.26, curl, jq, sha256sum or shasum, network.
set -eu

GO=${GO:-go}
ARCHES=${ARCHES:-amd64}
UPSTREAM=${UPSTREAM:-https://raw.githubusercontent.com/Silo-Server/silo-plugins/main/manifest.json}
ASSET_BASE=${1:?usage: $0 <asset-base-url>}
ASSET_BASE=${ASSET_BASE%/}

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
dist="$root/dist"
mkdir -p "$dist"

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT INT TERM

echo "==> fetching upstream catalog"
curl -fsSL "$UPSTREAM" -o "$tmp/upstream.json"

count=$(jq '.plugins | length' "$tmp/upstream.json")
echo "==> upstream lists $count plugins"

mkdir -p "$tmp/entries"
n=0
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

	slug=$(printf '%s' "$id" | tr '/.' '--')
	echo "==> $id $version"
	src="$tmp/src-$slug"
	if ! git clone --quiet --depth 1 --branch "v$version" "$repo.git" "$src" 2>/dev/null; then
		if ! git clone --quiet --depth 1 "$repo.git" "$src" 2>/dev/null; then
			echo "  !! clone failed, skipping"
			continue
		fi
	fi

	# Keep upstream's supported_platforms, adding freebsd/<arch> if absent.
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
		'{manifest:$m, repo_url:$r, binaries:$b}' > "$tmp/entries/$slug.json"
	n=$((n + 1))
done

jq -s '{plugins: .}' "$tmp"/entries/*.json > "$root/manifest.json"
echo "==> wrote $root/manifest.json with $n plugins"
