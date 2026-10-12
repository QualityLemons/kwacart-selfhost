#!/bin/sh
cd "$(dirname "$0")" || exit 1
for candidate in python3.13 python3.14 python3.12 python3 python; do
    if "$candidate" -c 'import sys; sys.exit(not ((3,12) <= sys.version_info[:2] < (3,15)))' >/dev/null 2>&1; then
        "$candidate" ./start_kwacart.py "$@"
        result=$?
        if [ "$result" -ne 0 ]; then
            printf '\nRead the error above. Press Enter to close this window.'
            read -r unused
        fi
        exit "$result"
    fi
done
printf '\nPython was not found. Install Python 3.13 from python.org, then try again.\n'
printf 'Press Enter to close this window.'
read -r unused
exit 1
