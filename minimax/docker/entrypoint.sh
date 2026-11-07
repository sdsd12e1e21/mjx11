#!/bin/sh
set -eu
if ! ip link show sddlocal0 >/dev/null 2>&1; then
    ip link add sddlocal0 type dummy
    ip address add 198.18.0.1/32 dev sddlocal0
    ip link set sddlocal0 up
fi
exec setpriv --reuid 10001 --regid 10001 --clear-groups "$@"
