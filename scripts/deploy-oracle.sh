#!/bin/sh
# Deprecated path. The deploy script is now scripts/deploy-production.sh, named for
# what it does rather than for one hosting provider, because naming it after the
# provider is what made a move from Oracle Cloud to OVHcloud a rename across the repo.
#
# This shim exists for one reason: scripts/install-autodeploy bakes this path into
# /usr/local/sbin/ns-trackstar-autodeploy on the server, and that generated file lives
# outside the repository. A VM that installed autodeploy before the rename would pull
# the new commit, find no deploy script, and fail inside a systemd oneshot where nobody
# would see it.
#
# Re-run scripts/install-autodeploy on the server to regenerate the runner, then delete
# this file.
set -eu
echo "scripts/deploy-oracle.sh is deprecated; running scripts/deploy-production.sh." >&2
echo "Re-run scripts/install-autodeploy on the server, then delete this shim." >&2
exec "$(dirname "$0")/deploy-production.sh" "$@"
