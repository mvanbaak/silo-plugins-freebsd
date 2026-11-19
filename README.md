# silo-plugins-freebsd

FreeBSD builds of [Silo](https://siloserver.org) plugins that Silo's own
catalogs do not ship for FreeBSD.

Silo's official catalog and its approved-community catalog both publish
FreeBSD binaries today, so nothing from either needs rebuilding here. This
repository exists for the rest: plugins whose upstream project only builds
Linux and macOS.

## Use it

Add this URL as a repository in Silo: **Admin → Plugins → Repositories →
add**, enabled.

```
https://raw.githubusercontent.com/mvanbaak/silo-plugins-freebsd/main/manifest.json
```

Then install from **Admin → Plugins → Catalog**.

## What it carries

`scripts/plugins.txt` lists the repositories to build, one
`https://github.com/OWNER/REPO` per line. For each one the workflow takes the
latest GitHub release, fetches the `manifest.json` at that tag, cross-builds
FreeBSD `amd64` and `arm64`, and publishes the binaries in a release.

Only non-first-party plugin ids work here. Silo enforces a signing policy for
`silo.*` ids and refuses a binary that did not come from that plugin's own
release workflow, so a rebuilt official plugin could never install.

These are unreviewed third-party builds republished under FreeBSD. They install
as **unsigned**, because Silo does not verify a third-party repository's
binaries. Each release still ships `plugin.sigstore.json`, so a downloaded
binary can be checked by hand:

```sh
gh attestation verify plugin-freebsd-amd64 --repo mvanbaak/silo-plugins-freebsd
```

## No port patches

The `multimedia/silo` FreeBSD port carries no plugin-catalog patch. This
repository is added by hand, exactly like any other third-party catalog.
